"""Card execution / agent endpoints: agent assignment, routing suggestion,
duplication, card execution prompt, board plan execution, AI enrichment.

``enrich_router`` is separate because enrich_card was declared after the
relations endpoints in the original module — the package ``__init__``
includes it at that exact position.
"""

import json
import logging

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Card, Workspace, new_uuid, utcnow
from app.models.card import CardResponse, AgentAssignment
from app.services.agent_router import get_agent_router
from app.services.agent_personas import AgentType, get_persona
from app.services import turn_card_registry

from .serializers import _broadcast_card_change, _card_to_response

logger = logging.getLogger(__name__)

router = APIRouter()

# Declared after the relations endpoints in the original module.
enrich_router = APIRouter()


@router.post("/cards/{card_id}/assign", response_model=CardResponse)
async def assign_agent(
    card_id: str,
    body: AgentAssignment,
    db: AsyncSession = Depends(get_db),
):
    """Assign or reassign a card to a specific agent type."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")

    agent_type = AgentType(body.agent_type)
    persona = get_persona(agent_type)

    card.agent_type = agent_type.value
    card.agent_assigned = f"{persona.emoji} {persona.name}"
    if body.agent_context:
        card.agent_context = body.agent_context
    card.updated_at = utcnow()

    await db.commit()
    await db.refresh(card, ['time_entries', 'dependencies', 'checklist_items'])
    _broadcast_card_change(card)
    return _card_to_response(card)


@router.get("/cards/{card_id}/routing", response_model=dict)
async def get_routing_suggestion(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get agent routing suggestion for a card (without applying it)."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")

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
async def duplicate_card(
    card_id: str,
    db: AsyncSession = Depends(get_db),
    x_voxyflow_chat_id: str | None = Header(default=None),
):
    """Duplicate a card: copies all fields except id/created_at. Title gets ' (copy)' appended."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")

    new_card = Card(
        id=new_uuid(),
        workspace_id=card.workspace_id,
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
        recurring=card.recurring or False,
        recurrence=card.recurrence,
        recurrence_next=card.recurrence_next,
    )

    db.add(new_card)
    await db.commit()
    await db.refresh(new_card, ['time_entries', 'dependencies', 'checklist_items'])
    _broadcast_card_change(new_card)
    if x_voxyflow_chat_id:
        turn_card_registry.record_created_card(x_voxyflow_chat_id, new_card.id)
    return _card_to_response(new_card)


@router.post("/cards/{card_id}/execute")
async def execute_card(card_id: str, db: AsyncSession = Depends(get_db)):
    """Build an execution prompt from card content and optionally move to in-progress."""
    stmt = select(Card).where(Card.id == card_id).options(
        selectinload(Card.checklist_items),
    )
    result = await db.execute(stmt)
    card = result.scalar_one_or_none()
    if not card:
        raise HTTPException(404, "Card not found.")

    # Build checklist section
    checklist_lines = []
    if card.checklist_items:
        for item in card.checklist_items:
            mark = "x" if item.completed else " "
            checklist_lines.append(f"- [{mark}] {item.text}")

    # Build linked files section
    files = json.loads(card.files) if card.files else []

    # Look up workspace name if card belongs to a workspace
    workspace_name = None
    if card.workspace_id:
        workspace = await db.get(Workspace, card.workspace_id)
        if workspace:
            workspace_name = workspace.title
        # Move card to in-progress for workspace cards
        if card.status in ("backlog", "todo"):
            card.status = "in-progress"
            await db.commit()

    # Build structured prompt
    parts = ["[CARD EXECUTION]"]
    parts.append(f"Title: {card.title}")
    if card.description:
        parts.append(f"Description: {card.description}")
    if checklist_lines:
        parts.append("\nChecklist:\n" + "\n".join(checklist_lines))
    if files:
        parts.append(f"\nLinked files: {', '.join(files)}")
    if workspace_name:
        parts.append(f"\nWorkspace: {workspace_name}")
    parts.append("\nExecute this card. Read the description carefully and do what it asks.")
    parts.append("If anything is unclear, ask for clarification in the card chat.")
    parts.append("When you complete checklist items, check them off.")
    parts.append("When done, summarize what you did.")

    prompt = "\n".join(parts)
    return {"prompt": prompt, "projectName": workspace_name}


@router.post("/workspaces/{workspace_id}/boards/execute")
async def execute_board_plan(
    workspace_id: str,
    statuses: str = "todo,in-progress",
    db: AsyncSession = Depends(get_db),
):
    """Build an execution plan for all matching cards on a workspace board.

    Returns the ordered list of cards that will be executed sequentially.
    The actual execution is triggered via WebSocket (kanban:execute:start).
    """
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    from app.services.board_executor import build_execution_plan

    status_list = [s.strip() for s in statuses.split(",") if s.strip()]
    plan = await build_execution_plan(workspace_id, status_list)

    return {
        "executionId": plan.execution_id,
        "cards": [
            {"id": c.id, "title": c.title, "status": c.status, "position": c.position}
            for c in plan.cards
        ],
        "total": plan.total,
    }


class EnrichResponse(BaseModel):
    description: str
    checklist_items: list[str]
    effort: str
    tags: list[str]


@enrich_router.post("/cards/{card_id}/enrich", response_model=EnrichResponse)
async def enrich_card(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """AI enrichment: generate description, checklist, effort, and tags for a card."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")

    from app.services.claude_service import ClaudeService
    claude = ClaudeService()

    agent_type = card.agent_type or "general"
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
            system="You are a workspace assistant. Generate structured task enrichment data. Respond with valid JSON only.",
            messages=[{"role": "user", "content": prompt}],
            client=claude.fast_client,
            client_type=claude.fast_client_type,
            use_tools=False,
        )

        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        data = json.loads(text)

        description = str(data.get("description", ""))
        effort = str(data.get("effort", "M"))
        tags = [str(t) for t in data.get("tags", [])]
        checklist_items = [str(i) for i in data.get("checklist_items", [])]

        # Persist description to DB (only field that exists on Card model)
        if description:
            card.description = description
            await db.commit()

        return EnrichResponse(
            description=description,
            checklist_items=checklist_items,
            effort=effort,
            tags=tags,
        )
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(f"enrich_card: parse error for card_id={card_id!r}: {e}")
        raise HTTPException(500, f"Enrichment failed: could not parse AI response")
    except httpx.TimeoutException as e:
        logger.error(f"enrich_card: timeout for card_id={card_id!r}: {e}")
        raise HTTPException(504, f"Enrichment failed: upstream timeout")
    except httpx.HTTPError as e:
        logger.error(f"enrich_card: HTTP error for card_id={card_id!r}: {e}")
        raise HTTPException(502, f"Enrichment failed: upstream API error")
