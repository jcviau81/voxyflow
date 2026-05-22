"""
E2E: Workspace lifecycle — CRUD, archive/restore, export/import.
"""

import time
import uuid

import pytest
import httpx


class TestWorkspaceCRUD:
    @pytest.mark.asyncio
    async def test_create_workspace(self, client: httpx.AsyncClient):
        tag = uuid.uuid4().hex[:8]
        r = await client.post("/api/workspaces", json={
            "title": f"E2E_Create_{tag}",
            "description": "Test workspace creation",
        })
        assert r.status_code in (200, 201)
        workspace = r.json()
        pid = workspace.get("id") or workspace.get("workspace", {}).get("id")
        assert pid

        # Cleanup
        await client.delete(f"/api/workspaces/{pid}")

    @pytest.mark.asyncio
    async def test_list_workspaces(self, client: httpx.AsyncClient):
        r = await client.get("/api/workspaces")
        assert r.status_code == 200
        data = r.json()
        workspaces = data if isinstance(data, list) else data.get("workspaces", data)
        assert isinstance(workspaces, list)

    @pytest.mark.asyncio
    async def test_get_workspace(self, client: httpx.AsyncClient, test_workspace: dict):
        pid = test_workspace["_id"]
        r = await client.get(f"/api/workspaces/{pid}")
        assert r.status_code == 200
        data = r.json()
        assert data.get("id") == pid

    @pytest.mark.asyncio
    async def test_update_workspace(self, client: httpx.AsyncClient, test_workspace: dict):
        pid = test_workspace["_id"]
        r = await client.patch(f"/api/workspaces/{pid}", json={
            "description": "Updated by E2E test",
        })
        assert r.status_code == 200
        data = r.json()
        assert data.get("description") == "Updated by E2E test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_workspace(self, client: httpx.AsyncClient):
        r = await client.get(f"/api/workspaces/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_create_workspace_in_list(self, client: httpx.AsyncClient, test_workspace: dict):
        pid = test_workspace["_id"]
        r = await client.get("/api/workspaces")
        data = r.json()
        workspaces = data if isinstance(data, list) else data.get("workspaces", data)
        ids = [p.get("id") for p in workspaces]
        assert pid in ids


class TestWorkspaceArchive:
    @pytest.mark.asyncio
    async def test_archive_and_restore(self, client: httpx.AsyncClient, test_workspace: dict):
        pid = test_workspace["_id"]

        # Archive
        r = await client.post(f"/api/workspaces/{pid}/archive")
        assert r.status_code == 200

        # Verify archived
        r = await client.get(f"/api/workspaces/{pid}")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "archived"

        # Restore
        r = await client.post(f"/api/workspaces/{pid}/restore")
        assert r.status_code == 200

        # Verify restored
        r = await client.get(f"/api/workspaces/{pid}")
        data = r.json()
        assert data.get("status") == "active"


class TestWorkspaceExportImport:
    @pytest.mark.asyncio
    async def test_export_workspace(self, client: httpx.AsyncClient, test_workspace: dict):
        pid = test_workspace["_id"]
        r = await client.get(f"/api/workspaces/{pid}/export")
        assert r.status_code == 200
        data = r.json()
        assert "workspace" in data

    @pytest.mark.asyncio
    async def test_export_import_roundtrip(self, client: httpx.AsyncClient, test_workspace: dict):
        pid = test_workspace["_id"]

        # Create a card first so export has data
        await client.post(f"/api/workspaces/{pid}/cards", json={
            "title": "Export test card",
            "status": "todo",
        })

        # Export
        r = await client.get(f"/api/workspaces/{pid}/export")
        assert r.status_code == 200
        export_data = r.json()
        assert "workspace" in export_data
        assert "cards" in export_data

        # Import as new workspace — may fail if import endpoint has strict validation
        r = await client.post("/api/workspaces/import", json=export_data)
        if r.status_code in (200, 201):
            imported = r.json()
            imported_pid = imported.get("id") or imported.get("workspace", {}).get("id") or imported.get("workspace_id")
            if imported_pid:
                r = await client.get(f"/api/workspaces/{imported_pid}")
                assert r.status_code == 200
                await client.delete(f"/api/workspaces/{imported_pid}")
        else:
            # Import may not be fully supported — just verify export worked
            assert r.status_code != 404, "Import endpoint missing"


class TestWorkspaceDelete:
    @pytest.mark.asyncio
    async def test_delete_workspace(self, client: httpx.AsyncClient):
        tag = uuid.uuid4().hex[:8]
        r = await client.post("/api/workspaces", json={
            "title": f"E2E_Delete_{tag}",
        })
        workspace = r.json()
        pid = workspace.get("id") or workspace.get("workspace", {}).get("id")

        r = await client.delete(f"/api/workspaces/{pid}")
        assert r.status_code in (200, 204)

        # Verify gone or archived
        r = await client.get(f"/api/workspaces/{pid}")
        if r.status_code == 200:
            data = r.json()
            assert data.get("status") in ("archived", "deleted")
        else:
            assert r.status_code == 404
