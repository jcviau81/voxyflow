"""Tool Registry — central registry mapping tool names to schemas and handlers.

All tools (MCP/REST and system) are registered here. Role-based filtering
controls which tools each AI role can access:

- **Dispatcher** (fast or deep chat) — lightweight read + basic CRUD tools.
  Fast vs deep is purely a model selection (Haiku vs Opus), NOT a tool change.
  The dispatcher must stay non-blocking; heavy work is delegated to workers.

- **Codex dispatcher** — stricter read-only dispatcher profile used by Codex CLI.
  Codex has stronger agentic execution instincts, so it gets eyes-only tools and
  delegates all action work to workers.

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
    # ---- Read ----
    "voxyflow.health",
    "voxyflow.workspace.list", "voxyflow.workspace.get",
    "voxyflow.card.list", "voxyflow.card.get",
    "voxyflow.card.list_unassigned", "voxyflow.card.list_archived",
    "voxyflow.card.history",
    "voxyflow.wiki.list", "voxyflow.wiki.get",
    "voxyflow.doc.list",
    "voxyflow.jobs.list",
    "voxyflow.heartbeat.read",
    "voxyflow.autonomy.status",
    "voxyflow.focus.analytics",
    "voxyflow.sessions.list",
    "voxyflow.session.read",
    "voxyflow.endpoint.list",
    "voxyflow.undo.list",
    "memory.search", "memory.get", "knowledge.search",

    # ---- Workspace / Card / Wiki CRUD (instant, non-blocking) ----
    "voxyflow.workspace.create", "voxyflow.workspace.update",
    "voxyflow.workspace.archive", "voxyflow.workspace.restore",
    "voxyflow.card.create", "voxyflow.card.create_unassigned",
    "voxyflow.card.update", "voxyflow.card.move",
    "voxyflow.card.archive", "voxyflow.card.restore",
    "voxyflow.card.duplicate",
    "voxyflow.wiki.create", "voxyflow.wiki.update",

    # ---- Card sub-resources (row-level CRUD, all instant) ----
    # Checklist — needed for the enrich "propose → confirm → apply" flow.
    "voxyflow.card.checklist.add", "voxyflow.card.checklist.add_bulk",
    "voxyflow.card.checklist.list", "voxyflow.card.checklist.update",
    "voxyflow.card.checklist.delete",
    "voxyflow.card.relation.add", "voxyflow.card.relation.list", "voxyflow.card.relation.delete",
    "voxyflow.card.time.log", "voxyflow.card.time.list", "voxyflow.card.time.delete",

    # ---- Memory write (instant; scope enforced via env var) ----
    "memory.save", "memory.delete",

    # ---- Skills (learned procedures — instant local file ops, scope
    # enforced via env var; lets the user say "save this as a skill") ----
    "voxyflow.skill.list", "voxyflow.skill.get",
    "voxyflow.skill.save", "voxyflow.skill.delete",

    # ---- Knowledge graph (instant local DB ops; temporal model is
    # reversible — kg.invalidate sets valid_to, doesn't hard-delete) ----
    "kg.add", "kg.query", "kg.timeline", "kg.invalidate", "kg.stats",

    # ---- Destructive whole-entity deletes / exports ----
    # Single-user local deployment: the user is always present and the undo
    # journal (voxyflow.undo.*) reverses these, so inline delete is fine.
    "voxyflow.workspace.delete", "voxyflow.workspace.export",
    "voxyflow.card.delete",
    "voxyflow.doc.delete",
    "voxyflow.wiki.delete",

    # ---- Focus / activity logging ----
    "voxyflow.focus.log",
    # heartbeat.write is instant (single DB upsert) — dispatcher records
    # "I acted" pings without spawning a worker.
    "voxyflow.heartbeat.write",

    # ---- Jobs (cron-like; all REST CRUD, instant) ----
    "voxyflow.jobs.create", "voxyflow.jobs.update", "voxyflow.jobs.delete",
    # schedule_nl = create a recurring natural-language task (instant local
    # jobs.json write; execution happens later via the scheduler).
    "voxyflow.jobs.schedule_nl",

    # ---- Per-workspace autonomy — thin REST wrappers, instant/non-blocking ----
    "voxyflow.autonomy.enable", "voxyflow.autonomy.disable", "voxyflow.autonomy.run_now",

    # ---- Worker monitoring + control (no need to spawn another worker) ----
    "voxyflow.workers.list", "voxyflow.workers.get_result", "voxyflow.workers.read_artifact",
    "voxyflow.workers.ack_artifact", "voxyflow.workers.list_unread",
    "voxyflow.task.peek", "voxyflow.task.cancel",
    # task.steer = inject a redirect message into a running worker (instant
    # queue write, scope-enforced). Pairs with task.peek + task.cancel.
    "task.steer",

    # ---- Endpoints (LLM Providers) — instant CRUD ----
    "voxyflow.endpoint.add", "voxyflow.endpoint.remove",

    # ---- Undo journal — revert a reversible action Voxy just took ----
    "voxyflow.undo.apply",

    # ---- Delegate — spawn background workers (canonical MCP tool) ----
    # Available to dispatchers so Claude/Codex CLI can call voxyflow.delegate
    # via MCP tool_use in addition to the Anthropic/OpenAI native tool paths.
    "voxyflow.delegate",
}

# NOTE: there is intentionally no provider-specific dispatcher tool set. The
# tool list per layer is defined here by ROLE only ("dispatcher" / "worker") and
# is identical for any model or provider (Claude CLI, Codex CLI, native SDK …).
# Codex was formerly a read-only `dispatcher_codex` subset, which made it spawn
# workers for trivial CRUD; it now uses the standard "dispatcher" role like every
# other dispatcher. Provider differences live only in the prompt, not the tools.


# Worker tools: dispatcher set PLUS the heavy / dangerous / lifecycle tools.
# Anything listed here must NOT also appear in TOOLS_DISPATCHER above
# (the set union would silently mask the duplication).
_WORKER_EXTRAS = {
    # Worker lifecycle
    "voxyflow.worker.claim", "voxyflow.worker.complete",

    # Heavy AI features
    "voxyflow.ai.standup", "voxyflow.ai.brief", "voxyflow.ai.health",
    "voxyflow.ai.prioritize", "voxyflow.ai.review_code",
    # Synchronous LLM call — blocks inline chat, worker-only per CLAUDE.md
    # §"Tool Access Architecture" (the dispatcher proposes via delegate).
    "voxyflow.card.enrich",

    # OS / dev-environment access
    "system.exec",
    "file.read", "file.write", "file.patch", "file.list",
    "git.status", "git.log", "git.diff", "git.branches", "git.commit",
    "tmux.list", "tmux.capture", "tmux.run", "tmux.send", "tmux.new", "tmux.kill",
    "web.search", "web.fetch",

    # Worker dynamic tool loading
    "tools.load",

    # Programmatic tool calling — runs arbitrary Python in the MCP subprocess
    # to chain many tool calls in one turn. Arbitrary code execution, so it is
    # worker-only forever (same boundary as system.exec).
    "voxyflow.script",
}

# Sanity guard — fail loudly at import time if a tool is listed in both sets.
# Set union would otherwise silently hide the duplication.
_overlap = TOOLS_DISPATCHER & _WORKER_EXTRAS
assert not _overlap, f"Tool listed in both TOOLS_DISPATCHER and _WORKER_EXTRAS: {_overlap}"

TOOLS_WORKER = TOOLS_DISPATCHER | _WORKER_EXTRAS

_ROLE_TOOL_SETS = {
    "dispatcher": TOOLS_DISPATCHER,
    "worker": TOOLS_WORKER,
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

    def get_by_role(self, role: str) -> list[ToolDefinition]:
        """Return tools allowed for a given role.

        Recognised roles are "dispatcher" and "worker" — the same for any model
        or provider. Anything else (model-tier names like "fast"/"deep"/"haiku",
        or a legacy "dispatcher_codex") falls back to the dispatcher set:
        fast/deep/provider is model selection, not a tool tier.
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
                             "voxyflow.workspace.delete", "voxyflow.card.delete",
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
