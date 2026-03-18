"""Card CRUD + kanban tools — create, move, update, delete, assign cards via AI."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Card, Project, new_uuid, utcnow
from app.tools.registry import register_tool, ToolDefinition, ToolResult
from app.services.agent_router import get_agent_router
from app.services.agent_personas import AgentType, get_persona


async def create_card(params: dict, db: AsyncSession = None) -> ToolResult:
    """Create a card in a project."""
    if not db:
        return ToolResult(success=False, error="No database session")

    project = await db.get(Project, params["project_id"])
    if not project:
        return ToolResult(success=False, error=f"Project not found: {params['project_id']}")

    # Auto-route to agent if not specified
    agent_type = params.get("agent_type")
    if not agent_type:
        router_service = get_agent_router()
        detected, _ = router_service.route(
            title=params["title"],
            description=params.get("description", ""),
            context="",
        )
        agent_type = detected.value

    persona = get_persona(AgentType(agent_type))
    agent_display = f"{persona.emoji} {persona.name}"

    card = Card(
        id=new_uuid(),
        project_id=params["project_id"],
        title=params["title"],
        description=params.get("description", ""),
        status=params.get("status", "idea"),
        priority=params.get("priority", 0),
        agent_type=agent_type,
        agent_assigned=agent_display,
    )
    db.add(card)
    await db.commit()
    await db.refresh(card)

    return ToolResult(
        success=True,
        data={
            "id": card.id,
            "title": card.title,
            "status": card.status,
            "agent": agent_display,
        },
        ui_action="refresh_kanban",
    )


async def move_card(params: dict, db: AsyncSession = None) -> ToolResult:
    """Move a card to a different status column."""
    if not db:
        return ToolResult(success=False, error="No database session")

    card = await db.get(Card, params["card_id"])
    if not card:
        return ToolResult(success=False, error=f"Card not found: {params['card_id']}")

    old_status = card.status
    card.status = params["new_status"]
    card.updated_at = utcnow()
    await db.commit()
    await db.refresh(card)

    return ToolResult(
        success=True,
        data={
            "card_id": card.id,
            "title": card.title,
            "old_status": old_status,
            "new_status": card.status,
        },
        ui_action="refresh_kanban",
    )


async def update_card(params: dict, db: AsyncSession = None) -> ToolResult:
    """Update card details (title, description, priority)."""
    if not db:
        return ToolResult(success=False, error="No database session")

    card = await db.get(Card, params["card_id"])
    if not card:
        return ToolResult(success=False, error=f"Card not found: {params['card_id']}")

    for field in ("title", "description", "priority", "status"):
        if field in params:
            setattr(card, field, params[field])
    card.updated_at = utcnow()
    await db.commit()
    await db.refresh(card)

    return ToolResult(
        success=True,
        data={"card_id": card.id, "title": card.title},
        ui_action="refresh_kanban",
    )


async def delete_card(params: dict, db: AsyncSession = None) -> ToolResult:
    """Delete a card."""
    if not db:
        return ToolResult(success=False, error="No database session")

    card = await db.get(Card, params["card_id"])
    if not card:
        return ToolResult(success=False, error=f"Card not found: {params['card_id']}")

    title = card.title
    await db.delete(card)
    await db.commit()

    return ToolResult(
        success=True,
        data={"deleted_id": params["card_id"], "title": title},
        ui_action="refresh_kanban",
    )


async def assign_agent(params: dict, db: AsyncSession = None) -> ToolResult:
    """Assign or reassign a card to a specific agent type."""
    if not db:
        return ToolResult(success=False, error="No database session")

    card = await db.get(Card, params["card_id"])
    if not card:
        return ToolResult(success=False, error=f"Card not found: {params['card_id']}")

    agent_type = AgentType(params["agent_type"])
    persona = get_persona(agent_type)

    card.agent_type = agent_type.value
    card.agent_assigned = f"{persona.emoji} {persona.name}"
    if "agent_context" in params:
        card.agent_context = params["agent_context"]
    card.updated_at = utcnow()
    await db.commit()
    await db.refresh(card)

    return ToolResult(
        success=True,
        data={
            "card_id": card.id,
            "title": card.title,
            "agent": card.agent_assigned,
        },
        ui_action="refresh_kanban",
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_tool(
    ToolDefinition(
        name="create_card",
        description="Create a new card/task in a project",
        parameters={
            "type": "object",
            "required": ["project_id", "title"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "title": {"type": "string", "description": "Card title"},
                "description": {"type": "string", "description": "Card description"},
                "status": {
                    "type": "string",
                    "enum": ["idea", "todo", "in_progress", "done"],
                    "description": "Initial status (default: idea)",
                },
                "priority": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 4,
                    "description": "Priority: 0=none, 1=low, 2=medium, 3=high, 4=critical",
                },
                "agent_type": {
                    "type": "string",
                    "enum": ["ember", "researcher", "coder", "designer", "architect", "writer", "qa"],
                    "description": "Agent type to assign (auto-routed if omitted)",
                },
            },
        },
    ),
    create_card,
)

register_tool(
    ToolDefinition(
        name="move_card",
        description="Move a card to a different status column on the kanban board",
        parameters={
            "type": "object",
            "required": ["card_id", "new_status"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID to move"},
                "new_status": {
                    "type": "string",
                    "enum": ["idea", "todo", "in_progress", "done", "archived"],
                    "description": "Target status",
                },
            },
        },
    ),
    move_card,
)

register_tool(
    ToolDefinition(
        name="update_card",
        description="Update a card's title, description, or priority",
        parameters={
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID to update"},
                "title": {"type": "string", "description": "New title"},
                "description": {"type": "string", "description": "New description"},
                "priority": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 4,
                    "description": "New priority",
                },
                "status": {
                    "type": "string",
                    "enum": ["idea", "todo", "in_progress", "done", "archived"],
                    "description": "New status",
                },
            },
        },
    ),
    update_card,
)

register_tool(
    ToolDefinition(
        name="delete_card",
        description="Delete a card (irreversible!)",
        parameters={
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID to delete"},
            },
        },
    ),
    delete_card,
)

register_tool(
    ToolDefinition(
        name="assign_agent",
        description="Assign or reassign a card to a specific agent type",
        parameters={
            "type": "object",
            "required": ["card_id", "agent_type"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
                "agent_type": {
                    "type": "string",
                    "enum": ["ember", "researcher", "coder", "designer", "architect", "writer", "qa"],
                    "description": "Agent type to assign",
                },
                "agent_context": {"type": "string", "description": "Context for the agent"},
            },
        },
    ),
    assign_agent,
)


register_tool(
    ToolDefinition(
        name="add_note",
        description="Add a sticky note/reminder to the FreeBoard (main chat board). Use this when the user wants to add a note, reminder, or idea to their personal board.",
        parameters={
            "content": {"type": "string", "description": "The text content of the note"},
            "color": {"type": "string", "enum": ["yellow", "blue", "green", "pink", "purple", "orange"], "description": "Optional color for the note", "default": None}
        },
        required_params=["content"],
        handler=lambda params: ToolResult(
            success=True,
            message=f"Note added to FreeBoard: {params.get('content', '')}",
            data={"action": "idea:add", "content": params.get("content", ""), "color": params.get("color")},
            ui_event={"type": "idea:add", "content": params.get("content", ""), "color": params.get("color")}
        )
    )
)
