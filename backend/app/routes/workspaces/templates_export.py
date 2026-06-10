"""Built-in workspace templates + workspace export/import endpoints.

Two routers so the package ``__init__`` can reproduce the original
registration order: the template routes registered at the top of the original
module (before the collection CRUD), while export/import registered after the
autonomy routes.
"""

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import (
    get_db, Workspace, Card,
    ChecklistItem, TimeEntry, CardRelation,
    new_uuid, utcnow,
)
from app.services.agent_personas import AgentType, get_persona

from app.routes.workspaces.schemas import (
    CreateFromTemplateRequest,
    CreateFromTemplateResponse,
    ExportPayload,
    ImportResponse,
    TemplateResponse,
)

templates_router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])
export_import_router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])

# ---------------------------------------------------------------------------
# Built-in workspace templates
# ---------------------------------------------------------------------------

TEMPLATES: dict[str, dict[str, Any]] = {
    "software": {
        "id": "software",
        "name": "Software Workspace",
        "emoji": "💻",
        "description": "Plan, build, test and ship a software product.",
        "color": "#54a0ff",
        "cards": [
            {"title": "Define requirements", "status": "todo", "priority": 1, "agent_type": "researcher"},
            {"title": "Design architecture", "status": "todo", "priority": 2, "agent_type": "architect"},
            {"title": "Implement features", "status": "todo", "priority": 3, "agent_type": "coder"},
            {"title": "Write tests", "status": "todo", "priority": 4, "agent_type": "qa"},
            {"title": "Deploy", "status": "todo", "priority": 5, "agent_type": "general"},
        ],
    },
    "research": {
        "id": "research",
        "name": "Research Workspace",
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
            {"title": "Brainstorm topics", "status": "todo", "priority": 1, "agent_type": "general"},
            {"title": "Outline", "status": "todo", "priority": 2, "agent_type": "writer"},
            {"title": "Draft", "status": "todo", "priority": 3, "agent_type": "writer"},
            {"title": "Review & edit", "status": "todo", "priority": 4, "agent_type": "qa"},
            {"title": "Publish", "status": "todo", "priority": 5, "agent_type": "general"},
        ],
    },
    "bugfix": {
        "id": "bugfix",
        "name": "Bug Fix",
        "emoji": "🐛",
        "description": "Systematic process to squash a bug and ship the fix.",
        "color": "#ff6b6b",
        "cards": [
            {"title": "Reproduce bug", "status": "todo", "priority": 1, "agent_type": "qa"},
            {"title": "Root cause analysis", "status": "todo", "priority": 2, "agent_type": "architect"},
            {"title": "Implement fix", "status": "todo", "priority": 3, "agent_type": "coder"},
            {"title": "Write regression test", "status": "todo", "priority": 4, "agent_type": "qa"},
            {"title": "Deploy fix", "status": "todo", "priority": 5, "agent_type": "general"},
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
            {"title": "Launch", "status": "todo", "priority": 5, "agent_type": "general"},
        ],
    },
}


@templates_router.get("/templates", response_model=list[TemplateResponse])
async def list_templates():
    """Return all built-in workspace templates."""
    return list(TEMPLATES.values())


@templates_router.post("/from-template/{template_id}", response_model=CreateFromTemplateResponse, status_code=201)
async def create_workspace_from_template(
    template_id: str,
    body: CreateFromTemplateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new workspace pre-populated with cards from a built-in template."""
    template = TEMPLATES.get(template_id)
    if not template:
        raise HTTPException(404, f"Template '{template_id}' not found")

    workspace = Workspace(
        id=new_uuid(),
        title=body.title,
        description=body.description,
        context="",
    )
    db.add(workspace)
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
            workspace_id=workspace.id,
            title=card_data["title"],
            description="",
            status=card_data.get("status", "todo"),
            priority=card_data.get("priority", 0),
            agent_type=card_data.get("agent_type"),
            agent_assigned=agent_assigned,
        )
        db.add(card)

    await db.commit()
    await db.refresh(workspace)

    return CreateFromTemplateResponse(
        workspace_id=workspace.id,
        workspace_title=workspace.title,
        cards_imported=len(template["cards"]),
        template_emoji=body.emoji or template["emoji"],
        template_color=body.color or template["color"],
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

@export_import_router.get("/{workspace_id}/export")
async def export_workspace(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """Export a workspace and all its cards as a JSON payload.

    Includes per-card: checklists (with completion state), time entries,
    file references, card relations, dependency IDs, and position.

    Wiki pages are intentionally excluded (see ExportPayload TODO).
    """
    stmt = (
        select(Workspace)
        .options(
            selectinload(Workspace.cards).selectinload(Card.checklist_items),
            selectinload(Workspace.cards).selectinload(Card.time_entries),
            selectinload(Workspace.cards).selectinload(Card.relations_as_source),
            selectinload(Workspace.cards).selectinload(Card.dependencies),
        )
        .where(Workspace.id == workspace_id)
    )
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    cards_data = []
    for card in workspace.cards:
        # Decode files — stored as a JSON string in the DB
        try:
            files = json.loads(card.files) if card.files else []
        except (ValueError, TypeError):
            files = []

        cards_data.append({
            "id": card.id,
            "title": card.title,
            "description": card.description or "",
            "status": card.status,
            "priority": card.priority,
            "position": card.position,
            "color": card.color,
            "agent_type": card.agent_type,
            "agent_context": card.agent_context,
            "assignee": card.assignee,
            "watchers": card.watchers or "",
            "files": files,
            "tags": [],
            "dependency_ids": [d.id for d in card.dependencies],
            "checklist_items": [
                {
                    "text": item.text,
                    "completed": item.completed,
                    "position": item.position,
                }
                for item in card.checklist_items
            ],
            "time_entries": [
                {
                    "duration_minutes": te.duration_minutes,
                    "note": te.note,
                    "logged_at": te.logged_at.isoformat() if te.logged_at else "",
                }
                for te in card.time_entries
            ],
            "relations": [
                {
                    "target_card_id": rel.target_card_id,
                    "relation_type": rel.relation_type,
                }
                for rel in card.relations_as_source
            ],
        })

    payload = {
        "version": "1.1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "workspace": {
            "title": workspace.title,
            "description": workspace.description or "",
            "status": workspace.status,
            "context": workspace.context or "",
            "github_repo": workspace.github_repo,
            "github_url": workspace.github_url,
            "github_branch": workspace.github_branch,
            "github_language": workspace.github_language,
            "local_path": workspace.local_path,
        },
        "cards": cards_data,
    }

    return JSONResponse(content=payload)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

@export_import_router.post("/import", response_model=ImportResponse, status_code=201)
async def import_workspace(body: ExportPayload, db: AsyncSession = Depends(get_db)):
    """Import a workspace from an exported JSON payload. Creates a new workspace.

    Handles all fields produced by the v1.1 export: checklist items, time
    entries, file references, card relations, dependencies, and position.
    For relations and dependencies, old card IDs are mapped to the newly-
    assigned IDs so cross-references remain consistent after import.
    """
    base_title = body.workspace.title.strip()

    async def _title_taken(candidate: str) -> bool:
        # Same case-insensitive duplicate check as create_workspace.
        existing = await db.execute(
            select(Workspace).where(
                func.lower(Workspace.title) == candidate.lower(),
                Workspace.status != "archived",
            )
        )
        return existing.scalar_one_or_none() is not None

    # De-duplicate the title: "X" → "X (imported)" → "X (imported 2)" → …
    title = base_title
    attempt = 0
    while await _title_taken(title):
        attempt += 1
        title = f"{base_title} (imported)" if attempt == 1 else f"{base_title} (imported {attempt})"

    workspace = Workspace(
        id=new_uuid(),
        title=title,
        description=body.workspace.description,
        status=body.workspace.status,
        context=body.workspace.context,
        github_repo=body.workspace.github_repo,
        github_url=body.workspace.github_url,
        github_branch=body.workspace.github_branch,
        github_language=body.workspace.github_language,
        local_path=body.workspace.local_path,
    )
    db.add(workspace)
    await db.flush()  # get workspace.id before creating cards

    # --- Pass 1: create cards and build old_id → new_id mapping ---
    # This mapping is needed to rewrite relations and dependency_ids.
    old_to_new_id: dict[str, str] = {}

    for card_data in body.cards:
        # Resolve agent display name if agent_type is provided
        agent_assigned = None
        if card_data.agent_type:
            try:
                persona = get_persona(AgentType(card_data.agent_type))
                agent_assigned = f"{persona.emoji} {persona.name}"
            except (ValueError, KeyError):
                pass

        new_id = new_uuid()
        if card_data.id:
            old_to_new_id[card_data.id] = new_id

        card = Card(
            id=new_id,
            workspace_id=workspace.id,
            title=card_data.title,
            description=card_data.description,
            status=card_data.status,
            priority=card_data.priority,
            position=card_data.position,
            color=card_data.color,
            agent_type=card_data.agent_type,
            agent_context=card_data.agent_context,
            agent_assigned=agent_assigned,
            assignee=card_data.assignee,
            watchers=card_data.watchers or "",
            files=json.dumps(card_data.files),
        )
        db.add(card)

        # Checklist items — preserve order via position
        for item in card_data.checklist_items:
            db.add(ChecklistItem(
                id=new_uuid(),
                card_id=new_id,
                text=item.text,
                completed=item.completed,
                position=item.position,
            ))

        # Time entries — preserve the original logged_at timestamp so the
        # export/import round-trip does not rewrite time history (see docstring).
        for te in card_data.time_entries:
            logged_at = None
            if te.logged_at:
                try:
                    logged_at = datetime.fromisoformat(te.logged_at)
                except ValueError:
                    logged_at = None
            db.add(TimeEntry(
                id=new_uuid(),
                card_id=new_id,
                duration_minutes=te.duration_minutes,
                note=te.note,
                logged_at=logged_at or utcnow(),
            ))

    # Flush so all card rows exist before we add FK-referencing relations
    await db.flush()

    # --- Pass 2: create relations and dependencies using the ID mapping ---
    for card_data in body.cards:
        if not card_data.id or card_data.id not in old_to_new_id:
            continue
        new_source_id = old_to_new_id[card_data.id]

        # Card relations
        for rel in card_data.relations:
            new_target_id = old_to_new_id.get(rel.target_card_id)
            if new_target_id:
                db.add(CardRelation(
                    id=new_uuid(),
                    source_card_id=new_source_id,
                    target_card_id=new_target_id,
                    relation_type=rel.relation_type,
                ))

        # Dependencies (many-to-many via card_dependencies — raw insert to
        # avoid async lazy-load issues on the ORM relationship)
        for old_dep_id in card_data.dependency_ids:
            new_dep_id = old_to_new_id.get(old_dep_id)
            if new_dep_id:
                await db.execute(
                    text(
                        "INSERT OR IGNORE INTO card_dependencies "
                        "(card_id, depends_on_id) VALUES (:card_id, :dep_id)"
                    ),
                    {"card_id": new_source_id, "dep_id": new_dep_id},
                )

    await db.commit()
    await db.refresh(workspace)

    return ImportResponse(
        workspace_id=workspace.id,
        workspace_title=workspace.title,
        cards_imported=len(body.cards),
    )
