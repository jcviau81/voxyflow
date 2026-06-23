"""Knowledge Graph service tests.

Tests cover:
1. Entity CRUD (add, upsert, query)
2. Triple CRUD + invalidation
3. Attribute CRUD + invalidation
4. Workspace isolation
5. Timeline
6. Pinned context cache
7. LLM entity extraction integration
8. Stats
"""

import asyncio
import os
import sys
import time
import uuid

import pytest

pytestmark = pytest.mark.db

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Override database URL to use in-memory SQLite for tests
os.environ["DATABASE_URL"] = "sqlite+aiosqlite://"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def _init_db():
    """Initialize the in-memory database once per session."""
    from app.database import init_db
    await init_db()


@pytest.fixture
async def kg(_init_db):
    """Return a fresh KnowledgeGraphService instance."""
    from app.services.knowledge_graph_service import KnowledgeGraphService
    return KnowledgeGraphService()


def _pid():
    """Generate a unique workspace ID for test isolation."""
    return f"test-{uuid.uuid4().hex[:8]}"


# ============================================================================
# Entity CRUD
# ============================================================================

class TestEntityCRUD:
    @pytest.mark.asyncio
    async def test_add_entity(self, kg):
        pid = _pid()
        eid = await kg.add_entity("Redis", "technology", pid)
        assert eid
        assert isinstance(eid, str)

    @pytest.mark.asyncio
    async def test_upsert_returns_same_id(self, kg):
        pid = _pid()
        eid1 = await kg.add_entity("Redis", "technology", pid)
        eid2 = await kg.add_entity("Redis", "technology", pid, properties={"version": "7"})
        assert eid1 == eid2

    @pytest.mark.asyncio
    async def test_query_entities(self, kg):
        pid = _pid()
        await kg.add_entity("Redis", "technology", pid)
        await kg.add_entity("PostgreSQL", "technology", pid)
        await kg.add_entity("Alice", "person", pid)

        results = await kg.query_entities(pid)
        assert len(results) == 3

        # Filter by type
        techs = await kg.query_entities(pid, entity_type="technology")
        assert len(techs) == 2

        # Filter by name
        redis = await kg.query_entities(pid, name="redis")
        assert len(redis) == 1
        assert redis[0]["name"] == "Redis"


# ============================================================================
# Triple CRUD + Invalidation
# ============================================================================

class TestTriples:
    @pytest.mark.asyncio
    async def test_add_and_query_triple(self, kg):
        pid = _pid()
        eid1 = await kg.add_entity("auth-service", "component", pid)
        eid2 = await kg.add_entity("JWT", "technology", pid)
        tid = await kg.add_triple(eid1, "uses", eid2)
        assert tid

        rels = await kg.query_relationships(pid)
        assert len(rels) == 1
        assert rels[0]["subject"] == "auth-service"
        assert rels[0]["predicate"] == "uses"
        assert rels[0]["object"] == "JWT"

    @pytest.mark.asyncio
    async def test_invalidate_triple(self, kg):
        pid = _pid()
        eid1 = await kg.add_entity("app", "component", pid)
        eid2 = await kg.add_entity("Redis", "technology", pid)
        tid = await kg.add_triple(eid1, "uses", eid2)

        ok = await kg.invalidate(triple_id=tid)
        assert ok is True

        # Should no longer appear in active relationships
        rels = await kg.query_relationships(pid)
        assert len(rels) == 0

    @pytest.mark.asyncio
    async def test_invalidate_nonexistent(self, kg):
        ok = await kg.invalidate(triple_id="nonexistent-id")
        assert ok is False

    @pytest.mark.asyncio
    async def test_invalidate_scoped_to_workspace(self, kg):
        """A workspace can only invalidate its own facts."""
        pid_a = _pid()
        pid_b = _pid()
        eid1 = await kg.add_entity("app", "component", pid_a)
        eid2 = await kg.add_entity("Redis", "technology", pid_a)
        tid = await kg.add_triple(eid1, "uses", eid2)

        # Wrong workspace — refused, fact stays active
        ok = await kg.invalidate(triple_id=tid, workspace_id=pid_b)
        assert ok is False
        assert len(await kg.query_relationships(pid_a)) == 1

        # Owning workspace — closed
        ok = await kg.invalidate(triple_id=tid, workspace_id=pid_a)
        assert ok is True

    @pytest.mark.asyncio
    async def test_invalidate_env_scoping(self, kg):
        """VOXYFLOW_WORKSPACE_ID scopes invalidate when no explicit workspace_id."""
        pid_a = _pid()
        eid = await kg.add_entity("Redis", "technology", pid_a)
        aid = await kg.add_attribute(eid, "status", "active")
        prev = os.environ.get("VOXYFLOW_WORKSPACE_ID")
        try:
            os.environ["VOXYFLOW_WORKSPACE_ID"] = _pid()  # another workspace
            assert await kg.invalidate(attribute_id=aid) is False
            os.environ["VOXYFLOW_WORKSPACE_ID"] = pid_a
            assert await kg.invalidate(attribute_id=aid) is True
        finally:
            if prev is None:
                os.environ.pop("VOXYFLOW_WORKSPACE_ID", None)
            else:
                os.environ["VOXYFLOW_WORKSPACE_ID"] = prev

    @pytest.mark.asyncio
    async def test_as_of_sees_invalidated_triple(self, kg):
        """A triple invalidated AFTER as_of should still appear in as_of queries."""
        from datetime import datetime, timezone, timedelta

        pid = _pid()
        eid1 = await kg.add_entity("app", "component", pid)
        eid2 = await kg.add_entity("Redis", "technology", pid)
        tid = await kg.add_triple(eid1, "uses", eid2)

        # Snapshot a time when the triple was active
        point_in_time = datetime.now(timezone.utc)

        # Small delay so invalidation timestamp is strictly after point_in_time
        import asyncio
        await asyncio.sleep(0.05)

        # Invalidate the triple (valid_to = now, which is after point_in_time)
        await kg.invalidate(triple_id=tid)

        # Current query: triple should be gone
        current = await kg.query_relationships(pid)
        assert len(current) == 0

        # as_of query at point_in_time: triple should still appear
        historical = await kg.query_relationships(pid, as_of=point_in_time)
        assert len(historical) == 1
        assert historical[0]["subject"] == "app"


# ============================================================================
# Attribute CRUD + Invalidation
# ============================================================================

class TestAttributes:
    @pytest.mark.asyncio
    async def test_add_attribute(self, kg):
        pid = _pid()
        eid = await kg.add_entity("Redis", "technology", pid)
        aid = await kg.add_attribute(eid, "version", "7.2")
        assert aid

    @pytest.mark.asyncio
    async def test_invalidate_attribute(self, kg):
        pid = _pid()
        eid = await kg.add_entity("Redis", "technology", pid)
        aid = await kg.add_attribute(eid, "status", "active")

        ok = await kg.invalidate(attribute_id=aid)
        assert ok is True

        # Second invalidation should return False (already closed)
        ok2 = await kg.invalidate(attribute_id=aid)
        assert ok2 is False


# ============================================================================
# Workspace Isolation
# ============================================================================

class TestWorkspaceIsolation:
    @pytest.mark.asyncio
    async def test_entities_isolated_by_workspace(self, kg):
        pid_a = _pid()
        pid_b = _pid()

        await kg.add_entity("Redis", "technology", pid_a)
        await kg.add_entity("PostgreSQL", "technology", pid_b)

        a_results = await kg.query_entities(pid_a)
        b_results = await kg.query_entities(pid_b)

        assert len(a_results) == 1
        assert a_results[0]["name"] == "Redis"
        assert len(b_results) == 1
        assert b_results[0]["name"] == "PostgreSQL"

    @pytest.mark.asyncio
    async def test_relationships_isolated(self, kg):
        pid_a = _pid()
        pid_b = _pid()

        a1 = await kg.add_entity("app", "component", pid_a)
        a2 = await kg.add_entity("Redis", "technology", pid_a)
        await kg.add_triple(a1, "uses", a2)

        b1 = await kg.add_entity("api", "component", pid_b)
        b2 = await kg.add_entity("Postgres", "technology", pid_b)
        await kg.add_triple(b1, "uses", b2)

        a_rels = await kg.query_relationships(pid_a)
        b_rels = await kg.query_relationships(pid_b)
        assert len(a_rels) == 1
        assert a_rels[0]["subject"] == "app"
        assert len(b_rels) == 1
        assert b_rels[0]["subject"] == "api"


# ============================================================================
# Timeline
# ============================================================================

class TestTimeline:
    @pytest.mark.asyncio
    async def test_timeline_includes_triples_and_attributes(self, kg):
        pid = _pid()
        eid = await kg.add_entity("Redis", "technology", pid)
        eid2 = await kg.add_entity("app", "component", pid)
        await kg.add_triple(eid2, "uses", eid)
        await kg.add_attribute(eid, "version", "7.2")

        events = await kg.get_timeline(pid)
        assert len(events) == 2
        kinds = {e["kind"] for e in events}
        assert "triple" in kinds
        assert "attribute" in kinds

    @pytest.mark.asyncio
    async def test_timeline_filter_by_entity(self, kg):
        pid = _pid()
        eid1 = await kg.add_entity("Redis", "technology", pid)
        eid2 = await kg.add_entity("Postgres", "technology", pid)
        await kg.add_attribute(eid1, "version", "7")
        await kg.add_attribute(eid2, "version", "16")

        events = await kg.get_timeline(pid, entity_name="Redis")
        assert len(events) >= 1
        assert all("Redis" in e.get("subject", "") for e in events)


# ============================================================================
# Pinned Context Cache
# ============================================================================

class TestPinnedCache:
    @pytest.mark.asyncio
    async def test_pinned_cache_empty_initially(self, kg):
        pid = _pid()
        pinned = kg.get_pinned_context(pid)
        assert pinned == []

    @pytest.mark.asyncio
    async def test_pinned_cache_populated_after_refresh(self, kg):
        pid = _pid()
        eid = await kg.add_entity("Redis", "technology", pid)
        await kg.add_attribute(eid, "pinned", "true")

        await kg.refresh_pinned_cache(pid)
        pinned = kg.get_pinned_context(pid)
        assert len(pinned) == 1
        assert pinned[0]["name"] == "Redis"

    @pytest.mark.asyncio
    async def test_pinned_cache_serves_stale_and_schedules_refresh(self, kg):
        """Expired entries are served stale while a background refresh runs."""
        pid = _pid()
        eid = await kg.add_entity("Redis", "technology", pid)
        await kg.add_attribute(eid, "pinned", "true")
        await kg.refresh_pinned_cache(pid)

        # Manually expire the entry — read must serve stale data, not []
        data = kg._pinned_cache[pid][1]
        kg._pinned_cache[pid] = (time.time() - 999.0, data)
        pinned = kg.get_pinned_context(pid)
        assert len(pinned) == 1, "stale pinned data should be served on expiry"

        # The scheduled background refresh re-populates the cache
        for _ in range(50):
            await asyncio.sleep(0.01)
            if (time.time() - kg._pinned_cache[pid][0]) < 60.0:
                break
        assert (time.time() - kg._pinned_cache[pid][0]) < 60.0, \
            "background refresh did not run"


# ============================================================================
# LLM Entity Extraction
# ============================================================================

class TestExtraction:
    @pytest.mark.asyncio
    async def test_extract_entities_from_llm_output(self, kg):
        pid = _pid()
        entities = [
            {
                "name": "Redis",
                "type": "technology",
                "relationships": [
                    {"predicate": "used_by", "target": "auth-service", "target_type": "component"}
                ],
            },
            {
                "name": "Alice",
                "type": "person",
                "relationships": [],
            },
        ]

        ids = await kg.extract_entities_from_llm_output(entities, pid)
        assert len(ids) == 2

        # Verify entities exist
        all_entities = await kg.query_entities(pid)
        names = {e["name"] for e in all_entities}
        assert "Redis" in names
        assert "Alice" in names
        assert "auth-service" in names  # created as relationship target

        # Verify relationship
        rels = await kg.query_relationships(pid)
        assert len(rels) == 1
        assert rels[0]["predicate"] == "used_by"

    @pytest.mark.asyncio
    async def test_extract_skips_empty_names(self, kg):
        pid = _pid()
        entities = [
            {"name": "", "type": "technology"},
            {"name": "  ", "type": "concept"},
        ]
        ids = await kg.extract_entities_from_llm_output(entities, pid)
        assert len(ids) == 0


# ============================================================================
# Stats
# ============================================================================

class TestStats:
    @pytest.mark.asyncio
    async def test_stats(self, kg):
        pid = _pid()
        eid1 = await kg.add_entity("Redis", "technology", pid)
        eid2 = await kg.add_entity("app", "component", pid)
        await kg.add_triple(eid1, "powers", eid2)
        await kg.add_attribute(eid1, "version", "7")

        stats = await kg.get_stats(pid)
        assert stats["entities"] == 2
        assert stats["active_triples"] == 1
        assert stats["active_attributes"] == 1

    @pytest.mark.asyncio
    async def test_stats_empty_workspace(self, kg):
        pid = _pid()
        stats = await kg.get_stats(pid)
        assert stats["entities"] == 0
        assert stats["active_triples"] == 0
        assert stats["active_attributes"] == 0
