"""Project endpoints."""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db, Project, Card, new_uuid, utcnow
from app.models.project import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectWithCards
from app.services.agent_personas import AgentType, get_persona

# ---------------------------------------------------------------------------
# Standup helpers
# ---------------------------------------------------------------------------

VOXYFLOW_DIR = Path(os.environ.get("VOXYFLOW_DATA_DIR", os.path.expanduser("~/.voxyflow")))
JOBS_FILE = VOXYFLOW_DIR / "jobs.json"


def _load_jobs() -> list[dict]:
    if not JOBS_FILE.exists():
        return []
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_jobs(jobs: list[dict]) -> None:
    VOXYFLOW_DIR.mkdir(parents=True, exist_ok=True)
    with open(JOBS_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2)

router = APIRouter(prefix="/projects", tags=["projects"])

# ---------------------------------------------------------------------------
# Built-in project templates
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, dict[str, Any]] = {
    "software": {
        "id": "software",
        "name": "Software Project",
        "emoji": "💻",
        "description": "Plan, build, test and ship a software product.",
        "color": "#54a0ff",
        "cards": [
            {"title": "Define requirements", "status": "todo", "priority": 1, "agent_type": "researcher"},
            {"title": "Design architecture", "status": "todo", "priority": 2, "agent_type": "architect"},
            {"title": "Implement features", "status": "todo", "priority": 3, "agent_type": "coder"},
            {"title": "Write tests", "status": "todo", "priority": 4, "agent_type": "qa"},
            {"title": "Deploy", "status": "todo", "priority": 5, "agent_type": "ember"},
        ],
    },
    "research": {
        "id": "research",
        "name": "Research Project",
        "emoji": "🔬",
        "description": "Structured process from question to published findings.",
        "color": "#96ceb4",
        "cards": [
            {"title": "Define research question", "status": "todo", "priority": 1, "agent_type": "researcher"},
            {"title": "Literature review", "status": "todo", "priority": 2, "agent_type": "researcher"},
            {"title": "Data collection", "status": "todo", "priority": 3, "agent_type": "researcher"},
            {"title": "Analysis", "status": "todo", "priority": 4, "agent_type": "researcher"},
            {"title": "Write report", "status": "todo", "priority": 5, "agent_type": "writer"},
        ],
    },
    "content": {
        "id": "content",
        "name": "Content Creation",
        "emoji": "✍️",
        "description": "From brainstorm to published content, end to end.",
        "color": "#ff9ff3",
        "cards": [
            {"title": "Brainstorm topics", "status": "idea", "priority": 1, "agent_type": "ember"},
            {"title": "Outline", "status": "todo", "priority": 2, "agent_type": "writer"},
            {"title": "Draft", "status": "todo", "priority": 3, "agent_type": "writer"},
            {"title": "Review & edit", "status": "todo", "priority": 4, "agent_type": "qa"},
            {"title": "Publish", "status": "todo", "priority": 5, "agent_type": "ember"},
        ],
    },
    "bugfix": {
        "id": "bugfix",
        "name": "Bug Fix Sprint",
        "emoji": "🐛",
        "description": "Systematic process to squash a bug and ship the fix.",
        "color": "#ff6b6b",
        "cards": [
            {"title": "Reproduce bug", "status": "todo", "priority": 1, "agent_type": "qa"},
            {"title": "Root cause analysis", "status": "todo", "priority": 2, "agent_type": "architect"},
            {"title": "Implement fix", "status": "todo", "priority": 3, "agent_type": "coder"},
            {"title": "Write regression test", "status": "todo", "priority": 4, "agent_type": "qa"},
            {"title": "Deploy fix", "status": "todo", "priority": 5, "agent_type": "ember"},
        ],
    },
    "launch": {
        "id": "launch",
        "name": "Product Launch",
        "emoji": "🚀",
        "description": "Take a product idea from zero to market.",
        "color": "#feca57",
        "cards": [
            {"title": "Market research", "status": "todo", "priority": 1, "agent_type": "researcher"},
            {"title": "MVP definition", "status": "todo", "priority": 2, "agent_type": "architect"},
            {"title": "Build MVP", "status": "todo", "priority": 3, "agent_type": "coder"},
            {"title": "Beta testing", "status": "todo", "priority": 4, "agent_type": "qa"},
            {"title": "Launch", "status": "todo", "priority": 5, "agent_type": "ember"},
        ],
    },
}


class TemplateResponse(BaseModel):
    id: str
    name: str
    emoji: str
    description: str
    color: str
    cards: list[dict[str, Any]]


class CreateFromTemplateRequest(BaseModel):
    title: str
    description: str = ""
    emoji: str | None = None
    color: str | None = None


class CreateFromTemplateResponse(BaseModel):
    project_id: str
    project_title: str
    cards_imported: int
    template_emoji: str
    template_color: str


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


@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates():
    """Return all built-in project templates."""
    return list(TEMPLATES.values())


@router.post("/from-template/{template_id}", response_model=CreateFromTemplateResponse, status_code=201)
async def create_project_from_template(
    template_id: str,
    body: CreateFromTemplateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new project pre-populated with cards from a built-in template."""
    template = TEMPLATES.get(template_id)
    if not template:
        raise HTTPException(404, f"Template '{template_id}' not found")

    project = Project(
        id=new_uuid(),
        title=body.title,
        description=body.description,
        context="",
    )
    db.add(project)
    await db.flush()

    for card_data in template["cards"]:
        agent_assigned = None
        if card_data.get("agent_type"):
            try:
                persona = get_persona(AgentType(card_data["agent_type"]))
                agent_assigned = f"{persona.emoji} {persona.name}"
            except (ValueError, KeyError):
                pass

        card = Card(
            id=new_uuid(),
            project_id=project.id,
            title=card_data["title"],
            description="",
            status=card_data.get("status", "todo"),
            priority=card_data.get("priority", 0),
            agent_type=card_data.get("agent_type"),
            agent_assigned=agent_assigned,
        )
        db.add(card)

    await db.commit()
    await db.refresh(project)

    return CreateFromTemplateResponse(
        project_id=project.id,
        project_title=project.title,
        cards_imported=len(template["cards"]),
        template_emoji=body.emoji or template["emoji"],
        template_color=body.color or template["color"],
    )


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


# ---------------------------------------------------------------------------
# Daily Standup
# ---------------------------------------------------------------------------

class StandupResponse(BaseModel):
    summary: str
    generated_at: str


class StandupScheduleRequest(BaseModel):
    enabled: bool = True
    hour: int = 9    # 09:00 local time
    minute: int = 0


class StandupScheduleResponse(BaseModel):
    job_id: str
    project_id: str
    schedule: str
    enabled: bool


@router.post("/{project_id}/standup", response_model=StandupResponse)
async def generate_standup(project_id: str, db: AsyncSession = Depends(get_db)):
    """Generate a daily standup summary for a project using the fast AI model."""
    # Fetch project + cards
    stmt = (
        select(Project)
        .options(selectinload(Project.cards))
        .where(Project.id == project_id)
    )
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")

    cards = project.cards

    # Categorize cards
    in_progress = [c for c in cards if c.status == "in-progress"]
    done_cards = [c for c in cards if c.status == "done"]
    blocked = [c for c in cards if c.priority == 3]  # critical priority = potential blocker
    todo = [c for c in cards if c.status == "todo"]

    def card_line(c: Card) -> str:
        agent = f" [{c.agent_type}]" if c.agent_type else ""
        return f"- {c.title}{agent}"

    in_progress_text = "\n".join(card_line(c) for c in in_progress) or "None"
    done_text = "\n".join(card_line(c) for c in done_cards) or "None"
    blocked_text = "\n".join(card_line(c) for c in blocked) or "None"
    todo_text = "\n".join(card_line(c) for c in todo[:5]) or "None"  # top 5 upcoming

    prompt = (
        f"Generate a concise daily standup for project: **{project.title}**\n\n"
        f"Project description: {project.description or 'N/A'}\n\n"
        f"Cards IN PROGRESS:\n{in_progress_text}\n\n"
        f"Cards DONE:\n{done_text}\n\n"
        f"BLOCKED / Critical priority:\n{blocked_text}\n\n"
        f"Next TODO (upcoming):\n{todo_text}\n\n"
        f"Total cards: {len(cards)} | Done: {len(done_cards)} | In Progress: {len(in_progress)} | Todo: {len(todo)}"
    )

    from app.services.claude_service import ClaudeService
    svc = ClaudeService()
    summary = await svc.generate_standup(prompt)

    return StandupResponse(
        summary=summary,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/{project_id}/standup/schedule", response_model=StandupScheduleResponse | None)
async def get_standup_schedule(project_id: str):
    """Get the current standup schedule for a project, or null if not configured."""
    jobs = _load_jobs()
    for job in jobs:
        if (
            job.get("type") == "standup"
            and job.get("payload", {}).get("project_id") == project_id
        ):
            return StandupScheduleResponse(
                job_id=job["id"],
                project_id=project_id,
                schedule=job["schedule"],
                enabled=job.get("enabled", True),
            )
    return None


@router.post("/{project_id}/standup/schedule", response_model=StandupScheduleResponse, status_code=201)
async def set_standup_schedule(
    project_id: str,
    body: StandupScheduleRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create or update the daily standup schedule for a project."""
    # Verify project exists
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    schedule = f"0 {body.minute} {body.hour} * * *"  # cron: daily at HH:MM

    jobs = _load_jobs()

    # Remove existing standup job for this project if any
    jobs = [
        j for j in jobs
        if not (j.get("type") == "standup" and j.get("payload", {}).get("project_id") == project_id)
    ]

    job_id = str(uuid.uuid4())
    new_job = {
        "id": job_id,
        "name": f"Daily Standup — {project.title}",
        "type": "standup",
        "schedule": schedule,
        "enabled": body.enabled,
        "payload": {
            "project_id": project_id,
            "project_name": project.title,
            "hour": body.hour,
            "minute": body.minute,
        },
    }
    jobs.append(new_job)
    _save_jobs(jobs)

    return StandupScheduleResponse(
        job_id=job_id,
        project_id=project_id,
        schedule=schedule,
        enabled=body.enabled,
    )
