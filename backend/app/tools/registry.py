"""Tool registry — register, discover, and execute tools for AI agents."""

import logging
from typing import Any, Callable, Dict

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema


class ToolResult(BaseModel):
    success: bool
    data: Any = None
    error: str | None = None
    ui_action: str | None = None  # Frontend-actionable hint


# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------

TOOLS: Dict[str, tuple[ToolDefinition, Callable]] = {}


def register_tool(definition: ToolDefinition, handler: Callable) -> None:
    """Register a tool handler with its schema."""
    TOOLS[definition.name] = (definition, handler)
    logger.debug(f"Registered tool: {definition.name}")


async def execute_tool(name: str, params: Dict[str, Any], db=None) -> ToolResult:
    """Execute a registered tool by name."""
    if name not in TOOLS:
        return ToolResult(success=False, error=f"Unknown tool: {name}")

    definition, handler = TOOLS[name]
    try:
        result = await handler(params, db=db)
        logger.info(f"Tool executed: {name} → success={result.success}")
        return result
    except Exception as e:
        logger.error(f"Tool execution failed: {name} → {e}")
        return ToolResult(success=False, error=str(e))


def get_tool_definitions() -> list[dict]:
    """Return all tool schemas for injection into Claude system prompt."""
    return [
        {
            "name": defn.name,
            "description": defn.description,
            "parameters": defn.parameters,
        }
        for defn, _ in TOOLS.values()
    ]
