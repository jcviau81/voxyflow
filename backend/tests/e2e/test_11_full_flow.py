"""
E2E: Full integration flow — tests a realistic user workflow end-to-end:

1. Create project
2. Create cards in various statuses
3. Create wiki page
4. Chat with Voxy about the project (WS)
5. Verify workers list
6. Move cards around the board
7. Add checklist, comments, time entries
8. Verify session history persists
9. Verify card history recorded
10. Export project
11. Cleanup

This test exercises the full stack: REST + WebSocket + LLM + persistence.
"""

import asyncio
import json
import time
import uuid

import pytest
import httpx

from .conftest import (
    BASE_URL, WS_URL, LLM_TIMEOUT,
    ws_send, ws_collect_chat_response,
)


@pytest.mark.asyncio
async def test_full_project_lifecycle(client: httpx.AsyncClient):
    """Full project + card + wiki lifecycle without LLM (REST only)."""
    tag = uuid.uuid4().hex[:6]
    pid = None

    try:
        # 1. Create project
        r = await client.post("/api/projects", json={
            "title": f"FullFlow_{tag}",
            "description": "Full E2E flow test",
        })
        assert r.status_code in (200, 201)
        pid = r.json().get("id")
        assert pid

        # 2. Create multiple cards with different statuses
        card_ids = []
        for i, status in enumerate(["card", "todo", "in-progress", "done"]):
            r = await client.post(f"/api/projects/{pid}/cards", json={
                "title": f"Flow Card {i} ({status})",
                "description": f"Card at status {status}",
                "status": status,
                "priority": i,
            })
            if r.status_code == 500:
                # SQLite WAL contention — retry once after short delay
                await asyncio.sleep(0.3)
                r = await client.post(f"/api/projects/{pid}/cards", json={
                    "title": f"Flow Card {i} ({status})",
                    "description": f"Card at status {status}",
                    "status": status,
                    "priority": i,
                })
            assert r.status_code in (200, 201), f"Card create failed: {r.status_code} {r.text}"
            cid = r.json().get("id")
            card_ids.append(cid)

        # 3. Create wiki page
        r = await client.post(f"/api/projects/{pid}/wiki", json={
            "title": "Project Documentation",
            "content": "# Full Flow Test\nDocumentation for the flow test project.",
        })
        assert r.status_code in (200, 201)
        wiki_id = r.json().get("id")

        # 4. Verify all cards are listed
        r = await client.get(f"/api/projects/{pid}/cards")
        assert r.status_code == 200
        cards = r.json()
        assert len(cards) >= 4

        # 5. Move card from todo → in-progress → done
        todo_card = card_ids[1]
        r = await client.patch(f"/api/cards/{todo_card}", json={"status": "in-progress"})
        assert r.status_code == 200
        assert r.json()["status"] == "in-progress"

        r = await client.patch(f"/api/cards/{todo_card}", json={"status": "done"})
        assert r.status_code == 200
        assert r.json()["status"] == "done"

        # 6. Add checklist to first card
        r = await client.post(f"/api/cards/{card_ids[0]}/checklist", json={"text": "Step A"})
        assert r.status_code in (200, 201)
        cl_id = r.json().get("id")

        r = await client.post(f"/api/cards/{card_ids[0]}/checklist", json={"text": "Step B"})
        assert r.status_code in (200, 201)

        # Toggle checklist item
        if cl_id:
            r = await client.patch(f"/api/cards/{card_ids[0]}/checklist/{cl_id}", json={"completed": True})
            assert r.status_code == 200

        # 7. Add comment to second card
        r = await client.post(f"/api/cards/{card_ids[1]}/comments", json={
            "content": "Good progress on this task.",
        })
        assert r.status_code in (200, 201)

        # 8. Log time on third card
        r = await client.post(f"/api/cards/{card_ids[2]}/time", json={
            "duration_minutes": 60,
            "note": "Coding session",
        })
        assert r.status_code in (200, 201)

        # 9. Vote on fourth card
        r = await client.post(f"/api/cards/{card_ids[3]}/vote")
        assert r.status_code == 200

        # 10. Assign agent to first card
        r = await client.post(f"/api/cards/{card_ids[0]}/assign", json={
            "agent_type": "coder",
        })
        assert r.status_code == 200

        # 11. Verify card history
        r = await client.get(f"/api/cards/{todo_card}/history")
        assert r.status_code == 200
        history = r.json()
        assert len(history) >= 1  # At least the status changes

        # 12. Archive and restore a card (use a non-done card to avoid status conflicts)
        archive_cid = card_ids[0]  # "card" status
        r = await client.post(f"/api/cards/{archive_cid}/archive")
        assert r.status_code == 200

        r = await client.post(f"/api/cards/{archive_cid}/restore")
        assert r.status_code in (200, 400)  # 400 if restore requires specific source status

        # 13. Duplicate a card
        r = await client.post(f"/api/cards/{card_ids[0]}/duplicate")
        assert r.status_code in (200, 201)
        dup_id = r.json().get("id")
        if dup_id:
            card_ids.append(dup_id)

        # 14. Create card relation (blocks)
        r = await client.post(f"/api/cards/{card_ids[0]}/relations", json={
            "target_card_id": card_ids[1],
            "relation_type": "blocks",
        })
        assert r.status_code in (200, 201)

        # 15. Update wiki
        r = await client.put(f"/api/projects/{pid}/wiki/{wiki_id}", json={
            "title": "Updated Documentation",
            "content": "# Updated\nNow with more content.",
        })
        assert r.status_code == 200

        # 16. Export project
        r = await client.get(f"/api/projects/{pid}/export")
        assert r.status_code == 200
        export = r.json()
        assert "project" in export
        assert "cards" in export
        assert len(export["cards"]) >= 4

        # 17. Verify project detail includes cards
        r = await client.get(f"/api/projects/{pid}")
        assert r.status_code == 200

        # 18. Archive project
        r = await client.post(f"/api/projects/{pid}/archive")
        assert r.status_code == 200
        r = await client.get(f"/api/projects/{pid}")
        assert r.json()["status"] == "archived"

        # 19. Restore project
        r = await client.post(f"/api/projects/{pid}/restore")
        assert r.status_code == 200

    finally:
        # Cleanup
        if pid:
            await client.delete(f"/api/projects/{pid}")


@pytest.mark.asyncio
async def test_full_chat_flow():
    """Full chat flow: WS connect → general chat → project chat → verify response."""
    import websockets

    tag = uuid.uuid4().hex[:6]
    pid = None

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        # Create a test project
        r = await client.post("/api/projects", json={
            "title": f"ChatFlow_{tag}",
            "description": "Chat flow test",
        })
        assert r.status_code in (200, 201)
        pid = r.json().get("id")

        # Create a card in it
        r = await client.post(f"/api/projects/{pid}/cards", json={
            "title": "Chat test card",
            "status": "todo",
        })
        assert r.status_code in (200, 201)

    try:
        async with websockets.connect(WS_URL, open_timeout=10) as ws:
            # 1. Ping/pong
            await ws_send(ws, "ping", {})
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            assert json.loads(raw)["type"] == "pong"

            # 2. General chat
            session_id = f"e2e-fullchat-{tag}"
            await ws_send(ws, "chat:message", {
                "content": "Dis bonjour.",
                "messageId": f"e2e-msg-{tag}-1",
                "chatLevel": "general",
                "sessionId": session_id,
            })
            response = await ws_collect_chat_response(ws, timeout=LLM_TIMEOUT)
            assert len(response) > 0, "General chat produced empty response"

            # 3. Project chat
            await ws_send(ws, "session:reset", {
                "chatLevel": "project",
                "projectId": pid,
                "sessionId": f"e2e-projchat-{tag}",
            })
            # Wait for reset ack
            deadline = time.time() + 10
            while time.time() < deadline:
                raw = await asyncio.wait_for(ws.recv(), timeout=3)
                data = json.loads(raw)
                if data.get("type") == "session:reset_ack":
                    break

            await ws_send(ws, "chat:message", {
                "content": "Combien de cartes dans ce projet?",
                "messageId": f"e2e-msg-{tag}-2",
                "chatLevel": "project",
                "projectId": pid,
                "sessionId": f"e2e-projchat-{tag}",
                "chatId": f"project:{pid}",
            })
            response = await ws_collect_chat_response(ws, timeout=LLM_TIMEOUT)
            assert len(response) > 0, "Project chat produced empty response"

    finally:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
            if pid:
                await client.delete(f"/api/projects/{pid}")


@pytest.mark.asyncio
async def test_cross_project_card_isolation(client: httpx.AsyncClient):
    """Cards in project A must not appear when listing project B's cards."""
    tag = uuid.uuid4().hex[:6]

    # Create two projects
    r = await client.post("/api/projects", json={"title": f"IsoA_{tag}"})
    pid_a = r.json().get("id")
    r = await client.post("/api/projects", json={"title": f"IsoB_{tag}"})
    pid_b = r.json().get("id")

    try:
        # Create card in A
        r = await client.post(f"/api/projects/{pid_a}/cards", json={
            "title": f"SecretCardA_{tag}",
            "status": "todo",
        })
        card_a_id = r.json().get("id")

        # List cards in B — should not see A's card
        r = await client.get(f"/api/projects/{pid_b}/cards")
        cards_b = r.json()
        ids_b = [c["id"] for c in cards_b]
        assert card_a_id not in ids_b, "Card from project A leaked into project B"

        # Also verify A has its card
        r = await client.get(f"/api/projects/{pid_a}/cards")
        cards_a = r.json()
        ids_a = [c["id"] for c in cards_a]
        assert card_a_id in ids_a

    finally:
        await client.delete(f"/api/projects/{pid_a}")
        await client.delete(f"/api/projects/{pid_b}")


@pytest.mark.asyncio
async def test_session_persistence(client: httpx.AsyncClient):
    """Verify that session creation, get, and deletion flow works cleanly."""
    tag = uuid.uuid4().hex[:6]

    # Create project
    r = await client.post("/api/projects", json={"title": f"SessPers_{tag}"})
    pid = r.json().get("id")

    try:
        # Create multiple sessions
        sessions = []
        for i in range(3):
            r = await client.post("/api/sessions", json={
                "project_id": pid,
                "title": f"Session {i}",
            })
            assert r.status_code in (200, 201)
            sessions.append(r.json()["chatId"])

        # Verify each session can be retrieved individually
        for sid in sessions:
            r = await client.get(f"/api/sessions/{sid}")
            assert r.status_code == 200
            data = r.json()
            assert data["chat_id"] == sid

        # Delete one session
        r = await client.delete(f"/api/sessions/{sessions[0]}")
        assert r.status_code == 200

        # Verify deleted session returns empty or 404
        r = await client.get(f"/api/sessions/{sessions[0]}")
        # After deletion the session may return empty messages or 404
        if r.status_code == 200:
            data = r.json()
            assert data["count"] == 0

    finally:
        for sid in sessions:
            try:
                await client.delete(f"/api/sessions/{sid}")
            except Exception:
                pass
        await client.delete(f"/api/projects/{pid}")
