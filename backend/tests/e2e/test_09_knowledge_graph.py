"""
E2E: Knowledge Graph — entity/triple/attribute CRUD, temporal queries,
project isolation, pinned context, stats.

Uses in-memory SQLite — no backend required.
"""

import asyncio
import os
import sys
import uuid

import pytest

# Ensure backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# Override database URL to use in-memory SQLite for tests
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite://")


def _pid():
    return f"e2e-kg-{uuid.uuid4().hex[:8]}"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def _init_db():
    from app.database import init_db
    await init_db()


@pytest.fixture
async def kg(_init_db):
    from app.services.knowledge_graph_service import KnowledgeGraphService
    return KnowledgeGraphService()


# ── Entity CRUD ──────────────────────────────────────────────────────────────

class TestEntityCRUD:
    @pytest.mark.asyncio
    async def test_add_entity(self, kg):
        pid = _pid()
        eid = await kg.add_entity("Redis", "technology", pid)
        assert eid is not None

    @pytest.mark.asyncio
    async def test_upsert_returns_same_id(self, kg):
        pid = _pid()
        eid1 = await kg.add_entity("Redis", "technology", pid)
        eid2 = await kg.add_entity("Redis", "technology", pid)
        assert eid1 == eid2

    @pytest.mark.asyncio
    async def test_query_entities(self, kg):
        pid = _pid()
        await kg.add_entity("Python", "technology", pid)
        await kg.add_entity("FastAPI", "technology", pid)
        await kg.add_entity("JC", "person", pid)

        entities = await kg.query_entities(pid)
        assert len(entities) == 3

        # Filter by type
        techs = await kg.query_entities(pid, entity_type="technology")
        assert len(techs) == 2

    @pytest.mark.asyncio
    async def test_query_entities_by_name(self, kg):
        pid = _pid()
        await kg.add_entity("UniqueEntity", "concept", pid)
        await kg.add_entity("OtherEntity", "concept", pid)

        results = await kg.query_entities(pid, name="UniqueEntity")
        assert len(results) == 1
        assert results[0]["name"] == "UniqueEntity"


# ── Triples (Temporal) ───────────────────────────────────────────────────────

class TestTriples:
    @pytest.mark.asyncio
    async def test_add_and_query_triple(self, kg):
        pid = _pid()
        sub = await kg.add_entity("FastAPI", "technology", pid)
        obj = await kg.add_entity("Python", "technology", pid)

        tid = await kg.add_triple(sub, "built_with", obj, pid)
        assert tid is not None

        rels = await kg.query_relationships(pid)
        assert len(rels) >= 1
        assert any(r["predicate"] == "built_with" for r in rels)

    @pytest.mark.asyncio
    async def test_invalidate_triple(self, kg):
        pid = _pid()
        sub = await kg.add_entity("A", "concept", pid)
        obj = await kg.add_entity("B", "concept", pid)

        tid = await kg.add_triple(sub, "links_to", obj, pid)
        await kg.invalidate(triple_id=tid)

        # Current query should not show invalidated triple
        rels = await kg.query_relationships(pid)
        active = [r for r in rels if r.get("valid_to") is None]
        assert not any(r["id"] == tid for r in active)

    @pytest.mark.asyncio
    async def test_multiple_triples(self, kg):
        pid = _pid()
        a = await kg.add_entity("A", "concept", pid)
        b = await kg.add_entity("B", "concept", pid)
        c = await kg.add_entity("C", "concept", pid)

        await kg.add_triple(a, "links_to", b, pid)
        await kg.add_triple(b, "links_to", c, pid)
        await kg.add_triple(a, "depends_on", c, pid)

        rels = await kg.query_relationships(pid)
        assert len(rels) == 3


# ── Attributes (Temporal) ────────────────────────────────────────────────────
# add_attribute(entity_id, key, value) — project_id is inferred from entity

class TestAttributes:
    @pytest.mark.asyncio
    async def test_add_and_invalidate_attribute(self, kg):
        pid = _pid()
        eid = await kg.add_entity("Redis", "technology", pid)

        aid = await kg.add_attribute(eid, "version", "6.2")
        assert aid is not None

        # Invalidate and add new version
        await kg.invalidate(attribute_id=aid)
        aid2 = await kg.add_attribute(eid, "version", "7.0")
        assert aid2 is not None
        assert aid2 != aid

    @pytest.mark.asyncio
    async def test_multiple_attributes(self, kg):
        pid = _pid()
        eid = await kg.add_entity("Service", "component", pid)

        await kg.add_attribute(eid, "port", "8080")
        await kg.add_attribute(eid, "language", "Python")
        await kg.add_attribute(eid, "framework", "FastAPI")

        stats = await kg.get_stats(pid)
        assert stats["active_attributes"] >= 3


# ── Timeline ─────────────────────────────────────────────────────────────────

class TestTimeline:
    @pytest.mark.asyncio
    async def test_entity_timeline(self, kg):
        pid = _pid()
        eid = await kg.add_entity("Redis", "technology", pid)

        await kg.add_attribute(eid, "version", "6.0")
        aid = await kg.add_attribute(eid, "version", "6.2")
        await kg.invalidate(attribute_id=aid)
        await kg.add_attribute(eid, "version", "7.0")

        timeline = await kg.get_timeline(project_id=pid, entity_name="Redis")
        assert len(timeline) >= 3

    @pytest.mark.asyncio
    async def test_project_timeline(self, kg):
        pid = _pid()
        eid1 = await kg.add_entity("A", "concept", pid)
        eid2 = await kg.add_entity("B", "concept", pid)
        await kg.add_triple(eid1, "related_to", eid2, pid)

        timeline = await kg.get_timeline(project_id=pid)
        assert len(timeline) >= 1


# ── Project Isolation ────────────────────────────────────────────────────────

class TestKGProjectIsolation:
    @pytest.mark.asyncio
    async def test_entities_isolated(self, kg):
        pid_a = _pid()
        pid_b = _pid()

        await kg.add_entity("SecretA", "concept", pid_a)
        await kg.add_entity("PublicB", "concept", pid_b)

        entities_a = await kg.query_entities(pid_a)
        entities_b = await kg.query_entities(pid_b)

        names_a = {e["name"] for e in entities_a}
        names_b = {e["name"] for e in entities_b}

        assert "SecretA" in names_a
        assert "SecretA" not in names_b
        assert "PublicB" in names_b
        assert "PublicB" not in names_a

    @pytest.mark.asyncio
    async def test_triples_isolated(self, kg):
        pid_a = _pid()
        pid_b = _pid()

        sub_a = await kg.add_entity("X", "concept", pid_a)
        obj_a = await kg.add_entity("Y", "concept", pid_a)
        await kg.add_triple(sub_a, "is_a", obj_a, pid_a)

        rels_b = await kg.query_relationships(pid_b)
        assert len(rels_b) == 0

    @pytest.mark.asyncio
    async def test_stats_isolated(self, kg):
        pid_a = _pid()
        pid_b = _pid()

        await kg.add_entity("Thing", "concept", pid_a)

        stats_a = await kg.get_stats(pid_a)
        stats_b = await kg.get_stats(pid_b)

        assert stats_a["entities"] >= 1
        assert stats_b["entities"] == 0

    @pytest.mark.asyncio
    async def test_attributes_isolated(self, kg):
        pid_a = _pid()
        pid_b = _pid()

        eid = await kg.add_entity("SecretService", "component", pid_a)
        await kg.add_attribute(eid, "secret_key", "abc123")

        stats_b = await kg.get_stats(pid_b)
        assert stats_b["active_attributes"] == 0


# ── Pinned Context (L0) ─────────────────────────────────────────────────────

class TestPinnedContext:
    @pytest.mark.asyncio
    async def test_pinned_entities(self, kg):
        pid = _pid()
        eid = await kg.add_entity("CoreService", "component", pid)
        await kg.add_attribute(eid, "pinned", "true")

        # get_pinned_context is sync — returns cached list
        pinned = kg.get_pinned_context(pid)
        assert isinstance(pinned, list)


# ── Stats ────────────────────────────────────────────────────────────────────

class TestStats:
    @pytest.mark.asyncio
    async def test_stats(self, kg):
        pid = _pid()
        eid1 = await kg.add_entity("A", "concept", pid)
        eid2 = await kg.add_entity("B", "concept", pid)
        await kg.add_triple(eid1, "links", eid2, pid)
        await kg.add_attribute(eid1, "color", "red")

        stats = await kg.get_stats(pid)
        assert stats["entities"] == 2
        assert stats["active_triples"] >= 1
        assert stats["active_attributes"] >= 1

    @pytest.mark.asyncio
    async def test_stats_empty_project(self, kg):
        pid = _pid()
        stats = await kg.get_stats(pid)
        assert stats["entities"] == 0
        assert stats["active_triples"] == 0
        assert stats["active_attributes"] == 0
