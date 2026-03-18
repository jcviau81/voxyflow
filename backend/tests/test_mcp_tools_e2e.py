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
async def test_note_add():
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BASE}/api/notes", json={"content": "Test note E2E", "color": "blue"})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"
        data = r.json()
        assert data.get("success") == True or "id" in data or "note" in data


@pytest.mark.asyncio
async def test_session_search_messages():
    async with httpx.AsyncClient() as c:
        r = await c.get(f"{BASE}/api/sessions/search/messages", params={"q": "test"})
        assert r.status_code == 200, f"Got {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_project_full_lifecycle():
    """
    Test all project/card/wiki/sprint endpoints in one test to maintain state.
    Cleans up at the end.
    """
    async with httpx.AsyncClient(timeout=30.0) as c:
        # ── CREATE PROJECT ──────────────────────────────────────────────────
        r = await c.post(f"{BASE}/api/projects", json={
            "title": "MCP_Test_Project_E2E",
            "description": "Automated E2E test — safe to delete"
        })
        assert r.status_code in (200, 201), f"Create project: {r.status_code} {r.text}"
        project = r.json()
        pid = project.get("id") or project.get("project", {}).get("id")
        assert pid, f"No project id in response: {project}"

        # ── LIST PROJECTS ───────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/projects")
        assert r.status_code == 200, f"List projects: {r.status_code}"
        projects = r.json()
        # Might be a list or {"projects": [...]}
        project_list = projects if isinstance(projects, list) else projects.get("projects", [])
        assert any(p.get("id") == pid for p in project_list), f"Project {pid} not in list"

        # ── GET PROJECT ─────────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/projects/{pid}")
        assert r.status_code == 200, f"Get project: {r.status_code} {r.text}"

        # ── EXPORT PROJECT ──────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/projects/{pid}/export")
        assert r.status_code == 200, f"Export project: {r.status_code} {r.text}"
        export_data = r.json()
        assert "project" in export_data, f"No 'project' key in export: {export_data.keys()}"

        # ── CREATE CARD ─────────────────────────────────────────────────────
        r = await c.post(f"{BASE}/api/projects/{pid}/cards", json={
            "title": "Test Card E2E",
            "status": "todo"
        })
        assert r.status_code in (200, 201), f"Create card: {r.status_code} {r.text}"
        card_data = r.json()
        card_id = card_data.get("id") or card_data.get("card", {}).get("id")
        assert card_id, f"No card id in response: {card_data}"

        # ── LIST CARDS ──────────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/projects/{pid}/cards")
        assert r.status_code == 200, f"List cards: {r.status_code}"

        # ── UPDATE CARD ─────────────────────────────────────────────────────
        r = await c.patch(f"{BASE}/api/cards/{card_id}", json={"status": "in_progress"})
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
        r = await c.post(f"{BASE}/api/projects/{pid}/wiki", json={
            "title": "Test Wiki Page",
            "content": "# Hello from E2E test"
        })
        assert r.status_code in (200, 201), f"Wiki create: {r.status_code} {r.text}"
        wiki_data = r.json()
        wiki_id = wiki_data.get("id") or wiki_data.get("page", {}).get("id")
        assert wiki_id, f"No wiki id in response: {wiki_data}"

        # ── WIKI LIST ───────────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/projects/{pid}/wiki")
        assert r.status_code == 200, f"Wiki list: {r.status_code}"

        # ── WIKI GET ────────────────────────────────────────────────────────
        r = await c.get(f"{BASE}/api/projects/{pid}/wiki/{wiki_id}")
        assert r.status_code == 200, f"Wiki get: {r.status_code} {r.text}"

        # ── SPRINT CREATE ───────────────────────────────────────────────────
        r = await c.post(f"{BASE}/api/projects/{pid}/sprints", json={
            "name": "Sprint E2E Test",
            "start_date": "2026-03-18",
            "end_date": "2026-04-01"
        })
        assert r.status_code in (200, 201), f"Sprint create: {r.status_code} {r.text}"

        # ── CLEANUP ─────────────────────────────────────────────────────────
        # Delete duplicate card if we got an id
        if dup_id:
            await c.delete(f"{BASE}/api/cards/{dup_id}")

        # Delete project (may not exist — that's ok)
        r = await c.delete(f"{BASE}/api/projects/{pid}")
        # Don't assert — endpoint may not exist

        print(f"\n✅ All project/card/wiki/sprint endpoints passed! (project_id={pid})")
