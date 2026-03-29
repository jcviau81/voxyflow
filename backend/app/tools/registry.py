"""Tool Registry — central registry mapping tool names to schemas and handlers.

All tools (MCP/REST and system) are registered here. Layer-based filtering
controls which tools each AI layer can access.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool sets by layer — controls which tools each AI layer can use
# ---------------------------------------------------------------------------

# Read-only tools: Fast layer can read/search but NOT write or execute
TOOLS_READ_ONLY = {
    "voxyflow.health",
    "voxyflow.card.list_unassigned",
    "voxyflow.project.list", "voxyflow.project.get",
    "voxyflow.card.list", "voxyflow.card.get",
    "voxyflow.wiki.list", "voxyflow.wiki.get",
    "voxyflow.doc.list",
    "voxyflow.jobs.list",
}

# CRUD tools: Analyzer (Haiku) can do trivial dashboard actions + web search
TOOLS_VOXYFLOW_CRUD = TOOLS_READ_ONLY | {
    "voxyflow.card.create_unassigned",
    "voxyflow.project.create",
    "voxyflow.card.create", "voxyflow.card.update", "voxyflow.card.move",
    "voxyflow.card.duplicate", "voxyflow.card.enrich",
    "voxyflow.wiki.create", "voxyflow.wiki.update",
    "task.complete",  # Worker supervision — all tiers must signal completion
    "web.search", "web.fetch",  # Web research available to all worker tiers
}

# Full tools: Deep (Opus) can do everything including exec, write, delete
TOOLS_FULL = TOOLS_VOXYFLOW_CRUD | {
    "system.exec",
    "file.write",
    "voxyflow.project.delete", "voxyflow.project.export",
    "voxyflow.card.delete",
    "voxyflow.doc.delete",
    "voxyflow.ai.standup", "voxyflow.ai.brief", "voxyflow.ai.health",
    "voxyflow.ai.prioritize", "voxyflow.ai.review_code",
    "voxyflow.jobs.create",
    "git.commit",
    "tmux.run", "tmux.send", "tmux.new", "tmux.kill",
}

_LAYER_TOOL_SETS = {
    "fast": TOOLS_READ_ONLY,
    "analyzer": TOOLS_VOXYFLOW_CRUD,
    "deep": TOOLS_FULL,
    "sonnet": TOOLS_FULL,  # Sonnet gets same access as Opus
}


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict  # JSON Schema for arguments
    handler: Callable  # async function(params: dict) -> dict
    category: str = "voxyflow"
    dangerous: bool = False


class ToolRegistry:
    """Central registry: tool name → ToolDefinition."""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name} ({tool.category})")

    def get(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    def list_tools(self, categories: Optional[set[str]] = None) -> list[ToolDefinition]:
        if categories is None:
            return list(self._tools.values())
        return [t for t in self._tools.values() if t.category in categories]

    def get_by_layer(self, layer: str) -> list[ToolDefinition]:
        """Return tools allowed for a given layer (fast/analyzer/deep)."""
        allowed_names = _LAYER_TOOL_SETS.get(layer, TOOLS_READ_ONLY)
        return [t for name, t in self._tools.items() if name in allowed_names]

    def get_names(self) -> set[str]:
        return set(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)


def _register_all_tools(registry: ToolRegistry) -> None:
    """Auto-register all tools from mcp_server.py definitions."""
    from app.mcp_server import _TOOL_DEFINITIONS, _call_api, _get_system_handler

    for tool_def in _TOOL_DEFINITIONS:
        name = tool_def["name"]
        description = tool_def["description"]
        parameters = tool_def["inputSchema"]

        # Determine category from name prefix
        if name.startswith("voxyflow."):
            category = "voxyflow"
        elif name.startswith("system."):
            category = "system"
        elif name.startswith("web."):
            category = "web"
        elif name.startswith("file."):
            category = "file"
        elif name.startswith("git."):
            category = "git"
        elif name.startswith("tmux."):
            category = "tmux"
        else:
            category = "other"

        dangerous = name in {"system.exec", "file.write", "git.commit",
                             "voxyflow.project.delete", "voxyflow.card.delete",
                             "voxyflow.doc.delete", "tmux.kill"}

        # Build handler — reuse existing mcp_server infrastructure
        if "_handler" in tool_def:
            # System tool: direct async handler
            handler_name = tool_def["_handler"]
            handler_fn = _get_system_handler(handler_name)
            if handler_fn is None:
                logger.warning(f"No handler found for system tool: {name} ({handler_name})")
                continue

            async def _make_handler(params, _fn=handler_fn):
                return await _fn(params)
        else:
            # REST API tool: use _call_api
            async def _make_handler(params, _td=tool_def):
                return await _call_api(_td, params)

        registry.register(ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            handler=_make_handler,
            category=category,
            dangerous=dangerous,
        ))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _register_all_tools(_registry)
        logger.info(f"ToolRegistry initialized with {len(_registry)} tools")
    return _registry
