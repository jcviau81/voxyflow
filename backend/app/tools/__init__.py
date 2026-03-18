"""Voxyflow Tool System — lets AI agents execute actions, not just chat."""

from app.tools.registry import (
    ToolDefinition,
    ToolResult,
    register_tool,
    execute_tool,
    get_tool_definitions,
)

# Import tool modules to trigger registration
import app.tools.project_tools  # noqa: F401
import app.tools.card_tools  # noqa: F401
import app.tools.info_tools  # noqa: F401
import app.tools.navigation_tools  # noqa: F401
import app.tools.github_tools  # noqa: F401

__all__ = [
    "ToolDefinition",
    "ToolResult",
    "register_tool",
    "execute_tool",
    "get_tool_definitions",
]
