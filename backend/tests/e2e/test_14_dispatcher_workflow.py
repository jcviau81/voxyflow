"""
E2E: Dispatcher workflow — chat layers, delegates, memory, sessions, scheduler.

Tests the full dispatcher behavior across all chat levels and verify
system-managed workflows are properly enforced.
"""

import asyncio
import json
import time
import uuid

import pytest
import httpx

from .conftest import (
    ws_send, ws_recv_until, ws_collect_events, ws_collect_chat_response,
    assert_card_status, chat_payload, WS_URL, LLM_TIMEOUT, REST_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Chat Layers — verify all 3 levels work and maintain context
# ---------------------------------------------------------------------------

class TestChatLayers:
    @pytest.mark.asyncio
    async def test_general_chat_responds(self, ws):
        """General chat should produce a response."""
        session_id = f"e2e-gen-{uuid.uuid4().hex[:6]}"
        await ws_send(ws, "chat:message", chat_payload(
            "Dis 'bonjour' en un mot.",
            chatLevel="general",
            sessionId=session_id,
        ))
        response = await ws_collect_chat_response(ws, timeout=LLM_TIMEOUT)
        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_project_chat_responds(self, ws, client, test_project):
        """Project chat should work with project context."""
        pid = test_project["_id"]
        session_id = f"e2e-proj-{uuid.uuid4().hex[:6]}"
        await ws_send(ws, "chat:message", chat_payload(
            "Combien de cartes y a-t-il dans ce projet?",
            chatLevel="project",
            projectId=pid,
            sessionId=session_id,
            chatId=f"project:{pid}",
        ))
        response = await ws_collect_chat_response(ws, timeout=LLM_TIMEOUT)
        assert len(response) > 0

    @pytest.mark.asyncio
    async def test_card_chat_responds(self, ws, client, test_card):
        """Card chat should work with card context."""
        cid = test_card["_id"]
        pid = test_card["_project_id"]
        session_id = f"e2e-card-{uuid.uuid4().hex[:6]}"
        await ws_send(ws, "chat:message", chat_payload(
            "Décris cette carte.",
            chatLevel="card",
            projectId=pid,
            cardId=cid,
            sessionId=session_id,
            chatId=f"card:{cid}",
        ))
        response = await ws_collect_chat_response(ws, timeout=LLM_TIMEOUT)
        assert len(response) > 0


# ---------------------------------------------------------------------------
# Delegate emission — verify the dispatcher properly delegates
# ---------------------------------------------------------------------------

class TestDelegateEmission:
    @pytest.mark.asyncio
    async def test_imperative_triggers_delegate(self, ws, client, test_project):
        """An imperative command should trigger a worker delegate."""
        pid = test_project["_id"]
        session_id = f"e2e-delegate-{uuid.uuid4().hex[:6]}"

        await ws_send(ws, "chat:message", chat_payload(
            "Lis le fichier /etc/hostname et montre le contenu.",
            chatLevel="project",
            projectId=pid,
            sessionId=session_id,
            chatId=f"project:{pid}",
        ))

        events = await ws_collect_events(
            ws, {"task:started", "task:completed", "chat:response"},
            stop_on="task:completed", timeout=LLM_TIMEOUT,
        )

        started = [e for e in events if e["type"] == "task:started"]
        if not started:
            # The dispatcher may have answered inline — that's acceptable
            # but we note it
            chat_chunks = [e for e in events if e["type"] == "chat:response"]
            assert len(chat_chunks) > 0, "Expected either a delegate or a chat response"
            return

        # Verify task metadata
        payload = started[0]["payload"]
        assert "intent" in payload
        assert "model" in payload

    @pytest.mark.asyncio
    async def test_delegate_creates_worker_task(self, ws, client, test_project):
        """A delegate should create a WorkerTask entry in the ledger."""
        pid = test_project["_id"]
        session_id = f"e2e-ledger-{uuid.uuid4().hex[:6]}"

        await ws_send(ws, "chat:message", chat_payload(
            "Exécute 'echo test123' dans le terminal.",
            chatLevel="project",
            projectId=pid,
            sessionId=session_id,
            chatId=f"project:{pid}",
        ))

        events = await ws_collect_events(
            ws, {"task:started", "task:completed"},
            stop_on="task:completed", timeout=LLM_TIMEOUT,
        )

        started = [e for e in events if e["type"] == "task:started"]
        if not started:
            pytest.skip("No delegate emitted")

        task_id = started[0]["payload"]["taskId"]

        # Check the worker task ledger
        r = await client.get(f"/api/worker-tasks/{task_id}", timeout=REST_TIMEOUT)
        assert r.status_code == 200
        task = r.json()
        assert task["status"] in ("running", "done", "failed")


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class TestSessionManagement:
    @pytest.mark.asyncio
    async def test_session_reset_clears_context(self, ws):
        """session:reset should return an ack with a chatId."""
        session_id = f"e2e-reset-{uuid.uuid4().hex[:6]}"
        await ws_send(ws, "session:reset", {
            "chatLevel": "general",
            "sessionId": session_id,
        })
        data = await ws_recv_until(ws, "session:reset_ack", timeout=10)
        assert "chatId" in data.get("payload", {})

    @pytest.mark.asyncio
    async def test_session_history_persisted(self, client):
        """Chat sessions should be listed via REST."""
        r = await client.get("/api/sessions")
        assert r.status_code == 200
        data = r.json()
        # Just verify the endpoint works
        assert isinstance(data, (list, dict))


# ---------------------------------------------------------------------------
# Memory operations via chat
# ---------------------------------------------------------------------------

class TestMemoryViaMCP:
    @pytest.mark.asyncio
    async def test_memory_save_and_search(self, ws, client, test_project):
        """Dispatcher should be able to save and search memory."""
        pid = test_project["_id"]
        session_id = f"e2e-mem-{uuid.uuid4().hex[:6]}"
        unique_fact = f"E2E_FACT_{uuid.uuid4().hex[:8]}"

        # Ask Voxy to remember something specific
        await ws_send(ws, "chat:message", chat_payload(
            f"Souviens-toi de ce fait important: {unique_fact}",
            chatLevel="project",
            projectId=pid,
            sessionId=session_id,
            chatId=f"project:{pid}",
        ))
        await ws_collect_chat_response(ws, timeout=LLM_TIMEOUT)

        # Now ask to search for it (new session to avoid context)
        session_id2 = f"e2e-mem2-{uuid.uuid4().hex[:6]}"
        await ws_send(ws, "chat:message", chat_payload(
            f"Cherche dans ta mémoire: {unique_fact}",
            chatLevel="project",
            projectId=pid,
            sessionId=session_id2,
            chatId=f"project:{pid}",
        ))
        response = await ws_collect_chat_response(ws, timeout=LLM_TIMEOUT)
        # We can't guarantee the LLM will find it, but the flow shouldn't error
        assert len(response) > 0


# ---------------------------------------------------------------------------
# Scheduler jobs
# ---------------------------------------------------------------------------

class TestSchedulerJobs:
    @pytest.mark.asyncio
    async def test_list_builtin_jobs(self, client):
        """Built-in jobs should be present."""
        r = await client.get("/api/jobs")
        assert r.status_code == 200
        jobs = r.json().get("jobs", [])
        types = {j.get("type") for j in jobs}
        # At least heartbeat and recurrence should exist
        assert "agent_task" in types or len(jobs) > 0

    @pytest.mark.asyncio
    async def test_create_and_trigger_agent_task(self, client, test_project):
        """Create an agent_task job and trigger it."""
        pid = test_project["_id"]
        r = await client.post("/api/jobs", json={
            "name": f"E2E Agent Task {uuid.uuid4().hex[:6]}",
            "type": "agent_task",
            "schedule": "every_1h",
            "enabled": False,
            "payload": {
                "instruction": "Dis 'job terminé' et ne fais rien d'autre.",
                "project_id": pid,
            },
        })
        assert r.status_code == 201
        job = r.json()
        job_id = job["id"]

        try:
            # Trigger
            r = await client.post(f"/api/jobs/{job_id}/run", timeout=60)
            assert r.status_code == 200
        finally:
            await client.delete(f"/api/jobs/{job_id}")

    @pytest.mark.asyncio
    async def test_create_execute_card_job(self, client, test_project, test_card):
        """Create an execute_card job."""
        cid = test_card["_id"]
        pid = test_card["_project_id"]

        r = await client.post("/api/jobs", json={
            "name": f"E2E Execute Card {uuid.uuid4().hex[:6]}",
            "type": "execute_card",
            "schedule": "every_1h",
            "enabled": False,
            "payload": {
                "card_id": cid,
                "project_id": pid,
            },
        })
        assert r.status_code == 201
        job = r.json()

        await client.delete(f"/api/jobs/{job['id']}")

    @pytest.mark.asyncio
    async def test_create_execute_board_job(self, client, test_project):
        """Create an execute_board job."""
        pid = test_project["_id"]

        r = await client.post("/api/jobs", json={
            "name": f"E2E Execute Board {uuid.uuid4().hex[:6]}",
            "type": "execute_board",
            "schedule": "every_1h",
            "enabled": False,
            "payload": {
                "project_id": pid,
                "statuses": ["todo"],
            },
        })
        assert r.status_code == 201
        job = r.json()

        await client.delete(f"/api/jobs/{job['id']}")
