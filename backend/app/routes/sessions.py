"""Session persistence API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Message, SYSTEM_MAIN_WORKSPACE_ID
from app.services.session_store import session_store
from app.services.ws_broadcast import ws_broadcast

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


class CreateSessionRequest(BaseModel):
    """Request body for creating a new session."""
    workspace_id: str = SYSTEM_MAIN_WORKSPACE_ID
    title: str | None = None


@router.get("")
async def list_sessions(
    prefix: str = Query("", description="Filter by chat_id prefix"),
    active: bool = Query(False, description="If true, return active sessions (last 24h) with lastMessage info"),
    max_age_hours: int = Query(720, description="Max age in hours for active sessions (default 720 = 30 days)"),
):
    """List all persisted sessions.

    Use ?active=true to get sessions from the last N hours with lastMessage info
    (for cross-device sync). Returns [{ chatId, title, lastMessage, messageCount, updatedAt }].
    """
    if active:
        return session_store.list_active_sessions(max_age_hours=max_age_hours)
    return session_store.list_sessions(prefix)


@router.post("")
async def create_session(body: CreateSessionRequest):
    """Create a new session with a stable chat_id.

    Returns { chatId, title } for the new session.
    The chat_id is deterministic: workspace:{workspaceId}:session-N where N is incremental.
    """
    chat_id = session_store.create_session(body.workspace_id, body.title)
    title = body.title or chat_id.split(":")[-1].replace("-", " ").title()
    return {"chatId": chat_id, "title": title}


# ---------------------------------------------------------------------------
# Chat History Search
# ---------------------------------------------------------------------------
# NOTE: declared BEFORE the ``{chat_id:path}`` catch-all below, otherwise the
# path converter greedily captures "search/messages" as a chat_id and this
# endpoint becomes unreachable (mirrors delete_message ordered before
# delete_session).

def _make_snippet(content: str, query: str, radius: int = 50) -> str:
    """Return ~100 chars around the first case-insensitive match."""
    idx = content.lower().find(query.lower())
    if idx == -1:
        return content[:100]
    start = max(0, idx - radius)
    end = min(len(content), idx + len(query) + radius)
    snippet = content[start:end]
    if start > 0:
        snippet = "…" + snippet
    if end < len(content):
        snippet = snippet + "…"
    return snippet


@router.get("/search/messages")
async def search_messages(
    q: str = Query(..., min_length=1, description="Search query"),
    workspace_id: str | None = Query(None, description="Filter by workspace_id (matches chat_id prefix 'workspace:{id}')"),
    limit: int = Query(20, ge=1, le=100, description="Max results"),
    db: AsyncSession = Depends(get_db),
):
    """
    Keyword search across persisted messages (case-insensitive substring match).

    Returns a list of matching messages with a snippet (~100 chars) around the match.
    Optionally filters to a specific workspace by matching chat_id prefix 'workspace:{workspace_id}'.
    """
    stmt = (
        select(Message)
        .where(Message.content.ilike(f"%{q}%"))
        .order_by(Message.created_at.desc())
        .limit(limit)
    )

    if workspace_id:
        stmt = stmt.where(Message.chat_id.like(f"workspace:{workspace_id}%"))

    result = await db.execute(stmt)
    messages = result.scalars().all()

    return [
        {
            "message_id": msg.id,
            "chat_id": msg.chat_id,
            "role": msg.role,
            "content": msg.content,
            "snippet": _make_snippet(msg.content, q),
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
        }
        for msg in messages
    ]


@router.get("/{chat_id:path}")
async def get_session(chat_id: str, limit: int = Query(50, ge=1, le=500)):
    """Get messages for a specific session."""
    # Backfill stable per-message ids on demand so the manual delete endpoint
    # can target individual messages. No-op once every message has an id.
    session_store.backfill_message_ids(chat_id)
    messages = session_store.get_recent_messages(chat_id, limit)
    # Filter out internal tool_results messages (system context, not for UI)
    visible = [m for m in messages if m.get("type") != "tool_results"]
    return {"chat_id": chat_id, "messages": visible, "count": len(visible)}


@router.delete("/{chat_id:path}/messages/{message_id}")
async def delete_message(chat_id: str, message_id: str):
    """Permanently delete a single message from a chat (file-backed store).

    Chat history lives in JSON files under ``~/.voxyflow/sessions/`` —
    not the SQLite ``messages`` table — so the delete operates on the
    file via ``session_store.delete_message``. Broadcasts
    ``message.deleted`` so other tabs/devices viewing the same chat
    remove the bubble live.

    Declared BEFORE ``delete_session`` because that route uses
    ``{chat_id:path}`` which would greedily swallow ``/messages/...``.
    """
    removed = session_store.delete_message(chat_id, message_id)
    if not removed:
        raise HTTPException(status_code=404, detail="message not found in chat")

    await ws_broadcast.emit_to_chat(
        chat_id,
        "message.deleted",
        {"message_id": message_id, "chat_id": chat_id},
    )

    return {"deleted": message_id, "chat_id": chat_id}


@router.delete("/{chat_id:path}")
async def delete_session(chat_id: str):
    """Permanently delete a session from disk."""
    session_store.delete_session(chat_id)
    return {"deleted": chat_id}
