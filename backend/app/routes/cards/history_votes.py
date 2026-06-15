"""Card history (audit log) and vote endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Card, CardHistory, utcnow

router = APIRouter()


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
        raise HTTPException(404, "Card not found.")

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
    """Increment vote count on a card. Returns {"votes": <new_count>}.

    Atomic: a single UPDATE ... RETURNING avoids the read-modify-write race
    where two concurrent taps both read N and both write N+1.
    """
    stmt = (
        update(Card)
        .where(Card.id == card_id)
        .values(votes=func.coalesce(Card.votes, 0) + 1, updated_at=utcnow())
        .returning(Card.votes)
    )
    result = await db.execute(stmt)
    row = result.first()
    if row is None:
        raise HTTPException(404, "Card not found.")
    await db.commit()
    return {"votes": row[0]}


@router.delete("/cards/{card_id}/vote", response_model=dict)
async def unvote_card(card_id: str, db: AsyncSession = Depends(get_db)):
    """Decrement vote count on a card (min 0). Returns {"votes": <new_count>}."""
    from sqlalchemy import case
    current = func.coalesce(Card.votes, 0)
    stmt = (
        update(Card)
        .where(Card.id == card_id)
        .values(
            votes=case((current > 0, current - 1), else_=0),
            updated_at=utcnow(),
        )
        .returning(Card.votes)
    )
    result = await db.execute(stmt)
    row = result.first()
    if row is None:
        raise HTTPException(404, "Card not found.")
    await db.commit()
    return {"votes": row[0]}
