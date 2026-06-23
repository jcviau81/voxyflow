"""Tests — memory curation job + nl_task proactive autonomy.

Covers:
1. Curation writes to the CORRECT collection per scope and never crosses
   the workspace/global isolation boundary (LLM mocked with canned JSON).
2. Curation reconciles the temporal KG via invalidate-then-add (real KG
   service against the test DB) and closes stale facts.
3. Curation dedupes near-duplicate memories via semantic similarity.
4. nl_task: REST CRUD roundtrip with the new job type.
5. nl_task handler enqueues the prompt through the orchestrator with the
   right workspace scope and delivers the result (orchestrator mocked).
6. voxyflow.jobs.schedule_nl MCP handler: env-scoped job creation +
   garbage-schedule rejection.
7. normalize_schedule unit coverage.
"""

import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.memory_service_constants import GLOBAL_COLLECTION, _workspace_collection


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeMemoryService:
    """Captures store/search calls; configurable dedupe hit."""

    def __init__(self, search_results=None):
        self._chromadb_enabled = True
        self.stored = []          # list of (text, collection, metadata)
        self.searched = []        # list of collections lists
        self._search_results = search_results or []

    def search_memory(self, query, collections=None, limit=10, **kwargs):
        if collections is None:
            raise ValueError("collections= is required for search_memory")
        self.searched.append(list(collections))
        return list(self._search_results)

    def store_memory(self, text, collection, metadata=None):
        self.stored.append((text, collection, dict(metadata or {})))
        return f"mem-{uuid.uuid4().hex[:8]}"


class FakeKg:
    """No-op KG used when a test only exercises the memory side."""

    async def add_entity(self, name, etype, workspace_id, properties=None):
        return f"e-{name}"

    async def add_attribute(self, entity_id, key, value):
        return f"a-{key}"

    async def add_triple(self, s, p, o, confidence=1.0, source="auto"):
        return "t-1"

    async def get_timeline(self, workspace_id, entity_name=None, limit=50):
        return []

    async def query_relationships(self, workspace_id, entity_name=None,
                                  predicate=None, as_of=None, limit=20):
        return []

    async def invalidate(self, triple_id=None, attribute_id=None, workspace_id=None):
        return True


def _canned_llm(payload):
    """Return an async _llm_curate replacement yielding ``payload``."""
    async def _fake(messages_block, scope_label):
        return payload
    return _fake


_MSGS = [
    {"role": "user", "content": "On passe à Redis 7 pour le cache."},
    {"role": "assistant", "content": "Noté — Redis 7 remplace la version 6."},
]


# ---------------------------------------------------------------------------
# 1+2. Curation — collection isolation per scope
# ---------------------------------------------------------------------------


async def test_curation_workspace_scope_never_touches_global(monkeypatch):
    from app.services import memory_curation as mc
    from app.services import memory_service as memsvc
    from app.services import knowledge_graph_service as kgsvc

    ms = FakeMemoryService()
    monkeypatch.setattr(memsvc, "get_memory_service", lambda: ms)
    monkeypatch.setattr(kgsvc, "get_knowledge_graph_service", lambda: FakeKg())
    monkeypatch.setattr(mc, "_llm_curate", _canned_llm({
        "new_memories": [
            {"content": "Decision: Redis 7 replaces Redis 6 for the cache layer",
             "type": "decision", "importance": "high"},
        ],
        "kg_facts": [],
        "stale_candidates": [],
    }))

    counts = await mc.curate_scope("ws-uuid-1", _MSGS)

    assert counts["memories_added"] == 1
    expected = _workspace_collection("ws-uuid-1")
    # Write landed in the workspace collection only
    assert [c for _, c, _ in ms.stored] == [expected]
    # Dedupe lookup queried the SAME single collection — global never appears
    for cols in ms.searched:
        assert cols == [expected]
        assert GLOBAL_COLLECTION not in cols
        assert _workspace_collection("system-main") not in cols


async def test_curation_system_main_scope_writes_global_only(monkeypatch):
    from app.services import memory_curation as mc
    from app.services import memory_service as memsvc
    from app.services import knowledge_graph_service as kgsvc

    ms = FakeMemoryService()
    monkeypatch.setattr(memsvc, "get_memory_service", lambda: ms)
    monkeypatch.setattr(kgsvc, "get_knowledge_graph_service", lambda: FakeKg())
    monkeypatch.setattr(mc, "_llm_curate", _canned_llm({
        "new_memories": [
            {"content": "User prefers French replies in the general chat",
             "type": "preference", "importance": "medium"},
        ],
        "kg_facts": [],
        "stale_candidates": [],
    }))

    counts = await mc.curate_scope("system-main", _MSGS)

    assert counts["memories_added"] == 1
    assert [c for _, c, _ in ms.stored] == [GLOBAL_COLLECTION]
    for cols in ms.searched:
        assert cols == [GLOBAL_COLLECTION]
        # No workspace collection may leak into the general-chat scope
        assert not any(c.startswith("memory-workspace-") for c in cols)


# ---------------------------------------------------------------------------
# 3. Curation — KG invalidate-then-add on a changed fact (real KG, test DB)
# ---------------------------------------------------------------------------


@pytest.mark.db
async def test_curation_kg_invalidate_then_add(monkeypatch):
    from app.services import memory_curation as mc
    from app.services import memory_service as memsvc
    from app.services.knowledge_graph_service import KnowledgeGraphService

    scope = f"cur-kg-{uuid.uuid4().hex[:8]}"
    kg = KnowledgeGraphService()

    # Seed: Redis version=6 (active), auth-service depends_on Memcached (active)
    redis_id = await kg.add_entity("Redis", "technology", scope)
    await kg.add_attribute(redis_id, "version", "6")
    auth_id = await kg.add_entity("auth-service", "component", scope)
    mem_id = await kg.add_entity("Memcached", "technology", scope)
    await kg.add_triple(auth_id, "depends_on", mem_id, source="test")

    ms = FakeMemoryService()
    monkeypatch.setattr(memsvc, "get_memory_service", lambda: ms)
    monkeypatch.setattr(mc, "_llm_curate", _canned_llm({
        "new_memories": [],
        "kg_facts": [
            {"entity": "Redis", "entity_type": "technology",
             "attribute": "version", "value": "7"},
        ],
        "stale_candidates": [
            {"entity": "auth-service", "relation": "depends_on", "target": "Memcached"},
        ],
    }))

    counts = await mc.curate_scope(scope, _MSGS)

    assert counts["kg_updated"] == 1
    # 1 from the attribute supersede + 1 from the stale relation closure
    assert counts["kg_invalidated"] == 2

    timeline = await kg.get_timeline(scope, entity_name="Redis", limit=50)
    versions = [r for r in timeline if r["kind"] == "attribute" and r["predicate"] == "version"]
    active = [r for r in versions if r["valid_to"] is None]
    closed = [r for r in versions if r["valid_to"] is not None]
    # invalidate-then-add: old value closed, new value active — audit trail kept
    assert [r["object"] for r in active] == ["7"]
    assert [r["object"] for r in closed] == ["6"]

    # The contradicted relationship is no longer current...
    rels = await kg.query_relationships(scope, entity_name="auth-service", predicate="depends_on")
    assert rels == []
    # ...but still visible in the timeline (historical, not deleted)
    tl = await kg.get_timeline(scope, entity_name="auth-service", limit=50)
    dep = [r for r in tl if r["kind"] == "triple" and r["predicate"] == "depends_on"]
    assert len(dep) == 1 and dep[0]["valid_to"] is not None


@pytest.mark.db
async def test_curation_kg_unchanged_fact_is_not_rewritten(monkeypatch):
    from app.services import memory_curation as mc
    from app.services import memory_service as memsvc
    from app.services.knowledge_graph_service import KnowledgeGraphService

    scope = f"cur-kg-{uuid.uuid4().hex[:8]}"
    kg = KnowledgeGraphService()
    eid = await kg.add_entity("Postgres", "technology", scope)
    await kg.add_attribute(eid, "version", "16")

    monkeypatch.setattr(memsvc, "get_memory_service", lambda: FakeMemoryService())
    monkeypatch.setattr(mc, "_llm_curate", _canned_llm({
        "new_memories": [],
        "kg_facts": [{"entity": "Postgres", "attribute": "version", "value": "16"}],
        "stale_candidates": [],
    }))

    counts = await mc.curate_scope(scope, _MSGS)
    assert counts["kg_unchanged"] == 1
    assert counts["kg_invalidated"] == 0
    timeline = await kg.get_timeline(scope, entity_name="Postgres", limit=50)
    attrs = [r for r in timeline if r["kind"] == "attribute" and r["predicate"] == "version"]
    assert len(attrs) == 1 and attrs[0]["valid_to"] is None


# ---------------------------------------------------------------------------
# 4. Curation — semantic dedupe skips near-duplicates
# ---------------------------------------------------------------------------


async def test_curation_dedupe_skips_near_duplicate(monkeypatch):
    from app.services import memory_curation as mc
    from app.services import memory_service as memsvc
    from app.services import knowledge_graph_service as kgsvc

    # Existing memory scores 0.97 against the candidate → above threshold
    ms = FakeMemoryService(search_results=[
        {"id": "mem-old", "text": "Redis 7 is the cache", "score": 0.97, "metadata": {}},
    ])
    monkeypatch.setattr(memsvc, "get_memory_service", lambda: ms)
    monkeypatch.setattr(kgsvc, "get_knowledge_graph_service", lambda: FakeKg())
    monkeypatch.setattr(mc, "_llm_curate", _canned_llm({
        "new_memories": [
            {"content": "Decision: Redis 7 is used for the cache layer",
             "type": "decision", "importance": "high"},
        ],
        "kg_facts": [],
        "stale_candidates": [],
    }))

    counts = await mc.curate_scope("ws-uuid-2", _MSGS)
    assert counts["memories_added"] == 0
    assert counts["memories_deduped"] == 1
    assert ms.stored == []


# ---------------------------------------------------------------------------
# Curation — scope/collection mapping invariant
# ---------------------------------------------------------------------------


def test_collection_for_scope_mapping():
    from app.services.memory_curation import _collection_for_scope

    assert _collection_for_scope("system-main") == GLOBAL_COLLECTION
    assert _collection_for_scope("") == GLOBAL_COLLECTION
    assert _collection_for_scope("abc-123") == "memory-workspace-abc-123"


# ---------------------------------------------------------------------------
# 5. nl_task — REST CRUD roundtrip with the new type
# ---------------------------------------------------------------------------


async def test_nl_task_job_crud_roundtrip(monkeypatch):
    from app.routes import jobs as jobs_routes
    from app.routes.jobs import JobCreateRequest, JobUpdateRequest

    store: list[dict] = []
    monkeypatch.setattr(jobs_routes, "_load_jobs", lambda: [dict(j) for j in store])

    def _save(jobs):
        store[:] = [dict(j) for j in jobs]

    monkeypatch.setattr(jobs_routes, "_save_jobs", _save)

    created = await jobs_routes.create_job(JobCreateRequest(
        name="Friday review",
        type="nl_task",
        schedule="0 17 * * fri",
        payload={"prompt": "review stalled cards and message me", "deliver": "both"},
    ))
    assert created["type"] == "nl_task"
    assert created["payload"]["prompt"] == "review stalled cards and message me"
    assert any(j["id"] == created["id"] for j in store)

    updated = await jobs_routes.update_job(created["id"], JobUpdateRequest(enabled=False))
    assert updated["enabled"] is False
    assert store[0]["enabled"] is False

    listing = await jobs_routes.list_jobs()
    assert any(j["type"] == "nl_task" for j in listing["jobs"])

    await jobs_routes.delete_job(created["id"])
    assert store == []


def test_memory_curation_type_accepted_by_schema():
    from app.routes.jobs import JobCreateRequest

    req = JobCreateRequest(name="Curation", type="memory_curation", schedule="30 2 * * *")
    assert req.type == "memory_curation"


# ---------------------------------------------------------------------------
# 6. nl_task handler — enqueues through the orchestrator + delivers
# ---------------------------------------------------------------------------


class FakeOrchestrator:
    def __init__(self):
        self.calls = []
        self._worker_pools: dict = {}

    async def handle_message(self, **kwargs):
        self.calls.append(kwargs)
        return []

    def reset_session(self, chat_id, session_id):
        pass

    async def stop_worker_pool(self, session_id):
        pass


async def test_nl_task_handler_enqueues_and_delivers(monkeypatch):
    import app.main as app_main
    from app.services import job_runner

    fake_orch = FakeOrchestrator()
    monkeypatch.setattr(app_main, "_orchestrator", fake_orch)

    delivered = {}

    async def _fake_deliver(job, workspace_id, deliver, summary, success):
        delivered.update(job=job, workspace_id=workspace_id,
                         deliver=deliver, summary=summary, success=success)

    monkeypatch.setattr(job_runner, "_deliver_nl_task_result", _fake_deliver)
    monkeypatch.setattr(job_runner, "_collect_nl_task_summary", lambda chat_id: "All done.")

    job = {
        "id": "job-nl-1",
        "name": "Friday review",
        "type": "nl_task",
        "payload": {
            "prompt": "review stalled cards and message me",
            "workspace_id": "ws-uuid-9",
            "deliver": "push",
        },
    }
    result = await job_runner._execute_job(job)

    assert result["status"] == "ok"
    assert len(fake_orch.calls) == 1
    call = fake_orch.calls[0]
    assert "review stalled cards and message me" in call["content"]
    assert call["workspace_id"] == "ws-uuid-9"
    assert call["chat_level"] == "workspace"
    assert call["session_id"] == "job-job-nl-1"

    assert delivered["deliver"] == "push"
    assert delivered["workspace_id"] == "ws-uuid-9"
    assert delivered["summary"] == "All done."
    assert delivered["success"] is True


async def test_nl_task_handler_requires_prompt():
    from app.services import job_runner

    result = await job_runner._execute_job({
        "id": "job-nl-2", "name": "broken", "type": "nl_task", "payload": {},
    })
    assert result["status"] == "error"
    assert "prompt" in result["message"].lower()


# ---------------------------------------------------------------------------
# 7. schedule_nl MCP handler — env-scoped creation + garbage rejection
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code=201, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = "fake"

    def json(self):
        return self._body


class _FakeHttpClient:
    def __init__(self):
        self.posts = []

    async def post(self, url, json=None):
        self.posts.append((url, json))
        return _FakeResp(201, {"id": "job-xyz", **(json or {})})


async def test_schedule_nl_creates_env_scoped_job(monkeypatch):
    from app import mcp_server

    handler = mcp_server._get_system_handler("jobs_schedule_nl")
    assert handler is not None, "jobs_schedule_nl handler not registered"

    fake_client = _FakeHttpClient()
    monkeypatch.setattr(mcp_server, "_http_client", fake_client)
    monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", "ws-env-7")

    result = await handler({
        "prompt": "every Friday at 5pm review stalled cards and message me",
        "schedule": {"every": "week", "at": "17:00", "weekday": "friday"},
    })

    assert result["success"] is True
    assert result["job_id"] == "job-xyz"
    assert result["schedule"] == "0 17 * * fri"
    assert len(fake_client.posts) == 1
    url, body = fake_client.posts[0]
    assert url == "/api/jobs"
    assert body["type"] == "nl_task"
    assert body["schedule"] == "0 17 * * fri"
    # Workspace scope came from the env var, never from a schema param
    assert body["payload"]["workspace_id"] == "ws-env-7"
    assert body["payload"]["deliver"] == "both"


async def test_schedule_nl_general_chat_has_no_workspace(monkeypatch):
    from app import mcp_server

    handler = mcp_server._get_system_handler("jobs_schedule_nl")
    fake_client = _FakeHttpClient()
    monkeypatch.setattr(mcp_server, "_http_client", fake_client)
    monkeypatch.setenv("VOXYFLOW_WORKSPACE_ID", "system-main")

    result = await handler({"prompt": "morning digest", "schedule": "every_day", "deliver": "chat"})
    assert result["success"] is True
    _, body = fake_client.posts[0]
    assert "workspace_id" not in body["payload"]
    assert body["payload"]["deliver"] == "chat"


async def test_schedule_nl_rejects_garbage_schedule(monkeypatch):
    from app import mcp_server

    handler = mcp_server._get_system_handler("jobs_schedule_nl")
    fake_client = _FakeHttpClient()
    monkeypatch.setattr(mcp_server, "_http_client", fake_client)

    result = await handler({"prompt": "do things", "schedule": "whenever you feel like it"})
    assert result["success"] is False
    assert "invalid schedule" in result["error"].lower()
    assert fake_client.posts == []  # rejected before any HTTP call

    result2 = await handler({"prompt": "do things", "schedule": {"every": "fortnight"}})
    assert result2["success"] is False
    assert "invalid schedule" in result2["error"].lower()


async def test_schedule_nl_requires_prompt(monkeypatch):
    from app import mcp_server

    handler = mcp_server._get_system_handler("jobs_schedule_nl")
    result = await handler({"schedule": "every_day"})
    assert result["success"] is False
    assert "prompt" in result["error"]


# ---------------------------------------------------------------------------
# normalize_schedule
# ---------------------------------------------------------------------------


def test_normalize_schedule_variants():
    from app.services.scheduler_service import normalize_schedule

    # Pass-through forms
    assert normalize_schedule("0 17 * * fri") == "0 17 * * fri"
    assert normalize_schedule("every_30min") == "every_30min"
    assert normalize_schedule("every_day") == "every_day"

    # Object forms
    assert normalize_schedule({"every": "day", "at": "07:30"}) == "30 7 * * *"
    assert normalize_schedule({"every": "week", "at": "17:00", "weekday": "fri"}) == "0 17 * * fri"
    assert normalize_schedule({"every": "week", "weekday": 5, "at": "9:15"}) == "15 9 * * fri"
    assert normalize_schedule({"every": "weekdays", "at": "08:00"}) == "0 8 * * mon-fri"
    assert normalize_schedule({"every": "hour"}) == "every_1h"

    # Garbage
    for bad in ["", "not a schedule", "1 2 3", {"every": "fortnight"},
                {"every": "day", "at": "25:99"}, {"every": "week", "weekday": "someday"}]:
        with pytest.raises(ValueError):
            normalize_schedule(bad)


# ---------------------------------------------------------------------------
# Role wiring — schedule_nl is dispatcher-allowed
# ---------------------------------------------------------------------------


def test_schedule_nl_in_dispatcher_toolset():
    from app.tools.registry import TOOLS_DISPATCHER, TOOLS_WORKER

    assert "voxyflow.jobs.schedule_nl" in TOOLS_DISPATCHER
    assert "voxyflow.jobs.schedule_nl" in TOOLS_WORKER


def test_memory_curation_default_job_disabled():
    from app.services.scheduler_service import SchedulerService

    curation = [j for j in SchedulerService._DEFAULT_JOBS if j["type"] == "memory_curation"]
    assert len(curation) == 1
    assert curation[0]["enabled"] is False  # opt-in
    assert curation[0]["builtin"] is True
