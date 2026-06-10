"""Card relations endpoints (typed card-to-card links)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Card, CardRelation, new_uuid, utcnow

router = APIRouter()


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
        raise HTTPException(404, "Source card not found.")

    target_card = await db.get(Card, body.target_card_id)
    if not target_card:
        raise HTTPException(404, "Target card not found.")

    if card_id == body.target_card_id:
        raise HTTPException(400, "A card cannot relate to itself.")

    # Prevent duplicate relations of the same type
    stmt = select(CardRelation).where(
        CardRelation.source_card_id == card_id,
        CardRelation.target_card_id == body.target_card_id,
        CardRelation.relation_type == body.relation_type,
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "This relation already exists.")

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
        raise HTTPException(404, "Card not found.")

    # Relations where this card is source
    stmt_src = select(CardRelation).where(CardRelation.source_card_id == card_id)
    src_results = (await db.execute(stmt_src)).scalars().all()

    # Relations where this card is target
    stmt_tgt = select(CardRelation).where(CardRelation.target_card_id == card_id)
    tgt_results = (await db.execute(stmt_tgt)).scalars().all()

    all_relations = []

    # Batch-fetch related cards to avoid N+1 db.get calls.
    related_ids = {rel.target_card_id for rel in src_results}
    related_ids |= {rel.source_card_id for rel in tgt_results}
    related_by_id: dict[str, Card] = {}
    if related_ids:
        related_cards = (
            await db.execute(select(Card).where(Card.id.in_(related_ids)))
        ).scalars().all()
        related_by_id = {c.id: c for c in related_cards}

    for rel in src_results:
        related = related_by_id.get(rel.target_card_id)
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
        related = related_by_id.get(rel.source_card_id)
        if related:
            # Invert display: from the perspective of this card (target)
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
    stmt = select(CardRelation).where(CardRelation.id == relation_id)
    relation = (await db.execute(stmt)).scalar_one_or_none()
    if not relation:
        raise HTTPException(404, "Relation not found.")
    if relation.source_card_id != card_id and relation.target_card_id != card_id:
        raise HTTPException(403, "Card is not part of this relation.")
    await db.delete(relation)
    await db.commit()
