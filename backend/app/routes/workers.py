"""Worker session routes — query active/recent worker sessions.

GET /api/workers/sessions          → list active + recent sessions (last 1 hour)
GET /api/workers/sessions/{task_id} → single task status
"""

from typing import Optional

from fastapi import APIRouter, HTTPException

from app.services.worker_session_store import get_worker_session_store

router = APIRouter(prefix="/api/workers", tags=["workers"])


@router.get("/sessions")
async def list_worker_sessions(
    session_id: Optional[str] = None,
    project_id: Optional[str] = None,
):
    """Return active + recent worker sessions (last 1 hour).

    Filter by project_id (stable across reconnects) or session_id.
    If both provided, project_id takes precedence.
    """
    store = get_worker_session_store()
    if project_id:
        sessions = store.get_sessions_by_project(project_id=project_id)
    else:
        sessions = store.get_sessions(session_id=session_id)
    return {"sessions": sessions}


@router.get("/sessions/{task_id}")
async def get_worker_session(task_id: str):
    """Get a single worker session by task_id."""
    store = get_worker_session_store()
    session = store.get_session(task_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Worker session not found.")
    return session
