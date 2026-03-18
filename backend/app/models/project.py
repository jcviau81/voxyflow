"""Project schemas."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


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
    cards: list = []  # Will be list[CardResponse] — avoiding circular import
