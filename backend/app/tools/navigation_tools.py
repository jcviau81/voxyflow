"""Navigation tools — tell the frontend to switch views, open projects/cards."""

from app.tools.registry import register_tool, ToolDefinition, ToolResult


async def open_project(params: dict, db=None) -> ToolResult:
    """Tell frontend to switch to a project tab."""
    return ToolResult(
        success=True,
        data={"project_id": params["project_id"]},
        ui_action="open_project_tab",
    )


async def open_card(params: dict, db=None) -> ToolResult:
    """Tell frontend to open a card's detail/chat view."""
    return ToolResult(
        success=True,
        data={"card_id": params["card_id"]},
        ui_action="open_card",
    )


async def show_kanban(params: dict, db=None) -> ToolResult:
    """Tell frontend to switch to the kanban board view."""
    return ToolResult(
        success=True,
        data={"view": "kanban"},
        ui_action="show_kanban",
    )


async def show_chat(params: dict, db=None) -> ToolResult:
    """Tell frontend to switch to the chat view."""
    return ToolResult(
        success=True,
        data={"view": "chat"},
        ui_action="show_chat",
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_tool(
    ToolDefinition(
        name="open_project",
        description="Switch the UI to show a specific project tab",
        parameters={
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID to open"},
            },
        },
    ),
    open_project,
)

register_tool(
    ToolDefinition(
        name="open_card",
        description="Open a specific card's detail view in the UI",
        parameters={
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID to open"},
            },
        },
    ),
    open_card,
)

register_tool(
    ToolDefinition(
        name="show_kanban",
        description="Switch the UI to the kanban board view",
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
    show_kanban,
)

register_tool(
    ToolDefinition(
        name="show_chat",
        description="Switch the UI to the chat view",
        parameters={
            "type": "object",
            "properties": {},
        },
    ),
    show_chat,
)
