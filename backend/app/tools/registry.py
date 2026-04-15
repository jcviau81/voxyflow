"""Tool Registry — central registry mapping tool names to schemas and handlers.

All tools (MCP/REST and system) are registered here. Role-based filtering
controls which tools each AI role can access:

- **Dispatcher** (fast or deep chat) — lightweight read + basic CRUD tools.
  Fast vs deep is purely a model selection (Haiku vs Opus), NOT a tool change.
  The dispatcher must stay non-blocking; heavy work is delegated to workers.

- **Worker** — full MCP tool access (exec, files, git, tmux, AI features,
  destructive ops). Workers run in background subprocesses with full tooling.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tool sets by role — Dispatcher vs Worker
# ---------------------------------------------------------------------------

# Dispatcher tools: read + basic CRUD. Both fast and deep dispatchers get the
# SAME tools — the fast/deep distinction is purely model selection (Haiku vs
# Opus), NOT a tool escalation. The dispatcher must stay lightweight and
# non-blocking; anything heavy goes to a worker via delegate_action.
TOOLS_DISPATCHER = {
    # Read
    "voxyflow.health",
    "voxyflow.card.list_unassigned",
    "voxyflow.project.list", "voxyflow.project.get",
    "voxyflow.card.list", "voxyflow.card.get",
    "voxyflow.wiki.list", "voxyflow.wiki.get",
    "voxyflow.doc.list",
    "voxyflow.jobs.list", "voxyflow.jobs.create", "voxyflow.jobs.update", "voxyflow.jobs.delete",
    "voxyflow.heartbeat.read", "voxyflow.heartbeat.write",
    "memory.search", "knowledge.search",
    # Basic CRUD (instant, non-blocking)
    "memory.save",
    "voxyflow.card.create_unassigned",
    "voxyflow.project.create",
    "voxyflow.card.create", "voxyflow.card.update", "voxyflow.card.move",
    "voxyflow.card.archive",
    # Worker management (dispatcher needs to monitor/read worker results)
    "voxyflow.workers.list", "voxyflow.workers.get_result", "voxyflow.workers.read_artifact",
    # Endpoint management (My Machines) — instant, non-blocking CRUD
    "voxyflow.endpoint.list", "voxyflow.endpoint.add", "voxyflow.endpoint.remove",
}

# Worker tools: full MCP access — exec, files, git, tmux, AI features,
# destructive ops. Workers run in background subprocesses.
TOOLS_WORKER = TOOLS_DISPATCHER | {
    "task.complete",  # Worker supervision — workers signal completion
    "voxyflow.card.duplicate", "voxyflow.card.enrich",
    "voxyflow.wiki.create", "voxyflow.wiki.update",
    "system.exec",
    "file.read", "file.write", "file.patch", "file.list",
    "voxyflow.project.delete", "voxyflow.project.export",
    "voxyflow.card.delete",
    "voxyflow.doc.delete",
    "voxyflow.ai.standup", "voxyflow.ai.brief", "voxyflow.ai.health",
    "voxyflow.ai.prioritize", "voxyflow.ai.review_code",
    "git.status", "git.log", "git.diff", "git.branches", "git.commit",
    "tmux.list", "tmux.capture", "tmux.run", "tmux.send", "tmux.new", "tmux.kill",
    "web.search", "web.fetch",
    "kg.add", "kg.query", "kg.timeline", "kg.invalidate", "kg.stats",
    "memory.delete", "memory.get",
    "voxyflow.card.history",
    "voxyflow.card.comment.add", "voxyflow.card.comment.list", "voxyflow.card.comment.delete",
    "voxyflow.card.relation.add", "voxyflow.card.relation.list", "voxyflow.card.relation.delete",
    "voxyflow.card.time.log", "voxyflow.card.time.list", "voxyflow.card.time.delete",
    "voxyflow.card.checklist.add", "voxyflow.card.checklist.add_bulk",
    "voxyflow.card.checklist.list", "voxyflow.card.checklist.update", "voxyflow.card.checklist.delete",
    "voxyflow.card.restore", "voxyflow.card.list_archived",
    "voxyflow.wiki.delete",
    "voxyflow.focus.log", "voxyflow.focus.analytics",
    "voxyflow.sessions.list",
    "voxyflow.workers.list", "voxyflow.workers.get_result", "voxyflow.workers.read_artifact",
    "voxyflow.task.peek", "voxyflow.task.cancel",
    "voxyflow.project.archive", "voxyflow.project.restore",
    "task.steer", "tools.load",
}

# Legacy aliases — kept so existing imports don't break during transition
TOOLS_READ_ONLY = TOOLS_DISPATCHER

_ROLE_TOOL_SETS = {
    "dispatcher": TOOLS_DISPATCHER,
    "worker": TOOLS_WORKER,
    # Legacy layer names map to dispatcher (model selection, not tool escalation)
    "fast": TOOLS_DISPATCHER,
    "deep": TOOLS_DISPATCHER,
}

# Deprecated — use _ROLE_TOOL_SETS
_LAYER_TOOL_SETS = _ROLE_TOOL_SETS


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

    def get_by_role(self, role: str) -> list[ToolDefinition]:
        """Return tools allowed for a given role (dispatcher/worker).

        Also accepts legacy layer names (fast/deep) which both map to dispatcher.
        """
        allowed_names = _ROLE_TOOL_SETS.get(role, TOOLS_DISPATCHER)
        return [t for name, t in self._tools.items() if name in allowed_names]

    # Deprecated alias
    get_by_layer = get_by_role

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

        dangerous = name in {"system.exec", "file.write", "file.patch", "git.commit",
                             "voxyflow.project.delete", "voxyflow.card.delete",
                             "voxyflow.doc.delete", "voxyflow.jobs.delete", "tmux.kill"}

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
