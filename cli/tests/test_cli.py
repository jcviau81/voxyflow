"""Offline unit tests for the voxy CLI — no live backend required."""

import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from voxy.chatws import build_chat_envelope, build_session_sync
from voxy.client import CliError, resolve_workspace
from voxy.commands.skills import parse_frontmatter
from voxy.config import load_token, ws_url


# ---------------------------------------------------------------------------
# Workspace-name resolution
# ---------------------------------------------------------------------------

WORKSPACES = [
    {"id": "aaa-111", "title": "Voxyflow Dev"},
    {"id": "bbb-222", "title": "Personal"},
    {"id": "ccc-333", "title": "personal"},  # ambiguous with bbb-222 by name
    {"id": "ddd-444", "title": "Groceries"},
]


class TestResolveWorkspace:
    def test_resolve_by_exact_id(self):
        assert resolve_workspace(WORKSPACES, "aaa-111")["title"] == "Voxyflow Dev"

    def test_resolve_by_title_case_insensitive(self):
        assert resolve_workspace(WORKSPACES, "voxyflow dev")["id"] == "aaa-111"
        assert resolve_workspace(WORKSPACES, "VOXYFLOW DEV")["id"] == "aaa-111"

    def test_resolve_by_unique_prefix(self):
        assert resolve_workspace(WORKSPACES, "groc")["id"] == "ddd-444"

    def test_ambiguous_title_raises(self):
        with pytest.raises(CliError, match="ambiguous"):
            resolve_workspace(WORKSPACES, "Personal")

    def test_not_found_raises(self):
        with pytest.raises(CliError, match="not found"):
            resolve_workspace(WORKSPACES, "nonexistent")

    def test_id_match_wins_over_title(self):
        spaces = [{"id": "x", "title": "y"}, {"id": "y", "title": "z"}]
        assert resolve_workspace(spaces, "y")["title"] == "z"


# ---------------------------------------------------------------------------
# Envelope construction
# ---------------------------------------------------------------------------

class TestEnvelopes:
    def test_chat_envelope_shape(self):
        env = build_chat_envelope(
            "hello", session_id="sess-1", message_id="msg-1",
            workspace_id="ws-1", deep=True,
        )
        assert env["type"] == "chat:message"
        assert isinstance(env["timestamp"], int)
        p = env["payload"]
        assert p["content"] == "hello"
        assert p["messageId"] == "msg-1"
        assert p["sessionId"] == "sess-1"
        assert p["workspaceId"] == "ws-1"
        assert p["layers"] == {"deep": True}
        assert "cardId" not in p

    def test_chat_envelope_defaults(self):
        env = build_chat_envelope("hi", session_id="s")
        p = env["payload"]
        assert p["layers"] == {"deep": False}
        assert "workspaceId" not in p
        # auto-generated messageId is a valid uuid
        uuid.UUID(p["messageId"])

    def test_chat_envelope_card_id(self):
        env = build_chat_envelope("hi", session_id="s", card_id="card-9")
        assert env["payload"]["cardId"] == "card-9"

    def test_chat_envelope_is_json_serializable(self):
        json.dumps(build_chat_envelope("hi", session_id="s"))

    def test_session_sync_envelope(self):
        env = build_session_sync("sess-42")
        assert env["type"] == "session:sync"
        assert env["payload"] == {"sessionId": "sess-42"}
        assert isinstance(env["timestamp"], int)


# ---------------------------------------------------------------------------
# Token loading
# ---------------------------------------------------------------------------

class TestLoadToken:
    def test_reads_token_from_file(self, tmp_path):
        token_file = tmp_path / "auth_token"
        token_file.write_text("file-token\n")
        http_get = MagicMock()
        assert load_token("http://x", token_path=token_file, http_get=http_get) == "file-token"
        http_get.assert_not_called()

    def test_bootstraps_and_caches_when_file_missing(self, tmp_path):
        token_file = tmp_path / "sub" / "auth_token"
        resp = MagicMock()
        resp.json.return_value = {"token": "boot-token"}
        resp.raise_for_status.return_value = None
        http_get = MagicMock(return_value=resp)

        token = load_token("http://backend:1234", token_path=token_file, http_get=http_get)

        assert token == "boot-token"
        http_get.assert_called_once()
        assert http_get.call_args[0][0] == "http://backend:1234/api/auth/bootstrap"
        # cached back to disk with restrictive mode
        assert token_file.read_text().strip() == "boot-token"
        assert (token_file.stat().st_mode & 0o777) == 0o600

    def test_empty_file_falls_back_to_bootstrap(self, tmp_path):
        token_file = tmp_path / "auth_token"
        token_file.write_text("")
        resp = MagicMock()
        resp.json.return_value = {"token": "t2"}
        resp.raise_for_status.return_value = None
        http_get = MagicMock(return_value=resp)
        assert load_token("http://x", token_path=token_file, http_get=http_get) == "t2"

    def test_bootstrap_without_token_raises(self, tmp_path):
        resp = MagicMock()
        resp.json.return_value = {}
        resp.raise_for_status.return_value = None
        http_get = MagicMock(return_value=resp)
        with pytest.raises(RuntimeError):
            load_token("http://x", token_path=tmp_path / "none", http_get=http_get)


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

class TestWsUrl:
    def test_http(self):
        assert ws_url("http://localhost:8000") == "ws://localhost:8000/ws"

    def test_https(self):
        assert ws_url("https://voxy.example.com") == "wss://voxy.example.com/ws"


class TestFrontmatter:
    def test_parses_name_and_description(self):
        text = "---\nname: my-skill\ndescription: Does things\n---\n# Body\ncontent"
        meta, body = parse_frontmatter(text)
        assert meta["name"] == "my-skill"
        assert meta["description"] == "Does things"
        assert body.strip().startswith("# Body")

    def test_no_frontmatter(self):
        meta, body = parse_frontmatter("# Just markdown")
        assert meta == {}
        assert body == "# Just markdown"


# ---------------------------------------------------------------------------
# voxy use — persistent default workspace
# ---------------------------------------------------------------------------

from voxy.config import (  # noqa: E402
    clear_default_workspace,
    effective_workspace_ref,
    get_default_workspace,
    load_cli_config,
    set_default_workspace,
)


class TestCliConfig:
    def test_roundtrip(self, tmp_path):
        p = tmp_path / "cli.json"
        assert get_default_workspace(p) is None
        set_default_workspace("ws-123", "Voxyflow", p)
        ws = get_default_workspace(p)
        assert ws == {"id": "ws-123", "title": "Voxyflow"}
        clear_default_workspace(p)
        assert get_default_workspace(p) is None

    def test_clear_preserves_other_keys(self, tmp_path):
        p = tmp_path / "cli.json"
        p.write_text('{"other": 1, "workspace": {"id": "a", "title": "A"}}')
        clear_default_workspace(p)
        assert load_cli_config(p) == {"other": 1}

    def test_corrupt_file_is_empty_config(self, tmp_path):
        p = tmp_path / "cli.json"
        p.write_text("{not json")
        assert load_cli_config(p) == {}
        assert get_default_workspace(p) is None


class TestEffectiveWorkspaceRef:
    DEFAULT = {"id": "ws-default", "title": "Default WS"}

    def test_explicit_option_wins(self):
        assert effective_workspace_ref("other", self.DEFAULT) == "other"

    def test_general_forces_none(self):
        for ref in ("general", "GENERAL", "main", "home", "none"):
            assert effective_workspace_ref(ref, self.DEFAULT) is None

    def test_default_applies_when_no_option(self):
        assert effective_workspace_ref(None, self.DEFAULT) == "ws-default"

    def test_no_option_no_default_is_general(self):
        assert effective_workspace_ref(None, None) is None


# ---------------------------------------------------------------------------
# voxy config — dotted-path settings access
# ---------------------------------------------------------------------------

from voxy.commands.config_cmd import get_path, parse_value, set_path  # noqa: E402

SETTINGS = {
    "assistant_name": "Voxy",
    "models": {
        "fast": {"model": "claude-haiku-4-5", "provider_type": "cli"},
        "endpoints": [{"id": "e1", "name": "Mac", "api_key": "***"}],
    },
    "voice": {"tts_enabled": True},
}


class TestDottedPath:
    def test_get_nested(self):
        assert get_path(SETTINGS, "models.fast.model") == "claude-haiku-4-5"

    def test_get_list_index(self):
        assert get_path(SETTINGS, "models.endpoints.0.name") == "Mac"

    def test_get_unknown_key_raises_with_siblings(self):
        with pytest.raises(CliError, match="unknown key"):
            get_path(SETTINGS, "models.fastt")

    def test_get_bad_index_raises(self):
        with pytest.raises(CliError, match="out of range"):
            get_path(SETTINGS, "models.endpoints.5")
        with pytest.raises(CliError, match="not a list index"):
            get_path(SETTINGS, "models.endpoints.first")

    def test_get_descend_into_scalar_raises(self):
        with pytest.raises(CliError, match="cannot descend"):
            get_path(SETTINGS, "assistant_name.x")

    def test_set_returns_old_value(self):
        data = json.loads(json.dumps(SETTINGS))
        old = set_path(data, "models.fast.model", "claude-sonnet-4-6")
        assert old == "claude-haiku-4-5"
        assert data["models"]["fast"]["model"] == "claude-sonnet-4-6"

    def test_set_in_list(self):
        data = json.loads(json.dumps(SETTINGS))
        set_path(data, "models.endpoints.0.api_key", "sk-real")
        assert data["models"]["endpoints"][0]["api_key"] == "sk-real"

    def test_set_unknown_leaf_raises(self):
        data = json.loads(json.dumps(SETTINGS))
        with pytest.raises(CliError, match="unknown key"):
            set_path(data, "models.fast.modle", "x")

    def test_set_scalar_over_container_raises(self):
        data = json.loads(json.dumps(SETTINGS))
        with pytest.raises(CliError, match="is a dict"):
            set_path(data, "models.fast", "oops")

    def test_parse_value(self):
        assert parse_value("true") is True
        assert parse_value("5") == 5
        assert parse_value('{"a": 1}') == {"a": 1}
        assert parse_value("plain string") == "plain string"
        assert parse_value("claude-haiku-4-5") == "claude-haiku-4-5"


# ---------------------------------------------------------------------------
# voxy update — repo discovery + diff-driven plan
# ---------------------------------------------------------------------------

from voxy.repo import find_repo_root, plan_update  # noqa: E402


class TestFindRepoRoot:
    def test_finds_checkout_from_nested_path(self, tmp_path):
        (tmp_path / ".git").mkdir()
        (tmp_path / "backend").mkdir()
        (tmp_path / "cli").mkdir()
        nested = tmp_path / "cli" / "voxy" / "repo.py"
        nested.parent.mkdir(parents=True)
        nested.write_text("")
        assert find_repo_root(nested) == tmp_path

    def test_none_outside_a_checkout(self, tmp_path):
        f = tmp_path / "somewhere" / "repo.py"
        f.parent.mkdir(parents=True)
        f.write_text("")
        assert find_repo_root(f) is None

    def test_plain_git_repo_without_layout_is_not_voxyflow(self, tmp_path):
        (tmp_path / ".git").mkdir()
        f = tmp_path / "x.py"
        f.write_text("")
        assert find_repo_root(f) is None


class TestPlanUpdate:
    def test_backend_change_restarts_only(self):
        plan = plan_update(["backend/app/main.py"])
        assert plan == {"pip": False, "cli": False, "frontend": False, "backend_restart": True}

    def test_requirements_change_triggers_pip(self):
        assert plan_update(["backend/requirements.txt"])["pip"] is True

    def test_frontend_change_triggers_build_not_restart(self):
        plan = plan_update(["frontend-react/src/App.tsx"])
        assert plan["frontend"] is True
        assert plan["backend_restart"] is False

    def test_cli_code_change_needs_no_reinstall(self):
        plan = plan_update(["cli/voxy/app.py"])
        assert plan["cli"] is False  # editable install — code applies immediately

    def test_cli_packaging_change_reinstalls(self):
        assert plan_update(["cli/pyproject.toml"])["cli"] is True

    def test_docs_only_change_is_a_noop(self):
        plan = plan_update(["README.md", "docs/CLI.md"])
        assert plan == {"pip": False, "cli": False, "frontend": False, "backend_restart": False}

    def test_full_forces_everything(self):
        plan = plan_update([], full=True)
        assert all(plan.values())
