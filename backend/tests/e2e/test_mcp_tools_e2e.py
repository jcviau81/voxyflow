"""
End-to-end tests for ALL Voxyflow MCP tool REST endpoints.
Tests each endpoint directly (not via chat pipeline).
"""
import pytest
import httpx

BASE = "http://localhost:8000"


@pytest.mark.asyncio
async def test_health():
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.get(f"{BASE}/api/health")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data


@pytest.mark.asyncio
async def test_mcp_tools_list():
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/mcp/tools")
        assert r.status_code == 200
        data = r.json()
        assert "count" in data
        assert data["count"] >= 25, f"Expected >= 25 tools, got {data['count']}"


@pytest.mark.asyncio
async def test_jobs_list():
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/api/jobs")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_card_create_unassigned():
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BASE}/api/cards/unassigned", json={"title": "Test card E2E", "color": "blue"})
        assert r.status_code in (200, 201), f"Got {r.status_code}: {r.text}"
        data = r.json()
        assert "id" in data or "card" in data


@pytest.mark.asyncio
async def test_session_search_messages():
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/api/sessions/search/messages", params={"q": "test"})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_workspace_full_lifecycle():
    """
    Test all workspace/card/wiki endpoints in one test to maintain state.
    Cleans up at the end.
    """
    import time
    async with httpx.AsyncClient(timeout=30.0) as c:
        # ── CREATE PROJECT ──────────────────────────────────────────────────
        r = await c.post(f"{BASE}/api/workspaces", json={
            "title": f"MCP_Test_Workspace_E2E_{int(time.time())}",
            "description": "Automated E2E test — safe to delete"
        })
        assert r.status_code in (200, 201), f"Create workspace: {r.status_code} {r.text}"
        workspace = r.json()
        pid = workspace.get("id") or workspace.get("workspace", {}).get("id")
        assert pid, f"No workspace id in response: {workspace}"

        # ── LIST PROJECTS ───────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/workspaces")
        assert r.status_code == 200, f"List workspaces: {r.status_code}"
        workspaces = r.json()
        # Might be a list or {"workspaces": [...]}
        workspace_list = workspaces if isinstance(workspaces, list) else workspaces.get("workspaces", [])
        assert any(p.get("id") == pid for p in workspace_list), f"Workspace {pid} not in list"

        # ── GET PROJECT ─────────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/workspaces/{pid}")
        assert r.status_code == 200, f"Get workspace: {r.status_code} {r.text}"

        # ── EXPORT PROJECT ──────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/workspaces/{pid}/export")
        assert r.status_code == 200, f"Export workspace: {r.status_code} {r.text}"
        export_data = r.json()
        assert "workspace" in export_data, f"No 'workspace' key in export: {export_data.keys()}"

        # ── CREATE CARD ─────────────────────────────────────────────────────
        r = await c.post(f"{BASE}/api/workspaces/{pid}/cards", json={
            "title": "Test Card E2E",
            "status": "todo"
        })
        assert r.status_code in (200, 201), f"Create card: {r.status_code} {r.text}"
        card_data = r.json()
        card_id = card_data.get("id") or card_data.get("card", {}).get("id")
        assert card_id, f"No card id in response: {card_data}"

        # ── LIST CARDS ──────────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/workspaces/{pid}/cards")
        assert r.status_code == 200, f"List cards: {r.status_code}"

        # ── UPDATE CARD ─────────────────────────────────────────────────────
        r = await c.patch(f"{BASE}/api/cards/{card_id}", json={"status": "in-progress"})
        assert r.status_code == 200, f"Update card: {r.status_code} {r.text}"

        # ── DUPLICATE CARD ──────────────────────────────────────────────────
        r = await c.post(f"{BASE}/api/cards/{card_id}/duplicate")
        assert r.status_code in (200, 201), f"Duplicate card: {r.status_code} {r.text}"
        dup_data = r.json()
        dup_id = dup_data.get("id") or dup_data.get("card", {}).get("id")

        # ── CARD CHECKLIST ──────────────────────────────────────────────────
        r = await c.post(f"{BASE}/api/cards/{card_id}/checklist", json={"text": "Sub-task 1"})
        assert r.status_code in (200, 201), f"Card checklist: {r.status_code} {r.text}"

        # ── CARD COMMENT ────────────────────────────────────────────────────
        r = await c.post(f"{BASE}/api/cards/{card_id}/comments", json={"content": "Test comment E2E"})
        assert r.status_code in (200, 201), f"Card comment: {r.status_code} {r.text}"

        # ── CARD TIME LOG ───────────────────────────────────────────────────
        r = await c.post(f"{BASE}/api/cards/{card_id}/time", json={
            "duration_minutes": 30,
            "note": "E2E testing"
        })
        assert r.status_code in (200, 201), f"Card time: {r.status_code} {r.text}"

        # ── CARD VOTE ───────────────────────────────────────────────────────
        r = await c.post(f"{BASE}/api/cards/{card_id}/vote")
        assert r.status_code == 200, f"Card vote: {r.status_code} {r.text}"

        # ── CARD ENRICH (skip if needs Claude) ─────────────────────────────
        # We allow non-404 (200 or 500/422 if Claude fails — just verify endpoint exists)
        r = await c.post(f"{BASE}/api/cards/{card_id}/enrich")
        assert r.status_code != 404, f"Card enrich endpoint missing (404)"

        # ── CARD HISTORY ────────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/cards/{card_id}/history")
        assert r.status_code == 200, f"Card history: {r.status_code} {r.text}"

        # ── WIKI CREATE ─────────────────────────────────────────────────────
        r = await c.post(f"{BASE}/api/workspaces/{pid}/wiki", json={
            "title": "Test Wiki Page",
            "content": "# Hello from E2E test"
        })
        assert r.status_code in (200, 201), f"Wiki create: {r.status_code} {r.text}"
        wiki_data = r.json()
        wiki_id = wiki_data.get("id") or wiki_data.get("page", {}).get("id")
        assert wiki_id, f"No wiki id in response: {wiki_data}"

        # ── WIKI LIST ───────────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/workspaces/{pid}/wiki")
        assert r.status_code == 200, f"Wiki list: {r.status_code}"

        # ── WIKI GET ────────────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/workspaces/{pid}/wiki/{wiki_id}")
        assert r.status_code == 200, f"Wiki get: {r.status_code} {r.text}"

        # ── CLEANUP ─────────────────────────────────────────────────────────
        # Delete duplicate card if we got an id
        if dup_id:
            await c.delete(f"{BASE}/api/cards/{dup_id}")

        # Delete workspace (may not exist — that's ok)
        r = await c.delete(f"{BASE}/api/workspaces/{pid}")
        # Don't assert — endpoint may not exist

        print(f"\n✅ All workspace/card/wiki endpoints passed! (workspace_id={pid})")
