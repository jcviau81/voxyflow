"""
E2E: Wiki page lifecycle — CRUD within projects.
"""

import pytest
import httpx


class TestWikiCRUD:
    @pytest.mark.asyncio
    async def test_create_wiki_page(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]
        r = await client.post(f"/api/projects/{pid}/wiki", json={
            "title": "E2E Wiki Page",
            "content": "# Hello\nThis is an E2E test wiki page.",
        })
        assert r.status_code in (200, 201)
        page = r.json()
        page_id = page.get("id") or page.get("page", {}).get("id")
        assert page_id

    @pytest.mark.asyncio
    async def test_list_wiki_pages(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]

        # Create a page first
        await client.post(f"/api/projects/{pid}/wiki", json={
            "title": "List test page",
            "content": "Content",
        })

        r = await client.get(f"/api/projects/{pid}/wiki")
        assert r.status_code == 200
        pages = r.json()
        assert isinstance(pages, list)
        assert len(pages) >= 1

    @pytest.mark.asyncio
    async def test_get_wiki_page(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]

        # Create
        r = await client.post(f"/api/projects/{pid}/wiki", json={
            "title": "Get test page",
            "content": "Get this content",
        })
        page = r.json()
        page_id = page.get("id") or page.get("page", {}).get("id")

        # Get
        r = await client.get(f"/api/projects/{pid}/wiki/{page_id}")
        assert r.status_code == 200
        data = r.json()
        assert data.get("title") == "Get test page"

    @pytest.mark.asyncio
    async def test_update_wiki_page(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]

        # Create
        r = await client.post(f"/api/projects/{pid}/wiki", json={
            "title": "Update test page",
            "content": "Original content",
        })
        page = r.json()
        page_id = page.get("id") or page.get("page", {}).get("id")

        # Update
        r = await client.put(f"/api/projects/{pid}/wiki/{page_id}", json={
            "title": "Updated title",
            "content": "Updated content",
        })
        assert r.status_code == 200
        data = r.json()
        assert data.get("content") == "Updated content"

    @pytest.mark.asyncio
    async def test_delete_wiki_page(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]

        # Create
        r = await client.post(f"/api/projects/{pid}/wiki", json={
            "title": "Delete test page",
            "content": "To be deleted",
        })
        page = r.json()
        page_id = page.get("id") or page.get("page", {}).get("id")

        # Delete
        r = await client.delete(f"/api/projects/{pid}/wiki/{page_id}")
        assert r.status_code in (200, 204)

        # Verify gone
        r = await client.get(f"/api/projects/{pid}/wiki/{page_id}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_wiki_isolation_between_projects(self, client: httpx.AsyncClient):
        """Wiki pages in project A should not appear in project B."""
        import uuid
        tag = uuid.uuid4().hex[:8]

        # Create two projects
        r = await client.post("/api/projects", json={"title": f"WikiIso_A_{tag}"})
        proj_a = r.json()
        pid_a = proj_a.get("id")

        r = await client.post("/api/projects", json={"title": f"WikiIso_B_{tag}"})
        proj_b = r.json()
        pid_b = proj_b.get("id")

        try:
            # Create wiki page in project A
            await client.post(f"/api/projects/{pid_a}/wiki", json={
                "title": "Secret A page",
                "content": "Project A only",
            })

            # List wiki pages in project B — should be empty
            r = await client.get(f"/api/projects/{pid_b}/wiki")
            assert r.status_code == 200
            pages_b = r.json()
            titles_b = [p.get("title") for p in pages_b]
            assert "Secret A page" not in titles_b
        finally:
            await client.delete(f"/api/projects/{pid_a}")
            await client.delete(f"/api/projects/{pid_b}")
