"""Smoke test — project isolation in Voxyflow.

Run from backend/ with venv activated:
  cd backend && source venv/bin/activate && python scripts/smoke_test_isolation.py

This script verifies a set of fixes landed on main in April 2026 to prevent
cross-project context leaks in Voxy's memory / knowledge / chat layers.

It deliberately avoids importing anything that requires the backend server
to be running (no FastAPI app boot, no WebSocket, no subprocess spawn).
"""
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND))

PASS_COUNT = 0
FAIL_COUNT = 0
SKIP_COUNT = 0


def test(name):
    def decorator(fn):
        def wrapper():
            global PASS_COUNT, FAIL_COUNT, SKIP_COUNT
            try:
                result = fn()
                if result == "SKIP":
                    print(f"[SKIP] {name}")
                    SKIP_COUNT += 1
                else:
                    print(f"[PASS] {name}")
                    PASS_COUNT += 1
            except AssertionError as e:
                print(f"[FAIL] {name}: {e}")
                FAIL_COUNT += 1
            except Exception as e:
                print(f"[FAIL] {name}: unexpected {type(e).__name__}: {e}")
                FAIL_COUNT += 1
        return wrapper
    return decorator


# --- Test 1: memory constants ---------------------------------------------
@test("memory constants — GLOBAL_COLLECTION renamed, _project_collection by ID")
def test_memory_constants():
    from app.services.memory_service import GLOBAL_COLLECTION, _project_collection
    assert GLOBAL_COLLECTION == "memory-global", \
        f"expected 'memory-global', got {GLOBAL_COLLECTION!r}"
    assert _project_collection("abc-123") == "memory-project-abc-123", \
        f"expected 'memory-project-abc-123', got {_project_collection('abc-123')!r}"
    assert _project_collection("system-main") == "memory-project-system-main", \
        f"expected 'memory-project-system-main', got {_project_collection('system-main')!r}"


# --- Test 2: search_memory requires collections ---------------------------
@test("search_memory raises ValueError when collections=None")
def test_search_requires_collections():
    try:
        from app.services.memory_service import MemoryService
    except ImportError:
        return "SKIP"  # chromadb not installed

    ms = MemoryService()
    if not ms._chromadb_enabled:
        return "SKIP"

    try:
        ms.search_memory(query="test")
    except ValueError as e:
        assert "collections" in str(e).lower(), f"wrong error message: {e}"
        return
    raise AssertionError("expected ValueError, none raised")


# --- Test 3: search_memory accepts explicit collections -------------------
@test("search_memory works with explicit collections=")
def test_search_with_collections():
    try:
        from app.services.memory_service import MemoryService, GLOBAL_COLLECTION
    except ImportError:
        return "SKIP"

    ms = MemoryService()
    if not ms._chromadb_enabled:
        return "SKIP"

    # Should not raise — empty result or actual results both OK
    results = ms.search_memory(query="test", collections=[GLOBAL_COLLECTION])
    assert isinstance(results, list), f"expected list, got {type(results).__name__}"


# --- Test 4: MCP memory_search handler reads env var ----------------------
@test("mcp.memory.search handler reads VOXYFLOW_PROJECT_ID env")
def test_mcp_handler_reads_env():
    """Verify the memory_search handler picks up VOXYFLOW_PROJECT_ID from env.

    Implementation note: each handler in mcp_server._get_system_handler() does
    ``from app.services.memory_service import get_memory_service`` at CALL time
    (inside the handler body), not at module import time. That means we can
    monkey-patch ``app.services.memory_service.get_memory_service`` AFTER the
    handlers are registered and the patched version will be picked up.
    """
    import asyncio
    from app.services.memory_service import _project_collection, GLOBAL_COLLECTION
    from app import mcp_server
    from app.services import memory_service as memsvc

    handler = mcp_server._get_system_handler("memory_search")
    assert handler is not None, "memory_search handler not registered"

    captured = {}

    class FakeMs:
        def search_memory(self, query, collections=None, limit=10, offset=0, **kwargs):
            captured["collections"] = collections
            captured["query"] = query
            captured["limit"] = limit
            captured["offset"] = offset
            return []

    original_get = memsvc.get_memory_service
    memsvc.get_memory_service = lambda: FakeMs()
    prev_env = os.environ.get("VOXYFLOW_PROJECT_ID")
    os.environ["VOXYFLOW_PROJECT_ID"] = "test-proj-xyz"
    try:
        result = asyncio.run(handler({"query": "hello"}))
    finally:
        memsvc.get_memory_service = original_get
        if prev_env is None:
            os.environ.pop("VOXYFLOW_PROJECT_ID", None)
        else:
            os.environ["VOXYFLOW_PROJECT_ID"] = prev_env

    assert isinstance(result, dict), f"expected dict result, got {type(result).__name__}"
    cols = captured.get("collections") or []
    expected_proj = _project_collection("test-proj-xyz")
    assert expected_proj in cols, \
        f"expected {expected_proj!r} in collections, got {cols}"
    # STRICT ISOLATION: project chats must NEVER query memory-global.
    assert GLOBAL_COLLECTION not in cols, \
        f"isolation broken: {GLOBAL_COLLECTION!r} leaked into project query, got {cols}"
    # Ensure the system-main project collection is NOT mixed in when a real
    # project_id is active (otherwise isolation is broken).
    sysmain_col = _project_collection("system-main")
    assert sysmain_col not in cols, \
        f"unexpected {sysmain_col!r} leaking into collections, got {cols}"
    # And only the project collection should be present.
    assert cols == [expected_proj], \
        f"expected exactly [{expected_proj!r}], got {cols}"


# --- Test 4b: MCP memory_search handler defaults to global + system-main --
@test("mcp.memory.search handler — empty env means global + system-main")
def test_mcp_handler_empty_env():
    """When VOXYFLOW_PROJECT_ID is empty or 'system-main', search should cover
    the global collection + the system-main project collection (the general
    chat scope)."""
    import asyncio
    from app.services.memory_service import _project_collection, GLOBAL_COLLECTION
    from app import mcp_server
    from app.services import memory_service as memsvc

    handler = mcp_server._get_system_handler("memory_search")
    assert handler is not None

    captured = {}

    class FakeMs:
        def search_memory(self, query, collections=None, limit=10, offset=0, **kwargs):
            captured["collections"] = collections
            return []

    original_get = memsvc.get_memory_service
    memsvc.get_memory_service = lambda: FakeMs()
    prev_env = os.environ.get("VOXYFLOW_PROJECT_ID")
    os.environ.pop("VOXYFLOW_PROJECT_ID", None)
    try:
        asyncio.run(handler({"query": "hello"}))
    finally:
        memsvc.get_memory_service = original_get
        if prev_env is not None:
            os.environ["VOXYFLOW_PROJECT_ID"] = prev_env

    cols = captured.get("collections") or []
    assert GLOBAL_COLLECTION in cols, f"expected global, got {cols}"
    assert _project_collection("system-main") in cols, \
        f"expected system-main project collection, got {cols}"


# --- Test 4c: _build_chromadb_context never queries global for projects ---
@test("_build_chromadb_context — Project Chat mode never queries memory-global")
def test_build_context_project_no_global():
    """When called with project_id, _build_chromadb_context must NEVER call
    search_memory with the global collection. This is the system-prompt
    memory injection path — the most exposed leak vector."""
    from app.services import memory_service as memsvc
    from app.services.memory_service import (
        MemoryService,
        GLOBAL_COLLECTION,
        _project_collection,
    )

    captured_calls = []

    class FakeMs(MemoryService):
        def __init__(self):
            self._chromadb_enabled = True

        def search_memory(self, query, collections=None, limit=10, **kwargs):
            captured_calls.append(list(collections or []))
            return []

        def _build_file_context(self, **kwargs):
            return None

    ms = FakeMs()

    # Project Chat mode
    captured_calls.clear()
    ms._build_chromadb_context(query="test", project_id="proj-xyz")
    for call_cols in captured_calls:
        assert GLOBAL_COLLECTION not in call_cols, \
            f"Project Chat leaked global into query: {call_cols}"
        assert _project_collection("system-main") not in call_cols, \
            f"Project Chat leaked system-main into query: {call_cols}"

    # Card Chat mode
    captured_calls.clear()
    ms._build_chromadb_context(query="test", project_id="proj-xyz", card_id="card-1")
    for call_cols in captured_calls:
        assert GLOBAL_COLLECTION not in call_cols, \
            f"Card Chat leaked global into query: {call_cols}"

    # General/Main Chat mode (no project_id) — global IS allowed
    captured_calls.clear()
    ms._build_chromadb_context(query="test")
    flat = [c for call in captured_calls for c in call]
    assert GLOBAL_COLLECTION in flat, \
        f"General Chat must query global, got {captured_calls}"


# --- Test 5: cli_backend injects VOXYFLOW_PROJECT_ID ----------------------
@test("cli_backend._build_mcp_config injects VOXYFLOW_PROJECT_ID")
def test_cli_backend_injects_env():
    import json
    from app.services.llm.cli_backend import ClaudeCliBackend

    b = ClaudeCliBackend()

    # With explicit project_id
    cfg_str = b._build_mcp_config(role="dispatcher", project_id="proj-abc")
    cfg = json.loads(cfg_str)
    env = cfg["mcpServers"]["voxyflow"]["env"]
    assert env.get("VOXYFLOW_PROJECT_ID") == "proj-abc", \
        f"expected 'proj-abc', got {env.get('VOXYFLOW_PROJECT_ID')!r}"

    # Default should be system-main (empty project_id)
    cfg_str2 = b._build_mcp_config(role="dispatcher")
    cfg2 = json.loads(cfg_str2)
    env2 = cfg2["mcpServers"]["voxyflow"]["env"]
    assert env2.get("VOXYFLOW_PROJECT_ID") == "system-main", \
        f"expected 'system-main', got {env2.get('VOXYFLOW_PROJECT_ID')!r}"

    # Worker role with explicit project_id
    cfg_str3 = b._build_mcp_config(role="worker", project_id="proj-worker-42")
    cfg3 = json.loads(cfg_str3)
    env3 = cfg3["mcpServers"]["voxyflow"]["env"]
    assert env3.get("VOXYFLOW_PROJECT_ID") == "proj-worker-42"
    assert env3.get("VOXYFLOW_MCP_ROLE") == "worker"


# --- Test 6: chat_id validation logic replica ------------------------------
@test("chat_id validation rejects mismatched frontend chatId")
def test_chat_id_validation():
    """Exercise the shared ``resolve_chat_id`` helper that main.py uses."""
    from app.services.chat_id_utils import resolve_chat_id

    def derive_chat_id(project_id, card_id, frontend_chat_id):
        chat_id, _, _ = resolve_chat_id(project_id, card_id, frontend_chat_id)
        return chat_id

    # Exact match — passthrough
    assert derive_chat_id("A", None, "project:A") == "project:A"
    # Sub-session OK (prefix match)
    assert derive_chat_id("A", None, "project:A:s-xyz") == "project:A:s-xyz"
    # Mismatched project — rejected, fallback to canonical
    assert derive_chat_id("A", None, "project:B") == "project:A"
    # No chatId, fallback to canonical
    assert derive_chat_id("A", None, None) == "project:A"
    # Card mode — exact match
    assert derive_chat_id("A", "card-123", "card:card-123") == "card:card-123"
    # Card mode — mismatched (project-style id) rejected
    assert derive_chat_id("A", "card-123", "project:A") == "card:card-123"
    # No project, no card — canonical becomes project:system-main
    assert derive_chat_id(None, None, None) == "project:system-main"
    # No project, no card, matching frontend id
    assert derive_chat_id(None, None, "project:system-main") == "project:system-main"
    # No project, no card, bogus id — rejected
    assert derive_chat_id(None, None, "project:evil") == "project:system-main"


# --- Test 7: workers_list auto-scopes to current project ------------------
@test("mcp.workers.list auto-scopes to VOXYFLOW_PROJECT_ID; scope='all' opts out")
def test_workers_list_scoping():
    import asyncio
    from app import mcp_server
    from app.services import worker_session_store as wss_mod

    class FakeSess:
        def __init__(self, task_id, project_id, status="running"):
            self.task_id = task_id
            self.project_id = project_id
            self.status = status

        def to_dict(self):
            return {
                "task_id": self.task_id,
                "project_id": self.project_id,
                "status": self.status,
            }

    class FakeStore:
        def __init__(self):
            self._sessions = [
                FakeSess("t-home-1", "proj-home"),
                FakeSess("t-armored-1", "proj-armored"),
                FakeSess("t-home-2", "proj-home", status="done"),
            ]

        def get_sessions(self, session_id=None, include_old=False):
            return [s.to_dict() for s in self._sessions]

    original = wss_mod.get_worker_session_store
    wss_mod.get_worker_session_store = lambda: FakeStore()
    prev_env = os.environ.get("VOXYFLOW_PROJECT_ID")
    handler = mcp_server._get_system_handler("workers_list")
    assert handler is not None, "workers_list handler not registered"

    try:
        # Project chat — default scope filters to current project
        os.environ["VOXYFLOW_PROJECT_ID"] = "proj-home"
        result = asyncio.run(handler({}))
        assert result["scope"] == "project", f"expected scope=project, got {result!r}"
        assert result["project_id"] == "proj-home"
        ids = [w["task_id"] for w in result.get("workers", [])]
        assert ids == ["t-home-1", "t-home-2"], f"wrong workers: {ids}"

        # scope='all' opt-out returns the full ledger even in a project chat
        result_all = asyncio.run(handler({"scope": "all"}))
        assert result_all["scope"] == "all"
        ids_all = {w["task_id"] for w in result_all.get("workers", [])}
        assert ids_all == {"t-home-1", "t-armored-1", "t-home-2"}, \
            f"scope=all should return everything, got {ids_all}"

        # General chat — no scope filter
        os.environ.pop("VOXYFLOW_PROJECT_ID", None)
        result_gen = asyncio.run(handler({}))
        assert result_gen["scope"] == "all"
        assert len(result_gen.get("workers", [])) == 3
    finally:
        wss_mod.get_worker_session_store = original
        if prev_env is None:
            os.environ.pop("VOXYFLOW_PROJECT_ID", None)
        else:
            os.environ["VOXYFLOW_PROJECT_ID"] = prev_env


# --- Test 7b: task-scope enforcement rejects cross-project access ---------
@test("mcp._enforce_task_scope rejects tasks from other projects")
def test_enforce_task_scope():
    import asyncio
    from app import mcp_server
    from app.services import worker_session_store as wss_mod

    class FakeSess:
        def __init__(self, task_id, project_id):
            self.task_id = task_id
            self.project_id = project_id
            self.status = "running"

        def to_dict(self):
            return {
                "task_id": self.task_id,
                "project_id": self.project_id,
                "status": self.status,
            }

    class FakeStore:
        def __init__(self):
            self._sessions = {
                "t-home": FakeSess("t-home", "proj-home"),
                "t-other": FakeSess("t-other", "proj-armored"),
            }

        def get_session(self, task_id):
            s = self._sessions.get(task_id)
            return s.to_dict() if s else None

    original = wss_mod.get_worker_session_store
    wss_mod.get_worker_session_store = lambda: FakeStore()
    prev_env = os.environ.get("VOXYFLOW_PROJECT_ID")

    try:
        # Same project — allowed
        os.environ["VOXYFLOW_PROJECT_ID"] = "proj-home"
        assert asyncio.run(mcp_server._enforce_task_scope("t-home", None)) is None

        # Cross-project — rejected
        err = asyncio.run(mcp_server._enforce_task_scope("t-other", None))
        assert err is not None and "different project" in err["error"], \
            f"expected rejection, got {err!r}"

        # scope='all' bypasses the check
        assert asyncio.run(mcp_server._enforce_task_scope("t-other", "all")) is None

        # General chat — no enforcement
        os.environ.pop("VOXYFLOW_PROJECT_ID", None)
        assert asyncio.run(mcp_server._enforce_task_scope("t-other", None)) is None
    finally:
        wss_mod.get_worker_session_store = original
        if prev_env is None:
            os.environ.pop("VOXYFLOW_PROJECT_ID", None)
        else:
            os.environ["VOXYFLOW_PROJECT_ID"] = prev_env


# --- Test 7c: sessions_list auto-scopes to current project ----------------
@test("mcp.sessions.list auto-scopes CLI sessions to the current project")
def test_sessions_list_scoping():
    import asyncio
    from app import mcp_server
    from app.services import cli_session_registry as reg_mod

    class FakeRegSess:
        def __init__(self, id_, project_id):
            self.id = id_
            self.pid = 1
            self.session_id = f"sess-{id_}"
            self.chat_id = "c"
            self.project_id = project_id
            self.model = "m"
            self.session_type = "chat"
            self.started_at = 0.0

    class FakeRegistry:
        def __init__(self):
            self._sessions = [
                FakeRegSess("x", "proj-home"),
                FakeRegSess("y", "proj-armored"),
                FakeRegSess("z", "proj-home"),
            ]

        def list_active(self):
            return self._sessions

        def count(self):
            return len(self._sessions)

    original = reg_mod.get_cli_session_registry
    reg_mod.get_cli_session_registry = lambda: FakeRegistry()
    prev_env = os.environ.get("VOXYFLOW_PROJECT_ID")
    handler = mcp_server._get_system_handler("sessions_list")
    assert handler is not None

    try:
        os.environ["VOXYFLOW_PROJECT_ID"] = "proj-home"
        result = asyncio.run(handler({}))
        assert result["scope"] == "project"
        ids = sorted(s["id"] for s in result["sessions"])
        assert ids == ["x", "z"], f"expected only Home sessions, got {ids}"

        result_all = asyncio.run(handler({"scope": "all"}))
        assert result_all["scope"] == "all"
        assert result_all["count"] == 3
    finally:
        reg_mod.get_cli_session_registry = original
        if prev_env is None:
            os.environ.pop("VOXYFLOW_PROJECT_ID", None)
        else:
            os.environ["VOXYFLOW_PROJECT_ID"] = prev_env


# --- Runner ----------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("Voxyflow project isolation smoke tests")
    print("=" * 60)
    print()

    tests = [
        test_memory_constants,
        test_search_requires_collections,
        test_search_with_collections,
        test_mcp_handler_reads_env,
        test_mcp_handler_empty_env,
        test_build_context_project_no_global,
        test_cli_backend_injects_env,
        test_chat_id_validation,
        test_workers_list_scoping,
        test_enforce_task_scope,
        test_sessions_list_scoping,
    ]

    for t in tests:
        t()

    print()
    print("=" * 60)
    print(f"Results: {PASS_COUNT} passed, {FAIL_COUNT} failed, {SKIP_COUNT} skipped")
    print("=" * 60)

    sys.exit(0 if FAIL_COUNT == 0 else 1)
