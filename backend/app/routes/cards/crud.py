"""Card CRUD endpoints: agents listing, create/list, Main Board aliases,
bulk reorder, workspace assignment, get/update, delete, archive/restore.

Split across two routers so the package ``__init__`` can reproduce the
original registration order exactly (the execution routes were declared
between PATCH /cards/{card_id} and DELETE /cards/{card_id}).
"""

import asyncio
import logging
import shutil

from fastapi import APIRouter, Depends, Header, HTTPException
from app.services.ws_broadcast import ws_broadcast
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Card, CardHistory, Workspace, new_uuid, utcnow, SYSTEM_MAIN_WORKSPACE_ID
from app.models.card import CardCreate, CardUpdate, CardResponse, BulkReorderRequest
from app.services.agent_router import get_agent_router
from app.services.agent_personas import AgentType, get_persona, get_all_personas
from app.services import turn_card_registry

from .serializers import ATTACHMENTS_BASE, _broadcast_card_change, _card_to_response

logger = logging.getLogger(__name__)

router = APIRouter()

# Routes declared after the execution group in the original module
# (DELETE /cards/{card_id}, archive/restore, archived list).
archive_router = APIRouter()


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


@router.post("/workspaces/{workspace_id}/cards", response_model=CardResponse, status_code=201)
async def create_card(
    workspace_id: str,
    body: CardCreate,
    db: AsyncSession = Depends(get_db),
    x_voxyflow_chat_id: str | None = Header(default=None),
):
    # Verify workspace exists
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

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
        workspace_id=workspace_id,
        title=body.title,
        description=body.description or "",
        status=body.status,
        priority=body.priority,
        source_message_id=body.source_message_id,
        auto_generated=body.auto_generated,
        agent_type=agent_type,
        agent_assigned=agent_display,
        agent_context=body.agent_context,
        recurring=body.recurring,
        recurrence=body.recurrence,
        recurrence_next=body.recurrence_next,
    )

    # Resolve dependencies
    if body.dependency_ids:
        for dep_id in body.dependency_ids:
            dep = await db.get(Card, dep_id)
            if dep and dep.workspace_id == workspace_id:
                card.dependencies.append(dep)

    db.add(card)
    await db.commit()
    await db.refresh(card, ['time_entries', 'dependencies', 'checklist_items'])

    _broadcast_card_change(card)
    if x_voxyflow_chat_id:
        turn_card_registry.record_created_card(x_voxyflow_chat_id, card.id)
    return _card_to_response(card)


@router.get("/workspaces/{workspace_id}/cards", response_model=list[CardResponse])
async def list_cards(
    workspace_id: str,
    status: str | None = None,
    agent_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Card)
        .where(Card.workspace_id == workspace_id, Card.archived_at.is_(None))
        .options(selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items))
        .order_by(Card.position)
    )
    if status:
        stmt = stmt.where(Card.status == status)
    if agent_type:
        stmt = stmt.where(Card.agent_type == agent_type)
    result = await db.execute(stmt)
    return [_card_to_response(c) for c in result.scalars().all()]


# ── Main Board / Unassigned Card endpoints (backward-compatible aliases) ────
# These now proxy to the system "Main" workspace (system-main).
# MUST be declared before /cards/{card_id} to avoid path conflicts.


class UnassignedCardCreate(BaseModel):
    """Create a card on the Main Board (system workspace)."""
    title: str
    description: str = ""
    color: str | None = None  # yellow|blue|green|pink|purple|orange
    priority: int = 0


@router.get("/cards/unassigned", response_model=list[CardResponse])
async def list_unassigned_cards(db: AsyncSession = Depends(get_db)):
    """List all cards on the Main Board (alias for system-main workspace cards)."""
    stmt = (
        select(Card)
        .where(Card.workspace_id == SYSTEM_MAIN_WORKSPACE_ID, Card.archived_at.is_(None))
        .options(selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items))
        .order_by(Card.created_at.desc())
    )
    result = await db.execute(stmt)
    return [_card_to_response(c) for c in result.scalars().all()]


@router.post("/cards/unassigned", response_model=CardResponse, status_code=201)
async def create_unassigned_card(
    body: UnassignedCardCreate,
    db: AsyncSession = Depends(get_db),
    x_voxyflow_chat_id: str | None = Header(default=None),
):
    """Create a card on the Main Board (alias — creates in system-main workspace)."""
    card = Card(
        id=new_uuid(),
        workspace_id=SYSTEM_MAIN_WORKSPACE_ID,
        title=body.title,
        description=body.description,
        status="backlog",
        priority=body.priority,
        color=body.color,
    )
    db.add(card)
    await db.commit()
    await db.refresh(card, ['time_entries', 'dependencies', 'checklist_items'])
    _broadcast_card_change(card)
    if x_voxyflow_chat_id:
        turn_card_registry.record_created_card(x_voxyflow_chat_id, card.id)
    return _card_to_response(card)


@router.post("/cards/bulk-reorder", status_code=204)
async def bulk_reorder_cards(
    body: BulkReorderRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reorder cards in bulk. Sets each card's position to its index in ordered_ids.

    Missing IDs are skipped silently. Emits one cards:changed broadcast per
    affected workspace at the end.
    """
    affected_workspace_ids: set[str] = set()
    # Prefetch workspace_ids in one query instead of a per-card SELECT (N+1).
    workspace_by_card: dict[str, str | None] = {}
    if body.ordered_ids:
        rows = (
            await db.execute(
                select(Card.id, Card.workspace_id).where(Card.id.in_(body.ordered_ids))
            )
        ).all()
        workspace_by_card = {cid: wsid for cid, wsid in rows}

    for idx, cid in enumerate(body.ordered_ids):
        if cid not in workspace_by_card:
            continue
        await db.execute(
            update(Card).where(Card.id == cid).values(position=idx, updated_at=utcnow())
        )
        affected_workspace_ids.add(workspace_by_card[cid] or 'system-main')

    await db.commit()

    for workspace_id in affected_workspace_ids:
        ws_broadcast.emit_sync("cards:changed", {"workspaceId": workspace_id, "cardId": None})


@router.patch("/cards/{card_id}/assign/{workspace_id}", response_model=CardResponse)
async def assign_card_to_project(
    card_id: str,
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Move a card to a workspace (assign workspace_id)."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    old_workspace_id = card.workspace_id or 'system-main'
    card.workspace_id = workspace_id
    card.updated_at = utcnow()

    db.add(CardHistory(id=new_uuid(), card_id=card_id, field_changed="workspace_id",
                       old_value=None, new_value=workspace_id, changed_at=utcnow(), changed_by="User"))

    await db.commit()
    await db.refresh(card, ['time_entries', 'dependencies', 'checklist_items'])
    _broadcast_card_change(card)
    # Also refresh the source board the card left, or it shows the card as stale.
    if old_workspace_id != workspace_id:
        ws_broadcast.emit_sync("cards:changed", {"workspaceId": old_workspace_id, "cardId": card_id})
    return _card_to_response(card)


@router.patch("/cards/{card_id}/unassign", response_model=CardResponse)
async def unassign_card_from_project(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Detach a card from its workspace (back to Main Board / system-main). Internal status becomes 'backlog'."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")

    old_workspace_id = card.workspace_id
    old_status = card.status
    card.workspace_id = SYSTEM_MAIN_WORKSPACE_ID
    card.status = "backlog"
    card.updated_at = utcnow()

    if old_status != "backlog":
        db.add(CardHistory(id=new_uuid(), card_id=card_id, field_changed="status",
                           old_value=old_status, new_value="backlog", changed_at=utcnow(), changed_by="User"))
    db.add(CardHistory(id=new_uuid(), card_id=card_id, field_changed="workspace_id",
                       old_value=old_workspace_id, new_value=SYSTEM_MAIN_WORKSPACE_ID, changed_at=utcnow(), changed_by="User"))

    await db.commit()
    await db.refresh(card, ['time_entries', 'dependencies', 'checklist_items'])
    _broadcast_card_change(card)
    # Also refresh the source board the card left, or it shows the card as stale.
    if old_workspace_id and old_workspace_id != SYSTEM_MAIN_WORKSPACE_ID:
        ws_broadcast.emit_sync("cards:changed", {"workspaceId": old_workspace_id, "cardId": card_id})
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
        raise HTTPException(404, "Card not found.")
    return _card_to_response(card)


@router.patch("/cards/{card_id}", response_model=CardResponse)
async def update_card(
    card_id: str,
    body: CardUpdate,
    db: AsyncSession = Depends(get_db),
):
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")

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
    await db.refresh(card, ['time_entries', 'dependencies', 'checklist_items'])
    _broadcast_card_change(card)
    return _card_to_response(card)


@archive_router.delete("/cards/{card_id}", status_code=204)
async def delete_card(card_id: str, force: bool = False, db: AsyncSession = Depends(get_db)):
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")
    if not card.archived_at and not force:
        raise HTTPException(
            400,
            "Cannot delete a card that is not archived. "
            "Archive it first (POST /api/cards/{card_id}/archive), "
            "then delete from archives.",
        )
    workspace_id = card.workspace_id or 'system-main'
    await db.delete(card)
    await db.commit()
    # CardAttachment rows cascade with the card — also remove their files on
    # disk, mirroring delete_attachment (best-effort, off the event loop).
    await asyncio.to_thread(shutil.rmtree, ATTACHMENTS_BASE / card_id, ignore_errors=True)
    ws_broadcast.emit_sync("cards:changed", {"workspaceId": workspace_id, "cardId": card_id})


@archive_router.post("/cards/{card_id}/archive", response_model=CardResponse)
async def archive_card(card_id: str, db: AsyncSession = Depends(get_db)):
    """Archive a card (soft-delete). Sets archived_at timestamp."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")
    if card.archived_at:
        raise HTTPException(400, "Card is already archived.")

    old_status = card.status
    card.archived_at = utcnow()
    card.updated_at = utcnow()

    db.add(CardHistory(
        id=new_uuid(), card_id=card_id, field_changed="archived_at",
        old_value=None, new_value=str(card.archived_at),
        changed_at=utcnow(), changed_by="User",
    ))

    await db.commit()
    await db.refresh(card, ['time_entries', 'dependencies', 'checklist_items'])
    _broadcast_card_change(card)
    return _card_to_response(card)


@archive_router.post("/cards/{card_id}/restore", response_model=CardResponse)
async def restore_card(card_id: str, db: AsyncSession = Depends(get_db)):
    """Restore an archived card back to active."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")
    if not card.archived_at:
        raise HTTPException(400, "Card is not archived.")

    old_archived = str(card.archived_at)
    card.archived_at = None
    card.updated_at = utcnow()

    db.add(CardHistory(
        id=new_uuid(), card_id=card_id, field_changed="archived_at",
        old_value=old_archived, new_value=None,
        changed_at=utcnow(), changed_by="User",
    ))

    await db.commit()
    await db.refresh(card, ['time_entries', 'dependencies', 'checklist_items'])
    _broadcast_card_change(card)
    return _card_to_response(card)


@archive_router.get("/workspaces/{workspace_id}/cards/archived", response_model=list[CardResponse])
async def list_archived_cards(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """List archived cards for a workspace."""
    stmt = (
        select(Card)
        .where(Card.workspace_id == workspace_id, Card.archived_at.isnot(None))
        .options(selectinload(Card.time_entries), selectinload(Card.dependencies), selectinload(Card.checklist_items))
        .order_by(Card.archived_at.desc())
    )
    result = await db.execute(stmt)
    return [_card_to_response(c) for c in result.scalars().all()]
