"""Tests for consumer-driven artifact retention (card ace0699c).

Covers:
- read_artifact marks read_at on first call
- read_artifact works after in-memory state cleared (disk-independent)
- ack_artifact deletes the .md file, second call returns 'already acked'
- list_unread shows only un-acked items
- get_result works after supervisor purge (via disk sidecar)
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_artifact_dir(tmp_path, monkeypatch):
    """Point all artifact operations at a fresh tmp dir for each test."""
    artifact_dir = tmp_path / "worker_artifacts"
    artifact_dir.mkdir()
    monkeypatch.setenv("VOXYFLOW_DATA_DIR", str(tmp_path))
    # Clear module-level _data_dir cache if any
    import importlib
    import app.services.worker_artifact_store as store
    importlib.reload(store)
    yield artifact_dir


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_artifact(task_id: str, body: str = "hello world", **kwargs) -> str:
    """Write an artifact and return its path."""
    from app.services.worker_artifact_store import write_artifact
    path = write_artifact(task_id, body, **kwargs)
    assert path is not None
    return path


# ---------------------------------------------------------------------------
# Test: write_artifact creates meta sidecar
# ---------------------------------------------------------------------------

def test_write_artifact_creates_meta_sidecar(isolated_artifact_dir):
    from app.services.worker_artifact_store import write_artifact, meta_path
    task_id = "test-write-001"
    _make_artifact(task_id, "some content")
    mp = meta_path(task_id)
    assert mp.exists(), "meta sidecar should be created"
    meta = json.loads(mp.read_text())
    assert meta["task_id"] == task_id
    assert meta["created_at"] is not None
    assert meta["read_at"] is None
    assert meta["acked_at"] is None
    assert meta["size_bytes"] > 0


# ---------------------------------------------------------------------------
# Test: read_artifact marks read_at on first call (idempotent)
# ---------------------------------------------------------------------------

def test_read_artifact_marks_read_at(isolated_artifact_dir):
    from app.services.worker_artifact_store import read_artifact, _read_meta
    task_id = "test-read-001"
    _make_artifact(task_id, "content here")

    # First read — read_at should be set
    result = read_artifact(task_id)
    assert result is not None
    meta = _read_meta(task_id)
    assert meta is not None
    assert meta["read_at"] is not None, "read_at should be set after first read"
    first_read_at = meta["read_at"]

    # Second read — read_at should remain unchanged (idempotent)
    time.sleep(0.01)
    read_artifact(task_id)
    meta2 = _read_meta(task_id)
    assert meta2["read_at"] == first_read_at, "read_at should not change on subsequent reads"


# ---------------------------------------------------------------------------
# Test: read_artifact works after in-memory state cleared
# ---------------------------------------------------------------------------

def test_read_artifact_works_after_in_memory_purge(isolated_artifact_dir):
    """read_artifact must work by disk lookup, independent of in-memory state."""
    from app.services.worker_artifact_store import write_artifact, read_artifact
    from app.services.worker_session_store import get_worker_session_store

    task_id = "test-purge-001"
    _make_artifact(task_id, "disk content that survives purge")

    # Simulate in-memory purge by clearing the session store
    store = get_worker_session_store()
    # Add a fake session and then remove it
    if hasattr(store, '_sessions'):
        store._sessions.pop(task_id, None)

    # read_artifact should still work
    result = read_artifact(task_id)
    assert result is not None, "read_artifact must work after in-memory purge"
    assert "disk content" in result["content"]


# ---------------------------------------------------------------------------
# Test: ack_artifact deletes file, second call returns 'already acked'
# ---------------------------------------------------------------------------

def test_ack_artifact_deletes_file(isolated_artifact_dir):
    from app.services.worker_artifact_store import (
        write_artifact, ack_artifact, artifact_path, meta_path
    )
    task_id = "test-ack-001"
    _make_artifact(task_id, "ackable content")

    apath = artifact_path(task_id)
    assert apath.exists()

    result = ack_artifact(task_id)
    assert result["success"] is True
    assert "acked_at" in result
    assert result["size_bytes_freed"] > 0
    assert not apath.exists(), ".md file should be deleted after ack"

    # Meta sidecar must be kept
    mp = meta_path(task_id)
    assert mp.exists(), "meta sidecar must survive ack"
    meta = json.loads(mp.read_text())
    assert meta["acked_at"] is not None


def test_ack_artifact_double_ack_returns_error(isolated_artifact_dir):
    from app.services.worker_artifact_store import ack_artifact
    task_id = "test-ack-002"
    _make_artifact(task_id, "content")

    result1 = ack_artifact(task_id)
    assert result1["success"] is True

    result2 = ack_artifact(task_id)
    assert result2["success"] is False
    assert "Already acked" in result2["error"]


def test_ack_artifact_unknown_task(isolated_artifact_dir):
    from app.services.worker_artifact_store import ack_artifact
    result = ack_artifact("nonexistent-task-id")
    assert result["success"] is False
    assert "Unknown task" in result["error"]


# ---------------------------------------------------------------------------
# Test: list_unread shows only un-acked items
# ---------------------------------------------------------------------------

def test_list_unread_shows_only_unacked(isolated_artifact_dir):
    from app.services.worker_artifact_store import (
        write_artifact, ack_artifact, list_unread
    )

    # Write 3 artifacts
    for i in range(3):
        _make_artifact(f"task-unread-{i:03d}", f"content {i}")

    # Ack one of them
    ack_artifact("task-unread-001")

    unread = list_unread()
    unread_ids = {u["task_id"] for u in unread}
    assert "task-unread-000" in unread_ids
    assert "task-unread-002" in unread_ids
    assert "task-unread-001" not in unread_ids, "acked artifact should not appear in list_unread"


def test_list_unread_includes_summary_preview(isolated_artifact_dir):
    from app.services.worker_artifact_store import write_artifact, write_completion, list_unread
    task_id = "test-preview-001"
    _make_artifact(task_id, "body")
    write_completion(task_id, {"summary": "A" * 300, "status": "success"})

    unread = list_unread()
    entry = next((u for u in unread if u["task_id"] == task_id), None)
    assert entry is not None
    assert entry["summary_preview"] is not None
    assert len(entry["summary_preview"]) == 200, "summary_preview should be truncated to 200 chars"


def test_list_unread_sorted_desc(isolated_artifact_dir):
    """list_unread should be sorted by created_at descending."""
    from app.services.worker_artifact_store import write_artifact, list_unread
    import time

    for i in range(3):
        _make_artifact(f"task-sort-{i:03d}", f"content {i}")
        time.sleep(0.02)  # ensure distinct timestamps

    unread = list_unread()
    ids = [u["task_id"] for u in unread if u["task_id"].startswith("task-sort-")]
    assert ids == ["task-sort-002", "task-sort-001", "task-sort-000"], (
        f"Expected descending order, got: {ids}"
    )


# ---------------------------------------------------------------------------
# Test: get_result works after in-memory supervisor purge (disk sidecar)
# ---------------------------------------------------------------------------

def test_get_result_after_supervisor_purge(isolated_artifact_dir):
    """workers.get_result must reconstruct from disk when supervisor GC'd."""
    from app.services.worker_artifact_store import write_artifact, write_completion
    from app.services.worker_supervisor import get_worker_supervisor

    task_id = "test-getresult-001"
    _make_artifact(task_id, "full output here", status="success", intent="test")
    write_completion(task_id, {
        "status": "success",
        "summary": "Test completed",
        "findings": ["finding 1"],
    })

    # Purge from supervisor
    supervisor = get_worker_supervisor()
    supervisor.cleanup_task(task_id)
    # WorkerSupervisor doesn't expose get_task; verify task was cleaned up via is_completed
    assert not supervisor.is_completed(task_id)

    # read_completion (used by get_result fallback) must still work
    from app.services.worker_artifact_store import read_completion
    comp = read_completion(task_id)
    assert comp is not None
    assert comp["summary"] == "Test completed"

    # read_artifact_meta must also work
    from app.services.worker_artifact_store import read_artifact_meta
    meta = read_artifact_meta(task_id)
    assert meta is not None
    assert meta.get("status") == "success"


# ---------------------------------------------------------------------------
# Test: legacy artifact (no meta sidecar) — backward compat
# ---------------------------------------------------------------------------

def test_legacy_artifact_no_meta_sidecar(isolated_artifact_dir):
    """Artifacts written before meta sidecars were introduced should work."""
    from app.services.worker_artifact_store import (
        artifact_path, meta_path, read_artifact, ack_artifact
    )
    task_id = "legacy-001"

    # Write raw artifact WITHOUT creating a meta sidecar (simulates old behavior)
    apath = artifact_path(task_id)
    apath.write_text("---\ntask_id: \"legacy-001\"\n---\n\nlegacy body\n", encoding="utf-8")
    assert not meta_path(task_id).exists(), "no meta sidecar for legacy artifact"

    # read_artifact should synthesize meta and mark read_at
    result = read_artifact(task_id)
    assert result is not None
    assert "legacy body" in result["content"]
    assert meta_path(task_id).exists(), "meta sidecar should be created on first read"

    meta = json.loads(meta_path(task_id).read_text())
    assert meta["read_at"] is not None

    # ack_artifact should work on legacy artifact too
    ack_result = ack_artifact(task_id)
    assert ack_result["success"] is True


# ---------------------------------------------------------------------------
# Test: delete_artifact closes the lifecycle (no ghosts in list_unread)
# ---------------------------------------------------------------------------

def test_delete_artifact_stamps_acked_and_hides_from_unread(isolated_artifact_dir):
    """Internally-deleted artifacts must not linger in list_unread as ghosts."""
    from app.services.worker_artifact_store import (
        delete_artifact, list_unread, meta_path, artifact_path
    )
    task_id = "test-delete-001"
    _make_artifact(task_id, "to be internally deleted")

    assert delete_artifact(task_id) is True
    assert not artifact_path(task_id).exists()

    # Meta sidecar is kept as a historical trace, but acked_at is stamped
    meta = json.loads(meta_path(task_id).read_text())
    assert meta["acked_at"] is not None

    unread_ids = {u["task_id"] for u in list_unread()}
    assert task_id not in unread_ids, "deleted artifact must not appear in list_unread"


# ---------------------------------------------------------------------------
# Test: atomic writes leave no .tmp leftovers
# ---------------------------------------------------------------------------

def test_atomic_writes_leave_no_tmp_files(isolated_artifact_dir):
    from app.services.worker_artifact_store import write_artifact, write_completion, _data_dir
    task_id = "test-atomic-001"
    _make_artifact(task_id, "atomic body")
    write_completion(task_id, {"summary": "done", "status": "success"})

    leftovers = list(_data_dir().glob("*.tmp"))
    assert leftovers == [], f".tmp files should be replaced into place, found: {leftovers}"


# ---------------------------------------------------------------------------
# Test: orphan scan is throttled
# ---------------------------------------------------------------------------

def test_orphan_check_throttled(isolated_artifact_dir):
    """The orphan scan must run at most once per ORPHAN_CHECK_INTERVAL_S."""
    import app.services.worker_artifact_store as store

    store._last_orphan_check = 0.0
    _make_artifact("test-throttle-001", "a")  # triggers a scan
    first_stamp = store._last_orphan_check
    assert first_stamp > 0.0

    _make_artifact("test-throttle-002", "b")  # within the interval — no rescan
    assert store._last_orphan_check == first_stamp, (
        "orphan scan should not rerun within ORPHAN_CHECK_INTERVAL_S"
    )


# ---------------------------------------------------------------------------
# Test: cleanup_old does NOT delete artifacts
# ---------------------------------------------------------------------------

def test_cleanup_old_does_not_delete_artifacts(isolated_artifact_dir):
    """cleanup_old removes in-memory sessions but must NOT delete artifact files."""
    from app.services.worker_artifact_store import write_artifact, artifact_path
    from app.services.worker_session_store import get_worker_session_store, WorkerSession

    task_id = "test-cleanup-001"
    _make_artifact(task_id, "should survive cleanup")

    store = get_worker_session_store()
    # Inject a fake old session
    from unittest.mock import MagicMock
    session = MagicMock()
    session.status = "done"
    session.start_time = time.time() - 999999  # very old
    if hasattr(store, '_sessions'):
        store._sessions[task_id] = session
        removed = store.cleanup_old(max_age_seconds=1)
        assert removed >= 1

    # Artifact must still exist
    assert artifact_path(task_id).exists(), (
        "artifact must NOT be deleted by cleanup_old (consumer-driven retention)"
    )


# ---------------------------------------------------------------------------
# Test: workers.list_unread MCP handler is workspace-scoped
# ---------------------------------------------------------------------------

def test_list_unread_handler_scoped_to_workspace(isolated_artifact_dir, monkeypatch):
    """The MCP workers.list_unread handler must not leak artifact summaries
    across workspaces: a workspace chat only sees its own workspace's
    artifacts unless scope='all' is passed (same boundary as workers.list)."""
    import asyncio
    from app.mcp_server import _get_system_handler

    _make_artifact("test-scope-a", "output A", workspace_id="WS-A")
    _make_artifact("test-scope-b", "output B", workspace_id="WS-B")

    handler = _get_system_handler("workers_list_unread")
    assert handler is not None

    # Workspace chat → only WS-A artifacts visible.
    monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", "WS-A")
    res = asyncio.run(handler({}))
    assert res["success"] and res["scope"] == "workspace"
    assert [e["task_id"] for e in res["unread"]] == ["test-scope-a"]

    # Explicit scope='all' bypasses the filter.
    res_all = asyncio.run(handler({"scope": "all"}))
    assert res_all["scope"] == "all"
    assert sorted(e["task_id"] for e in res_all["unread"]) == ["test-scope-a", "test-scope-b"]

    # General chat (system-main) sees everything.
    monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", "system-main")
    res_gen = asyncio.run(handler({}))
    assert res_gen["scope"] == "all" and res_gen["count"] == 2
