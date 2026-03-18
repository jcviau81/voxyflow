"""Card/Task schemas — with agent assignment support."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class CardCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    status: str = Field(default="idea", pattern="^(idea|todo|in_progress|done|archived)$")
    priority: int = Field(default=0, ge=0, le=4)
    source_message_id: Optional[str] = None
    auto_generated: bool = False
    dependency_ids: list[str] = []
    # Agent assignment
    agent_type: Optional[str] = Field(
        None,
        pattern="^(ember|researcher|coder|designer|architect|writer|qa)$",
        description="Specialized agent type assigned to this card",
    )
    agent_context: Optional[str] = Field(
        None,
        description="Relevant docs/requirements context for the assigned agent",
    )


class CardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(idea|todo|in_progress|done|archived)$")
    priority: Optional[int] = Field(None, ge=0, le=4)
    position: Optional[int] = None
    agent_assigned: Optional[str] = None
    agent_type: Optional[str] = Field(
        None,
        pattern="^(ember|researcher|coder|designer|architect|writer|qa)$",
    )
    agent_context: Optional[str] = None
    assignee: Optional[str] = None
    watchers: Optional[str] = None


class TimeEntryCreate(BaseModel):
    duration_minutes: int = Field(..., ge=1, description="Time logged in minutes")
    note: Optional[str] = None


class TimeEntryResponse(BaseModel):
    id: str
    card_id: str
    duration_minutes: int
    note: Optional[str] = None
    logged_at: datetime

    model_config = {"from_attributes": True}


class CardResponse(BaseModel):
    id: str
    project_id: str
    title: str
    description: str
    status: str
    priority: int
    position: int
    source_message_id: Optional[str] = None
    auto_generated: bool
    agent_assigned: Optional[str] = None
    agent_type: Optional[str] = None
    agent_context: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    dependency_ids: list[str] = []
    total_minutes: int = 0
    checklist_progress: Optional["ChecklistProgress"] = None
    assignee: Optional[str] = None
    watchers: str = ""
    votes: int = 0

    model_config = {"from_attributes": True}


class CardSuggestion(BaseModel):
    """Pushed to client via WebSocket when analyzer detects a potential card."""
    title: str
    description: str
    priority: int = 0
    source_message_id: str
    suggested_dependencies: list[str] = []
    confidence: float = Field(ge=0.0, le=1.0)
    # Agent routing
    agent_type: str = "ember"
    agent_name: str = "🔥 Ember"


class AgentAssignment(BaseModel):
    """Request to assign/reassign a card to a specific agent."""
    agent_type: str = Field(
        ...,
        pattern="^(ember|researcher|coder|designer|architect|writer|qa)$",
    )
    agent_context: Optional[str] = None


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1)
    author: str = "User"


class CommentResponse(BaseModel):
    id: str
    card_id: str
    author: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChecklistItemCreate(BaseModel):
    text: str = Field(..., min_length=1)


class ChecklistItemUpdate(BaseModel):
    text: Optional[str] = None
    completed: Optional[bool] = None


class ChecklistItemResponse(BaseModel):
    id: str
    card_id: str
    text: str
    completed: bool
    position: int
    created_at: datetime

    model_config = {"from_attributes": True}


class ChecklistProgress(BaseModel):
    total: int
    completed: int


class AttachmentResponse(BaseModel):
    id: str
    card_id: str
    filename: str
    file_size: int
    mime_type: str
    created_at: datetime

    model_config = {"from_attributes": True}
