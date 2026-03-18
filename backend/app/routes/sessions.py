"""Session persistence API endpoints."""

from fastapi import APIRouter, Query

from app.services.session_store import session_store

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("")
async def list_sessions(prefix: str = Query("", description="Filter by chat_id prefix")):
    """List all persisted sessions."""
    return session_store.list_sessions(prefix)


@router.get("/{chat_id:path}")
async def get_session(chat_id: str, limit: int = Query(50, ge=1, le=500)):
    """Get messages for a specific session."""
    messages = session_store.get_recent_messages(chat_id, limit)
    return {"chat_id": chat_id, "messages": messages, "count": len(messages)}


@router.delete("/{chat_id:path}")
async def clear_session(chat_id: str):
    """Clear (archive) a session's messages."""
    session_store.clear_session(chat_id)
    return {"status": "cleared", "chat_id": chat_id}
