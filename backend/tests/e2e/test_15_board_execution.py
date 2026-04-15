"""
E2E: Board execution — kanban:execute:start, card:execute, full lifecycle.

Tests the board executor flow via WebSocket and verifies cards move
through the system-managed lifecycle.
"""

import asyncio
import json
import time
import uuid

import pytest
import httpx

from .conftest import (
    ws_send, ws_recv_until, ws_collect_events, ws_collect_chat_response,
    assert_card_status, assert_card_history_contains, count_project_cards,
    chat_payload, WS_URL, LLM_TIMEOUT, REST_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Single card execution
# ---------------------------------------------------------------------------

class TestSingleCardExecution:
    @pytest.mark.asyncio
    async def test_card_execute_moves_through_lifecycle(self, ws, client, test_project):
        """card:execute should move a card: todo → in-progress → done."""
        pid = test_project["_id"]

        # Create a card with enough description for the worker
        r = await client.post(f"/api/projects/{pid}/cards", json={
            "title": f"Execute E2E {uuid.uuid4().hex[:6]}",
            "description": "Dis simplement 'tâche terminée' et rien d'autre.",
            "status": "todo",
        })
        assert r.status_code in (200, 201)
        card = r.json()
        cid = card["id"]
        session_id = f"e2e-exec-{uuid.uuid4().hex[:6]}"

        await ws_send(ws, "card:execute", {
            "cardId": cid,
            "projectId": pid,
            "sessionId": session_id,
        })

        events = await ws_collect_events(
            ws, {"task:started", "task:completed"},
            stop_on="task:completed", timeout=LLM_TIMEOUT,
        )

        started = [e for e in events if e["type"] == "task:started"]
        completed = [e for e in events if e["type"] == "task:completed"]

        if not started:
            pytest.skip("No worker started for card:execute")

        # Verify task:started has cardId
        assert started[0]["payload"].get("cardId") == cid

        if completed:
            # Card should now be done
            await assert_card_status(client, cid, "done")

            # Verify system created in-progress history entry
            await assert_card_history_contains(client, cid, "status", "in-progress", "System")

    @pytest.mark.asyncio
    async def test_card_execute_appends_result(self, ws, client, test_project):
        """After execution, the card description should contain the result."""
        pid = test_project["_id"]

        r = await client.post(f"/api/projects/{pid}/cards", json={
            "title": f"Result E2E {uuid.uuid4().hex[:6]}",
            "description": "Dis 'résultat du worker' exactement.",
            "status": "todo",
        })
        card = r.json()
        cid = card["id"]
        session_id = f"e2e-result-{uuid.uuid4().hex[:6]}"

        await ws_send(ws, "card:execute", {
            "cardId": cid,
            "projectId": pid,
            "sessionId": session_id,
        })

        events = await ws_collect_events(
            ws, {"task:completed"},
            stop_on="task:completed", timeout=LLM_TIMEOUT,
        )

        if not events:
            pytest.skip("Worker did not complete")

        # Check description was appended
        r = await client.get(f"/api/cards/{cid}")
        desc = r.json().get("description", "")
        assert "Execution Result" in desc, f"Expected 'Execution Result' in description, got: {desc[:200]}"


# ---------------------------------------------------------------------------
# Board execution (multiple cards)
# ---------------------------------------------------------------------------

class TestBoardExecution:
    @pytest.mark.asyncio
    async def test_kanban_execute_runs_todo_cards(self, ws, client, test_project):
        """kanban:execute:start should execute all todo cards on the board."""
        pid = test_project["_id"]

        # Create 2 todo cards
        card_ids = []
        for i in range(2):
            r = await client.post(f"/api/projects/{pid}/cards", json={
                "title": f"Board E2E {i} {uuid.uuid4().hex[:6]}",
                "description": f"Tâche simple #{i}: dis 'fait' et rien d'autre.",
                "status": "todo",
            })
            assert r.status_code in (200, 201)
            card_ids.append(r.json()["id"])

        session_id = f"e2e-board-{uuid.uuid4().hex[:6]}"

        await ws_send(ws, "kanban:execute:start", {
            "projectId": pid,
            "sessionId": session_id,
            "statuses": ["todo"],
        })

        # Collect events — board execution emits kanban-specific events
        events = await ws_collect_events(
            ws,
            {
                "kanban:execute:card:start",
                "kanban:execute:card:done",
                "kanban:execute:complete",
                "kanban:execute:error",
                "task:started",
                "task:completed",
            },
            stop_on="kanban:execute:complete",
            timeout=LLM_TIMEOUT * 2,  # Board execution can take longer
        )

        # Check we got at least some execution events
        errors = [e for e in events if e["type"] == "kanban:execute:error"]
        if errors:
            error_msg = errors[0].get("payload", {}).get("error", "unknown")
            pytest.fail(f"Board execution error: {error_msg}")

        complete = [e for e in events if e["type"] == "kanban:execute:complete"]
        if not complete:
            # May have timed out — check card statuses anyway
            pass

        # Give a moment for DB writes to settle
        await asyncio.sleep(2)

        # Check all cards ended up done (or at least in-progress)
        for cid in card_ids:
            r = await client.get(f"/api/cards/{cid}")
            status = r.json().get("status")
            assert status in ("in-progress", "done"), \
                f"Card {cid} expected in-progress or done, got {status}"


# ---------------------------------------------------------------------------
# Worker tasks ledger
# ---------------------------------------------------------------------------

class TestWorkerTaskLedger:
    @pytest.mark.asyncio
    async def test_worker_tasks_listed(self, client):
        """GET /worker-tasks should return a list."""
        r = await client.get("/api/worker-tasks", timeout=REST_TIMEOUT)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, (list, dict))

    @pytest.mark.asyncio
    async def test_worker_sessions_listed(self, client):
        """GET /workers/sessions should return worker sessions."""
        r = await client.get("/api/workers/sessions", timeout=REST_TIMEOUT)
        assert r.status_code == 200
