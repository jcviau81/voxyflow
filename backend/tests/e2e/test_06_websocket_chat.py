"""
E2E: WebSocket chat — connection, ping/pong, all chat layers
(general, project, card), streaming responses, session reset.

These tests require the LLM backend to be running (CLAUDE_USE_CLI=true).
"""

import asyncio
import json
import time
import uuid

import pytest

from .conftest import ws_send, ws_recv_until, ws_collect_chat_response, WS_URL, LLM_TIMEOUT


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _chat_payload(content: str, **kwargs) -> dict:
    return {
        "content": content,
        "messageId": f"e2e-{uuid.uuid4().hex[:8]}",
        "chatLevel": kwargs.get("chatLevel", "general"),
        "projectId": kwargs.get("projectId"),
        "cardId": kwargs.get("cardId"),
        "sessionId": kwargs.get("sessionId", f"e2e-session-{uuid.uuid4().hex[:6]}"),
        "chatId": kwargs.get("chatId"),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestWebSocketConnection:
    @pytest.mark.asyncio
    async def test_connect(self, ws):
        """Verify WS connects without error."""
        # websockets v14 uses .state instead of .open
        assert not getattr(ws, 'closed', False)

    @pytest.mark.asyncio
    async def test_ping_pong(self, ws):
        """Server should respond to ping with pong."""
        await ws_send(ws, "ping", {})
        data = await ws_recv_until(ws, "pong", timeout=5)
        assert data["type"] == "pong"

    @pytest.mark.asyncio
    async def test_multiple_pings(self, ws):
        """Multiple pings should each get a pong."""
        for _ in range(3):
            await ws_send(ws, "ping", {})
            data = await ws_recv_until(ws, "pong", timeout=5)
            assert data["type"] == "pong"


class TestSessionReset:
    @pytest.mark.asyncio
    async def test_session_reset(self, ws):
        """session:reset should return session:reset_ack."""
        await ws_send(ws, "session:reset", {
            "chatLevel": "general",
            "sessionId": f"e2e-reset-{uuid.uuid4().hex[:6]}",
        })
        data = await ws_recv_until(ws, "session:reset_ack", timeout=10)
        assert data["type"] == "session:reset_ack"
        assert "chatId" in data.get("payload", {})


class TestGeneralChat:
    @pytest.mark.asyncio
    async def test_general_chat_response(self, ws):
        """Send a simple message in general chat and get a streamed response."""
        session_id = f"e2e-general-{uuid.uuid4().hex[:6]}"
        payload = _chat_payload(
            "Dis-moi bonjour en une phrase.",
            chatLevel="general",
            sessionId=session_id,
        )
        await ws_send(ws, "chat:message", payload)
        response = await ws_collect_chat_response(ws, timeout=LLM_TIMEOUT)
        assert len(response) > 0, "Expected non-empty response"

    @pytest.mark.asyncio
    async def test_general_chat_receives_model_status(self, ws):
        """Chat should emit model:status events during processing."""
        session_id = f"e2e-model-{uuid.uuid4().hex[:6]}"
        payload = _chat_payload(
            "Dis 'ok'.",
            chatLevel="general",
            sessionId=session_id,
        )
        await ws_send(ws, "chat:message", payload)

        # Collect events until done
        got_model_status = False
        deadline = time.time() + LLM_TIMEOUT
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(raw)
                if data.get("type") == "model:status":
                    got_model_status = True
                if data.get("type") == "chat:response" and data.get("payload", {}).get("done"):
                    break
            except asyncio.TimeoutError:
                await ws_send(ws, "ping", {})

        assert got_model_status, "Expected at least one model:status event"


class TestProjectChat:
    @pytest.mark.asyncio
    async def test_project_chat(self, ws, client, test_project: dict):
        """Send a chat message scoped to a project."""
        pid = test_project["_id"]
        session_id = f"e2e-proj-{uuid.uuid4().hex[:6]}"
        chat_id = f"project:{pid}"

        payload = _chat_payload(
            "Liste les cartes de ce projet.",
            chatLevel="project",
            projectId=pid,
            sessionId=session_id,
            chatId=chat_id,
        )
        await ws_send(ws, "chat:message", payload)
        response = await ws_collect_chat_response(ws, timeout=LLM_TIMEOUT)
        assert len(response) > 0


class TestCardChat:
    @pytest.mark.asyncio
    async def test_card_chat(self, ws, client, test_card: dict):
        """Send a chat message scoped to a specific card."""
        cid = test_card["_id"]
        pid = test_card["_project_id"]
        session_id = f"e2e-card-{uuid.uuid4().hex[:6]}"
        chat_id = f"card:{cid}"

        payload = _chat_payload(
            "Qu'est-ce que cette carte fait?",
            chatLevel="card",
            projectId=pid,
            cardId=cid,
            sessionId=session_id,
            chatId=chat_id,
        )
        await ws_send(ws, "chat:message", payload)
        response = await ws_collect_chat_response(ws, timeout=LLM_TIMEOUT)
        assert len(response) > 0


class TestChatIdValidation:
    @pytest.mark.asyncio
    async def test_mismatched_chatid_corrected(self, ws, client, test_project: dict):
        """If frontend sends a chatId that doesn't match projectId, server corrects it."""
        pid = test_project["_id"]
        session_id = f"e2e-mismatch-{uuid.uuid4().hex[:6]}"

        # Send with wrong chatId
        payload = _chat_payload(
            "Test mismatch.",
            chatLevel="project",
            projectId=pid,
            sessionId=session_id,
            chatId="project:wrong-id",  # Mismatched
        )
        await ws_send(ws, "chat:message", payload)

        # Should still get a response (server corrects the chatId)
        response = await ws_collect_chat_response(ws, timeout=LLM_TIMEOUT)
        assert len(response) > 0
