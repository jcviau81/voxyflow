"""Project schemas.

``ProjectResponse`` is generated from the ORM ``Project`` model via
``_generated.ProjectBase``. ``ProjectWithCards`` adds a relationship-backed
``cards`` list using a hand-authored ``CardResponseMinimal`` (intentionally
a trimmed surface — not the full CardResponse).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.models._generated import ProjectBase


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
    is_favorite: Optional[bool] = None
    inherit_main_context: Optional[bool] = None


class ProjectResponse(ProjectBase):
    """Wire representation of a Project — pure column-backed."""
    pass


class CardResponseMinimal(BaseModel):
    """Minimal card surface embedded inside ``ProjectWithCards``.

    Intentionally a trimmed view — not the full ``CardResponse``. Declared
    by hand because the wire shape is narrower than the column set.
    """
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


class ProjectWithCards(ProjectResponse):
    """Project response that includes its cards."""
    cards: list[CardResponseMinimal] = []


# Rebuild the model now that CardResponseMinimal is defined
ProjectWithCards.model_rebuild()
