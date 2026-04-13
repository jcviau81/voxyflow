"""
E2E: Jobs CRUD — create, list, update, delete, trigger.
"""

import uuid

import pytest
import httpx


class TestJobCRUD:
    @pytest.mark.asyncio
    async def test_list_jobs(self, client: httpx.AsyncClient):
        r = await client.get("/api/jobs")
        assert r.status_code == 200
        data = r.json()
        assert "jobs" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_create_job(self, client: httpx.AsyncClient):
        r = await client.post("/api/jobs", json={
            "name": f"E2E Test Job {uuid.uuid4().hex[:6]}",
            "type": "custom",
            "schedule": "every_30min",
            "enabled": False,
            "payload": {"test": True},
        })
        assert r.status_code == 201
        job = r.json()
        assert "id" in job
        assert job["enabled"] is False

        # Cleanup
        await client.delete(f"/api/jobs/{job['id']}")

    @pytest.mark.asyncio
    async def test_update_job(self, client: httpx.AsyncClient):
        # Create
        r = await client.post("/api/jobs", json={
            "name": f"Update Test {uuid.uuid4().hex[:6]}",
            "type": "custom",
            "schedule": "every_1h",
        })
        job = r.json()
        job_id = job["id"]

        # Update
        r = await client.patch(f"/api/jobs/{job_id}", json={
            "name": "Updated Job Name",
            "enabled": False,
        })
        assert r.status_code == 200
        updated = r.json()
        assert updated["name"] == "Updated Job Name"
        assert updated["enabled"] is False

        # Cleanup
        await client.delete(f"/api/jobs/{job_id}")

    @pytest.mark.asyncio
    async def test_delete_job(self, client: httpx.AsyncClient):
        # Create
        r = await client.post("/api/jobs", json={
            "name": f"Delete Test {uuid.uuid4().hex[:6]}",
            "type": "custom",
            "schedule": "every_1h",
        })
        job = r.json()
        job_id = job["id"]

        # Delete
        r = await client.delete(f"/api/jobs/{job_id}")
        assert r.status_code == 204

        # Verify gone
        r = await client.get("/api/jobs")
        jobs = r.json()["jobs"]
        assert not any(j["id"] == job_id for j in jobs)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_job(self, client: httpx.AsyncClient):
        r = await client.delete(f"/api/jobs/{uuid.uuid4()}")
        assert r.status_code == 404


class TestJobTypes:
    @pytest.mark.asyncio
    async def test_create_reminder_job(self, client: httpx.AsyncClient):
        r = await client.post("/api/jobs", json={
            "name": f"E2E Reminder {uuid.uuid4().hex[:6]}",
            "type": "reminder",
            "schedule": "every_1h",
            "payload": {"message": "Test reminder"},
        })
        assert r.status_code == 201
        job = r.json()
        assert job["type"] == "reminder"

        await client.delete(f"/api/jobs/{job['id']}")

    @pytest.mark.asyncio
    async def test_create_rag_index_job(self, client: httpx.AsyncClient):
        r = await client.post("/api/jobs", json={
            "name": f"E2E RAG {uuid.uuid4().hex[:6]}",
            "type": "rag_index",
            "schedule": "every_30min",
            "payload": {},
        })
        assert r.status_code == 201
        job = r.json()
        assert job["type"] == "rag_index"

        await client.delete(f"/api/jobs/{job['id']}")


class TestJobTrigger:
    @pytest.mark.asyncio
    async def test_trigger_custom_job(self, client: httpx.AsyncClient):
        # Create a custom job
        r = await client.post("/api/jobs", json={
            "name": f"E2E Trigger {uuid.uuid4().hex[:6]}",
            "type": "custom",
            "schedule": "every_1h",
        })
        job = r.json()
        job_id = job["id"]

        # Trigger immediately
        r = await client.post(f"/api/jobs/{job_id}/run")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "triggered"
        assert data["job_id"] == job_id

        await client.delete(f"/api/jobs/{job_id}")

    @pytest.mark.asyncio
    async def test_trigger_nonexistent_job(self, client: httpx.AsyncClient):
        r = await client.post(f"/api/jobs/{uuid.uuid4()}/run")
        assert r.status_code == 404


class TestJobInList:
    @pytest.mark.asyncio
    async def test_created_job_appears_in_list(self, client: httpx.AsyncClient):
        r = await client.post("/api/jobs", json={
            "name": f"E2E Listed {uuid.uuid4().hex[:6]}",
            "type": "custom",
            "schedule": "every_1h",
        })
        job = r.json()
        job_id = job["id"]

        r = await client.get("/api/jobs")
        jobs = r.json()["jobs"]
        ids = [j["id"] for j in jobs]
        assert job_id in ids

        await client.delete(f"/api/jobs/{job_id}")
