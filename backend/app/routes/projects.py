"""Project endpoints."""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import logging

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db, Project, Card, WikiPage, Sprint, new_uuid, utcnow
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
    # Prevent duplicate project names (case-insensitive, active projects only)
    existing = await db.execute(
        select(Project).where(
            func.lower(Project.title) == body.title.strip().lower(),
            Project.status != "archived",
        )
    )
    if existing.scalar_one_or_none():
        logger.warning("Duplicate project name rejected: %s", body.title.strip())
        raise HTTPException(
            status_code=409,
            detail=f"A project named '{body.title.strip()}' already exists."
        )

    project = Project(
        id=new_uuid(),
        title=body.title.strip(),
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
    archived: bool | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Project).order_by(Project.updated_at.desc())
    if status:
        stmt = stmt.where(Project.status == status)
    elif archived is not None:
        if archived:
            stmt = stmt.where(Project.status == "archived")
        else:
            stmt = stmt.where(Project.status == "active")
    else:
        # Default: only active projects
        stmt = stmt.where(Project.status == "active")
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


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a project and all its cards (irreversible)."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Delete all cards belonging to this project
    stmt = select(Card).where(Card.project_id == project_id)
    result = await db.execute(stmt)
    for card in result.scalars().all():
        await db.delete(card)

    await db.delete(project)
    await db.commit()


@router.post("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Archive a project (hide from main list, keep all data)."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    project.status = "archived"
    project.updated_at = utcnow()
    await db.commit()
    await db.refresh(project)
    return project


@router.post("/{project_id}/restore", response_model=ProjectResponse)
async def restore_project(project_id: str, db: AsyncSession = Depends(get_db)):
    """Restore an archived project back to active."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    project.status = "active"
    project.updated_at = utcnow()
    await db.commit()
    await db.refresh(project)
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
# AI Meeting Notes Extractor
# ---------------------------------------------------------------------------

class MeetingNotesRequest(BaseModel):
    notes: str
    project_id: str | None = None  # optional, for context (unused in extraction but accepted)


class MeetingCardPreview(BaseModel):
    title: str
    description: str
    priority: int
    agent_type: str


class MeetingNotesResponse(BaseModel):
    cards: list[MeetingCardPreview]
    summary: str


class MeetingConfirmRequest(BaseModel):
    cards: list[MeetingCardPreview]


class MeetingConfirmResponse(BaseModel):
    created: int
    card_ids: list[str]


@router.post("/{project_id}/meeting-notes", response_model=MeetingNotesResponse)
async def extract_meeting_notes(
    project_id: str,
    body: MeetingNotesRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Extract action items from meeting notes using the Fast AI model.
    Returns a preview of cards — user confirms before creation.
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    if not body.notes or not body.notes.strip():
        raise HTTPException(400, "Meeting notes cannot be empty")

    from app.services.claude_service import ClaudeService
    svc = ClaudeService()
    data = await svc.generate_meeting_notes(body.notes)

    cards = []
    for item in data.get("cards", []):
        cards.append(
            MeetingCardPreview(
                title=str(item.get("title", "Untitled action"))[:200],
                description=str(item.get("description", ""))[:1000],
                priority=max(0, min(3, int(item.get("priority", 1)))),
                agent_type=str(item.get("agent_type", "ember")),
            )
        )

    return MeetingNotesResponse(
        cards=cards,
        summary=str(data.get("summary", ""))[:500],
    )


@router.post("/{project_id}/meeting-notes/confirm", response_model=MeetingConfirmResponse, status_code=201)
async def confirm_meeting_notes(
    project_id: str,
    body: MeetingConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create cards from confirmed meeting notes extraction.
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    card_ids = []
    for i, card_data in enumerate(body.cards):
        agent_assigned = None
        try:
            persona = get_persona(AgentType(card_data.agent_type))
            agent_assigned = f"{persona.emoji} {persona.name}"
        except (ValueError, KeyError):
            pass

        card = Card(
            id=new_uuid(),
            project_id=project_id,
            title=card_data.title,
            description=card_data.description,
            status="todo",
            priority=card_data.priority,
            agent_type=card_data.agent_type,
            agent_assigned=agent_assigned,
        )
        db.add(card)
        card_ids.append(card.id)

    project.updated_at = utcnow()
    await db.commit()

    return MeetingConfirmResponse(created=len(card_ids), card_ids=card_ids)


# ---------------------------------------------------------------------------
# AI Project Brief Generator
# ---------------------------------------------------------------------------

class BriefResponse(BaseModel):
    brief: str
    generated_at: str


@router.post("/{project_id}/brief", response_model=BriefResponse)
async def generate_brief(project_id: str, db: AsyncSession = Depends(get_db)):
    """Generate a comprehensive AI project brief / PRD using the Deep (Opus) model."""
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

    # Group cards by status
    def card_lines(filtered_cards) -> str:
        if not filtered_cards:
            return "  (none)"
        lines = []
        for c in filtered_cards:
            agent = f" [{c.agent_type}]" if c.agent_type else ""
            priority_map = {0: "low", 1: "medium", 2: "high", 3: "critical"}
            prio = priority_map.get(c.priority or 0, "low")
            desc = f" — {c.description[:120]}" if c.description else ""
            lines.append(f"  - {c.title}{agent} (priority: {prio}){desc}")
        return "\n".join(lines)

    idea_cards    = [c for c in cards if c.status == "idea"]
    todo_cards    = [c for c in cards if c.status == "todo"]
    inprog_cards  = [c for c in cards if c.status == "in-progress"]
    done_cards    = [c for c in cards if c.status == "done"]

    tech_stack = ""
    if project.github_language:
        tech_stack += f"Primary language: {project.github_language}. "
    if project.github_repo:
        tech_stack += f"Repo: {project.github_repo}. "
    if project.local_path:
        tech_stack += f"Local path: {project.local_path}. "
    if not tech_stack:
        tech_stack = "Not specified — infer from context."

    prompt = (
        f"Generate a professional project brief for: **{project.title}**\n\n"
        f"Description: {project.description or 'No description provided.'}\n\n"
        f"Tech stack: {tech_stack}\n\n"
        f"Cards/Features by status:\n\n"
        f"💡 IDEAS:\n{card_lines(idea_cards)}\n\n"
        f"📋 TODO:\n{card_lines(todo_cards)}\n\n"
        f"🔨 IN PROGRESS:\n{card_lines(inprog_cards)}\n\n"
        f"✅ DONE:\n{card_lines(done_cards)}\n\n"
        f"Total cards: {len(cards)} | Done: {len(done_cards)} | "
        f"In Progress: {len(inprog_cards)} | Todo: {len(todo_cards)} | "
        f"Ideas: {len(idea_cards)}\n\n"
        f"Generate a comprehensive project brief with the following sections:\n"
        f"1. Executive Summary (2-3 paragraphs)\n"
        f"2. Problem Statement\n"
        f"3. Goals & Success Metrics\n"
        f"4. Features List (organized from the cards above)\n"
        f"5. Technical Architecture (inferred from tech stack and card context)\n"
        f"6. Timeline Estimate (based on card count and complexity)\n"
        f"7. Risk Assessment\n\n"
        f"Format as clean, professional markdown. Be specific and actionable."
    )

    from app.services.claude_service import ClaudeService
    svc = ClaudeService()
    brief = await svc.generate_brief(prompt)

    return BriefResponse(
        brief=brief,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


# ---------------------------------------------------------------------------
# Project Health Check
# ---------------------------------------------------------------------------

class HealthIssue(BaseModel):
    severity: str  # "critical" | "warning" | "info"
    message: str


class HealthResponse(BaseModel):
    score: int
    grade: str  # "A" | "B" | "C" | "D" | "F"
    summary: str
    strengths: list[str]
    issues: list[HealthIssue]
    recommendations: list[str]
    generated_at: str


def _compute_health(project: "Project", cards: list["Card"], sprints: list["Sprint"]) -> dict:
    """Rule-based health analysis. Returns raw data dict (no AI summary yet)."""
    now = datetime.now(timezone.utc)
    issues: list[dict] = []
    strengths: list[str] = []
    recommendations: list[str] = []

    total = len(cards)
    idea_cards = [c for c in cards if c.status == "idea"]
    todo_cards = [c for c in cards if c.status == "todo"]
    inprog_cards = [c for c in cards if c.status == "in-progress"]
    done_cards = [c for c in cards if c.status == "done"]

    # ── Issue: no cards in-progress ──────────────────────────────────────────
    if total > 0 and len(inprog_cards) == 0:
        issues.append({"severity": "warning", "message": "No cards are currently in progress."})
        recommendations.append("Move at least one card to 'in-progress' to keep momentum going.")
    elif len(inprog_cards) > 0:
        strengths.append(f"{len(inprog_cards)} card(s) actively in progress — work is moving forward.")

    # ── Issue: stale todo cards (no activity > 7 days) ──────────────────────
    stale_count = 0
    seven_days_ago = now.timestamp() - 7 * 86400
    for c in todo_cards:
        updated = c.updated_at
        if updated:
            # Make timezone-aware for comparison
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if updated.timestamp() < seven_days_ago:
                stale_count += 1
    if stale_count > 0:
        issues.append({
            "severity": "warning",
            "message": f"{stale_count} todo card(s) have had no activity in over 7 days.",
        })
        recommendations.append("Review and prioritize stale todo cards or archive ones no longer relevant.")

    # ── Issue: high ratio of idea cards (backlog bloat) ─────────────────────
    if total > 0:
        idea_ratio = len(idea_cards) / total
        if idea_ratio > 0.4:
            issues.append({
                "severity": "info",
                "message": f"{len(idea_cards)} of {total} cards ({round(idea_ratio*100)}%) are in the idea/backlog stage.",
            })
            recommendations.append("Groom your backlog: promote the best ideas to 'todo' or archive low-priority ones.")

    # ── Issue: cards with no description ────────────────────────────────────
    no_desc = [c for c in cards if not (c.description or "").strip()]
    if no_desc:
        issues.append({
            "severity": "info",
            "message": f"{len(no_desc)} card(s) have no description.",
        })
        recommendations.append("Add descriptions to cards so agents and teammates have the context they need.")

    # ── Issue: cards with no assignee ──────────────────────────────────────
    no_assignee = [c for c in cards if not c.assignee and not c.agent_type and not c.agent_assigned]
    if total > 0 and len(no_assignee) > total * 0.5:
        issues.append({
            "severity": "info",
            "message": f"{len(no_assignee)} card(s) have no assignee or agent.",
        })
        recommendations.append("Assign cards to agents or team members to ensure clear ownership.")

    # ── Strength: checklist usage + completion ──────────────────────────────
    all_checklist = []
    for c in cards:
        if hasattr(c, "checklist_items") and c.checklist_items:
            all_checklist.extend(c.checklist_items)
    if all_checklist:
        completed_items = [i for i in all_checklist if i.completed]
        completion_rate = len(completed_items) / len(all_checklist)
        if completion_rate >= 0.5:
            strengths.append(
                f"Checklist items are {round(completion_rate*100)}% complete — good tracking discipline."
            )
        elif completion_rate < 0.2 and len(all_checklist) > 3:
            issues.append({
                "severity": "info",
                "message": f"Checklist completion is low ({round(completion_rate*100)}% of {len(all_checklist)} items done).",
            })

    # ── Strength: sprint planning in use ──────────────────────────────────
    if sprints:
        active_sprints = [s for s in sprints if s.status == "active"]
        if active_sprints:
            strengths.append("Active sprint in progress — structured planning is in use.")
        else:
            strengths.append(f"{len(sprints)} sprint(s) defined — sprint planning is in use.")
        recommendations_text = "Continue using sprint planning to maintain velocity and focus."
    else:
        if total > 5:
            recommendations.append("Consider using sprint planning to group and prioritize your cards.")

    # ── Issue: blocked cards (cards with is_blocked_by relations) ──────────
    blocked_cards = []
    for c in cards:
        if hasattr(c, "relations_as_target") and c.relations_as_target:
            for rel in c.relations_as_target:
                if rel.relation_type == "is_blocked_by":
                    source = rel.source_card
                    if source and source.status not in ("done",):
                        blocked_cards.append(c)
                        break
    if blocked_cards:
        issues.append({
            "severity": "warning",
            "message": f"{len(blocked_cards)} card(s) are blocked by unresolved dependencies.",
        })
        recommendations.append("Resolve blocked card dependencies to unblock your team.")

    # ── Strength: done cards signal progress ────────────────────────────────
    if done_cards:
        strengths.append(f"{len(done_cards)} card(s) completed — real progress delivered.")

    # ── Score algorithm ─────────────────────────────────────────────────────
    score = 100
    severity_deductions = {"critical": -15, "warning": -5, "info": -2}
    for issue in issues:
        score += severity_deductions.get(issue["severity"], 0)
    score += len(strengths) * 5
    score = max(0, min(100, score))

    # ── Grade ───────────────────────────────────────────────────────────────
    if score >= 90:
        grade = "A"
    elif score >= 80:
        grade = "B"
    elif score >= 70:
        grade = "C"
    elif score >= 60:
        grade = "D"
    else:
        grade = "F"

    return {
        "score": score,
        "grade": grade,
        "strengths": strengths,
        "issues": [HealthIssue(**i) for i in issues],
        "recommendations": recommendations,
        # Context for AI summary
        "_meta": {
            "total": total,
            "todo": len(todo_cards),
            "inprog": len(inprog_cards),
            "done": len(done_cards),
            "idea": len(idea_cards),
            "sprints": len(sprints),
            "project_title": project.title,
        },
    }


@router.post("/{project_id}/health", response_model=HealthResponse)
async def project_health_check(project_id: str, db: AsyncSession = Depends(get_db)):
    """Analyse project health and return a score, grade, strengths, issues, and recommendations."""
    from sqlalchemy.orm import selectinload as slo

    from app.database import CardRelation, ChecklistItem
    stmt = (
        select(Project)
        .options(
            slo(Project.cards).selectinload(Card.checklist_items),
            slo(Project.cards).selectinload(Card.relations_as_target).selectinload(CardRelation.source_card),
            slo(Project.sprints),
        )
        .where(Project.id == project_id)
    )
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")

    cards = list(project.cards)
    sprints = list(project.sprints) if hasattr(project, "sprints") else []

    health = _compute_health(project, cards, sprints)

    # Build AI summary prompt
    meta = health.pop("_meta")
    strengths_text = "\n".join(f"- {s}" for s in health["strengths"]) or "None"
    issues_text = "\n".join(
        f"- [{i.severity.upper()}] {i.message}" for i in health["issues"]
    ) or "None"
    recs_text = "\n".join(f"- {r}" for r in health["recommendations"]) or "None"

    summary_prompt = (
        f"Project: {meta['project_title']}\n"
        f"Health score: {health['score']}/100 (Grade {health['grade']})\n"
        f"Cards: {meta['total']} total — {meta['inprog']} in-progress, {meta['todo']} todo, "
        f"{meta['done']} done, {meta['idea']} ideas\n"
        f"Sprints: {meta['sprints']}\n\n"
        f"Strengths:\n{strengths_text}\n\n"
        f"Issues:\n{issues_text}\n\n"
        f"Recommendations:\n{recs_text}\n\n"
        f"Write a concise 2-3 sentence health summary for this project."
    )

    from app.services.claude_service import ClaudeService
    svc = ClaudeService()
    summary = await svc.generate_health_summary(summary_prompt)

    return HealthResponse(
        score=health["score"],
        grade=health["grade"],
        summary=summary,
        strengths=health["strengths"],
        issues=health["issues"],
        recommendations=health["recommendations"],
        generated_at=datetime.now(timezone.utc).isoformat(),
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


# ---------------------------------------------------------------------------
# Project Wiki
# ---------------------------------------------------------------------------

class WikiPageSummary(BaseModel):
    id: str
    title: str
    updated_at: str


class WikiPageDetail(BaseModel):
    id: str
    project_id: str
    title: str
    content: str
    created_at: str
    updated_at: str


class WikiPageCreate(BaseModel):
    title: str = "Untitled Page"
    content: str = ""


class WikiPageUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


@router.get("/{project_id}/wiki", response_model=list[WikiPageSummary])
async def list_wiki_pages(project_id: str, db: AsyncSession = Depends(get_db)):
    """List all wiki pages for a project (title + id + updated_at)."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    stmt = (
        select(WikiPage)
        .where(WikiPage.project_id == project_id)
        .order_by(WikiPage.updated_at.desc())
    )
    result = await db.execute(stmt)
    pages = result.scalars().all()
    return [
        WikiPageSummary(
            id=p.id,
            title=p.title,
            updated_at=p.updated_at.isoformat() if p.updated_at else "",
        )
        for p in pages
    ]


@router.post("/{project_id}/wiki", response_model=WikiPageDetail, status_code=201)
async def create_wiki_page(
    project_id: str,
    body: WikiPageCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new wiki page for a project."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    page = WikiPage(
        id=new_uuid(),
        project_id=project_id,
        title=body.title,
        content=body.content,
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return WikiPageDetail(
        id=page.id,
        project_id=page.project_id,
        title=page.title,
        content=page.content,
        created_at=page.created_at.isoformat() if page.created_at else "",
        updated_at=page.updated_at.isoformat() if page.updated_at else "",
    )


@router.get("/{project_id}/wiki/{page_id}", response_model=WikiPageDetail)
async def get_wiki_page(project_id: str, page_id: str, db: AsyncSession = Depends(get_db)):
    """Get full content of a single wiki page."""
    page = await db.get(WikiPage, page_id)
    if not page or page.project_id != project_id:
        raise HTTPException(404, "Wiki page not found")
    return WikiPageDetail(
        id=page.id,
        project_id=page.project_id,
        title=page.title,
        content=page.content,
        created_at=page.created_at.isoformat() if page.created_at else "",
        updated_at=page.updated_at.isoformat() if page.updated_at else "",
    )


@router.put("/{project_id}/wiki/{page_id}", response_model=WikiPageDetail)
async def update_wiki_page(
    project_id: str,
    page_id: str,
    body: WikiPageUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a wiki page's title and/or content."""
    page = await db.get(WikiPage, page_id)
    if not page or page.project_id != project_id:
        raise HTTPException(404, "Wiki page not found")
    if body.title is not None:
        page.title = body.title
    if body.content is not None:
        page.content = body.content
    page.updated_at = utcnow()
    await db.commit()
    await db.refresh(page)
    return WikiPageDetail(
        id=page.id,
        project_id=page.project_id,
        title=page.title,
        content=page.content,
        created_at=page.created_at.isoformat() if page.created_at else "",
        updated_at=page.updated_at.isoformat() if page.updated_at else "",
    )


@router.delete("/{project_id}/wiki/{page_id}", status_code=204)
async def delete_wiki_page(
    project_id: str,
    page_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a wiki page."""
    page = await db.get(WikiPage, page_id)
    if not page or page.project_id != project_id:
        raise HTTPException(404, "Wiki page not found")
    await db.delete(page)
    await db.commit()


# ---------------------------------------------------------------------------
# Sprint Planning
# ---------------------------------------------------------------------------

class SprintCreate(BaseModel):
    name: str
    goal: str | None = None
    start_date: str  # ISO date string
    end_date: str    # ISO date string


class SprintUpdate(BaseModel):
    name: str | None = None
    goal: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class SprintResponse(BaseModel):
    id: str
    project_id: str
    name: str
    goal: str | None
    start_date: str
    end_date: str
    status: str
    created_at: str
    card_count: int = 0


def _sprint_to_response(sprint: Sprint, card_count: int = 0) -> SprintResponse:
    return SprintResponse(
        id=sprint.id,
        project_id=sprint.project_id,
        name=sprint.name,
        goal=sprint.goal,
        start_date=sprint.start_date.isoformat() if sprint.start_date else "",
        end_date=sprint.end_date.isoformat() if sprint.end_date else "",
        status=sprint.status,
        created_at=sprint.created_at.isoformat() if sprint.created_at else "",
        card_count=card_count,
    )


@router.get("/{project_id}/sprints", response_model=list[SprintResponse])
async def list_sprints(project_id: str, db: AsyncSession = Depends(get_db)):
    """List all sprints for a project with card counts."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    stmt = select(Sprint).where(Sprint.project_id == project_id).order_by(Sprint.start_date)
    result = await db.execute(stmt)
    sprints = result.scalars().all()

    # Count cards per sprint
    count_stmt = (
        select(Card.sprint_id, func.count(Card.id).label("cnt"))
        .where(Card.project_id == project_id)
        .where(Card.sprint_id.isnot(None))
        .group_by(Card.sprint_id)
    )
    count_result = await db.execute(count_stmt)
    counts = {row.sprint_id: row.cnt for row in count_result.fetchall()}

    return [_sprint_to_response(s, counts.get(s.id, 0)) for s in sprints]


@router.post("/{project_id}/sprints", response_model=SprintResponse, status_code=201)
async def create_sprint(
    project_id: str,
    body: SprintCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new sprint for a project."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    try:
        start = datetime.fromisoformat(body.start_date.replace("Z", "+00:00"))
        end = datetime.fromisoformat(body.end_date.replace("Z", "+00:00"))
    except ValueError as e:
        raise HTTPException(400, f"Invalid date format: {e}")

    if end <= start:
        raise HTTPException(400, "end_date must be after start_date")

    sprint = Sprint(
        id=new_uuid(),
        project_id=project_id,
        name=body.name,
        goal=body.goal,
        start_date=start,
        end_date=end,
        status="planning",
    )
    db.add(sprint)
    await db.commit()
    await db.refresh(sprint)
    return _sprint_to_response(sprint, 0)


@router.put("/{project_id}/sprints/{sprint_id}", response_model=SprintResponse)
async def update_sprint(
    project_id: str,
    sprint_id: str,
    body: SprintUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update sprint name, goal, or dates."""
    sprint = await db.get(Sprint, sprint_id)
    if not sprint or sprint.project_id != project_id:
        raise HTTPException(404, "Sprint not found")

    if body.name is not None:
        sprint.name = body.name
    if body.goal is not None:
        sprint.goal = body.goal
    if body.start_date is not None:
        try:
            sprint.start_date = datetime.fromisoformat(body.start_date.replace("Z", "+00:00"))
        except ValueError as e:
            raise HTTPException(400, f"Invalid start_date: {e}")
    if body.end_date is not None:
        try:
            sprint.end_date = datetime.fromisoformat(body.end_date.replace("Z", "+00:00"))
        except ValueError as e:
            raise HTTPException(400, f"Invalid end_date: {e}")

    await db.commit()
    await db.refresh(sprint)

    # Get card count
    count_result = await db.execute(
        select(func.count(Card.id)).where(Card.sprint_id == sprint_id)
    )
    card_count = count_result.scalar() or 0
    return _sprint_to_response(sprint, card_count)


@router.delete("/{project_id}/sprints/{sprint_id}", status_code=204)
async def delete_sprint(
    project_id: str,
    sprint_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a sprint. Cards in this sprint lose their sprint assignment."""
    sprint = await db.get(Sprint, sprint_id)
    if not sprint or sprint.project_id != project_id:
        raise HTTPException(404, "Sprint not found")

    # Unassign cards from this sprint
    stmt = select(Card).where(Card.sprint_id == sprint_id)
    result = await db.execute(stmt)
    for card in result.scalars().all():
        card.sprint_id = None

    await db.delete(sprint)
    await db.commit()


@router.post("/{project_id}/sprints/{sprint_id}/start", response_model=SprintResponse)
async def start_sprint(
    project_id: str,
    sprint_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Activate a sprint (set status to 'active'). Only one sprint can be active at a time."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    sprint = await db.get(Sprint, sprint_id)
    if not sprint or sprint.project_id != project_id:
        raise HTTPException(404, "Sprint not found")

    # Deactivate any currently active sprint
    stmt = select(Sprint).where(Sprint.project_id == project_id, Sprint.status == "active")
    result = await db.execute(stmt)
    for active in result.scalars().all():
        active.status = "planning"  # revert previous active to planning

    sprint.status = "active"
    await db.commit()
    await db.refresh(sprint)

    count_result = await db.execute(
        select(func.count(Card.id)).where(Card.sprint_id == sprint_id)
    )
    card_count = count_result.scalar() or 0
    return _sprint_to_response(sprint, card_count)


# ---------------------------------------------------------------------------
# Smart Card Prioritization
# ---------------------------------------------------------------------------

class PriorizedCard(BaseModel):
    card_id: str
    title: str
    score: float
    reasoning: str


class PrioritizeResponse(BaseModel):
    ordered_cards: list[PriorizedCard]
    summary: str


def _compute_priority_score(card: "Card", all_cards: list["Card"]) -> float:
    """
    Deterministic rule-based scoring (0-100).
    Weights:
      - priority field:      0-25 pts
      - votes:               0-20 pts  (capped at 10 votes = max)
      - unblocks others:     0-20 pts
      - age (days):          0-10 pts  (capped at 30 days)
      - checklist progress:  0-15 pts  (partially done = highest)
      - status:              0-10 pts
    Total max = 100
    """
    score = 0.0
    now = datetime.now(timezone.utc)

    # 1. Priority field (critical=4, high=3, medium=2, low=1, none=0)
    # Map DB values: 3=critical, 2=high, 1=medium, 0=low
    priority_map = {3: 25.0, 2: 18.75, 1: 12.5, 0: 6.25}
    score += priority_map.get(card.priority or 0, 6.25)

    # 2. Votes (more votes = higher) — capped at 10 votes for max score
    votes = card.votes or 0
    score += min(votes / 10.0, 1.0) * 20.0

    # 3. Dependencies: cards that unblock others → higher priority
    # Count how many OTHER cards depend on this card
    dependents_count = 0
    for other in all_cards:
        if other.id == card.id:
            continue
        if hasattr(other, "dependencies"):
            for dep in (other.dependencies or []):
                if dep.id == card.id:
                    dependents_count += 1
    score += min(dependents_count / 3.0, 1.0) * 20.0

    # 4. Age (older = slightly higher) — capped at 30 days
    created_at = card.created_at
    if created_at:
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = (now - created_at).total_seconds() / 86400
        score += min(age_days / 30.0, 1.0) * 10.0

    # 5. Checklist completion (partially done = highest: started but not finished)
    checklist = list(card.checklist_items) if hasattr(card, "checklist_items") else []
    if checklist:
        total_items = len(checklist)
        done_items = sum(1 for i in checklist if i.completed)
        completion_ratio = done_items / total_items
        # Partially done (0.1-0.9) = max points; fully done or not started = 0
        if 0.0 < completion_ratio < 1.0:
            # Peak at 50% completion
            partial_score = 1.0 - abs(completion_ratio - 0.5) * 2  # 0.5 → 1.0, 0 or 1 → 0
            score += partial_score * 15.0
        # fully done = 0 extra (already done is done)
    # No checklist = neutral (0 pts for this factor)

    # 6. Status (in-progress > todo > idea; done cards get 0 = should not appear)
    status_map = {"in-progress": 10.0, "todo": 6.0, "idea": 2.0, "done": 0.0}
    score += status_map.get(card.status or "todo", 2.0)

    return round(min(score, 100.0), 2)


@router.post("/{project_id}/prioritize", response_model=PrioritizeResponse)
async def smart_prioritize(project_id: str, db: AsyncSession = Depends(get_db)):
    """
    Analyze all non-done cards and return a suggested work order.
    Score is deterministic (rule-based). AI generates brief reasoning for top 3.
    """
    from sqlalchemy.orm import selectinload as slo
    from app.services.claude_service import ClaudeService

    stmt = (
        select(Project)
        .options(
            slo(Project.cards).selectinload(Card.checklist_items),
            slo(Project.cards).selectinload(Card.dependencies),
        )
        .where(Project.id == project_id)
    )
    result = await db.execute(stmt)
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")

    all_cards = list(project.cards)

    # Score only non-done cards (done cards have nothing left to prioritize)
    active_cards = [c for c in all_cards if c.status != "done"]

    if not active_cards:
        return PrioritizeResponse(
            ordered_cards=[],
            summary="All cards are done — nothing left to prioritize! 🎉",
        )

    # Compute scores
    scored = [(card, _compute_priority_score(card, all_cards)) for card in active_cards]
    scored.sort(key=lambda x: x[1], reverse=True)

    # Build top-3 AI reasoning prompt
    top3 = scored[:3]
    priority_label = {3: "critical", 2: "high", 1: "medium", 0: "low"}
    status_label = {"in-progress": "in progress", "todo": "todo", "idea": "idea"}

    top3_lines = []
    for rank, (card, score) in enumerate(top3, 1):
        votes = card.votes or 0
        checklist = list(card.checklist_items) if hasattr(card, "checklist_items") else []
        checklist_info = ""
        if checklist:
            done = sum(1 for i in checklist if i.completed)
            checklist_info = f", {done}/{len(checklist)} checklist items done"
        line = (
            f"#{rank}: \"{card.title}\" — score {score}/100, "
            f"priority={priority_label.get(card.priority or 0, 'low')}, "
            f"status={status_label.get(card.status, card.status)}, "
            f"votes={votes}{checklist_info}"
        )
        top3_lines.append(line)

    reasoning_prompt = (
        f"Project: {project.title}\n\n"
        f"Top 3 prioritized cards:\n" + "\n".join(top3_lines) + "\n\n"
        f"For each of the top 3 cards, write ONE short sentence (max 20 words) explaining WHY it should be done first. "
        f"Be specific: mention priority, blocking others, partial progress, or votes. "
        f"Respond ONLY with valid JSON: "
        f'[{{"card_rank": 1, "reasoning": "..."}}, {{"card_rank": 2, "reasoning": "..."}}, {{"card_rank": 3, "reasoning": "..."}}]'
    )

    svc = ClaudeService()
    reasoning_map: dict[int, str] = {}

    try:
        raw = await svc.generate_priority_reasoning(reasoning_prompt)
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0].strip()
        parsed = json.loads(text)
        for item in parsed:
            reasoning_map[item["card_rank"]] = str(item["reasoning"])[:200]
    except Exception as e:
        logger.warning(f"[Prioritize] AI reasoning failed, using fallback: {e}")
        # Fallback: deterministic reasoning
        for rank, (card, score) in enumerate(top3, 1):
            reasoning_map[rank] = f"Score {score}/100 based on priority, votes, and dependencies."

    # Build response
    ordered = []
    for rank, (card, score) in enumerate(scored, 1):
        reasoning = reasoning_map.get(rank, "")
        ordered.append(PriorizedCard(
            card_id=card.id,
            title=card.title,
            score=score,
            reasoning=reasoning,
        ))

    # Summary
    total = len(scored)
    in_prog = sum(1 for c, _ in scored if c.status == "in-progress")
    top_title = scored[0][0].title if scored else ""
    summary = (
        f"{total} card{'s' if total != 1 else ''} analyzed. "
        f"{in_prog} in progress. "
        f"Top priority: \"{top_title}\"."
    )

    return PrioritizeResponse(ordered_cards=ordered, summary=summary)


@router.post("/{project_id}/sprints/{sprint_id}/complete", response_model=SprintResponse)
async def complete_sprint(
    project_id: str,
    sprint_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Mark a sprint as completed."""
    sprint = await db.get(Sprint, sprint_id)
    if not sprint or sprint.project_id != project_id:
        raise HTTPException(404, "Sprint not found")

    sprint.status = "completed"
    await db.commit()
    await db.refresh(sprint)

    count_result = await db.execute(
        select(func.count(Card.id)).where(Card.sprint_id == sprint_id)
    )
    card_count = count_result.scalar() or 0
    return _sprint_to_response(sprint, card_count)
