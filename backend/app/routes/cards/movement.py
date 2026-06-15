"""Card movement endpoints: clone-to / move-to another workspace."""

from fastapi import APIRouter, Depends, HTTPException
from app.services.ws_broadcast import ws_broadcast
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Card, CardRelation, Workspace, ChecklistItem, new_uuid, utcnow
from app.models.card import CardResponse

from .serializers import _broadcast_card_change, _card_to_response

router = APIRouter()


@router.post("/cards/{card_id}/clone-to/{target_workspace_id}", response_model=CardResponse, status_code=201)
async def clone_card_to_project(
    card_id: str,
    target_workspace_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Clone a card to another workspace. Appends ' (cloned)' to title and creates a cloned_from relation."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")

    target_project = await db.get(Workspace, target_workspace_id)
    if not target_project:
        raise HTTPException(404, "Target workspace not found.")

    if card.workspace_id == target_workspace_id:
        raise HTTPException(400, "Card is already in the target workspace.")

    new_card = Card(
        id=new_uuid(),
        workspace_id=target_workspace_id,
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
        recurring=card.recurring or False,
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
    await db.refresh(new_card, ['time_entries', 'dependencies', 'checklist_items'])
    _broadcast_card_change(new_card)
    return _card_to_response(new_card)


@router.post("/cards/{card_id}/move-to/{target_workspace_id}", response_model=CardResponse)
async def move_card_to_project(
    card_id: str,
    target_workspace_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Move a card to another workspace. Moves all checklist items, comments, and attachments."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")

    target_project = await db.get(Workspace, target_workspace_id)
    if not target_project:
        raise HTTPException(404, "Target workspace not found.")

    if card.workspace_id == target_workspace_id:
        raise HTTPException(400, "Card is already in the target workspace.")

    old_workspace_id = card.workspace_id or 'system-main'
    card.workspace_id = target_workspace_id
    card.updated_at = utcnow()

    await db.commit()
    await db.refresh(card, ['time_entries', 'dependencies', 'checklist_items'])
    _broadcast_card_change(card)
    # Also refresh the source board the card left, or it shows the card as stale.
    if old_workspace_id != target_workspace_id:
        ws_broadcast.emit_sync("cards:changed", {"workspaceId": old_workspace_id, "cardId": card_id})
    return _card_to_response(card)
