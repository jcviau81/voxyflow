"""CLI session visibility — active `claude -p` subprocess listing and control."""

import time

from fastapi import APIRouter, HTTPException

from app.services.cli_session_registry import get_cli_session_registry

router = APIRouter(prefix="/api/cli-sessions", tags=["cli-sessions"])


@router.get("/active")
async def list_active_sessions():
    """List all active CLI subprocess sessions."""
    registry = get_cli_session_registry()
    now = time.time()
    return {
        "sessions": [
            {
                "id": s.id,
                "pid": s.pid,
                "sessionId": s.session_id,
                "chatId": s.chat_id,
                "projectId": s.project_id,
                "model": s.model,
                "type": s.session_type,
                "startedAt": s.started_at,
                "durationSeconds": round(now - s.started_at, 1),
            }
            for s in registry.list_active()
        ],
        "count": registry.count(),
    }


@router.post("/{session_id}/close")
async def close_session(session_id: str):
    """Kill an active CLI subprocess by registry session ID."""
    registry = get_cli_session_registry()
    killed = await registry.kill(session_id)
    if not killed:
        raise HTTPException(404, "Session not found or already completed")
    return {"killed": session_id}
