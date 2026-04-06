"""Worker session routes — query active/recent worker sessions.

GET /api/workers/sessions          → list active + recent sessions (last 1 hour)
GET /api/workers/sessions/{task_id} → single task status
GET /api/workers/snapshot           → consolidated snapshot (in-memory only, no SQLite)
"""

import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.services.worker_session_store import WorkerSessionStore, get_worker_session_store
from app.services.cli_session_registry import CliSessionRegistry, get_cli_session_registry

router = APIRouter(prefix="/api/workers", tags=["workers"])


@router.get("/sessions")
async def list_worker_sessions(
    session_id: Optional[str] = None,
    project_id: Optional[str] = None,
    store: WorkerSessionStore = Depends(get_worker_session_store),
):
    """Return active + recent worker sessions (last 1 hour).

    Filter by project_id (stable across reconnects) or session_id.
    If both provided, project_id takes precedence.
    """
    if project_id:
        sessions = store.get_sessions_by_project(project_id=project_id)
    else:
        sessions = store.get_sessions(session_id=session_id)
    return {"sessions": sessions}


@router.get("/sessions/{task_id}")
async def get_worker_session(
    task_id: str,
    store: WorkerSessionStore = Depends(get_worker_session_store),
):
    """Get a single worker session by task_id."""
    session = store.get_session(task_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Worker session not found.")
    return session


@router.get("/snapshot")
async def worker_snapshot(
    project_id: Optional[str] = None,
    store: WorkerSessionStore = Depends(get_worker_session_store),
    registry: CliSessionRegistry = Depends(get_cli_session_registry),
):
    """Consolidated worker state snapshot — reads only from in-memory stores.

    Returns all worker sessions + CLI sessions in one call.
    Used for initial page load and visibility-resume re-sync.
    """
    # Worker sessions from WorkerSessionStore
    if project_id:
        raw_sessions = store.get_sessions_by_project(project_id)
    else:
        raw_sessions = store.get_sessions()

    workers = []
    for s in raw_sessions:
        workers.append({
            "taskId": s["task_id"],
            "projectId": s.get("project_id"),
            "cardId": s.get("card_id"),
            "chatId": None,  # WorkerSessionStore doesn't track chatId
            "action": s.get("intent", "unknown"),
            "description": s.get("summary", ""),
            "model": s.get("model", "sonnet"),
            "status": s.get("status", "running"),
            "startedAt": int((s.get("start_time") or 0) * 1000),
            "completedAt": int(s["end_time"] * 1000) if s.get("end_time") else None,
            "toolCount": 0,
            "lastTool": None,
            "resultSummary": s.get("result_summary"),
        })

    # CLI sessions from CliSessionRegistry
    cli_sessions = []
    for cs in registry.list_active():
        # Filter by project_id if provided
        if project_id and cs.project_id != project_id:
            continue
        cli_sessions.append({
            "id": cs.id,
            "pid": cs.pid,
            "chatId": cs.chat_id,
            "projectId": cs.project_id,
            "model": cs.model,
            "type": cs.session_type,
            "startedAt": cs.started_at,
            "taskId": cs.task_id,
        })

    return {
        "workers": workers,
        "cliSessions": cli_sessions,
        "timestamp": int(time.time() * 1000),
    }
