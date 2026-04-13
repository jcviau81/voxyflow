"""Worker Tasks routes — query the Worker Ledger for task history and results.

GET  /api/worker-tasks              → list recent worker tasks (filterable)
GET  /api/worker-tasks/{task_id}    → get full details of a specific task
GET  /api/worker-tasks/{task_id}/peek   → live peek (running) or DB fallback (finished)
POST /api/worker-tasks/{task_id}/cancel → cancel a running worker task
POST /api/worker-tasks/{task_id}/steer  → inject a steering message into a running worker task
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, WorkerTask

router = APIRouter(prefix="/api/worker-tasks", tags=["worker-tasks"])


@router.get("")
async def list_worker_tasks(
    session_id: Optional[str] = None,
    project_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
):
    """List recent worker tasks from the Worker Ledger.

    Filters: session_id, project_id, status (pending/running/done/failed/cancelled).
    """
    query = select(WorkerTask).order_by(desc(WorkerTask.created_at))

    if session_id:
        query = query.where(WorkerTask.session_id == session_id)
    if project_id:
        query = query.where(WorkerTask.project_id == project_id)
    if status:
        query = query.where(WorkerTask.status == status)

    query = query.limit(min(limit, 100))

    result = await db.execute(query)
    tasks = result.scalars().all()

    return {
        "tasks": [
            {
                "id": t.id,
                "session_id": t.session_id,
                "project_id": t.project_id,
                "card_id": t.card_id,
                "action": t.action,
                "description": t.description,
                "model": t.model,
                "status": t.status,
                "result_summary": t.result_summary,
                "error": t.error,
                "started_at": t.started_at.isoformat() if t.started_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in tasks
        ],
        "count": len(tasks),
    }


@router.get("/{task_id}/peek")
async def peek_worker_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Live peek into a running worker task, with DB fallback for finished tasks."""
    from app.main import _orchestrator

    live = _orchestrator.peek_worker_task(task_id)
    if live is not None:
        return {**live, "source": "live"}

    # Fallback: task may have completed — check DB
    result = await db.execute(
        select(WorkerTask).where(WorkerTask.id == task_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(status_code=404, detail="Worker task not found.")

    return {
        "task_id": task.id,
        "action": task.action,
        "model": task.model,
        "status": task.status,
        "result_summary": task.result_summary,
        "error": task.error,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "source": "db",
    }


class SteerRequest(BaseModel):
    message: str


@router.post("/{task_id}/steer")
async def steer_worker_task(task_id: str, body: SteerRequest):
    """Inject a steering message into a running worker task."""
    from app.main import _orchestrator

    if not body.message:
        raise HTTPException(status_code=400, detail="message is required")

    steered = await _orchestrator.steer_worker_task("", task_id, body.message)
    return {"queued": steered, "task_id": task_id}


@router.post("/{task_id}/cancel")
async def cancel_worker_task(task_id: str):
    """Cancel a running worker task across all active pools."""
    from app.main import _orchestrator

    cancelled = await _orchestrator.cancel_worker_task_global(task_id)
    return {"cancelled": cancelled, "task_id": task_id}


@router.get("/{task_id}")
async def get_worker_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get full details of a specific worker task."""
    result = await db.execute(
        select(WorkerTask).where(WorkerTask.id == task_id)
    )
    task = result.scalar_one_or_none()

    if task is None:
        raise HTTPException(status_code=404, detail="Worker task not found.")

    return {
        "id": task.id,
        "session_id": task.session_id,
        "project_id": task.project_id,
        "card_id": task.card_id,
        "action": task.action,
        "description": task.description,
        "model": task.model,
        "status": task.status,
        "result_summary": task.result_summary,
        "error": task.error,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }
