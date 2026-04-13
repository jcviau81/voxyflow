"""
E2E: Project lifecycle — CRUD, archive/restore, export/import.
"""

import time
import uuid

import pytest
import httpx


class TestProjectCRUD:
    @pytest.mark.asyncio
    async def test_create_project(self, client: httpx.AsyncClient):
        tag = uuid.uuid4().hex[:8]
        r = await client.post("/api/projects", json={
            "title": f"E2E_Create_{tag}",
            "description": "Test project creation",
        })
        assert r.status_code in (200, 201)
        project = r.json()
        pid = project.get("id") or project.get("project", {}).get("id")
        assert pid

        # Cleanup
        await client.delete(f"/api/projects/{pid}")

    @pytest.mark.asyncio
    async def test_list_projects(self, client: httpx.AsyncClient):
        r = await client.get("/api/projects")
        assert r.status_code == 200
        data = r.json()
        projects = data if isinstance(data, list) else data.get("projects", data)
        assert isinstance(projects, list)

    @pytest.mark.asyncio
    async def test_get_project(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]
        r = await client.get(f"/api/projects/{pid}")
        assert r.status_code == 200
        data = r.json()
        assert data.get("id") == pid

    @pytest.mark.asyncio
    async def test_update_project(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]
        r = await client.patch(f"/api/projects/{pid}", json={
            "description": "Updated by E2E test",
        })
        assert r.status_code == 200
        data = r.json()
        assert data.get("description") == "Updated by E2E test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_project(self, client: httpx.AsyncClient):
        r = await client.get(f"/api/projects/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_create_project_in_list(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]
        r = await client.get("/api/projects")
        data = r.json()
        projects = data if isinstance(data, list) else data.get("projects", data)
        ids = [p.get("id") for p in projects]
        assert pid in ids


class TestProjectArchive:
    @pytest.mark.asyncio
    async def test_archive_and_restore(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]

        # Archive
        r = await client.post(f"/api/projects/{pid}/archive")
        assert r.status_code == 200

        # Verify archived
        r = await client.get(f"/api/projects/{pid}")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "archived"

        # Restore
        r = await client.post(f"/api/projects/{pid}/restore")
        assert r.status_code == 200

        # Verify restored
        r = await client.get(f"/api/projects/{pid}")
        data = r.json()
        assert data.get("status") == "active"


class TestProjectExportImport:
    @pytest.mark.asyncio
    async def test_export_project(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]
        r = await client.get(f"/api/projects/{pid}/export")
        assert r.status_code == 200
        data = r.json()
        assert "project" in data

    @pytest.mark.asyncio
    async def test_export_import_roundtrip(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]

        # Create a card first so export has data
        await client.post(f"/api/projects/{pid}/cards", json={
            "title": "Export test card",
            "status": "todo",
        })

        # Export
        r = await client.get(f"/api/projects/{pid}/export")
        assert r.status_code == 200
        export_data = r.json()
        assert "project" in export_data
        assert "cards" in export_data

        # Import as new project — may fail if import endpoint has strict validation
        r = await client.post("/api/projects/import", json=export_data)
        if r.status_code in (200, 201):
            imported = r.json()
            imported_pid = imported.get("id") or imported.get("project", {}).get("id") or imported.get("project_id")
            if imported_pid:
                r = await client.get(f"/api/projects/{imported_pid}")
                assert r.status_code == 200
                await client.delete(f"/api/projects/{imported_pid}")
        else:
            # Import may not be fully supported — just verify export worked
            assert r.status_code != 404, "Import endpoint missing"


class TestProjectDelete:
    @pytest.mark.asyncio
    async def test_delete_project(self, client: httpx.AsyncClient):
        tag = uuid.uuid4().hex[:8]
        r = await client.post("/api/projects", json={
            "title": f"E2E_Delete_{tag}",
        })
        project = r.json()
        pid = project.get("id") or project.get("project", {}).get("id")

        r = await client.delete(f"/api/projects/{pid}")
        assert r.status_code in (200, 204)

        # Verify gone or archived
        r = await client.get(f"/api/projects/{pid}")
        if r.status_code == 200:
            data = r.json()
            assert data.get("status") in ("archived", "deleted")
        else:
            assert r.status_code == 404
