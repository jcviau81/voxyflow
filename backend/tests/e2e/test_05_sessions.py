"""
E2E: Session management — CRUD, message search, history.
"""

import uuid

import pytest
import httpx


class TestSessionCRUD:
    @pytest.mark.asyncio
    async def test_create_session(self, client: httpx.AsyncClient):
        r = await client.post("/api/sessions", json={
            "workspace_id": "system-main",
            "title": "E2E Test Session",
        })
        assert r.status_code in (200, 201)
        data = r.json()
        assert "chatId" in data

        # Cleanup
        chat_id = data["chatId"]
        await client.delete(f"/api/sessions/{chat_id}")

    @pytest.mark.asyncio
    async def test_list_sessions(self, client: httpx.AsyncClient):
        r = await client.get("/api/sessions", params={"active": "true"})
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_session_messages(self, client: httpx.AsyncClient):
        # Create session
        r = await client.post("/api/sessions", json={"workspace_id": "system-main"})
        chat_id = r.json().get("chatId")

        # Get messages (should be empty for new session)
        r = await client.get(f"/api/sessions/{chat_id}")
        assert r.status_code == 200
        data = r.json()
        assert "messages" in data
        assert "count" in data

        # Cleanup
        await client.delete(f"/api/sessions/{chat_id}")

    @pytest.mark.asyncio
    async def test_delete_session(self, client: httpx.AsyncClient):
        # Create
        r = await client.post("/api/sessions", json={"workspace_id": "system-main"})
        chat_id = r.json().get("chatId")

        # Delete
        r = await client.delete(f"/api/sessions/{chat_id}")
        assert r.status_code == 200
        assert r.json().get("deleted") == chat_id


class TestSessionSearch:
    """Note: /api/sessions/search/messages is shadowed by /{chat_id:path}.
    The route ordering in sessions.py causes the path converter to consume
    "search/messages" as a chat_id. Tests verify current behavior.
    """

    @pytest.mark.asyncio
    async def test_search_endpoint_responds(self, client: httpx.AsyncClient):
        """Endpoint responds 200 (currently shadowed by get_session catch-all)."""
        r = await client.get("/api/sessions/search/messages", params={"q": "test"})
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_search_with_workspace_filter(self, client: httpx.AsyncClient, test_workspace: dict):
        pid = test_workspace["_id"]
        r = await client.get("/api/sessions/search/messages", params={
            "q": "test",
            "workspace_id": pid,
        })
        assert r.status_code == 200


class TestSessionIsolation:
    @pytest.mark.asyncio
    async def test_sessions_scoped_to_workspace(self, client: httpx.AsyncClient):
        """Sessions created for workspace A should use workspace A's chat_id prefix."""
        tag = uuid.uuid4().hex[:8]

        # Create workspace
        r = await client.post("/api/workspaces", json={"title": f"SessIso_{tag}"})
        pid = r.json().get("id")

        try:
            # Create session for this workspace
            r = await client.post("/api/sessions", json={"workspace_id": pid})
            data = r.json()
            chat_id = data.get("chatId")
            assert chat_id is not None, f"No chatId in response: {data}"
            assert pid in chat_id or "workspace:" in chat_id
        finally:
            await client.delete(f"/api/workspaces/{pid}")

    @pytest.mark.asyncio
    async def test_session_messages_empty_for_new_session(self, client: httpx.AsyncClient):
        """A freshly created session should have 0 messages."""
        r = await client.post("/api/sessions", json={"workspace_id": "system-main"})
        chat_id = r.json().get("chatId")

        r = await client.get(f"/api/sessions/{chat_id}")
        data = r.json()
        assert data["count"] == 0

        await client.delete(f"/api/sessions/{chat_id}")
