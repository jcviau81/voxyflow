"""Chat & Message schemas.

``ChatResponse`` / ``MessageResponse`` are generated from the ORM
``Chat`` / ``Message`` models via ``_generated.py``; subclasses add
synthesized fields (``messages``, ``message_count``) that aren't
columns.
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models._generated import ChatBase, MessageBase


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

class MessageCreate(BaseModel):
    role: str = Field(default="user", pattern="^(user|assistant|system)$")
    content: str
    audio_url: Optional[str] = None


class MessageResponse(MessageBase):
    """Wire representation of a Message — pure column-backed."""
    pass


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatCreate(BaseModel):
    title: Optional[str] = "New Chat"
    project_id: Optional[str] = None


class ChatResponse(ChatBase):
    """Chat + its messages.

    ``messages`` is eager-loaded from the ``messages`` relationship.
    """
    messages: list[MessageResponse] = []


class ChatListItem(ChatBase):
    """Lightweight chat summary.

    Adds a synthesized ``message_count`` (computed by the route handler
    from a COUNT query — not a column).
    """
    message_count: int = 0
