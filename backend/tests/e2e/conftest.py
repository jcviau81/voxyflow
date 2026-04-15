"""
E2E test fixtures — shared helpers for all Voxyflow end-to-end tests.

These tests hit the LIVE backend at localhost:8000.
Run with:  pytest backend/tests/e2e/ -v --tb=short
"""

import asyncio
import json
import time
import uuid
from typing import AsyncGenerator

import httpx
import pytest

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws"

# Timeout for LLM-dependent operations (chat, enrich, etc.)
LLM_TIMEOUT = 90
# Timeout for quick REST ops
REST_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Reusable HTTP client
# ---------------------------------------------------------------------------

@pytest.fixture
async def client() -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=REST_TIMEOUT) as c:
        yield c


# ---------------------------------------------------------------------------
# Backend availability guard
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True, scope="session")
def _require_backend():
    """Skip the entire E2E suite if the backend is not running."""
    import httpx as _httpx
    try:
        r = _httpx.get(f"{BASE_URL}/api/health", timeout=5)
        if r.status_code != 200:
            pytest.skip("Backend returned non-200 health check")
    except Exception:
        pytest.skip("Backend not reachable at localhost:8000")


# ---------------------------------------------------------------------------
# Test project lifecycle (create → yield → cleanup)
# ---------------------------------------------------------------------------

@pytest.fixture
async def test_project(client: httpx.AsyncClient):
    """Create a throwaway project and clean it up after the test."""
    tag = uuid.uuid4().hex[:8]
    r = await client.post("/api/projects", json={
        "title": f"E2E_Test_{tag}",
        "description": "Automated E2E test — safe to delete",
    })
    assert r.status_code in (200, 201), f"Failed to create project: {r.status_code} {r.text}"
    project = r.json()
    pid = project.get("id") or project.get("project", {}).get("id")
    assert pid, f"No project id: {project}"
    project["_id"] = pid

    yield project

    # Cleanup — best effort
    try:
        await client.delete(f"/api/projects/{pid}")
    except Exception:
        pass


@pytest.fixture
async def test_card(client: httpx.AsyncClient, test_project: dict):
    """Create a throwaway card inside the test project."""
    pid = test_project["_id"]
    tag = uuid.uuid4().hex[:8]
    r = await client.post(f"/api/projects/{pid}/cards", json={
        "title": f"E2E Card {tag}",
        "description": "Test card for E2E",
        "status": "todo",
        "priority": 2,
    })
    assert r.status_code in (200, 201), f"Failed to create card: {r.status_code} {r.text}"
    card = r.json()
    card_id = card.get("id") or card.get("card", {}).get("id")
    assert card_id, f"No card id: {card}"
    card["_id"] = card_id
    card["_project_id"] = pid
    return card


# ---------------------------------------------------------------------------
# WebSocket helper
# ---------------------------------------------------------------------------

@pytest.fixture
async def ws():
    """Provide a connected WebSocket client (via websockets library)."""
    import websockets

    async with websockets.connect(WS_URL, open_timeout=10) as conn:
        yield conn


async def ws_send(ws, msg_type: str, payload: dict) -> None:
    """Send a typed message over the WebSocket."""
    await ws.send(json.dumps({
        "type": msg_type,
        "payload": payload,
        "id": str(uuid.uuid4()),
        "timestamp": int(time.time() * 1000),
    }))


async def ws_recv_until(ws, target_type: str, timeout: float = LLM_TIMEOUT) -> dict:
    """Receive messages until we get one matching target_type (or timeout)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2)
            data = json.loads(raw)
            if data.get("type") == target_type:
                return data
            if data.get("type") == "pong":
                continue
        except asyncio.TimeoutError:
            # Keep alive
            await ws_send(ws, "ping", {})
    raise TimeoutError(f"Did not receive {target_type!r} within {timeout}s")


async def ws_collect_chat_response(ws, timeout: float = LLM_TIMEOUT) -> str:
    """Collect streaming chat:response chunks until done=true. Returns full text."""
    content = ""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=3)
            data = json.loads(raw)
            msg_type = data.get("type")

            if msg_type == "pong":
                continue

            if msg_type == "chat:response":
                p = data.get("payload", {})
                chunk = p.get("content", "")
                done = p.get("done", False)
                content += chunk
                if done:
                    return content

            if msg_type == "error":
                raise RuntimeError(f"Chat error: {data}")

            if msg_type in ("task:completed",):
                return data.get("payload", {}).get("result", "")

        except asyncio.TimeoutError:
            await ws_send(ws, "ping", {})
    raise TimeoutError(f"Chat response not completed within {timeout}s")


# ---------------------------------------------------------------------------
# Enhanced WS helpers
# ---------------------------------------------------------------------------

async def ws_collect_events(
    ws, target_types: set[str],
    stop_on: str | None = None,
    timeout: float = LLM_TIMEOUT,
) -> list[dict]:
    """Collect all WS events matching target_types until stop_on or timeout."""
    events = []
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=3)
            data = json.loads(raw)
            msg_type = data.get("type")
            if msg_type == "pong":
                continue
            if msg_type in target_types:
                events.append(data)
            if stop_on and msg_type == stop_on:
                return events
        except asyncio.TimeoutError:
            await ws_send(ws, "ping", {})
    return events


# ---------------------------------------------------------------------------
# Card assertion helpers
# ---------------------------------------------------------------------------

async def assert_card_status(client, card_id: str, expected: str):
    """Assert a card has a specific status via REST."""
    r = await client.get(f"/api/cards/{card_id}")
    assert r.status_code == 200, f"Card {card_id} not found"
    actual = r.json()["status"]
    assert actual == expected, f"Card {card_id}: expected status={expected}, got {actual}"


async def assert_card_history_contains(
    client, card_id: str,
    field_changed: str, new_value: str, changed_by: str,
) -> dict:
    """Assert card history contains a specific entry. Returns matched entry."""
    r = await client.get(f"/api/cards/{card_id}/history")
    assert r.status_code == 200
    entries = r.json()
    match = [
        e for e in entries
        if e.get("field_changed") == field_changed
        and e.get("new_value") == new_value
        and e.get("changed_by") == changed_by
    ]
    assert len(match) >= 1, (
        f"Expected history ({field_changed}→{new_value} by {changed_by}) "
        f"not found in {len(entries)} entries: {entries}"
    )
    return match[0]


async def count_project_cards(client, project_id: str) -> int:
    """Return count of cards in a project."""
    r = await client.get(f"/api/projects/{project_id}/cards")
    assert r.status_code == 200
    data = r.json()
    cards = data.get("cards", data) if isinstance(data, dict) else data
    return len(cards) if isinstance(cards, list) else 0


def chat_payload(content: str, **kwargs) -> dict:
    """Build a chat:message payload with defaults."""
    return {
        "content": content,
        "messageId": f"e2e-{uuid.uuid4().hex[:8]}",
        "chatLevel": kwargs.get("chatLevel", "general"),
        "projectId": kwargs.get("projectId"),
        "cardId": kwargs.get("cardId"),
        "sessionId": kwargs.get("sessionId", f"e2e-{uuid.uuid4().hex[:6]}"),
        "chatId": kwargs.get("chatId"),
    }


# ---------------------------------------------------------------------------
# Additional fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def test_card_done(client: httpx.AsyncClient, test_project: dict):
    """Create a card with status='done' in the test project."""
    pid = test_project["_id"]
    tag = uuid.uuid4().hex[:8]
    r = await client.post(f"/api/projects/{pid}/cards", json={
        "title": f"Done Card {tag}",
        "description": "Card already done",
        "status": "done",
    })
    assert r.status_code in (200, 201)
    card = r.json()
    card["_id"] = card.get("id")
    card["_project_id"] = pid
    return card
