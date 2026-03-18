"""Info/query tools — list, search, and summarize projects and cards."""

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import Project, Card
from app.tools.registry import register_tool, ToolDefinition, ToolResult


async def list_projects(params: dict, db: AsyncSession = None) -> ToolResult:
    """List all projects, optionally filtered by status."""
    if not db:
        return ToolResult(success=False, error="No database session")

    stmt = select(Project).order_by(Project.updated_at.desc())
    status_filter = params.get("status")
    if status_filter:
        stmt = stmt.where(Project.status == status_filter)

    result = await db.execute(stmt)
    projects = result.scalars().all()

    return ToolResult(
        success=True,
        data=[
            {
                "id": p.id,
                "title": p.title,
                "description": p.description[:100] if p.description else "",
                "status": p.status,
                "github_repo": p.github_repo,
            }
            for p in projects
        ],
    )


async def list_cards(params: dict, db: AsyncSession = None) -> ToolResult:
    """List cards in a project, filterable by status, agent, priority."""
    if not db:
        return ToolResult(success=False, error="No database session")

    stmt = select(Card).where(Card.project_id == params["project_id"]).order_by(Card.position)

    if "status" in params:
        stmt = stmt.where(Card.status == params["status"])
    if "agent_type" in params:
        stmt = stmt.where(Card.agent_type == params["agent_type"])
    if "priority" in params:
        stmt = stmt.where(Card.priority >= params["priority"])

    result = await db.execute(stmt)
    cards = result.scalars().all()

    return ToolResult(
        success=True,
        data=[
            {
                "id": c.id,
                "title": c.title,
                "status": c.status,
                "priority": c.priority,
                "agent_type": c.agent_type,
                "agent_assigned": c.agent_assigned,
            }
            for c in cards
        ],
    )


async def get_project_status(params: dict, db: AsyncSession = None) -> ToolResult:
    """Get a summary of a project: card counts by status, blockers, etc."""
    if not db:
        return ToolResult(success=False, error="No database session")

    project = await db.get(Project, params["project_id"])
    if not project:
        return ToolResult(success=False, error=f"Project not found: {params['project_id']}")

    # Count cards by status
    stmt = (
        select(Card.status, func.count(Card.id))
        .where(Card.project_id == params["project_id"])
        .group_by(Card.status)
    )
    result = await db.execute(stmt)
    status_counts = {row[0]: row[1] for row in result.all()}

    # High priority cards (potential blockers)
    blocker_stmt = (
        select(Card)
        .where(Card.project_id == params["project_id"])
        .where(Card.priority >= 3)
        .where(Card.status.notin_(["done", "archived"]))
    )
    blocker_result = await db.execute(blocker_stmt)
    blockers = [
        {"id": c.id, "title": c.title, "priority": c.priority, "status": c.status}
        for c in blocker_result.scalars().all()
    ]

    total = sum(status_counts.values())

    return ToolResult(
        success=True,
        data={
            "project_id": project.id,
            "project_title": project.title,
            "total_cards": total,
            "by_status": status_counts,
            "blockers": blockers,
            "completion_pct": round(status_counts.get("done", 0) / total * 100, 1) if total > 0 else 0,
        },
    )


async def search_cards(params: dict, db: AsyncSession = None) -> ToolResult:
    """Search cards by keyword across title and description."""
    if not db:
        return ToolResult(success=False, error="No database session")

    query = params["query"].lower()
    pattern = f"%{query}%"

    stmt = select(Card).where(
        or_(
            Card.title.ilike(pattern),
            Card.description.ilike(pattern),
        )
    )

    # Optionally scope to a project
    if "project_id" in params:
        stmt = stmt.where(Card.project_id == params["project_id"])

    stmt = stmt.order_by(Card.updated_at.desc()).limit(20)
    result = await db.execute(stmt)
    cards = result.scalars().all()

    return ToolResult(
        success=True,
        data=[
            {
                "id": c.id,
                "project_id": c.project_id,
                "title": c.title,
                "status": c.status,
                "priority": c.priority,
                "agent_type": c.agent_type,
            }
            for c in cards
        ],
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_tool(
    ToolDefinition(
        name="list_projects",
        description="List all projects. Optionally filter by status (active/archived).",
        parameters={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["active", "archived"],
                    "description": "Filter by status",
                },
            },
        },
    ),
    list_projects,
)

register_tool(
    ToolDefinition(
        name="list_cards",
        description="List cards in a project. Can filter by status, agent_type, or minimum priority.",
        parameters={
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "status": {
                    "type": "string",
                    "enum": ["idea", "todo", "in_progress", "done", "archived"],
                    "description": "Filter by status",
                },
                "agent_type": {
                    "type": "string",
                    "description": "Filter by agent type",
                },
                "priority": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 4,
                    "description": "Minimum priority filter",
                },
            },
        },
    ),
    list_cards,
)

register_tool(
    ToolDefinition(
        name="get_project_status",
        description="Get a project summary: card counts by status, completion %, and blockers (high priority cards).",
        parameters={
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
        },
    ),
    get_project_status,
)

register_tool(
    ToolDefinition(
        name="search_cards",
        description="Search cards by keyword in title or description. Optionally scope to a project.",
        parameters={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Search keyword"},
                "project_id": {"type": "string", "description": "Limit search to this project"},
            },
        },
    ),
    search_cards,
)
