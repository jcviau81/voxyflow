"""Tool execution API endpoint — direct tool calls from frontend or external."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.tools import execute_tool, get_tool_definitions

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolExecuteRequest(BaseModel):
    name: str
    params: dict = {}


@router.post("/execute")
async def execute_tool_endpoint(
    body: ToolExecuteRequest,
    db: AsyncSession = Depends(get_db),
):
    """Execute a tool by name with params. Returns ToolResult."""
    result = await execute_tool(body.name, body.params, db=db)
    return result.model_dump()


@router.get("/definitions")
async def list_tool_definitions():
    """List all available tool definitions (for debugging/docs)."""
    return get_tool_definitions()
