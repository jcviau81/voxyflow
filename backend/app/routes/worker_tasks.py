"""Worker Tasks routes — query the Worker Ledger for task history and results.

GET /api/worker-tasks              → list recent worker tasks (filterable)
GET /api/worker-tasks/{task_id}    → get full details of a specific task
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends
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
        raise HTTPException(status_code=404, detail="Worker task not found")

    return {
        "id": task.id,
        "session_id": task.session_id,
        "project_id": task.project_id,
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
