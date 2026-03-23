"""Project schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass


class ProjectCreate(BaseModel):
    title: str
    description: Optional[str] = ""
    context: Optional[str] = ""
    github_repo: Optional[str] = None
    github_url: Optional[str] = None
    github_branch: Optional[str] = None
    github_language: Optional[str] = None
    local_path: Optional[str] = None


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = Field(None, pattern="^(active|archived)$")
    context: Optional[str] = None
    github_repo: Optional[str] = None
    github_url: Optional[str] = None
    github_branch: Optional[str] = None
    github_language: Optional[str] = None
    local_path: Optional[str] = None


class ProjectResponse(BaseModel):
    id: str
    title: str
    description: str
    status: str
    context: str
    is_system: bool = False
    deletable: bool = True
    github_repo: Optional[str] = None
    github_url: Optional[str] = None
    github_branch: Optional[str] = None
    github_language: Optional[str] = None
    local_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectWithCards(ProjectResponse):
    """Project response that includes its cards."""
    cards: list[CardResponseMinimal] = []


class CardResponseMinimal(BaseModel):
    """Minimal card representation for embedding inside ProjectWithCards."""
    id: str
    project_id: Optional[str] = None
    title: str
    description: str
    status: str
    priority: int
    position: int
    agent_assigned: Optional[str] = None
    agent_type: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# Rebuild the model now that CardResponseMinimal is defined
ProjectWithCards.model_rebuild()
