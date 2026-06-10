"""Card time tracking and checklist endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Card, TimeEntry, ChecklistItem, new_uuid, utcnow
from app.models.card import (
    TimeEntryCreate, TimeEntryResponse,
    ChecklistItemCreate, ChecklistItemUpdate, ChecklistItemResponse,
)

from .serializers import _broadcast_card_change

router = APIRouter()


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
        raise HTTPException(404, "Card not found.")

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
        raise HTTPException(404, "Card not found.")

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
        raise HTTPException(404, "Time entry not found.")
    await db.delete(entry)
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
        raise HTTPException(404, "Card not found.")

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
    _broadcast_card_change(card)
    return item


@router.get("/cards/{card_id}/checklist", response_model=list[ChecklistItemResponse])
async def list_checklist_items(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all checklist items for a card, ordered by position."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")

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
        raise HTTPException(404, "Checklist item not found.")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)

    await db.commit()
    await db.refresh(item)
    card = await db.get(Card, card_id)
    if card:
        _broadcast_card_change(card)
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
        raise HTTPException(404, "Checklist item not found.")
    await db.delete(item)
    await db.commit()
    card = await db.get(Card, card_id)
    if card:
        _broadcast_card_change(card)


@router.post("/cards/{card_id}/checklist/bulk", response_model=list[ChecklistItemResponse], status_code=201)
async def add_checklist_items_bulk(
    card_id: str,
    body: list[ChecklistItemCreate],
    db: AsyncSession = Depends(get_db),
):
    """Add multiple checklist items to a card in one call."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")

    stmt = select(func.max(ChecklistItem.position)).where(ChecklistItem.card_id == card_id)
    result = await db.execute(stmt)
    max_pos = result.scalar() or -1

    items = []
    for i, entry in enumerate(body):
        item = ChecklistItem(
            id=new_uuid(),
            card_id=card_id,
            text=entry.text,
            completed=False,
            position=max_pos + 1 + i,
            created_at=utcnow(),
        )
        db.add(item)
        items.append(item)

    await db.commit()
    for item in items:
        await db.refresh(item)
    _broadcast_card_change(card)
    return items
