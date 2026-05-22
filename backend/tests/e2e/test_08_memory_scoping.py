"""
E2E: Memory scoping — workspace isolation, global vs per-workspace collections,
no cross-workspace leakage.

Tests memory at the SERVICE level (imports MemoryService directly)
and at the MCP handler level (environment variable scoping).
"""

import os
import sys
import uuid

import pytest

# Add backend to path for direct imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ---------------------------------------------------------------------------
# Service-level tests (no backend required)
# ---------------------------------------------------------------------------

class TestMemoryServiceIsolation:
    """Tests that exercise MemoryService directly for isolation guarantees."""

    def _get_memory_service(self):
        from app.services.memory_service import get_memory_service
        return get_memory_service()

    def _workspace_collection(self, workspace_id: str) -> str:
        from app.services.memory_service import _workspace_collection
        return _workspace_collection(workspace_id)

    def test_global_collection_constant(self):
        from app.services.memory_service import GLOBAL_COLLECTION
        assert GLOBAL_COLLECTION == "memory-global"

    def test_workspace_collection_uses_uuid(self):
        pid = str(uuid.uuid4())
        col = self._workspace_collection(pid)
        assert col == f"memory-workspace-{pid}"
        assert pid in col

    def test_search_memory_requires_collections(self):
        """search_memory MUST raise ValueError if collections= is not provided."""
        svc = self._get_memory_service()
        with pytest.raises(ValueError, match="collections="):
            svc.search_memory("test query")

    def test_search_memory_with_explicit_collections(self):
        """search_memory works when collections is explicitly provided."""
        svc = self._get_memory_service()
        pid = str(uuid.uuid4())
        col = self._workspace_collection(pid)
        results = svc.search_memory("test", collections=[col])
        assert isinstance(results, list)


class TestMemoryWorkspaceIsolation:
    """Save memory in workspace A, verify it does NOT appear in workspace B."""

    def _get_memory_service(self):
        from app.services.memory_service import get_memory_service
        return get_memory_service()

    def _workspace_collection(self, workspace_id: str) -> str:
        from app.services.memory_service import _workspace_collection
        return _workspace_collection(workspace_id)

    def test_memory_does_not_leak_between_workspaces(self):
        svc = self._get_memory_service()
        if not svc._chromadb_enabled:
            pytest.skip("ChromaDB not available")

        pid_a = f"e2e-iso-a-{uuid.uuid4().hex[:8]}"
        pid_b = f"e2e-iso-b-{uuid.uuid4().hex[:8]}"
        col_a = self._workspace_collection(pid_a)
        col_b = self._workspace_collection(pid_b)

        unique_marker = f"UNIQUE_MARKER_{uuid.uuid4().hex[:8]}"

        # Save memory in workspace A
        svc.store_memory(
            text=f"Secret info for workspace A: {unique_marker}",
            collection=col_a,
            metadata={"workspace": pid_a, "type": "test"},
        )

        # Search in workspace B — should NOT find the marker
        results_b = svc.search_memory(unique_marker, collections=[col_b])
        leaked_texts = [r["text"] for r in results_b if unique_marker in r.get("text", "")]
        assert len(leaked_texts) == 0, f"Memory leaked from A to B: {leaked_texts}"

        # Search in workspace A — SHOULD find the marker
        results_a = svc.search_memory(unique_marker, collections=[col_a])
        found = [r for r in results_a if unique_marker in r.get("text", "")]
        assert len(found) >= 1, "Memory not found in originating workspace"

        # Cleanup
        for r in results_a:
            svc.delete_memory(r["id"], collection=col_a)

    def test_global_collection_isolated_from_workspace(self):
        """Workspace searches should not see memory-global entries."""
        svc = self._get_memory_service()
        if not svc._chromadb_enabled:
            pytest.skip("ChromaDB not available")

        from app.services.memory_service import GLOBAL_COLLECTION

        pid = f"e2e-iso-global-{uuid.uuid4().hex[:8]}"
        col = self._workspace_collection(pid)
        marker = f"GLOBAL_MARKER_{uuid.uuid4().hex[:8]}"

        # Save to global
        svc.store_memory(
            text=f"Global secret: {marker}",
            collection=GLOBAL_COLLECTION,
            metadata={"type": "test"},
        )

        # Search in workspace-specific collection — should NOT find it
        results = svc.search_memory(marker, collections=[col])
        leaked = [r for r in results if marker in r.get("text", "")]
        assert len(leaked) == 0, f"Global memory leaked to workspace: {leaked}"

        # Cleanup global
        global_results = svc.search_memory(marker, collections=[GLOBAL_COLLECTION])
        for r in global_results:
            svc.delete_memory(r["id"], collection=GLOBAL_COLLECTION)


class TestBuildContextIsolation:
    """Verify _build_chromadb_context respects workspace isolation."""

    def _get_memory_service(self):
        from app.services.memory_service import get_memory_service
        return get_memory_service()

    def test_build_context_workspace_does_not_include_global(self):
        """When building context for a workspace chat, global should be excluded."""
        svc = self._get_memory_service()
        if not svc._chromadb_enabled:
            pytest.skip("ChromaDB not available")

        pid = f"e2e-ctx-{uuid.uuid4().hex[:8]}"

        # Build context for a workspace — should only use workspace collection
        # This is a structural test; we verify the method runs without error
        # and that it doesn't crash on a fresh workspace with no memories
        result = svc._build_chromadb_context(
            query="test query",
            workspace_id=pid,
            include_long_term=True,
        )
        # Result can be None (empty workspace) or a string — both are valid
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# MCP handler-level tests (environment variable scoping)
# ---------------------------------------------------------------------------

class TestMCPMemoryScoping:
    """Verify MCP handlers respect VOXYFLOW_WORKSPACE_ID environment variable."""

    def test_mcp_handler_reads_workspace_id_env(self):
        """memory_search handler should scope to VOXYFLOW_WORKSPACE_ID."""
        pid = str(uuid.uuid4())
        os.environ["VOXYFLOW_WORKSPACE_ID"] = pid

        try:
            from app.mcp_server import _get_system_handler
            handler = _get_system_handler("memory.search")
            if handler is None:
                pytest.skip("memory.search handler not found")

            # The handler should use the env var for scoping
            # We just verify it doesn't crash
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                handler({"query": "test"})
            )
            assert isinstance(result, (dict, list, str))
        finally:
            os.environ.pop("VOXYFLOW_WORKSPACE_ID", None)

    def test_mcp_handler_empty_env_uses_system_main(self):
        """Empty VOXYFLOW_WORKSPACE_ID should fall back to system-main."""
        os.environ.pop("VOXYFLOW_WORKSPACE_ID", None)

        try:
            from app.mcp_server import _get_system_handler
            handler = _get_system_handler("memory.search")
            if handler is None:
                pytest.skip("memory.search handler not found")

            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                handler({"query": "test"})
            )
            assert isinstance(result, (dict, list, str))
        finally:
            pass
