"""Card/Task schemas — with agent assignment support.

``CardResponse`` is generated from the ORM ``Card`` model via
``_generated.CardBase``; this file layers on:

* request-side validators (``CardCreate`` / ``CardUpdate``) that the ORM
  can't express (pattern, range);
* synthesized response fields that don't map to a column:
  ``dependency_ids`` (from the ``dependencies`` relationship),
  ``total_minutes`` (sum of ``time_entries``),
  ``checklist_progress`` (derived from ``checklist_items``);
* the ``files`` override — stored as JSON text in the DB, emitted as
  ``list[str]`` on the wire.

See ``_generated.py`` for the generator rationale.
"""

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field

from app.models._generated import CardBase

RecurrenceType = Optional[Literal["daily", "weekly", "monthly"]]


class CardCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    status: str = Field(default="card", pattern="^(card|todo|in-progress|done|archived)$")
    priority: int = Field(default=0, ge=0, le=4)
    color: Optional[str] = Field(None, pattern="^(yellow|blue|green|pink|purple|orange)$")
    source_message_id: Optional[str] = None
    auto_generated: bool = False
    dependency_ids: list[str] = []
    # Agent assignment
    agent_type: Optional[str] = Field(
        None,
        pattern="^(general|researcher|coder|designer|architect|writer|qa)$",
        description="Specialized agent type assigned to this card",
    )
    agent_context: Optional[str] = Field(
        None,
        description="Relevant docs/requirements context for the assigned agent",
    )
    recurring: bool = False
    recurrence: RecurrenceType = None
    recurrence_next: Optional[datetime] = None


class CardUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(card|todo|in-progress|done|archived)$")
    priority: Optional[int] = Field(None, ge=0, le=4)
    position: Optional[int] = None
    color: Optional[str] = Field(None, pattern="^(yellow|blue|green|pink|purple|orange)$")
    agent_assigned: Optional[str] = None
    agent_type: Optional[str] = Field(
        None,
        pattern="^(general|researcher|coder|designer|architect|writer|qa)$",
    )
    agent_context: Optional[str] = None
    assignee: Optional[str] = None
    watchers: Optional[str] = None
    preferred_model: Optional[str] = None  # worker class UUID, or null for Auto
    recurring: Optional[bool] = None
    recurrence: RecurrenceType = None
    recurrence_next: Optional[datetime] = None


class BulkReorderRequest(BaseModel):
    """Bulk reorder cards: each ID's position is set to its index in the list."""
    ordered_ids: list[str]


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


class ChecklistProgress(BaseModel):
    total: int
    completed: int


class CardResponse(CardBase):
    """Wire representation of a Card.

    Inherits all column-backed fields from the generated ``CardBase``.
    Adds three synthesized fields that are computed by
    ``_card_to_response()`` in ``routes/cards.py``:

    * ``dependency_ids`` — ``[d.id for d in card.dependencies]``
      (requires ``dependencies`` to be eager-loaded)
    * ``total_minutes`` — sum of ``TimeEntry.duration_minutes``
    * ``checklist_progress`` — (total, completed) from ``checklist_items``

    And overrides the ``files`` column (stored as JSON text) to emit
    a ``list[str]`` on the wire.
    """
    dependency_ids: list[str] = []
    total_minutes: int = 0
    checklist_progress: Optional[ChecklistProgress] = None
    files: list[str] = []


class CardSuggestion(BaseModel):
    """Card suggestion model for potential card creation."""
    title: str
    description: str
    priority: int = 0
    source_message_id: str
    suggested_dependencies: list[str] = []
    confidence: float = Field(ge=0.0, le=1.0)
    # Agent routing
    agent_type: str = "general"
    agent_name: str = "⚡ General"


class AgentAssignment(BaseModel):
    """Request to assign/reassign a card to a specific agent."""
    agent_type: str = Field(
        ...,
        pattern="^(general|researcher|coder|designer|architect|writer|qa)$",
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


class AttachmentResponse(BaseModel):
    id: str
    card_id: str
    filename: str
    file_size: int
    mime_type: str
    created_at: datetime

    model_config = {"from_attributes": True}
