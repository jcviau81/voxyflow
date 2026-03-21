"""Card/Task endpoints — with agent assignment support."""

import logging
import mimetypes
from pathlib import Path

import json

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from fastapi.responses import FileResponse
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Card, CardAttachment, CardRelation, CardHistory, Project, TimeEntry, CardComment, ChecklistItem, new_uuid, utcnow
from app.models.card import (
    CardCreate, CardUpdate, CardResponse, AgentAssignment,
    TimeEntryCreate, TimeEntryResponse,
    CommentCreate, CommentResponse,
    ChecklistItemCreate, ChecklistItemUpdate, ChecklistItemResponse, ChecklistProgress,
    AttachmentResponse,
)
from app.services.agent_router import get_agent_router
from app.services.agent_personas import AgentType, get_persona, get_all_personas

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024  # 50 MB

ATTACHMENTS_BASE = Path.home() / ".voxyflow" / "attachments"

router = APIRouter(tags=["cards"])


@router.get("/agents")
async def list_agents():
    """Return all available agent personas (type, name, emoji, description, strengths)."""
    personas = get_all_personas()
    return [
        {
            "type": persona.agent_type.value,
            "name": persona.name,
            "emoji": persona.emoji,
            "description": persona.description,
            "strengths": persona.strengths,
            "keywords": persona.keywords,
        }
        for persona in personas.values()
    ]


@router.post("/projects/{project_id}/cards", response_model=CardResponse, status_code=201)
async def create_card(
    project_id: str,
    body: CardCreate,
    db: AsyncSession = Depends(get_db),
):
    # Verify project exists
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Auto-route to agent if not specified
    agent_type = body.agent_type
    if not agent_type:
        router_service = get_agent_router()
        detected_type, confidence = router_service.route(
            title=body.title,
            description=body.description or "",
            context=body.agent_context or "",
        )
        agent_type = detected_type.value

    # Get agent display name
    persona = get_persona(AgentType(agent_type))
    agent_display = f"{persona.emoji} {persona.name}"

    card = Card(
        id=new_uuid(),
        project_id=project_id,
        title=body.title,
        description=body.description or "",
        status=body.status,
        priority=body.priority,
        source_message_id=body.source_message_id,
        auto_generated=body.auto_generated,
        agent_type=agent_type,
        agent_assigned=agent_display,
        agent_context=body.agent_context,
        recurrence=body.recurrence,
        recurrence_next=body.recurrence_next,
    )

    # Resolve dependencies
    if body.dependency_ids:
        for dep_id in body.dependency_ids:
            dep = await db.get(Card, dep_id)
            if dep and dep.project_id == project_id:
                card.dependencies.append(dep)

    db.add(card)
    await db.commit()
    # Reload with relationships
    stmt = select(Card).where(Card.id == card.id).options(
        selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items)
    )
    result = await db.execute(stmt)
    card = result.scalar_one()

    return _card_to_response(card)


@router.get("/projects/{project_id}/cards", response_model=list[CardResponse])
async def list_cards(
    project_id: str,
    status: str | None = None,
    agent_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Card)
        .where(Card.project_id == project_id)
        .options(selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items))
        .order_by(Card.position)
    )
    if status:
        stmt = stmt.where(Card.status == status)
    if agent_type:
        stmt = stmt.where(Card.agent_type == agent_type)
    result = await db.execute(stmt)
    return [_card_to_response(c) for c in result.scalars().all()]


# ── Main Board / Unassigned Card endpoints ─────────────────────────────────
# These MUST be declared before /cards/{card_id} to avoid path conflicts


class UnassignedCardCreate(BaseModel):
    """Create a card on the Main Board (no project)."""
    title: str
    description: str = ""
    color: str | None = None  # yellow|blue|green|pink|purple|orange
    priority: int = 0


@router.get("/cards/unassigned", response_model=list[CardResponse])
async def list_unassigned_cards(db: AsyncSession = Depends(get_db)):
    """List all cards with no project (Main Board cards)."""
    stmt = (
        select(Card)
        .where(Card.project_id.is_(None))
        .options(selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items))
        .order_by(Card.created_at.desc())
    )
    result = await db.execute(stmt)
    return [_card_to_response(c) for c in result.scalars().all()]


@router.post("/cards/unassigned", response_model=CardResponse, status_code=201)
async def create_unassigned_card(
    body: UnassignedCardCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a card on the Main Board (no project). Internal status defaults to 'card'."""
    card = Card(
        id=new_uuid(),
        project_id=None,
        title=body.title,
        description=body.description,
        status="card",
        priority=body.priority,
        color=body.color,
    )
    db.add(card)
    await db.commit()
    stmt = select(Card).where(Card.id == card.id).options(
        selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items)
    )
    result = await db.execute(stmt)
    card = result.scalar_one()
    return _card_to_response(card)


@router.patch("/cards/{card_id}/assign/{project_id}", response_model=CardResponse)
async def assign_card_to_project(
    card_id: str,
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Move a card to a project (assign project_id). Changes internal status from 'card' to 'idea'."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    old_status = card.status
    card.project_id = project_id
    if card.status == "card":
        card.status = "idea"
    card.updated_at = utcnow()

    if old_status != card.status:
        db.add(CardHistory(id=new_uuid(), card_id=card_id, field_changed="status",
                           old_value=old_status, new_value=card.status, changed_at=utcnow(), changed_by="User"))
    db.add(CardHistory(id=new_uuid(), card_id=card_id, field_changed="project_id",
                       old_value=None, new_value=project_id, changed_at=utcnow(), changed_by="User"))

    await db.commit()
    stmt = select(Card).where(Card.id == card_id).options(
        selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items)
    )
    result = await db.execute(stmt)
    card = result.scalar_one()
    return _card_to_response(card)


@router.patch("/cards/{card_id}/unassign", response_model=CardResponse)
async def unassign_card_from_project(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Detach a card from its project (back to Main Board). Internal status becomes 'card'."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    old_project_id = card.project_id
    old_status = card.status
    card.project_id = None
    card.status = "card"
    card.updated_at = utcnow()

    if old_status != "card":
        db.add(CardHistory(id=new_uuid(), card_id=card_id, field_changed="status",
                           old_value=old_status, new_value="card", changed_at=utcnow(), changed_by="User"))
    db.add(CardHistory(id=new_uuid(), card_id=card_id, field_changed="project_id",
                       old_value=old_project_id, new_value=None, changed_at=utcnow(), changed_by="User"))

    await db.commit()
    stmt = select(Card).where(Card.id == card_id).options(
        selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items)
    )
    result = await db.execute(stmt)
    card = result.scalar_one()
    return _card_to_response(card)


# ── Generic card CRUD (by card_id) ────────────────────────────────────────

@router.get("/cards/{card_id}", response_model=CardResponse)
async def get_card(card_id: str, db: AsyncSession = Depends(get_db)):
    """Get details of a specific card by ID."""
    stmt = select(Card).where(Card.id == card_id).options(
        selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items)
    )
    result = await db.execute(stmt)
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(404, "Card not found")
    return _card_to_response(card)


@router.patch("/cards/{card_id}", response_model=CardResponse)
async def update_card(
    card_id: str,
    body: CardUpdate,
    db: AsyncSession = Depends(get_db),
):
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    update_data = body.model_dump(exclude_unset=True)

    # If agent_type is being updated, also update agent_assigned display
    if "agent_type" in update_data and update_data["agent_type"]:
        persona = get_persona(AgentType(update_data["agent_type"]))
        update_data["agent_assigned"] = f"{persona.emoji} {persona.name}"

    # Track history for meaningful field changes
    TRACKED_FIELDS = {"status", "priority", "title", "description", "assignee", "agent_type"}
    for field in TRACKED_FIELDS:
        if field in update_data:
            old_val = getattr(card, field, None)
            new_val = update_data[field]
            # Only record if value actually changed
            if str(old_val) != str(new_val) and not (old_val is None and new_val is None):
                history_entry = CardHistory(
                    id=new_uuid(),
                    card_id=card_id,
                    field_changed=field,
                    old_value=str(old_val) if old_val is not None else None,
                    new_value=str(new_val) if new_val is not None else None,
                    changed_at=utcnow(),
                    changed_by="User",
                )
                db.add(history_entry)

    for field, value in update_data.items():
        setattr(card, field, value)
    card.updated_at = utcnow()

    await db.commit()
    # Reload with relationships
    stmt = select(Card).where(Card.id == card_id).options(
        selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items)
    )
    result = await db.execute(stmt)
    card = result.scalar_one()
    return _card_to_response(card)


@router.post("/cards/{card_id}/assign", response_model=CardResponse)
async def assign_agent(
    card_id: str,
    body: AgentAssignment,
    db: AsyncSession = Depends(get_db),
):
    """Assign or reassign a card to a specific agent type."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    agent_type = AgentType(body.agent_type)
    persona = get_persona(agent_type)

    card.agent_type = agent_type.value
    card.agent_assigned = f"{persona.emoji} {persona.name}"
    if body.agent_context:
        card.agent_context = body.agent_context
    card.updated_at = utcnow()

    await db.commit()
    # Reload with relationships
    stmt = select(Card).where(Card.id == card_id).options(
        selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items)
    )
    result = await db.execute(stmt)
    card = result.scalar_one()
    return _card_to_response(card)


@router.get("/cards/{card_id}/routing", response_model=dict)
async def get_routing_suggestion(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get agent routing suggestion for a card (without applying it)."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    router_service = get_agent_router()
    details = router_service.route_with_details(
        title=card.title,
        description=card.description,
        context=card.agent_context or "",
    )
    details["current_agent_type"] = card.agent_type
    details["current_agent_assigned"] = card.agent_assigned
    return details


@router.post("/cards/{card_id}/duplicate", response_model=CardResponse, status_code=201)
async def duplicate_card(card_id: str, db: AsyncSession = Depends(get_db)):
    """Duplicate a card: copies all fields except id/created_at. Title gets ' (copy)' appended."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    new_card = Card(
        id=new_uuid(),
        project_id=card.project_id,
        title=f"{card.title} (copy)",
        description=card.description or "",
        status=card.status,
        priority=card.priority,
        position=card.position,
        source_message_id=card.source_message_id,
        auto_generated=card.auto_generated,
        agent_type=card.agent_type,
        agent_assigned=card.agent_assigned,
        agent_context=card.agent_context,
        assignee=card.assignee,
        watchers=card.watchers,
        votes=0,
        recurrence=card.recurrence,
        recurrence_next=card.recurrence_next,
    )

    db.add(new_card)
    await db.commit()

    # Reload with relationships
    stmt = select(Card).where(Card.id == new_card.id).options(
        selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items)
    )
    result = await db.execute(stmt)
    new_card = result.scalar_one()
    return _card_to_response(new_card)


@router.delete("/cards/{card_id}", status_code=204)
async def delete_card(card_id: str, db: AsyncSession = Depends(get_db)):
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    await db.delete(card)
    await db.commit()


@router.post("/cards/{card_id}/clone-to/{target_project_id}", response_model=CardResponse, status_code=201)
async def clone_card_to_project(
    card_id: str,
    target_project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Clone a card to another project. Appends ' (cloned)' to title and creates a cloned_from relation."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    target_project = await db.get(Project, target_project_id)
    if not target_project:
        raise HTTPException(404, "Target project not found")

    if card.project_id == target_project_id:
        raise HTTPException(400, "Card is already in the target project")

    new_card = Card(
        id=new_uuid(),
        project_id=target_project_id,
        title=f"{card.title} (cloned)",
        description=card.description or "",
        status=card.status,
        priority=card.priority,
        position=card.position,
        source_message_id=card.source_message_id,
        auto_generated=card.auto_generated,
        agent_type=card.agent_type,
        agent_assigned=card.agent_assigned,
        agent_context=card.agent_context,
        assignee=card.assignee,
        watchers=card.watchers,
        votes=0,
        recurrence=card.recurrence,
        recurrence_next=card.recurrence_next,
    )

    db.add(new_card)
    await db.flush()  # get new_card.id before adding relation

    # Clone checklist items
    stmt_items = select(ChecklistItem).where(ChecklistItem.card_id == card_id).order_by(ChecklistItem.position)
    items_result = await db.execute(stmt_items)
    for item in items_result.scalars().all():
        new_item = ChecklistItem(
            id=new_uuid(),
            card_id=new_card.id,
            text=item.text,
            completed=False,
            position=item.position,
            created_at=utcnow(),
        )
        db.add(new_item)

    # Create cloned_from relation
    relation = CardRelation(
        id=new_uuid(),
        source_card_id=new_card.id,
        target_card_id=card_id,
        relation_type="cloned_from",
        created_at=utcnow(),
    )
    db.add(relation)

    await db.commit()

    # Reload with relationships
    stmt = select(Card).where(Card.id == new_card.id).options(
        selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items)
    )
    result = await db.execute(stmt)
    new_card = result.scalar_one()
    return _card_to_response(new_card)


@router.post("/cards/{card_id}/move-to/{target_project_id}", response_model=CardResponse)
async def move_card_to_project(
    card_id: str,
    target_project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Move a card to another project. Moves all checklist items, comments, and attachments."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    target_project = await db.get(Project, target_project_id)
    if not target_project:
        raise HTTPException(404, "Target project not found")

    if card.project_id == target_project_id:
        raise HTTPException(400, "Card is already in the target project")

    card.project_id = target_project_id
    card.updated_at = utcnow()

    await db.commit()

    # Reload with relationships
    stmt = select(Card).where(Card.id == card_id).options(
        selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items)
    )
    result = await db.execute(stmt)
    card = result.scalar_one()
    return _card_to_response(card)


# ---------------------------------------------------------------------------
# History / Audit Log endpoint
# ---------------------------------------------------------------------------

class CardHistoryEntry(BaseModel):
    id: str
    card_id: str
    field_changed: str
    old_value: str | None
    new_value: str | None
    changed_at: str
    changed_by: str


@router.get("/cards/{card_id}/history", response_model=list[CardHistoryEntry])
async def get_card_history(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Return card change history, newest first, max 50 entries."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    stmt = (
        select(CardHistory)
        .where(CardHistory.card_id == card_id)
        .order_by(CardHistory.changed_at.desc())
        .limit(50)
    )
    result = await db.execute(stmt)
    entries = result.scalars().all()
    return [
        CardHistoryEntry(
            id=e.id,
            card_id=e.card_id,
            field_changed=e.field_changed,
            old_value=e.old_value,
            new_value=e.new_value,
            changed_at=e.changed_at.isoformat(),
            changed_by=e.changed_by,
        )
        for e in entries
    ]


# ---------------------------------------------------------------------------
# Vote endpoints
# ---------------------------------------------------------------------------

@router.post("/cards/{card_id}/vote", response_model=dict)
async def vote_card(card_id: str, db: AsyncSession = Depends(get_db)):
    """Increment vote count on a card. Returns {"votes": <new_count>}."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    card.votes = (card.votes or 0) + 1
    card.updated_at = utcnow()
    await db.commit()
    return {"votes": card.votes}


@router.delete("/cards/{card_id}/vote", response_model=dict)
async def unvote_card(card_id: str, db: AsyncSession = Depends(get_db)):
    """Decrement vote count on a card (min 0). Returns {"votes": <new_count>}."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    card.votes = max(0, (card.votes or 0) - 1)
    card.updated_at = utcnow()
    await db.commit()
    return {"votes": card.votes}


def _card_to_response(card: Card) -> CardResponse:
    """Convert ORM Card to response, extracting dependency IDs, summing time, and computing checklist progress."""
    total_minutes = sum(e.duration_minutes for e in card.time_entries) if card.time_entries else 0
    checklist_total = len(card.checklist_items) if card.checklist_items else 0
    checklist_completed = sum(1 for i in card.checklist_items if i.completed) if card.checklist_items else 0
    checklist_progress = ChecklistProgress(total=checklist_total, completed=checklist_completed) if checklist_total > 0 else None
    return CardResponse(
        id=card.id,
        project_id=card.project_id,
        title=card.title,
        description=card.description,
        status=card.status,
        priority=card.priority,
        position=card.position,
        source_message_id=card.source_message_id,
        auto_generated=card.auto_generated,
        agent_assigned=card.agent_assigned,
        agent_type=card.agent_type,
        agent_context=card.agent_context,
        color=card.color,
        created_at=card.created_at,
        updated_at=card.updated_at,
        dependency_ids=[d.id for d in card.dependencies] if card.dependencies else [],
        total_minutes=total_minutes,
        checklist_progress=checklist_progress,
        assignee=card.assignee,
        watchers=card.watchers or "",
        votes=card.votes or 0,
        recurrence=card.recurrence,
        recurrence_next=card.recurrence_next,
    )


# ---------------------------------------------------------------------------
# Time tracking endpoints
# ---------------------------------------------------------------------------

@router.post("/cards/{card_id}/time", response_model=TimeEntryResponse, status_code=201)
async def log_time(
    card_id: str,
    body: TimeEntryCreate,
    db: AsyncSession = Depends(get_db),
):
    """Log time spent on a card."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    entry = TimeEntry(
        id=new_uuid(),
        card_id=card_id,
        duration_minutes=body.duration_minutes,
        note=body.note,
        logged_at=utcnow(),
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return entry


@router.get("/cards/{card_id}/time", response_model=list[TimeEntryResponse])
async def list_time_entries(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all time entries for a card, newest first."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    stmt = select(TimeEntry).where(TimeEntry.card_id == card_id).order_by(TimeEntry.logged_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.delete("/cards/{card_id}/time/{entry_id}", status_code=204)
async def delete_time_entry(
    card_id: str,
    entry_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a specific time entry."""
    stmt = select(TimeEntry).where(TimeEntry.id == entry_id, TimeEntry.card_id == card_id)
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Time entry not found")
    await db.delete(entry)
    await db.commit()


# ---------------------------------------------------------------------------
# Comments endpoints
# ---------------------------------------------------------------------------

@router.post("/cards/{card_id}/comments", response_model=CommentResponse, status_code=201)
async def add_comment(
    card_id: str,
    body: CommentCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a comment to a card."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    comment = CardComment(
        id=new_uuid(),
        card_id=card_id,
        author=body.author,
        content=body.content,
        created_at=utcnow(),
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return comment


@router.get("/cards/{card_id}/comments", response_model=list[CommentResponse])
async def list_comments(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all comments for a card, newest first."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    stmt = select(CardComment).where(CardComment.card_id == card_id).order_by(CardComment.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().all()


@router.delete("/cards/{card_id}/comments/{comment_id}", status_code=204)
async def delete_comment(
    card_id: str,
    comment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a specific comment."""
    stmt = select(CardComment).where(CardComment.id == comment_id, CardComment.card_id == card_id)
    result = await db.execute(stmt)
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(404, "Comment not found")
    await db.delete(comment)
    await db.commit()


# ---------------------------------------------------------------------------
# Checklist endpoints
# ---------------------------------------------------------------------------

@router.post("/cards/{card_id}/checklist", response_model=ChecklistItemResponse, status_code=201)
async def add_checklist_item(
    card_id: str,
    body: ChecklistItemCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a checklist item to a card."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    # Determine next position
    stmt = select(func.max(ChecklistItem.position)).where(ChecklistItem.card_id == card_id)
    result = await db.execute(stmt)
    max_pos = result.scalar() or -1

    item = ChecklistItem(
        id=new_uuid(),
        card_id=card_id,
        text=body.text,
        completed=False,
        position=max_pos + 1,
        created_at=utcnow(),
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


@router.get("/cards/{card_id}/checklist", response_model=list[ChecklistItemResponse])
async def list_checklist_items(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all checklist items for a card, ordered by position."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    stmt = select(ChecklistItem).where(ChecklistItem.card_id == card_id).order_by(ChecklistItem.position)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.patch("/cards/{card_id}/checklist/{item_id}", response_model=ChecklistItemResponse)
async def update_checklist_item(
    card_id: str,
    item_id: str,
    body: ChecklistItemUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a checklist item (toggle completed or edit text)."""
    stmt = select(ChecklistItem).where(ChecklistItem.id == item_id, ChecklistItem.card_id == card_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Checklist item not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)

    await db.commit()
    await db.refresh(item)
    return item


@router.delete("/cards/{card_id}/checklist/{item_id}", status_code=204)
async def delete_checklist_item(
    card_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a checklist item."""
    stmt = select(ChecklistItem).where(ChecklistItem.id == item_id, ChecklistItem.card_id == card_id)
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "Checklist item not found")
    await db.delete(item)
    await db.commit()


# ---------------------------------------------------------------------------
# Attachment endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/cards/{card_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file attachment to a card",
)
async def upload_attachment(
    card_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file and attach it to a card. Max 50 MB, any type accepted."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    filename = file.filename or "attachment"

    # Read and size-check
    content = await file.read()
    file_size = len(content)
    if file_size > MAX_ATTACHMENT_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large ({file_size} bytes). Maximum allowed is {MAX_ATTACHMENT_SIZE} bytes (50 MB).",
        )

    # Determine MIME type
    mime_type = file.content_type or "application/octet-stream"
    if not mime_type or mime_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(filename)
        mime_type = guessed or "application/octet-stream"

    # Build storage path: ~/.voxyflow/attachments/{card_id}/{uuid}_{filename}
    att_id = new_uuid()
    safe_filename = Path(filename).name  # strip any directory components
    storage_filename = f"{att_id}_{safe_filename}"
    storage_dir = ATTACHMENTS_BASE / card_id
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / storage_filename

    storage_path.write_bytes(content)

    attachment = CardAttachment(
        id=att_id,
        card_id=card_id,
        filename=filename,
        file_size=file_size,
        mime_type=mime_type,
        storage_path=str(storage_path),
        created_at=utcnow(),
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    logger.info(f"upload_attachment: card_id={card_id!r} filename={filename!r} size={file_size}")
    return AttachmentResponse.model_validate(attachment)


@router.get(
    "/cards/{card_id}/attachments",
    response_model=list[AttachmentResponse],
    summary="List attachments for a card",
)
async def list_attachments(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all attachments for a card."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    stmt = (
        select(CardAttachment)
        .where(CardAttachment.card_id == card_id)
        .order_by(CardAttachment.created_at.desc())
    )
    result = await db.execute(stmt)
    attachments = result.scalars().all()
    return [AttachmentResponse.model_validate(a) for a in attachments]


@router.get(
    "/cards/{card_id}/attachments/{attachment_id}/download",
    summary="Download a card attachment",
)
async def download_attachment(
    card_id: str,
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Download a card attachment file."""
    stmt = select(CardAttachment).where(
        CardAttachment.id == attachment_id,
        CardAttachment.card_id == card_id,
    )
    result = await db.execute(stmt)
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(404, "Attachment not found")

    storage_path = Path(attachment.storage_path)
    if not storage_path.exists():
        raise HTTPException(404, "Attachment file not found on disk")

    return FileResponse(
        path=str(storage_path),
        media_type=attachment.mime_type,
        filename=attachment.filename,
    )


@router.delete(
    "/cards/{card_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a card attachment",
)
async def delete_attachment(
    card_id: str,
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a card attachment (removes file and DB record)."""
    stmt = select(CardAttachment).where(
        CardAttachment.id == attachment_id,
        CardAttachment.card_id == card_id,
    )
    result = await db.execute(stmt)
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(404, "Attachment not found")

    # Remove file from disk (non-fatal if missing)
    storage_path = Path(attachment.storage_path)
    if storage_path.exists():
        try:
            storage_path.unlink()
        except OSError as e:
            logger.warning(f"delete_attachment: could not remove file {storage_path}: {e}")

    await db.delete(attachment)
    await db.commit()
    logger.info(f"delete_attachment: deleted attachment_id={attachment_id!r} card_id={card_id!r}")


# ---------------------------------------------------------------------------
# AI Card Enrichment endpoint
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Card Relations endpoints
# ---------------------------------------------------------------------------

VALID_RELATION_TYPES = {"duplicates", "blocks", "is_blocked_by", "relates_to", "cloned_from"}


class RelationCreate(BaseModel):
    target_card_id: str
    relation_type: str  # duplicates|blocks|is_blocked_by|relates_to|cloned_from


class RelationResponse(BaseModel):
    id: str
    source_card_id: str
    target_card_id: str
    relation_type: str
    created_at: str
    related_card_id: str
    related_card_title: str
    related_card_status: str


@router.post("/cards/{card_id}/relations", response_model=RelationResponse, status_code=201)
async def add_relation(
    card_id: str,
    body: RelationCreate,
    db: AsyncSession = Depends(get_db),
):
    """Add a typed relation from this card to another card."""
    if body.relation_type not in VALID_RELATION_TYPES:
        raise HTTPException(400, f"Invalid relation_type. Must be one of: {', '.join(VALID_RELATION_TYPES)}")

    source_card = await db.get(Card, card_id)
    if not source_card:
        raise HTTPException(404, "Source card not found")

    target_card = await db.get(Card, body.target_card_id)
    if not target_card:
        raise HTTPException(404, "Target card not found")

    if card_id == body.target_card_id:
        raise HTTPException(400, "A card cannot relate to itself")

    # Prevent duplicate relations of the same type
    stmt = select(CardRelation).where(
        CardRelation.source_card_id == card_id,
        CardRelation.target_card_id == body.target_card_id,
        CardRelation.relation_type == body.relation_type,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "This relation already exists")

    relation = CardRelation(
        id=new_uuid(),
        source_card_id=card_id,
        target_card_id=body.target_card_id,
        relation_type=body.relation_type,
        created_at=utcnow(),
    )
    db.add(relation)
    await db.commit()
    await db.refresh(relation)

    return RelationResponse(
        id=relation.id,
        source_card_id=relation.source_card_id,
        target_card_id=relation.target_card_id,
        relation_type=relation.relation_type,
        created_at=relation.created_at.isoformat(),
        related_card_id=target_card.id,
        related_card_title=target_card.title,
        related_card_status=target_card.status,
    )


@router.get("/cards/{card_id}/relations", response_model=list[RelationResponse])
async def list_relations(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all relations for a card (both as source and as target)."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    # Relations where this card is source
    stmt_src = select(CardRelation).where(CardRelation.source_card_id == card_id)
    src_results = (await db.execute(stmt_src)).scalars().all()

    # Relations where this card is target
    stmt_tgt = select(CardRelation).where(CardRelation.target_card_id == card_id)
    tgt_results = (await db.execute(stmt_tgt)).scalars().all()

    all_relations = []

    for rel in src_results:
        related = await db.get(Card, rel.target_card_id)
        if related:
            all_relations.append(RelationResponse(
                id=rel.id,
                source_card_id=rel.source_card_id,
                target_card_id=rel.target_card_id,
                relation_type=rel.relation_type,
                created_at=rel.created_at.isoformat(),
                related_card_id=related.id,
                related_card_title=related.title,
                related_card_status=related.status,
            ))

    for rel in tgt_results:
        related = await db.get(Card, rel.source_card_id)
        if related:
            # Invert display: from the perspective of this card (target)
            # e.g. if source "blocks" target → target sees "is_blocked_by" source
            display_type = _invert_relation_type(rel.relation_type)
            all_relations.append(RelationResponse(
                id=rel.id,
                source_card_id=rel.source_card_id,
                target_card_id=rel.target_card_id,
                relation_type=display_type,
                created_at=rel.created_at.isoformat(),
                related_card_id=related.id,
                related_card_title=related.title,
                related_card_status=related.status,
            ))

    return all_relations


def _invert_relation_type(relation_type: str) -> str:
    """Return the inverse relation type from the perspective of the target card."""
    inversions = {
        "blocks": "is_blocked_by",
        "is_blocked_by": "blocks",
        "duplicates": "duplicated_by",
        "cloned_from": "cloned_to",
    }
    return inversions.get(relation_type, relation_type)


@router.delete("/cards/{card_id}/relations/{relation_id}", status_code=204)
async def delete_relation(
    card_id: str,
    relation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a relation. Card must be either source or target."""
    stmt = select(CardRelation).where(CardRelation.id == relation_id)
    relation = (await db.execute(stmt)).scalar_one_or_none()
    if not relation:
        raise HTTPException(404, "Relation not found")
    # Verify card_id is involved
    if relation.source_card_id != card_id and relation.target_card_id != card_id:
        raise HTTPException(403, "Card is not part of this relation")
    await db.delete(relation)
    await db.commit()


class EnrichResponse(BaseModel):
    description: str
    checklist_items: list[str]
    effort: str
    tags: list[str]


@router.post("/cards/{card_id}/enrich", response_model=EnrichResponse)
async def enrich_card(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    AI enrichment: given just a card title, generate a description,
    checklist items, effort estimate, and tags using the fast model.
    """
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")

    from app.services.claude_service import ClaudeService
    claude = ClaudeService()

    agent_type = card.agent_type or "ember"
    title = card.title
    existing_desc = (card.description or "").strip()

    prompt = (
        f"Given a task card titled '{title}' for a {agent_type} agent"
        + (f" (existing context: {existing_desc})" if existing_desc else "")
        + ", generate the following in valid JSON only (no markdown, no code block):\n"
        '{\n'
        '  "description": "2-3 sentence clear description of what this task involves",\n'
        '  "checklist_items": ["step 1", "step 2", "step 3"],\n'
        '  "effort": "XS|S|M|L|XL",\n'
        '  "tags": ["tag1", "tag2"]\n'
        '}\n'
        "Rules:\n"
        "- description: 2-3 sentences, actionable and specific\n"
        "- checklist_items: 3-5 concrete sub-tasks\n"
        "- effort: one of XS/S/M/L/XL based on complexity\n"
        "- tags: 2-4 short relevant tags (lowercase, no spaces, use hyphens)\n"
        "Respond ONLY with the JSON object."
    )

    try:
        raw = await claude._call_api(
            model=claude.fast_model,
            system="You are a project assistant. Generate structured task enrichment data. Respond with valid JSON only.",
            messages=[{"role": "user", "content": prompt}],
            client=claude.fast_client,
        )

        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        data = json.loads(text)

        return EnrichResponse(
            description=str(data.get("description", "")),
            checklist_items=[str(i) for i in data.get("checklist_items", [])],
            effort=str(data.get("effort", "M")),
            tags=[str(t) for t in data.get("tags", [])],
        )
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"enrich_card: parse error for card_id={card_id!r}: {e}")
        raise HTTPException(500, f"Enrichment failed: could not parse AI response")
    except httpx.HTTPError as e:
        logger.error(f"enrich_card: HTTP error for card_id={card_id!r}: {e}")
        raise HTTPException(502, f"Enrichment failed: upstream API error")
    except httpx.TimeoutException as e:
        logger.error(f"enrich_card: timeout for card_id={card_id!r}: {e}")
        raise HTTPException(504, f"Enrichment failed: upstream timeout")

