"""Project schemas."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    context: Optional[str] = ""


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|archived)$")
    context: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    context: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectWithCards(ProjectResponse):
    """Project response that includes its cards."""
    cards: list = []  # Will be list[CardResponse] — avoiding circular import
