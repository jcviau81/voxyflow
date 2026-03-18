"""Project endpoints."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db, Project, Card, new_uuid, utcnow
from app.models.project import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectWithCards
from app.services.agent_personas import AgentType, get_persona

router = APIRouter(prefix="/projects", tags=["projects"])


# ---------------------------------------------------------------------------
# Export/Import schemas
# ---------------------------------------------------------------------------

class CardExport(BaseModel):
    title: str
    description: str
    status: str
    priority: int
    agent_type: str | None = None
    tags: list[str] = []


class ProjectExport(BaseModel):
    title: str
    description: str
    status: str
    context: str
    github_repo: str | None = None
    github_url: str | None = None
    github_branch: str | None = None
    github_language: str | None = None
    local_path: str | None = None


class ExportPayload(BaseModel):
    version: str
    exported_at: str
    project: ProjectExport
    cards: list[CardExport]


class ImportResponse(BaseModel):
    project_id: str
    project_title: str
    cards_imported: int


@router.post("", response_model=ProjectResponse, status_code=201)
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)):
    project = Project(
        id=new_uuid(),
        title=body.title,
        description=body.description or "",
        context=body.context or "",
        github_repo=body.github_repo,
        github_url=body.github_url,
        github_branch=body.github_branch,
        github_language=body.github_language,
        local_path=body.local_path,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("", response_model=list[ProjectResponse])
async def list_projects(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Project).order_by(Project.updated_at.desc())
    if status:
        stmt = stmt.where(Project.status == status)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{project_id}", response_model=ProjectWithCards)
async def get_project(project_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Project)
        .options(selectinload(Project.cards))
        .where(Project.id == project_id)
    )
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)
    project.updated_at = utcnow()

    await db.commit()
    await db.refresh(project)
    return project


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@router.get("/{project_id}/export")
async def export_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Export a project and all its cards as a JSON payload."""
    stmt = (
        select(Project)
        .options(selectinload(Project.cards))
        .where(Project.id == project_id)
    )
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")

    cards_data = [
        {
            "title": card.title,
            "description": card.description or "",
            "status": card.status,
            "priority": card.priority,
            "agent_type": card.agent_type,
            "tags": [],
        }
        for card in project.cards
    ]

    payload = {
        "version": "1.0",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "project": {
            "title": project.title,
            "description": project.description or "",
            "status": project.status,
            "context": project.context or "",
            "github_repo": project.github_repo,
            "github_url": project.github_url,
            "github_branch": project.github_branch,
            "github_language": project.github_language,
            "local_path": project.local_path,
        },
        "cards": cards_data,
    }

    return JSONResponse(content=payload)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@router.post("/import", response_model=ImportResponse, status_code=201)
async def import_project(body: ExportPayload, db: AsyncSession = Depends(get_db)):
    """Import a project from an exported JSON payload. Creates a new project."""
    title = body.project.title

    # Check if a project with the same title exists → append "(imported)"
    stmt = select(Project).where(Project.title == title)
    existing = await db.execute(stmt)
    if existing.scalar_one_or_none():
        title = f"{title} (imported)"

    project = Project(
        id=new_uuid(),
        title=title,
        description=body.project.description,
        status=body.project.status,
        context=body.project.context,
        github_repo=body.project.github_repo,
        github_url=body.project.github_url,
        github_branch=body.project.github_branch,
        github_language=body.project.github_language,
        local_path=body.project.local_path,
    )
    db.add(project)
    await db.flush()  # Get project.id before creating cards

    for card_data in body.cards:
        # Resolve agent display name if agent_type is provided
        agent_assigned = None
        if card_data.agent_type:
            try:
                persona = get_persona(AgentType(card_data.agent_type))
                agent_assigned = f"{persona.emoji} {persona.name}"
            except (ValueError, KeyError):
                pass

        card = Card(
            id=new_uuid(),
            project_id=project.id,
            title=card_data.title,
            description=card_data.description,
            status=card_data.status,
            priority=card_data.priority,
            agent_type=card_data.agent_type,
            agent_assigned=agent_assigned,
        )
        db.add(card)

    await db.commit()
    await db.refresh(project)

    return ImportResponse(
        project_id=project.id,
        project_title=project.title,
        cards_imported=len(body.cards),
    )
