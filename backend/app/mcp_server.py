"""Voxyflow MCP Server — wraps all Voxyflow REST API endpoints as MCP tools.

This module is a thin HTTP client over the Voxyflow REST API (localhost:8000).
It does NOT access the database directly; every tool call goes through the API.

System tools (system.exec, web.search, web.fetch, file.*) are executed directly
via async handlers — they don't go through the REST API.

Transport modes:
  - SSE  → imported by routes/mcp.py  (web clients)
  - Stdio → imported by backend/mcp_stdio.py  (Claude Code, Cursor, etc.)
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime
from typing import Any

import httpx

try:
    from mcp.server import Server
    from mcp import types
    from mcp.types import Tool, TextContent
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    Server = None
    Tool = None
    TextContent = None

logger = logging.getLogger("voxyflow.mcp")

# ---------------------------------------------------------------------------
# Base URL for the Voxyflow REST API
# ---------------------------------------------------------------------------

VOXYFLOW_API_BASE = os.environ.get("VOXYFLOW_API_BASE", "http://localhost:8000")

# ---------------------------------------------------------------------------
# Persistent HTTP client — reuses TCP connections instead of one per tool call
# ---------------------------------------------------------------------------
_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Return (and lazily create) the module-level persistent HTTP client."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            base_url=VOXYFLOW_API_BASE,
            timeout=30.0,
        )
    return _http_client


# Role-based tool filtering: "dispatcher" limits tools to lightweight CRUD +
# knowledge; "worker" (or unset) exposes everything.  Set via env var
# VOXYFLOW_MCP_ROLE passed through the MCP config.
VOXYFLOW_MCP_ROLE = os.environ.get("VOXYFLOW_MCP_ROLE", "worker")

# Tools tagged _role="worker" are hidden from the dispatcher.
# Tools with no _role tag (or _role="all") are available to everyone.

# ---------------------------------------------------------------------------
# Dynamic tool scoping — workers start with core tools only and load more
# All scopes enabled by default — dynamic loading via tools.load is broken
# because Claude CLI does not support ToolListChangedNotification.
# ---------------------------------------------------------------------------
_active_scopes: set[str] = {"core", "file", "system", "voxyflow", "web", "git", "tmux"}

# ---------------------------------------------------------------------------
# MCP Tool definitions
# ---------------------------------------------------------------------------

# MCP tool catalog — see app/mcp_tool_defs.py for the full list.
# Kept as a module-level import so downstream code (tool registry,
# _find_tool, _call_api) can keep using the existing _TOOL_DEFINITIONS name.
from app.mcp_tool_defs import _TOOL_DEFINITIONS


# ---------------------------------------------------------------------------
# Helpers needed before consolidation
# ---------------------------------------------------------------------------

def _find_tool(name: str) -> dict | None:
    for t in _TOOL_DEFINITIONS:
        if t["name"] == name:
            return t
    return None


def _auto_injectable_params() -> set[str]:
    """Return the set of path params that are auto-injected from env vars.

    - project_id: stripped when VOXYFLOW_PROJECT_ID is a real UUID (not "system-main")
    - card_id: stripped when VOXYFLOW_CARD_ID is set
    """
    injectable = set()
    pid = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip()
    if pid and pid != "system-main":
        injectable.add("project_id")
    cid = os.environ.get("VOXYFLOW_CARD_ID", "").strip()
    if cid:
        injectable.add("card_id")
    return injectable


# ---------------------------------------------------------------------------
# Project scoping for ledger / session tools
# ---------------------------------------------------------------------------
# Worker ledger, CLI sessions, and task-control tools default to the current
# project (like memory_search), preventing cross-project leakage. Callers opt
# out via scope="all" when they really need a system-wide view.

def _current_project_scope() -> tuple[str, bool]:
    """Resolve the active project scope from VOXYFLOW_PROJECT_ID.

    Returns (project_id, is_project_scoped):
      - ("<uuid>", True)  → real project chat, should filter by that project
      - ("", False)       → general chat (empty or "system-main"), no filter
    """
    pid = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip()
    if pid and pid != "system-main":
        return pid, True
    return "", False


async def _lookup_task_project(task_id: str) -> str | None:
    """Resolve a worker task's project_id via live session store, then DB.

    Returns the project_id string (possibly empty), or None when the task
    is unknown in both stores.
    """
    try:
        from app.services.worker_session_store import get_worker_session_store
        session = get_worker_session_store().get_session(task_id)
        if session is not None:
            return (session.get("project_id") or "").strip()
    except Exception as live_err:
        logger.debug(f"[mcp._lookup_task_project] live lookup failed: {live_err}")

    try:
        from app.database import async_session, WorkerTask
        from sqlalchemy import select
        async with async_session() as db:
            row = (await db.execute(
                select(WorkerTask).where(WorkerTask.id == task_id)
            )).scalar_one_or_none()
            if row is None:
                return None
            return (row.project_id or "").strip()
    except Exception as db_err:
        logger.warning(f"[mcp._lookup_task_project] DB lookup failed for {task_id}: {db_err}")
        return None


async def _enforce_task_scope(task_id: str, scope: str | None) -> dict | None:
    """Return an error dict if the task falls outside the active project scope.

    scope handling:
      - "all" (case-insensitive) → bypass the check, return None
      - otherwise                → strict: task must belong to the current
                                    project when VOXYFLOW_PROJECT_ID is set
    In general chat (no project scope active), the check is a no-op.
    """
    if (scope or "").lower() == "all":
        return None
    current_pid, scoped = _current_project_scope()
    if not scoped:
        return None
    task_pid = await _lookup_task_project(task_id)
    if task_pid is None:
        return {"success": False, "error": f"Task {task_id} not found."}
    if task_pid != current_pid:
        return {
            "success": False,
            "error": (
                f"Task {task_id} belongs to a different project "
                f"(project_id={task_pid or '∅'}) and is not visible from the "
                f"current project scope. Pass scope='all' to override."
            ),
        }
    return None


# ---------------------------------------------------------------------------
# Tool Consolidation — groups of individual tools exposed as single MCP tools
# ---------------------------------------------------------------------------

_TOOL_GROUPS: dict[str, dict] = {
    "voxyflow.card": {
        "description": "Manage cards/tasks. project_id and card_id auto-injected from context.",
        "actions": {
            "create": "voxyflow.card.create",
            "create_unassigned": "voxyflow.card.create_unassigned",
            "list": "voxyflow.card.list",
            "list_unassigned": "voxyflow.card.list_unassigned",
            "get": "voxyflow.card.get",
            "update": "voxyflow.card.update",
            "move": "voxyflow.card.move",
            "archive": "voxyflow.card.archive",
            "delete": "voxyflow.card.delete",
            "duplicate": "voxyflow.card.duplicate",
            "enrich": "voxyflow.card.enrich",
            "restore": "voxyflow.card.restore",
            "list_archived": "voxyflow.card.list_archived",
            "history": "voxyflow.card.history",
        },
    },
    "voxyflow.card.comment": {
        "description": "Manage comments on cards. card_id auto-injected from context.",
        "actions": {
            "add": "voxyflow.card.comment.add",
            "list": "voxyflow.card.comment.list",
            "delete": "voxyflow.card.comment.delete",
        },
    },
    "voxyflow.card.relation": {
        "description": "Manage relations between cards. card_id auto-injected from context.",
        "actions": {
            "add": "voxyflow.card.relation.add",
            "list": "voxyflow.card.relation.list",
            "delete": "voxyflow.card.relation.delete",
        },
    },
    "voxyflow.card.time": {
        "description": "Track time on cards. card_id auto-injected from context.",
        "actions": {
            "log": "voxyflow.card.time.log",
            "list": "voxyflow.card.time.list",
            "delete": "voxyflow.card.time.delete",
        },
    },
    "voxyflow.card.checklist": {
        "description": "Manage checklists on cards. card_id auto-injected from context.",
        "actions": {
            "add": "voxyflow.card.checklist.add",
            "add_bulk": "voxyflow.card.checklist.add_bulk",
            "list": "voxyflow.card.checklist.list",
            "update": "voxyflow.card.checklist.update",
            "delete": "voxyflow.card.checklist.delete",
        },
    },
    "voxyflow.project": {
        "description": "Manage projects in Voxyflow.",
        "actions": {
            "create": "voxyflow.project.create",
            "list": "voxyflow.project.list",
            "get": "voxyflow.project.get",
            "update": "voxyflow.project.update",
            "delete": "voxyflow.project.delete",
            "export": "voxyflow.project.export",
            "archive": "voxyflow.project.archive",
            "restore": "voxyflow.project.restore",
        },
    },
    "voxyflow.wiki": {
        "description": "Manage wiki pages. project_id auto-injected from context.",
        "actions": {
            "list": "voxyflow.wiki.list",
            "create": "voxyflow.wiki.create",
            "get": "voxyflow.wiki.get",
            "update": "voxyflow.wiki.update",
            "delete": "voxyflow.wiki.delete",
        },
    },
    "voxyflow.ai": {
        "description": "AI-powered project analysis. project_id auto-injected from context.",
        "actions": {
            "standup": "voxyflow.ai.standup",
            "brief": "voxyflow.ai.brief",
            "health": "voxyflow.ai.health",
            "prioritize": "voxyflow.ai.prioritize",
            "review_code": "voxyflow.ai.review_code",
        },
    },
    "voxyflow.doc": {
        "description": "Manage project documents. project_id auto-injected from context.",
        "actions": {
            "list": "voxyflow.doc.list",
            "delete": "voxyflow.doc.delete",
        },
    },
    "voxyflow.focus": {
        "description": "Focus/Pomodoro session tracking.",
        "actions": {
            "log": "voxyflow.focus.log",
            "analytics": "voxyflow.focus.analytics",
        },
    },
    "voxyflow.jobs": {
        "description": "Manage scheduled jobs.",
        "actions": {
            "list": "voxyflow.jobs.list",
            "create": "voxyflow.jobs.create",
            "update": "voxyflow.jobs.update",
            "delete": "voxyflow.jobs.delete",
        },
    },
    "voxyflow.workers": {
        "description": "Monitor and read worker task results.",
        "actions": {
            "list": "voxyflow.workers.list",
            "get_result": "voxyflow.workers.get_result",
            "read_artifact": "voxyflow.workers.read_artifact",
        },
    },
    "voxyflow.task": {
        "description": "Monitor and control running worker tasks.",
        "actions": {
            "peek": "voxyflow.task.peek",
            "cancel": "voxyflow.task.cancel",
        },
    },
}

# Set of tool names that belong to a consolidated group
_GROUPED_TOOL_NAMES: set[str] = set()
for _g in _TOOL_GROUPS.values():
    _GROUPED_TOOL_NAMES.update(_g["actions"].values())


def _build_consolidated_tools() -> list[dict]:
    """Build consolidated MCP tool list from _TOOL_GROUPS + ungrouped tools.

    Each group becomes a single tool with an `action` enum. Properties from all
    sub-tools are merged into a flat union schema. Auto-injectable params
    (project_id, card_id) are stripped when env vars are set.
    """
    injectable = _auto_injectable_params()
    consolidated: list[dict] = []

    for group_name, group_info in _TOOL_GROUPS.items():
        actions = group_info["actions"]
        action_names = list(actions.keys())

        # Collect all properties across actions
        all_props: dict[str, dict] = {}
        used_by: dict[str, list[str]] = {}  # prop_name → [action_names]

        for action_name, tool_name in actions.items():
            tool_def = _find_tool(tool_name)
            if not tool_def:
                continue
            for prop_name, prop_schema in tool_def["inputSchema"].get("properties", {}).items():
                if prop_name in injectable:
                    continue
                if prop_name not in all_props:
                    all_props[prop_name] = dict(prop_schema)
                    used_by[prop_name] = []
                else:
                    # Merge enums — take the union of all values
                    existing = all_props[prop_name]
                    if "enum" in existing and "enum" in prop_schema:
                        combined = list(dict.fromkeys(existing["enum"] + prop_schema["enum"]))
                        existing["enum"] = combined
                used_by[prop_name].append(action_name)

        # Annotate descriptions with action scope when not universal
        for prop_name, action_list in used_by.items():
            if set(action_list) != set(action_names):
                desc = all_props[prop_name].get("description", prop_name)
                all_props[prop_name]["description"] = f"{desc} ({', '.join(action_list)})"

        schema: dict = {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": action_names,
                    "description": "Action to perform",
                },
                **all_props,
            },
        }

        consolidated.append({
            "name": group_name,
            "description": group_info["description"],
            "inputSchema": schema,
            "_dispatch": dict(actions),  # action_name → original tool name
            "_scope": "voxyflow",
        })

    # Add ungrouped tools (singletons, system, memory, etc.)
    for tool_def in _TOOL_DEFINITIONS:
        if tool_def["name"] not in _GROUPED_TOOL_NAMES:
            # Auto-assign scope for voxyflow tools that don't have one
            if "_scope" not in tool_def and tool_def["name"].startswith("voxyflow."):
                tool_def["_scope"] = "voxyflow"
            consolidated.append(tool_def)

    return consolidated


# Built at module load — env vars are already set by the MCP subprocess
_CONSOLIDATED_MCP_TOOLS: list[dict] = _build_consolidated_tools()


# ---------------------------------------------------------------------------
# System tool handler registry
# ---------------------------------------------------------------------------

_SYSTEM_HANDLERS: dict[str, Any] = {}


def _get_system_handler(name: str):
    """Lazily load and cache system tool handlers.

    Handler closures live in `app.mcp_system_handlers` (extracted from this
    module in April 2026 to keep mcp_server.py navigable). We pass in the
    shared helpers so the handlers can stay module-free of this file, and
    we populate `_SYSTEM_HANDLERS` on first access so subsequent lookups
    are dict reads.
    """
    if not _SYSTEM_HANDLERS:
        from app.mcp_system_handlers import build_handlers
        _SYSTEM_HANDLERS.update(
            build_handlers(
                server=server if MCP_AVAILABLE else None,
                types_module=types if MCP_AVAILABLE else None,
                get_http_client=_get_http_client,
                enforce_task_scope=_enforce_task_scope,
                current_project_scope=_current_project_scope,
                active_scopes=_active_scopes,
            )
        )
    return _SYSTEM_HANDLERS.get(name)




# ---------------------------------------------------------------------------
# HTTP call helper
# ---------------------------------------------------------------------------

def _build_url_and_payload(
    method: str,
    path_template: str,
    payload_transformer: Any,
    params: dict,
) -> tuple[str, dict, dict]:
    """
    Returns (url, json_body, query_params) after substituting path params.
    """
    # Extract path variables from template (e.g. {project_id})
    import re
    path_vars = re.findall(r"\{(\w+)\}", path_template)
    path = path_template
    remaining_params = dict(params)

    env_pid = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip()
    pid_hard_scope = bool(env_pid) and env_pid != "system-main"

    for var in path_vars:
        llm_value = remaining_params.pop(var, None)
        env_value = os.environ.get(f"VOXYFLOW_{var.upper()}", "").strip() or None

        # Hard boundary: in a project-scoped chat, env-supplied project_id
        # always wins over whatever the LLM passes. The schema strips it, but
        # some models re-emit it anyway — this enforces the invariant so a
        # stray/guessed UUID can't leak cards into the wrong project.
        if var == "project_id" and pid_hard_scope:
            if llm_value and llm_value != env_pid:
                logger.warning(
                    f"[MCP] Ignoring LLM-supplied project_id={llm_value!r}; "
                    f"forcing current-project scope {env_pid!r}"
                )
            value = env_pid
        else:
            value = llm_value if llm_value is not None else env_value

        if value is None:
            raise ValueError(f"Missing required path parameter: {var}")
        path = path.replace(f"{{{var}}}", str(value))

    url = path

    if payload_transformer is not None:
        body = payload_transformer(remaining_params)
    else:
        body = remaining_params

    # GET/DELETE → query params, others → JSON body
    if method in ("GET", "DELETE"):
        return url, {}, body  # body used as query params for GET
    else:
        return url, body, {}


async def _call_api(tool_def: dict, params: dict) -> dict:
    """Execute a tool — either via REST API (_http) or direct handler (_handler)."""

    # System tools use direct async handlers
    if "_handler" in tool_def:
        handler_name = tool_def["_handler"]
        handler = _get_system_handler(handler_name)
        if handler is None:
            return {"success": False, "error": f"Handler not found: {handler_name}"}
        try:
            return await handler(params)
        except Exception as e:
            logger.error(f"System tool handler failed: {handler_name} → {e}")
            return {"success": False, "error": str(e)}

    # Voxyflow REST API tools
    method, path_template, payload_transformer = tool_def["_http"]

    url, json_body, query_params = _build_url_and_payload(
        method, path_template, payload_transformer, params
    )

    logger.debug(f"MCP → {method} {url} body={json_body} query={query_params}")

    client = _get_http_client()
    resp = await client.request(
        method=method,
        url=url,
        json=json_body if json_body else None,
        params=query_params if query_params else None,
    )

    if resp.status_code == 204:
        return {"success": True, "status": "deleted"}

    try:
        data = resp.json()
    except Exception:
        data = {"text": resp.text}

    if resp.status_code >= 400:
        return {
            "success": False,
            "error": f"HTTP {resp.status_code}",
            "detail": data,
        }

    # Ensure success flag is present so the frontend tool:executed handler
    # can distinguish successes (it checks result.success).
    if isinstance(data, dict) and "success" not in data:
        data["success"] = True
    return data


# ---------------------------------------------------------------------------
# Build MCP tool list (consolidated, role-filtered, schema-stripped)
# ---------------------------------------------------------------------------

def _strip_auto_injected(schema: dict, injectable: set[str]) -> dict:
    """Return a copy of inputSchema with auto-injectable params removed."""
    if not injectable:
        return schema
    props = schema.get("properties", {})
    required = schema.get("required", [])
    to_strip = injectable & props.keys()
    if not to_strip:
        return schema
    new_schema = dict(schema)
    new_schema["properties"] = {k: v for k, v in props.items() if k not in to_strip}
    new_schema["required"] = [r for r in required if r not in to_strip]
    if not new_schema["required"]:
        new_schema.pop("required", None)
    return new_schema


def _visible_tools_consolidated() -> list[dict]:
    """Return consolidated tool definitions visible to the current role + active scopes."""
    role = VOXYFLOW_MCP_ROLE
    if role == "dispatcher":
        return [t for t in _CONSOLIDATED_MCP_TOOLS if t.get("_role", "all") != "worker"]
    # Workers: filter by active scopes
    return [t for t in _CONSOLIDATED_MCP_TOOLS if t.get("_scope", "core") in _active_scopes]


def _visible_tools_flat() -> list[dict]:
    """Return individual (flat) tool definitions visible to the current role + active scopes."""
    role = VOXYFLOW_MCP_ROLE
    if role == "dispatcher":
        return [t for t in _TOOL_DEFINITIONS if t.get("_role", "all") != "worker"]
    # Workers: filter by active scopes
    return [t for t in _TOOL_DEFINITIONS if t.get("_scope", "core") in _active_scopes]


def _public_tool_defs() -> list[dict]:
    """Return flat individual tool definitions without internal keys, with
    auto-injectable params stripped. Used by the inline/native SDK path."""
    injectable = _auto_injectable_params()
    result = []
    for t in _visible_tools_flat():
        cleaned = {k: v for k, v in t.items() if not k.startswith("_")}
        if injectable:
            cleaned["inputSchema"] = _strip_auto_injected(cleaned["inputSchema"], injectable)
        result.append(cleaned)
    return result


# ---------------------------------------------------------------------------
# MCP Server (only instantiated if mcp package is available)
# ---------------------------------------------------------------------------

if MCP_AVAILABLE:
    server = Server("voxyflow")

    def _find_consolidated(name: str) -> dict | None:
        """Find a tool in the consolidated list (for MCP dispatch)."""
        for t in _CONSOLIDATED_MCP_TOOLS:
            if t["name"] == name:
                return t
        return None

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Expose consolidated tools filtered by role, injectable params stripped."""
        injectable = _auto_injectable_params()
        tools = []
        for defn in _visible_tools_consolidated():
            schema = defn["inputSchema"]
            # Strip injectable params from ungrouped tools (consolidated already stripped)
            if injectable and "_dispatch" not in defn:
                schema = _strip_auto_injected(schema, injectable)
            tools.append(
                Tool(
                    name=defn["name"],
                    description=defn["description"],
                    inputSchema=schema,
                )
            )
        logger.info(f"[MCP] list_tools → role={VOXYFLOW_MCP_ROLE}, scopes={sorted(_active_scopes)}, {len(tools)} tools")
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """Route an MCP tool call — supports consolidated and individual tools."""
        args = dict(arguments or {})

        # 1. Try consolidated tool first
        consolidated = _find_consolidated(name)
        if consolidated and "_dispatch" in consolidated:
            action = args.pop("action", None)
            if not action:
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Missing required parameter: action",
                }))]
            original_name = consolidated["_dispatch"].get(action)
            if not original_name:
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Unknown action '{action}' for tool '{name}'. Valid: {list(consolidated['_dispatch'].keys())}",
                }))]
            tool_def = _find_tool(original_name)
            if tool_def is None:
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Internal error: action '{action}' maps to unknown tool '{original_name}'",
                }))]
            logger.debug(f"[MCP] Consolidated dispatch: {name}.{action} → {original_name}")
        else:
            # 2. Try individual tool (backward compat + ungrouped tools)
            tool_def = _find_tool(name)
            if tool_def is None:
                return [TextContent(type="text", text=json.dumps({
                    "success": False,
                    "error": f"Unknown tool: {name}",
                }))]
            # Log deprecation if this is a grouped tool called by old name
            if name in _GROUPED_TOOL_NAMES:
                logger.warning(f"[MCP] Deprecated individual tool call: {name} — use consolidated group instead")

        # Enforce role-based access (defense in depth — even if list_tools filters)
        if VOXYFLOW_MCP_ROLE == "dispatcher" and tool_def.get("_role") == "worker":
            logger.warning(f"[MCP] Blocked dispatcher from calling worker-only tool: {name}")
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Tool '{name}' is not available to the dispatcher. Delegate this task to a worker.",
            }))]

        try:
            result = await _call_api(tool_def, args)
        except Exception as e:
            logger.error(f"MCP tool call failed: {name} → {e}")
            result = {"success": False, "error": str(e)}

        return [TextContent(type="text", text=json.dumps(result, default=str, indent=2))]

else:
    server = None
    logger.warning(
        "mcp package not installed — MCP server disabled. "
        "Install with: pip install mcp>=1.0.0"
    )


# ---------------------------------------------------------------------------
# Helpers for the SSE route (used without mcp package for listing)
# ---------------------------------------------------------------------------

def get_tool_list() -> list[dict]:
    """Return all MCP tool definitions (public, no internal keys)."""
    return _public_tool_defs()
