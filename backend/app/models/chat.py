"""Chat & Message schemas."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

class MessageCreate(BaseModel):
    role: str = Field(default="user", pattern="^(user|assistant|system)$")
    content: str
    audio_url: Optional[str] = None


class MessageResponse(BaseModel):
    id: str
    chat_id: str
    role: str
    content: str
    audio_url: Optional[str] = None
    model_used: Optional[str] = None
    tokens_used: Optional[int] = None
    latency_ms: Optional[float] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class ChatCreate(BaseModel):
    title: Optional[str] = "New Chat"
    project_id: Optional[str] = None


class ChatResponse(BaseModel):
    id: str
    title: str
    project_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse] = []

    model_config = {"from_attributes": True}


class ChatListItem(BaseModel):
    """Lightweight chat summary for list endpoints."""
    id: str
    title: str
    project_id: Optional[str] = None
    created_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}
