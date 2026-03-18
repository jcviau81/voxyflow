"""Card/Task endpoints — with agent assignment support."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Card, Project, TimeEntry, CardComment, ChecklistItem, new_uuid, utcnow
from app.models.card import (
    CardCreate, CardUpdate, CardResponse, AgentAssignment,
    TimeEntryCreate, TimeEntryResponse,
    CommentCreate, CommentResponse,
    ChecklistItemCreate, ChecklistItemUpdate, ChecklistItemResponse, ChecklistProgress,
)
from app.services.agent_router import get_agent_router
from app.services.agent_personas import AgentType, get_persona, get_all_personas

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


@router.delete("/cards/{card_id}", status_code=204)
async def delete_card(card_id: str, db: AsyncSession = Depends(get_db)):
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    await db.delete(card)
    await db.commit()


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
        created_at=card.created_at,
        updated_at=card.updated_at,
        dependency_ids=[d.id for d in card.dependencies] if card.dependencies else [],
        total_minutes=total_minutes,
        checklist_progress=checklist_progress,
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
