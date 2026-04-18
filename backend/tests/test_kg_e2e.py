"""End-to-end tests for the Knowledge Graph + Lazy Context Loading system.

Tests:
1. KG MCP handlers (kg.add / kg.query / kg.timeline / kg.invalidate / kg.stats)
2. KG project isolation via MCP handlers
3. Memory extraction format change (memories + entities)
4. Lazy context loading L0/L1/L2 budget & layers
5. L0 bridge (pinned KG cache → _build_l0_identity)
6. Backward compatibility (empty KG = same as before)
7. KG tools appear in MCP tool list

Runs against the live backend (localhost:8000) for HTTP tests,
and directly for handler/service tests.
"""

import asyncio
import json
import os
import sys
import time
import uuid

import pytest
import httpx

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

BASE = "http://localhost:8000"


def _pid():
    return f"e2e-{uuid.uuid4().hex[:8]}"


# ============================================================================
# 1. KG MCP Handler Tests (direct handler invocation)
# ============================================================================

class TestKGMCPHandlers:
    """Test the 5 kg.* MCP handlers by calling them directly."""

    @pytest.fixture(autouse=True)
    def _set_project_env(self):
        """Set a unique project env for each test."""
        self.pid = _pid()
        prev = os.environ.get("VOXYFLOW_PROJECT_ID")
        os.environ["VOXYFLOW_PROJECT_ID"] = self.pid
        yield
        if prev is None:
            os.environ.pop("VOXYFLOW_PROJECT_ID", None)
        else:
            os.environ["VOXYFLOW_PROJECT_ID"] = prev

    def _handler(self, name):
        from app.mcp_server import _get_system_handler
        h = _get_system_handler(name)
        assert h is not None, f"Handler {name!r} not registered"
        return h

    @pytest.mark.asyncio
    async def test_kg_add_entity(self):
        h = self._handler("kg_add")
        result = await h({
            "entity_name": "Redis",
            "entity_type": "technology",
        })
        assert result.get("success") is True, f"kg.add failed: {result}"
        assert result.get("entity_id"), "Missing entity_id"
        assert result["entity_name"] == "Redis"

    @pytest.mark.asyncio
    async def test_kg_add_with_relationships_and_attributes(self):
        h = self._handler("kg_add")
        result = await h({
            "entity_name": "auth-service",
            "entity_type": "component",
            "relationships": [
                {"predicate": "uses", "target": "JWT", "target_type": "technology"},
                {"predicate": "depends_on", "target": "PostgreSQL", "target_type": "technology"},
            ],
            "attributes": [
                {"key": "status", "value": "production"},
                {"key": "pinned", "value": "true"},
            ],
        })
        assert result.get("success") is True, f"kg.add failed: {result}"
        assert len(result.get("relationships", [])) == 2
        assert len(result.get("attributes", [])) == 2

    @pytest.mark.asyncio
    async def test_kg_query_entities(self):
        add = self._handler("kg_add")
        await add({"entity_name": "Redis", "entity_type": "technology"})
        await add({"entity_name": "PostgreSQL", "entity_type": "technology"})
        await add({"entity_name": "Alice", "entity_type": "person"})

        query = self._handler("kg_query")

        # All entities
        result = await query({})
        assert result.get("count") == 3, f"Expected 3 entities, got {result}"

        # Filter by type
        result = await query({"entity_type": "technology"})
        assert result["count"] == 2

        # Filter by name
        result = await query({"name": "redis"})
        assert result["count"] == 1
        assert result["entities"][0]["name"] == "Redis"

    @pytest.mark.asyncio
    async def test_kg_query_with_relationships(self):
        add = self._handler("kg_add")
        await add({
            "entity_name": "app",
            "entity_type": "component",
            "relationships": [
                {"predicate": "uses", "target": "Redis", "target_type": "technology"},
            ],
        })

        query = self._handler("kg_query")
        result = await query({"include_relationships": True})
        assert "relationships" in result
        assert len(result["relationships"]) >= 1
        rel = result["relationships"][0]
        assert rel["predicate"] == "uses"

    @pytest.mark.asyncio
    async def test_kg_timeline(self):
        add = self._handler("kg_add")
        await add({
            "entity_name": "Redis",
            "entity_type": "technology",
            "attributes": [{"key": "version", "value": "7.2"}],
        })
        await add({
            "entity_name": "app",
            "entity_type": "component",
            "relationships": [
                {"predicate": "uses", "target": "Redis", "target_type": "technology"},
            ],
        })

        timeline = self._handler("kg_timeline")
        result = await timeline({})
        assert result["count"] >= 2, f"Expected >= 2 events, got {result}"

        # Filter by entity
        result = await timeline({"entity_name": "Redis"})
        assert result["count"] >= 1

    @pytest.mark.asyncio
    async def test_kg_invalidate_triple(self):
        add = self._handler("kg_add")
        result = await add({
            "entity_name": "app",
            "entity_type": "component",
            "relationships": [
                {"predicate": "uses", "target": "Redis", "target_type": "technology"},
            ],
        })
        triple_id = result["relationships"][0]["triple_id"]

        inv = self._handler("kg_invalidate")
        result = await inv({"triple_id": triple_id})
        assert result.get("success") is True

        # Verify it's gone from active relationships
        query = self._handler("kg_query")
        qr = await query({"name": "app", "include_relationships": True})
        for r in qr.get("relationships", []):
            assert r["id"] != triple_id, "Invalidated triple still in active results"

    @pytest.mark.asyncio
    async def test_kg_invalidate_attribute(self):
        add = self._handler("kg_add")
        result = await add({
            "entity_name": "Redis",
            "entity_type": "technology",
            "attributes": [{"key": "version", "value": "7.0"}],
        })
        attr_id = result["attributes"][0]["attribute_id"]

        inv = self._handler("kg_invalidate")
        result = await inv({"attribute_id": attr_id})
        assert result.get("success") is True

    @pytest.mark.asyncio
    async def test_kg_invalidate_requires_id(self):
        inv = self._handler("kg_invalidate")
        result = await inv({})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_kg_stats(self):
        add = self._handler("kg_add")
        await add({
            "entity_name": "Redis",
            "entity_type": "technology",
            "relationships": [
                {"predicate": "powers", "target": "app", "target_type": "component"},
            ],
            "attributes": [{"key": "version", "value": "7"}],
        })

        stats = self._handler("kg_stats")
        result = await stats({})
        assert result.get("success") is True
        assert result["entities"] >= 2  # Redis + app
        assert result["active_triples"] >= 1
        assert result["active_attributes"] >= 1

    @pytest.mark.asyncio
    async def test_kg_stats_empty_project(self):
        stats = self._handler("kg_stats")
        result = await stats({})
        assert result.get("success") is True
        assert result["entities"] == 0

    @pytest.mark.asyncio
    async def test_kg_add_validation(self):
        add = self._handler("kg_add")
        result = await add({})
        assert "error" in result, "Expected error for missing required params"

        result = await add({"entity_name": "Redis"})
        assert "error" in result, "Expected error for missing entity_type"

    @pytest.mark.asyncio
    async def test_kg_add_upsert(self):
        """Adding same entity twice returns same id (upsert)."""
        add = self._handler("kg_add")
        r1 = await add({"entity_name": "Redis", "entity_type": "technology"})
        r2 = await add({"entity_name": "Redis", "entity_type": "technology"})
        assert r1["entity_id"] == r2["entity_id"]


# ============================================================================
# 2. KG Project Isolation via MCP Handlers
# ============================================================================

class TestKGProjectIsolation:
    """Verify KG tools scope to VOXYFLOW_PROJECT_ID — no cross-project leaks."""

    @pytest.mark.asyncio
    async def test_entities_isolated(self):
        from app.mcp_server import _get_system_handler

        add = _get_system_handler("kg_add")
        query = _get_system_handler("kg_query")

        pid_a = _pid()
        pid_b = _pid()

        # Add entity in project A
        os.environ["VOXYFLOW_PROJECT_ID"] = pid_a
        await add({"entity_name": "Redis", "entity_type": "technology"})

        # Add entity in project B
        os.environ["VOXYFLOW_PROJECT_ID"] = pid_b
        await add({"entity_name": "PostgreSQL", "entity_type": "technology"})

        # Query project A — should only see Redis
        os.environ["VOXYFLOW_PROJECT_ID"] = pid_a
        result = await query({})
        names = {e["name"] for e in result.get("entities", [])}
        assert "Redis" in names, f"Redis missing from project A: {names}"
        assert "PostgreSQL" not in names, f"PostgreSQL leaked into project A: {names}"

        # Query project B — should only see PostgreSQL
        os.environ["VOXYFLOW_PROJECT_ID"] = pid_b
        result = await query({})
        names = {e["name"] for e in result.get("entities", [])}
        assert "PostgreSQL" in names
        assert "Redis" not in names, f"Redis leaked into project B: {names}"

        # Cleanup
        os.environ.pop("VOXYFLOW_PROJECT_ID", None)

    @pytest.mark.asyncio
    async def test_relationships_isolated(self):
        from app.mcp_server import _get_system_handler

        add = _get_system_handler("kg_add")
        query = _get_system_handler("kg_query")

        pid_a = _pid()
        pid_b = _pid()

        os.environ["VOXYFLOW_PROJECT_ID"] = pid_a
        await add({
            "entity_name": "app",
            "entity_type": "component",
            "relationships": [{"predicate": "uses", "target": "Redis", "target_type": "technology"}],
        })

        os.environ["VOXYFLOW_PROJECT_ID"] = pid_b
        result = await query({"include_relationships": True})
        assert len(result.get("relationships", [])) == 0, \
            f"Relationships from project A leaked to project B: {result.get('relationships')}"

        os.environ.pop("VOXYFLOW_PROJECT_ID", None)

    @pytest.mark.asyncio
    async def test_stats_isolated(self):
        from app.mcp_server import _get_system_handler

        add = _get_system_handler("kg_add")
        stats = _get_system_handler("kg_stats")

        pid_a = _pid()
        pid_b = _pid()

        os.environ["VOXYFLOW_PROJECT_ID"] = pid_a
        await add({"entity_name": "Redis", "entity_type": "technology"})

        os.environ["VOXYFLOW_PROJECT_ID"] = pid_b
        result = await stats({})
        assert result["entities"] == 0, f"Stats leaked from project A to B: {result}"

        os.environ.pop("VOXYFLOW_PROJECT_ID", None)


# ============================================================================
# 3. Memory Extraction Format Change
# ============================================================================

class TestMemoryExtractionFormat:
    """Verify _llm_extract_memories handles both old and new formats."""

    @pytest.mark.asyncio
    async def test_old_format_backward_compat(self):
        """Old format (plain list) should be wrapped into {memories: [...], entities: []}."""
        from app.services.memory_service import MemoryService

        ms = MemoryService()

        # Monkey-patch _call_api to return old-format JSON
        old_format = json.dumps([
            {"content": "Redis is used for caching", "type": "fact", "importance": "high", "confidence": 0.9},
        ])

        async def fake_call_api(**kwargs):
            return old_format

        # Inject via ClaudeService mock
        import app.services.claude_service as cs_mod
        original_class = cs_mod.ClaudeService

        class FakeClaude:
            haiku_model = "test"
            haiku_client = None
            haiku_client_type = "test"
            async def _call_api(self, **kwargs):
                return old_format

        cs_mod.ClaudeService = FakeClaude
        try:
            result = await ms._llm_extract_memories([
                {"role": "user", "content": "We decided to use Redis for caching."},
            ])
        finally:
            cs_mod.ClaudeService = original_class

        assert result is not None
        assert "memories" in result
        assert "entities" in result
        assert len(result["memories"]) == 1
        assert result["entities"] == []

    @pytest.mark.asyncio
    async def test_new_format_with_entities(self):
        """New format (dict with memories + entities) should be returned as-is."""
        from app.services.memory_service import MemoryService

        ms = MemoryService()

        new_format = json.dumps({
            "memories": [
                {"content": "Auth uses JWT tokens", "type": "fact", "importance": "high", "confidence": 0.95},
            ],
            "entities": [
                {"name": "JWT", "type": "technology", "relationships": []},
                {"name": "auth-service", "type": "component", "relationships": [
                    {"predicate": "uses", "target": "JWT", "target_type": "technology"},
                ]},
            ],
        })

        import app.services.claude_service as cs_mod
        original_class = cs_mod.ClaudeService

        class FakeClaude:
            haiku_model = "test"
            haiku_client = None
            haiku_client_type = "test"
            async def _call_api(self, **kwargs):
                return new_format

        cs_mod.ClaudeService = FakeClaude
        try:
            result = await ms._llm_extract_memories([
                {"role": "user", "content": "The auth service uses JWT tokens."},
            ])
        finally:
            cs_mod.ClaudeService = original_class

        assert result is not None
        assert len(result["memories"]) == 1
        assert len(result["entities"]) == 2
        assert result["entities"][0]["name"] == "JWT"

    @pytest.mark.asyncio
    async def test_extraction_handles_malformed_json(self):
        """Malformed JSON should return None, not crash."""
        from app.services.memory_service import MemoryService

        ms = MemoryService()

        import app.services.claude_service as cs_mod
        original_class = cs_mod.ClaudeService

        class FakeClaude:
            haiku_model = "test"
            haiku_client = None
            haiku_client_type = "test"
            async def _call_api(self, **kwargs):
                return "not valid json {{"

        cs_mod.ClaudeService = FakeClaude
        try:
            result = await ms._llm_extract_memories([
                {"role": "user", "content": "Hello world"},
            ])
        finally:
            cs_mod.ClaudeService = original_class

        assert result is None


# ============================================================================
# 4. Lazy Context Loading (L0/L1/L2 Budget & Layers)
# ============================================================================

class TestLazyContextLoading:
    """Verify build_memory_context respects budget and layers."""

    def _make_ms(self):
        """Create a MemoryService with controlled search results."""
        from app.services.memory_service import MemoryService
        return MemoryService()

    def test_estimate_tokens(self):
        from app.services.memory_service import MemoryService
        # ~1 token per 4 characters (BPE-style); min 1 token.
        assert MemoryService._estimate_tokens("hello world") == max(1, len("hello world") // 4)
        assert MemoryService._estimate_tokens("a b c d e f g h i j") == max(1, 19 // 4)
        # Floor at 1 token even for empty strings.
        assert MemoryService._estimate_tokens("") == 1

    def test_build_memory_context_signature(self):
        """Verify new parameters exist with correct defaults."""
        import inspect
        from app.services.memory_service import MemoryService
        sig = inspect.signature(MemoryService.build_memory_context)
        assert "budget" in sig.parameters
        assert "layers" in sig.parameters
        assert sig.parameters["budget"].default == 1500
        assert sig.parameters["layers"].default == (0, 1, 2)

    def test_l0_identity_empty_kg(self):
        """L0 returns None when KG is empty (backward compat)."""
        from app.services.memory_service import MemoryService
        ms = MemoryService()
        result = ms._build_l0_identity("nonexistent-project")
        assert result is None

    def test_l0_identity_with_pinned(self):
        """L0 returns pinned entities from KG cache."""
        from app.services.memory_service import MemoryService
        from app.services.knowledge_graph_service import get_knowledge_graph_service

        ms = MemoryService()
        kg = get_knowledge_graph_service()
        pid = _pid()

        # Manually populate the pinned cache
        kg._pinned_cache[pid] = (time.time(), [
            {"id": "1", "name": "Redis", "entity_type": "technology", "value": "caching layer"},
            {"id": "2", "name": "auth", "entity_type": "component", "value": "JWT-based"},
        ])

        result = ms._build_l0_identity(pid)
        assert result is not None
        assert "**Project identity:**" in result
        assert "Redis" in result
        assert "auth" in result

    def test_layers_control_what_is_loaded(self):
        """With layers=(0,) only L0 runs; L1/L2 are skipped."""
        from app.services.memory_service import MemoryService, _project_collection

        search_calls = []

        class TrackedMs(MemoryService):
            def __init__(self):
                self._chromadb_enabled = True

            def search_memory(self, query, collections=None, **kwargs):
                search_calls.append({"query": query, "collections": collections, "kwargs": kwargs})
                return []

            def _build_file_context(self, **kwargs):
                return None

        ms = TrackedMs()
        pid = _pid()

        # layers=(0,) — only L0, no ChromaDB searches
        search_calls.clear()
        result = ms._build_chromadb_context(query="test", project_id=pid, layers=(0,))
        assert len(search_calls) == 0, f"L0-only should not search ChromaDB, got {len(search_calls)} calls"

    def test_budget_caps_output(self):
        """Verify L2 respects budget by capping results."""
        from app.services.memory_service import MemoryService

        class BudgetMs(MemoryService):
            def __init__(self):
                self._chromadb_enabled = True

            def search_memory(self, query, collections=None, **kwargs):
                # Return many results with substantial text
                return [
                    {"id": f"m{i}", "text": f"This is memory item number {i} with enough words to consume token budget quickly " * 3, "score": 0.9, "metadata": {}}
                    for i in range(20)
                ]

            def _build_file_context(self, **kwargs):
                return None

        ms = BudgetMs()
        pid = _pid()

        # Small budget should limit output
        result = ms._build_chromadb_context(
            query="test", project_id=pid,
            budget=100, layers=(2,),
        )
        if result:
            tokens = MemoryService._estimate_tokens(result)
            # Some tolerance since we estimate
            assert tokens < 200, f"Budget 100 but got ~{tokens} tokens"

    def test_backward_compat_default_params(self):
        """Default params (budget=1500, layers=(0,1,2)) match old behavior."""
        from app.services.memory_service import MemoryService

        calls = []

        class CompatMs(MemoryService):
            def __init__(self):
                self._chromadb_enabled = True

            def search_memory(self, query, collections=None, **kwargs):
                calls.append(True)
                return [
                    {"id": "m1", "text": "A remembered fact", "score": 0.8, "metadata": {"importance": "high"}},
                ]

            def _build_file_context(self, **kwargs):
                return None

        ms = CompatMs()
        # Call with old-style params (no budget/layers)
        result = ms.build_memory_context(
            project_id="proj-x",
            query="test",
        )
        # Should still return something
        assert result is not None
        assert "A remembered fact" in result


# ============================================================================
# 5. L0 Bridge Integration
# ============================================================================

class TestL0Bridge:
    """Test the pinned KG cache → _build_l0_identity → build_memory_context pipeline."""

    @pytest.mark.asyncio
    async def test_pinned_entities_flow_into_context(self):
        """Add entity + pin it → refresh cache → L0 returns it in context."""
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        from app.services.memory_service import MemoryService

        kg = get_knowledge_graph_service()
        ms = MemoryService()
        pid = _pid()

        # Add entity and pin it
        eid = await kg.add_entity("Redis", "technology", pid)
        await kg.add_attribute(eid, "pinned", "true")
        await kg.refresh_pinned_cache(pid)

        # L0 should now return it
        l0 = ms._build_l0_identity(pid)
        assert l0 is not None
        assert "Redis" in l0
        assert "Project identity" in l0

    @pytest.mark.asyncio
    async def test_unpinned_entities_excluded(self):
        """Entities without pinned=true should not appear in L0."""
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        from app.services.memory_service import MemoryService

        kg = get_knowledge_graph_service()
        ms = MemoryService()
        pid = _pid()

        eid = await kg.add_entity("Redis", "technology", pid)
        # No pinned attribute
        await kg.refresh_pinned_cache(pid)

        l0 = ms._build_l0_identity(pid)
        assert l0 is None


# ============================================================================
# 6. Backward Compatibility
# ============================================================================

class TestBackwardCompat:
    """Verify that with empty KG, the system behaves identically to before."""

    def test_empty_kg_build_context_falls_through(self):
        """With empty KG, _build_chromadb_context returns same results as before."""
        from app.services.memory_service import MemoryService

        class OldStyleMs(MemoryService):
            def __init__(self):
                self._chromadb_enabled = True

            def search_memory(self, query, collections=None, **kwargs):
                return [
                    {"id": "m1", "text": "Old memory", "score": 0.85, "metadata": {}},
                ]

            def _build_file_context(self, **kwargs):
                return None

        ms = OldStyleMs()
        result = ms._build_chromadb_context(
            query="test",
            project_id="proj-test",
        )
        assert result is not None
        assert "Old memory" in result

    def test_isolation_unchanged(self):
        """Project isolation rules still hold with new layer system."""
        from app.services.memory_service import MemoryService, GLOBAL_COLLECTION

        captured_collections = []

        class IsolationMs(MemoryService):
            def __init__(self):
                self._chromadb_enabled = True

            def search_memory(self, query, collections=None, **kwargs):
                captured_collections.extend(collections or [])
                return []

            def _build_file_context(self, **kwargs):
                return None

        ms = IsolationMs()

        # Project mode — should NEVER query global
        captured_collections.clear()
        ms._build_chromadb_context(query="test", project_id="proj-x")
        assert GLOBAL_COLLECTION not in captured_collections, \
            f"Project mode leaked global: {captured_collections}"

        # Card mode — should NEVER query global
        captured_collections.clear()
        ms._build_chromadb_context(query="test", project_id="proj-x", card_id="card-1")
        assert GLOBAL_COLLECTION not in captured_collections, \
            f"Card mode leaked global: {captured_collections}"

        # General mode — SHOULD query global
        captured_collections.clear()
        ms._build_chromadb_context(query="test")
        assert GLOBAL_COLLECTION in captured_collections, \
            f"General mode should query global: {captured_collections}"


# ============================================================================
# 7. KG Tools in MCP Tool List (HTTP)
# ============================================================================

class TestKGToolsInMCPList:
    """Verify KG tools appear in the MCP tool registry."""

    @pytest.mark.asyncio
    async def test_kg_tools_in_tool_list(self):
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.get(f"{BASE}/mcp/tools")
            assert r.status_code == 200
            data = r.json()
            tool_names = {t["name"] for t in data.get("tools", [])}

            expected = {"kg.add", "kg.query", "kg.timeline", "kg.invalidate", "kg.stats"}
            missing = expected - tool_names
            assert not missing, f"KG tools missing from MCP list: {missing}"

    @pytest.mark.asyncio
    async def test_kg_tools_have_correct_scope(self):
        from app.mcp_server import _TOOL_DEFINITIONS
        kg_tools = [t for t in _TOOL_DEFINITIONS if t["name"].startswith("kg.")]
        assert len(kg_tools) == 5, f"Expected 5 KG tools, got {len(kg_tools)}"
        for t in kg_tools:
            assert t.get("_scope") == "voxyflow", f"KG tool {t['name']} has wrong scope: {t.get('_scope')}"
            assert t.get("_handler"), f"KG tool {t['name']} missing handler"

    @pytest.mark.asyncio
    async def test_kg_tools_have_input_schemas(self):
        from app.mcp_server import _TOOL_DEFINITIONS
        kg_tools = [t for t in _TOOL_DEFINITIONS if t["name"].startswith("kg.")]
        for t in kg_tools:
            schema = t.get("inputSchema", {})
            assert schema.get("type") == "object", \
                f"KG tool {t['name']} missing inputSchema.type=object"


# ============================================================================
# 8. Full Pipeline: KG Add → Query → Timeline → Invalidate cycle
# ============================================================================

class TestKGFullPipeline:
    """Test a complete entity lifecycle through MCP handlers."""

    @pytest.mark.asyncio
    async def test_full_entity_lifecycle(self):
        from app.mcp_server import _get_system_handler

        pid = _pid()
        prev = os.environ.get("VOXYFLOW_PROJECT_ID")
        os.environ["VOXYFLOW_PROJECT_ID"] = pid

        try:
            add = _get_system_handler("kg_add")
            query = _get_system_handler("kg_query")
            timeline = _get_system_handler("kg_timeline")
            invalidate = _get_system_handler("kg_invalidate")
            stats = _get_system_handler("kg_stats")

            # Step 1: Add entities with relationships
            r = await add({
                "entity_name": "Voxyflow",
                "entity_type": "component",
                "relationships": [
                    {"predicate": "uses", "target": "FastAPI", "target_type": "technology"},
                    {"predicate": "uses", "target": "React", "target_type": "technology"},
                ],
                "attributes": [
                    {"key": "version", "value": "2.0"},
                    {"key": "pinned", "value": "true"},
                ],
            })
            assert r["success"]
            entity_id = r["entity_id"]
            triple_ids = [rel["triple_id"] for rel in r["relationships"]]
            attr_ids = [a["attribute_id"] for a in r["attributes"]]

            # Step 2: Query — should find everything
            r = await query({"include_relationships": True})
            assert r["count"] == 3  # Voxyflow + FastAPI + React
            assert len(r["relationships"]) == 2

            # Step 3: Timeline — should show triples + attributes
            r = await timeline({})
            assert r["count"] >= 4  # 2 triples + 2 attributes

            # Step 4: Stats
            r = await stats({})
            assert r["entities"] == 3
            assert r["active_triples"] == 2
            assert r["active_attributes"] == 2

            # Step 5: Invalidate one relationship
            r = await invalidate({"triple_id": triple_ids[0]})
            assert r["success"]

            # Step 6: Verify relationship gone
            r = await query({"include_relationships": True})
            active_triple_ids = {rel["id"] for rel in r.get("relationships", [])}
            assert triple_ids[0] not in active_triple_ids
            assert triple_ids[1] in active_triple_ids

            # Step 7: Stats reflect the change
            r = await stats({})
            assert r["active_triples"] == 1  # one invalidated

            # Step 8: Invalidate attribute
            r = await invalidate({"attribute_id": attr_ids[0]})
            assert r["success"]
            r = await stats({})
            assert r["active_attributes"] == 1

        finally:
            if prev is None:
                os.environ.pop("VOXYFLOW_PROJECT_ID", None)
            else:
                os.environ["VOXYFLOW_PROJECT_ID"] = prev


# ============================================================================
# 9. Input Validation & Safety
# ============================================================================

class TestInputValidation:
    """Verify bounds checking, truncation, and error handling."""

    @pytest.fixture(autouse=True)
    def _set_project_env(self):
        self.pid = _pid()
        prev = os.environ.get("VOXYFLOW_PROJECT_ID")
        os.environ["VOXYFLOW_PROJECT_ID"] = self.pid
        yield
        if prev is None:
            os.environ.pop("VOXYFLOW_PROJECT_ID", None)
        else:
            os.environ["VOXYFLOW_PROJECT_ID"] = prev

    def _handler(self, name):
        from app.mcp_server import _get_system_handler
        return _get_system_handler(name)

    @pytest.mark.asyncio
    async def test_limit_clamped_to_max(self):
        """Passing limit=999999 should be clamped to 200."""
        add = self._handler("kg_add")
        await add({"entity_name": "X", "entity_type": "concept"})

        query = self._handler("kg_query")
        # Should not OOM — clamped internally
        result = await query({"limit": 999999})
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_limit_negative_clamped(self):
        query = self._handler("kg_query")
        result = await query({"limit": -5})
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_limit_non_integer(self):
        query = self._handler("kg_query")
        result = await query({"limit": "abc"})
        assert "error" not in result  # falls back to default

    @pytest.mark.asyncio
    async def test_long_entity_name_truncated(self):
        add = self._handler("kg_add")
        long_name = "A" * 10000
        result = await add({"entity_name": long_name, "entity_type": "concept"})
        assert result.get("success") is True
        # Name should be truncated to 500
        assert len(result["entity_name"]) == 500

    @pytest.mark.asyncio
    async def test_long_attribute_value_truncated(self):
        add = self._handler("kg_add")
        long_value = "V" * 50000
        result = await add({
            "entity_name": "test",
            "entity_type": "concept",
            "attributes": [{"key": "data", "value": long_value}],
        })
        assert result.get("success") is True
        assert len(result["attributes"][0]["value"]) == 5000

    @pytest.mark.asyncio
    async def test_malformed_as_of_returns_error(self):
        query = self._handler("kg_query")
        result = await query({"as_of": "not-a-date"})
        assert "error" in result
        assert "as_of" in result["error"].lower() or "datetime" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_valid_as_of_accepted(self):
        query = self._handler("kg_query")
        result = await query({"as_of": "2026-01-01T00:00:00"})
        assert "error" not in result

    @pytest.mark.asyncio
    async def test_confidence_nan_clamped(self):
        """NaN confidence should be clamped to 1.0."""
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        kg = get_knowledge_graph_service()
        pid = self.pid
        eid1 = await kg.add_entity("A", "concept", pid)
        eid2 = await kg.add_entity("B", "concept", pid)
        # Should not crash — NaN is sanitized
        tid = await kg.add_triple(eid1, "relates", eid2, confidence=float("nan"))
        assert tid

    @pytest.mark.asyncio
    async def test_confidence_negative_clamped(self):
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        kg = get_knowledge_graph_service()
        pid = self.pid
        eid1 = await kg.add_entity("C", "concept", pid)
        eid2 = await kg.add_entity("D", "concept", pid)
        tid = await kg.add_triple(eid1, "relates", eid2, confidence=-5.0)
        assert tid
        # Verify it was stored as 0.0
        rels = await kg.query_relationships(pid, entity_name="C")
        assert rels[0]["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_triple_with_nonexistent_entity_raises(self):
        from app.services.knowledge_graph_service import get_knowledge_graph_service
        kg = get_knowledge_graph_service()
        pid = self.pid
        eid = await kg.add_entity("real", "concept", pid)
        with pytest.raises(ValueError, match="does not exist"):
            await kg.add_triple(eid, "relates", "fake-entity-id")

    @pytest.mark.asyncio
    async def test_relationships_array_capped_at_50(self):
        add = self._handler("kg_add")
        rels = [{"predicate": "r", "target": f"t{i}", "target_type": "concept"} for i in range(100)]
        result = await add({
            "entity_name": "hub",
            "entity_type": "component",
            "relationships": rels,
        })
        assert result.get("success") is True
        assert len(result.get("relationships", [])) == 50
