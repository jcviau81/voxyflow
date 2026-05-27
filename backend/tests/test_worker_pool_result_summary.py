import os
import sys
from uuid import uuid4

import pytest
from sqlalchemy import select

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.database as db_module
from app.database import WorkerTask
from app.services.orchestration.worker_pool import DeepWorkerPool, PREVIEW_CHARS, _preview
from app.services.worker_session_store import get_worker_session_store


@pytest.mark.asyncio
async def test_result_summary_stores_full_content_in_db():
    task_id = f"task-{uuid4()}"
    long_result = "result-" + ("x" * 2400)

    async with db_module.async_session() as db:
        db.add(WorkerTask(
            id=task_id,
            session_id="sess-1",
            workspace_id="ws-1",
            action="feature",
            description="store result summary",
            model="gpt-5",
            status="running",
        ))
        await db.commit()

    await DeepWorkerPool._ledger_update(task_id, "done", result_summary=long_result)

    async with db_module.async_session() as db:
        row = (await db.execute(select(WorkerTask).where(WorkerTask.id == task_id))).scalar_one()

    assert row.result_summary == long_result
    assert len(row.result_summary) > PREVIEW_CHARS
    assert "truncated" not in row.result_summary


def test_worker_session_store_preview_still_truncates():
    task_id = f"task-{uuid4()}"
    store = get_worker_session_store()
    long_result = "result-" + ("y" * 2400)
    preview = _preview(long_result, PREVIEW_CHARS)

    store.register(task_id, session_id="sess-1", intent="feature", summary="demo")
    store.update_status(task_id, "completed", preview)

    session = store.get_session(task_id)
    assert session is not None
    assert session["result_summary"] == preview
    assert "[... truncated" in session["result_summary"]
    assert len(session["result_summary"]) < len(long_result)

    store._sessions.pop(task_id, None)
    store._cleanup_file(task_id)
