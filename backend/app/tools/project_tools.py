"""Project CRUD tools — create, update, delete projects via AI."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Project, new_uuid, utcnow
from app.tools.registry import register_tool, ToolDefinition, ToolResult


async def create_project(params: dict, db: AsyncSession = None) -> ToolResult:
    """Create a new project."""
    if not db:
        return ToolResult(success=False, error="No database session")

    title = params["title"]
    project = Project(
        id=new_uuid(),
        title=title,
        description=params.get("description", ""),
        context=params.get("context", ""),
        github_repo=params.get("github_repo"),
        github_url=params.get("github_url"),
        local_path=params.get("local_path"),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    return ToolResult(
        success=True,
        data={"id": project.id, "title": project.title},
        ui_action="open_project_tab",
    )


async def update_project(params: dict, db: AsyncSession = None) -> ToolResult:
    """Update an existing project."""
    if not db:
        return ToolResult(success=False, error="No database session")

    project = await db.get(Project, params["project_id"])
    if not project:
        return ToolResult(success=False, error=f"Project not found: {params['project_id']}")

    for field in ("title", "description", "status", "context", "github_repo", "local_path"):
        if field in params:
            setattr(project, field, params[field])
    project.updated_at = utcnow()

    await db.commit()
    await db.refresh(project)

    return ToolResult(
        success=True,
        data={"id": project.id, "title": project.title, "status": project.status},
        ui_action="refresh_project",
    )


async def delete_project(params: dict, db: AsyncSession = None) -> ToolResult:
    """Delete a project and its cards."""
    if not db:
        return ToolResult(success=False, error="No database session")

    project = await db.get(Project, params["project_id"])
    if not project:
        return ToolResult(success=False, error=f"Project not found: {params['project_id']}")

    title = project.title
    await db.delete(project)
    await db.commit()

    return ToolResult(
        success=True,
        data={"deleted_id": params["project_id"], "title": title},
        ui_action="close_project_tab",
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

register_tool(
    ToolDefinition(
        name="create_project",
        description="Create a new project in Voxyflow",
        parameters={
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {"type": "string", "description": "Project name"},
                "description": {"type": "string", "description": "Project description"},
                "context": {"type": "string", "description": "Relevant docs/requirements context"},
                "github_repo": {"type": "string", "description": "GitHub repo (owner/repo)"},
                "github_url": {"type": "string", "description": "GitHub URL"},
                "local_path": {"type": "string", "description": "Local filesystem path"},
            },
        },
    ),
    create_project,
)

register_tool(
    ToolDefinition(
        name="update_project",
        description="Update an existing project's title, description, status, or context",
        parameters={
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID to update"},
                "title": {"type": "string", "description": "New title"},
                "description": {"type": "string", "description": "New description"},
                "status": {"type": "string", "enum": ["active", "archived"], "description": "Project status"},
                "context": {"type": "string", "description": "Updated context"},
                "github_repo": {"type": "string", "description": "GitHub repo (owner/repo)"},
                "local_path": {"type": "string", "description": "Local filesystem path"},
            },
        },
    ),
    update_project,
)

register_tool(
    ToolDefinition(
        name="delete_project",
        description="Delete a project and all its cards (irreversible!)",
        parameters={
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID to delete"},
            },
        },
    ),
    delete_project,
)
