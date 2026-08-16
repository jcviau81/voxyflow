"""Regression guard: one workspace, one working directory.

Voxyflow used to resolve a workspace's directory two different ways — the
creation route slugified the title into ``workspaces/<slug>`` and stored it in
``local_path`` (the path the frontend shows), while the worker runtime keyed a
second folder by id, ``workspaces/<uuid>``. Every workspace that ran a worker
ended up with two folders and the user's files were in the one the UI never
mentioned.

These tests pin the resolution order and, most importantly, that the folder the
creation route makes is the folder the worker runtime resolves.
"""

import sqlite3
from pathlib import Path

import pytest

from app.services import workspace_paths
from app.services.sandbox_service import SandboxService
from app.services.workspace_paths import (
    resolve_workspace_dir,
    sanitize_id,
    slugify,
    workspace_sandbox_area,
)


@pytest.fixture
def ws_env(tmp_path, monkeypatch):
    """A throwaway sandbox + workspaces DB wired into the resolver."""
    import app.config as config_module

    sandbox = tmp_path / "sandbox"
    (sandbox / "workspaces").mkdir(parents=True)

    db_file = tmp_path / "voxyflow.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE workspaces (id TEXT PRIMARY KEY, title TEXT, local_path TEXT)")
    conn.commit()
    conn.close()

    class _FakeSettings:
        database_url = f"sqlite+aiosqlite:///{db_file}"

    monkeypatch.setattr(config_module, "get_settings", lambda: _FakeSettings())
    monkeypatch.setattr(config_module, "VOXYFLOW_SANDBOX_DIR", sandbox)
    workspace_paths.invalidate()
    yield sandbox, db_file
    workspace_paths.invalidate()


def _insert(db_file: Path, ws_id: str, title: str, local_path: str | None):
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO workspaces (id, title, local_path) VALUES (?, ?, ?)",
        (ws_id, title, local_path),
    )
    conn.commit()
    conn.close()
    workspace_paths.invalidate()


def test_local_path_wins(ws_env):
    """The path stored at creation — what the frontend shows — is what we use."""
    sandbox, db_file = ws_env
    expected = sandbox / "workspaces" / "uo-outlands-guild-system"
    _insert(db_file, "f0c3149b-853f-496c-bdfa-3dc883c9d17a", "UO Outlands Guild System", str(expected))

    assert resolve_workspace_dir("f0c3149b-853f-496c-bdfa-3dc883c9d17a") == expected


def test_falls_back_to_slugified_title_when_local_path_null(ws_env):
    """Rows predating the backfill still resolve to a readable name, not the id."""
    sandbox, db_file = ws_env
    _insert(db_file, "8783efc6-9d1f-4041-ad88-3470d1d81852", "Home Automation", None)

    resolved = resolve_workspace_dir("8783efc6-9d1f-4041-ad88-3470d1d81852")
    assert resolved == sandbox / "workspaces" / "home-automation"
    assert "8783efc6" not in str(resolved)


def test_external_checkout_is_used_when_it_exists(ws_env, tmp_path):
    sandbox, db_file = ws_env
    checkout = tmp_path / "projects" / "toshokan-cms"
    checkout.mkdir(parents=True)
    _insert(db_file, "33db87b1", "Toshokan CMS", str(checkout))

    assert resolve_workspace_dir("33db87b1") == checkout


def test_missing_external_checkout_falls_back_to_sandbox(ws_env, tmp_path):
    """A stale external path must not be silently re-created as an empty tree."""
    sandbox, db_file = ws_env
    _insert(db_file, "bf887632", "CTOTD", str(tmp_path / "gone" / "ctotd-site"))

    assert resolve_workspace_dir("bf887632") == sandbox / "workspaces" / "ctotd"


def test_sandbox_area_never_returns_an_external_checkout(ws_env, tmp_path):
    """Voxyflow control files must not be written into the user's own repo.

    The worker cwd follows the external checkout; the sandbox area does not.
    """
    sandbox, db_file = ws_env
    checkout = tmp_path / "projects" / "toshokan-cms"
    checkout.mkdir(parents=True)
    _insert(db_file, "33db87b1", "Toshokan CMS", str(checkout))

    assert resolve_workspace_dir("33db87b1") == checkout
    assert workspace_sandbox_area("33db87b1") == sandbox / "workspaces" / "toshokan-cms"


def test_heartbeat_file_uses_the_readable_sandbox_area(ws_env, tmp_path):
    """The autonomy directive used to be keyed by id — regression guard."""
    from app.services import workspace_autonomy

    sandbox, db_file = ws_env
    checkout = tmp_path / "projects" / "toshokan-cms"
    checkout.mkdir(parents=True)
    _insert(db_file, "33db87b1", "Toshokan CMS", str(checkout))

    path = workspace_autonomy.heartbeat_file("33db87b1")
    assert path == sandbox / "workspaces" / "toshokan-cms" / "heartbeat.md"
    assert "33db87b1" not in str(path)
    assert not path.is_relative_to(checkout)


def test_heartbeat_gate_is_reresolved_not_trusted(ws_env, tmp_path):
    """A stale gate path in jobs.json must not silently mute the heartbeat.

    ``build_job_dict`` freezes the heartbeat path into ``jobs.json`` when
    autonomy is enabled. That snapshot goes stale on a rename, and went stale
    for every install when the id-keyed folders were migrated to readable
    names — the gate would then check a file nobody writes and the heartbeat
    would stop firing with no error anywhere.
    """
    from app.services.job_runner import _check_payload_gate

    sandbox, db_file = ws_env
    _insert(db_file, "f0c3149b", "UO Outlands Guild System", None)

    live = sandbox / "workspaces" / "uo-outlands-guild-system" / "heartbeat.md"
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_text("# preamble\n---\nDo the thing.\n", encoding="utf-8")

    payload = {
        "workspace_id": "f0c3149b",
        "workspace_heartbeat": True,
        # The pre-migration snapshot: an id-keyed path that no longer exists.
        "gate": {
            "type": "file_has_directive",
            "path": str(sandbox / "workspaces" / "f0c3149b" / "heartbeat.md"),
            "divider": "---",
        },
    }

    assert _check_payload_gate({"id": "proj-heartbeat-f0c3149b"}, payload) is None


def test_non_heartbeat_file_gate_keeps_its_explicit_path(ws_env, tmp_path):
    """Only heartbeats re-resolve; an arbitrary file gate stays literal."""
    from app.services.job_runner import _check_payload_gate

    empty = tmp_path / "nothing.md"
    empty.write_text("# preamble only\n", encoding="utf-8")
    payload = {
        "workspace_id": "f0c3149b",
        "gate": {"type": "file_has_directive", "path": str(empty), "divider": "---"},
    }

    result = _check_payload_gate({"id": "some-other-job"}, payload)
    assert result is not None and result["status"] == "skipped"


def test_unknown_id_falls_back_to_sanitized_id(ws_env):
    """No row (tests, deleted workspace) — the id-keyed folder is the last resort."""
    sandbox, _ = ws_env
    assert resolve_workspace_dir("bogus-id-xyz") == sandbox / "workspaces" / "bogus-id-xyz"


def test_empty_id_is_system_main(ws_env):
    sandbox, _ = ws_env
    assert resolve_workspace_dir("") == sandbox / "workspaces" / "system-main"
    assert resolve_workspace_dir(None) == sandbox / "workspaces" / "system-main"


def test_broken_mount_does_not_raise(ws_env, monkeypatch):
    """os.stat on a dead mount raises OSError; system.exec must survive it."""
    sandbox, db_file = ws_env
    _insert(db_file, "37125887", "Voxyflow", "/mnt/dead-nfs/voxyflow-rog")

    def _boom(self):
        raise OSError(5, "Input/output error")

    monkeypatch.setattr(Path, "is_dir", _boom)
    assert resolve_workspace_dir("37125887") == sandbox / "workspaces" / "voxyflow"


def test_creation_and_runtime_agree(ws_env):
    """THE invariant: the folder creation makes is the folder workers resolve.

    ``SandboxService.ensure_workspace_sandbox`` (the creation route) and
    ``resolve_workspace_dir`` (the worker runtime) must never disagree — the
    drift between them is the bug this module exists to prevent.
    """
    sandbox, db_file = ws_env
    title = "UO Outlands Guild System"

    service = SandboxService()
    service._sandbox_root = sandbox
    created = service.ensure_workspace_sandbox(title)

    _insert(db_file, "ws-1", title, str(created))
    assert resolve_workspace_dir("ws-1") == created


def test_slugify_has_a_single_implementation():
    """SandboxService must delegate, not keep a second copy of the rules."""
    service = SandboxService()
    for name in ["UO Outlands Guild System", "🚀 Voxyflow Launch HQ", "Voxy's Dreamlab", "  ", "D&D Web App"]:
        assert service._slugify(name) == slugify(name)


def test_slugify_produces_readable_names():
    assert slugify("UO Outlands Guild System") == "uo-outlands-guild-system"
    assert slugify("🚀 Voxyflow Launch HQ") == "voxyflow-launch-hq"
    assert slugify("Voxy's Dreamlab") == "voxys-dreamlab"
    assert slugify("") == "unnamed"


def test_sanitize_id_never_escapes_a_directory_level():
    assert "/" not in sanitize_id("../../etc/passwd")
    assert sanitize_id("") == "system-main"
