"""
E2E: Worker lifecycle — sessions, snapshot, worker task ledger, peek, cancel.
"""

import uuid

import pytest
import httpx


class TestWorkerSessions:
    @pytest.mark.asyncio
    async def test_list_worker_sessions(self, client: httpx.AsyncClient):
        r = await client.get("/api/workers/sessions")
        assert r.status_code == 200
        data = r.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)

    @pytest.mark.asyncio
    async def test_list_worker_sessions_by_project(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]
        r = await client.get("/api/workers/sessions", params={"project_id": pid})
        assert r.status_code == 200
        data = r.json()
        assert "sessions" in data

    @pytest.mark.asyncio
    async def test_get_nonexistent_worker_session(self, client: httpx.AsyncClient):
        r = await client.get(f"/api/workers/sessions/{uuid.uuid4()}")
        assert r.status_code == 404


class TestWorkerSnapshot:
    @pytest.mark.asyncio
    async def test_snapshot(self, client: httpx.AsyncClient):
        r = await client.get("/api/workers/snapshot")
        assert r.status_code == 200
        data = r.json()
        assert "workers" in data
        assert "cliSessions" in data
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_snapshot_filtered_by_project(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]
        r = await client.get("/api/workers/snapshot", params={"project_id": pid})
        assert r.status_code == 200
        data = r.json()
        # All returned workers should match the project_id (or be empty)
        for w in data["workers"]:
            if w.get("projectId"):
                assert w["projectId"] == pid


class TestWorkerTaskLedger:
    @pytest.mark.asyncio
    async def test_list_worker_tasks(self, client: httpx.AsyncClient):
        r = await client.get("/api/worker-tasks")
        assert r.status_code == 200
        data = r.json()
        assert "tasks" in data
        assert "count" in data
        assert isinstance(data["tasks"], list)

    @pytest.mark.asyncio
    async def test_list_worker_tasks_by_status(self, client: httpx.AsyncClient):
        r = await client.get("/api/worker-tasks", params={"status": "done"})
        assert r.status_code == 200
        data = r.json()
        for task in data["tasks"]:
            assert task["status"] == "done"

    @pytest.mark.asyncio
    async def test_list_worker_tasks_by_project(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]
        r = await client.get("/api/worker-tasks", params={"project_id": pid})
        assert r.status_code == 200
        data = r.json()
        for task in data["tasks"]:
            assert task["project_id"] == pid

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, client: httpx.AsyncClient):
        r = await client.get(f"/api/worker-tasks/{uuid.uuid4()}")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_peek_nonexistent_task(self, client: httpx.AsyncClient):
        r = await client.get(f"/api/worker-tasks/{uuid.uuid4()}/peek")
        assert r.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, client: httpx.AsyncClient):
        r = await client.post(f"/api/worker-tasks/{uuid.uuid4()}/cancel")
        assert r.status_code == 200
        data = r.json()
        assert data["cancelled"] is False


class TestWorkerTaskSchema:
    @pytest.mark.asyncio
    async def test_task_fields(self, client: httpx.AsyncClient):
        """Verify worker task responses have expected fields."""
        r = await client.get("/api/worker-tasks", params={"limit": 5})
        data = r.json()
        for task in data["tasks"]:
            assert "id" in task
            assert "action" in task
            assert "status" in task
            assert "created_at" in task
            assert task["status"] in ("pending", "running", "done", "failed", "cancelled", "timed_out")
