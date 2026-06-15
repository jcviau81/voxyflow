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

from app.tools.registry import TOOLS_DISPATCHER

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
    """Return (and lazily create) the module-level persistent HTTP client.

    Forwards ``VOXYFLOW_CHAT_ID`` as ``X-Voxyflow-Chat-Id`` so the backend
    can attribute side effects (e.g. cards created in a turn) to the
    originating dispatcher chat — see ``turn_card_registry``.
    """
    global _http_client
    if _http_client is None:
        headers = {}
        chat_id = os.environ.get("VOXYFLOW_CHAT_ID", "").strip()
        if chat_id:
            headers["X-Voxyflow-Chat-Id"] = chat_id
        _http_client = httpx.AsyncClient(
            base_url=VOXYFLOW_API_BASE,
            timeout=30.0,
            headers=headers or None,
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

    - workspace_id: stripped when VOXYFLOW_WORKSPACE_ID is a real UUID (not "system-main")
    - card_id: stripped when VOXYFLOW_CARD_ID is set
    """
    injectable = set()
    pid = os.environ.get("VOXYFLOW_WORKSPACE_ID", "").strip()
    if pid and pid != "system-main":
        injectable.add("workspace_id")
    cid = os.environ.get("VOXYFLOW_CARD_ID", "").strip()
    if cid:
        injectable.add("card_id")
    return injectable


def _injectable_for_tool(tool_name: str, injectable: set[str]) -> set[str]:
    """Params actually auto-injected for *tool_name*.

    Workspace-ENTITY tools (voxyflow.workspace.*) keep workspace_id visible in
    their schema: there workspace_id identifies the TARGET workspace
    (get/update/delete/archive another workspace), not the scope of a child
    resource — stripping it would make other workspaces unreachable and let
    the env override silently redirect deletes onto the current workspace.
    """
    if tool_name.startswith("voxyflow.workspace."):
        return injectable - {"workspace_id"}
    return injectable


# ---------------------------------------------------------------------------
# Workspace scoping for ledger / session tools
# ---------------------------------------------------------------------------
# Worker ledger, CLI sessions, and task-control tools default to the current
# workspace (like memory_search), preventing cross-workspace leakage. Callers opt
# out via scope="all" when they really need a system-wide view.

def _current_workspace_scope() -> tuple[str, bool]:
    """Resolve the active workspace scope from VOXYFLOW_WORKSPACE_ID.

    Returns (workspace_id, is_workspace_scoped):
      - ("<uuid>", True)  → real workspace chat, should filter by that workspace
      - ("", False)       → general chat (empty or "system-main"), no filter
    """
    pid = os.environ.get("VOXYFLOW_WORKSPACE_ID", "").strip()
    if pid and pid != "system-main":
        return pid, True
    return "", False


async def _lookup_task_workspace(task_id: str) -> str | None:
    """Resolve a worker task's workspace_id via live session store, then DB.

    Returns the workspace_id string (possibly empty), or None when the task
    is unknown in both stores.
    """
    try:
        from app.services.worker_session_store import get_worker_session_store
        session = get_worker_session_store().get_session(task_id)
        if session is not None:
            return (session.get("workspace_id") or "").strip()
    except Exception as live_err:
        logger.debug(f"[mcp._lookup_task_workspace] live lookup failed: {live_err}")

    try:
        from app.database import async_session, WorkerTask
        from sqlalchemy import select
        async with async_session() as db:
            row = (await db.execute(
                select(WorkerTask).where(WorkerTask.id == task_id)
            )).scalar_one_or_none()
            if row is not None:
                return (row.workspace_id or "").strip()
    except Exception as db_err:
        # Don't return early — fall through to the artifact-frontmatter lookup
        # below so a transient DB failure doesn't make finished tasks (whose
        # metadata is readable on disk) report as "not found".
        logger.warning(f"[mcp._lookup_task_workspace] DB lookup failed for {task_id}: {db_err}")

    # Last resort: artifact frontmatter on disk (no TTL). Lets the dispatcher
    # still scope-check + read tasks whose live/DB rows have been GC'd.
    try:
        from app.services.worker_artifact_store import read_artifact_meta
        meta = read_artifact_meta(task_id)
        if meta is not None:
            return (meta.get("workspace_id") or "").strip()
    except Exception as art_err:
        logger.debug(f"[mcp._lookup_task_workspace] artifact lookup failed: {art_err}")
    return None


async def _enforce_task_scope(task_id: str, scope: str | None) -> dict | None:
    """Return an error dict if the task falls outside the active workspace scope.

    scope handling:
      - "all" (case-insensitive) → bypass the check, return None
      - otherwise                → strict: task must belong to the current
                                    workspace when VOXYFLOW_WORKSPACE_ID is set
    In general chat (no workspace scope active), the check is a no-op.
    """
    if (scope or "").lower() == "all":
        return None
    current_pid, scoped = _current_workspace_scope()
    if not scoped:
        return None
    task_pid = await _lookup_task_workspace(task_id)
    if task_pid is None:
        return {"success": False, "error": f"Task {task_id} not found."}
    if task_pid != current_pid:
        return {
            "success": False,
            "error": (
                f"Task {task_id} belongs to a different workspace "
                f"(workspace_id={task_pid or '∅'}) and is not visible from the "
                f"current workspace scope. Pass scope='all' to override."
            ),
        }
    return None


# ---------------------------------------------------------------------------
# Tool Consolidation — groups of individual tools exposed as single MCP tools
# ---------------------------------------------------------------------------

_TOOL_GROUPS: dict[str, dict] = {
    "voxyflow.card": {
        "description": "Manage cards/tasks. workspace_id and card_id auto-injected from context.",
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
    "voxyflow.workspace": {
        "description": "Manage workspaces in Voxyflow.",
        "actions": {
            "create": "voxyflow.workspace.create",
            "list": "voxyflow.workspace.list",
            "get": "voxyflow.workspace.get",
            "update": "voxyflow.workspace.update",
            "delete": "voxyflow.workspace.delete",
            "export": "voxyflow.workspace.export",
            "archive": "voxyflow.workspace.archive",
            "restore": "voxyflow.workspace.restore",
        },
    },
    "voxyflow.wiki": {
        "description": "Manage wiki pages. workspace_id auto-injected from context.",
        "actions": {
            "list": "voxyflow.wiki.list",
            "create": "voxyflow.wiki.create",
            "get": "voxyflow.wiki.get",
            "update": "voxyflow.wiki.update",
            "delete": "voxyflow.wiki.delete",
        },
    },
    "voxyflow.ai": {
        "description": "AI-powered workspace analysis. workspace_id auto-injected from context.",
        "actions": {
            "standup": "voxyflow.ai.standup",
            "brief": "voxyflow.ai.brief",
            "health": "voxyflow.ai.health",
            "prioritize": "voxyflow.ai.prioritize",
            "review_code": "voxyflow.ai.review_code",
        },
    },
    "voxyflow.doc": {
        "description": "Manage workspace documents. workspace_id auto-injected from context.",
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
            "ack_artifact": "voxyflow.workers.ack_artifact",
            "list_unread": "voxyflow.workers.list_unread",
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


# ---------------------------------------------------------------------------
# Bulk-capable tools — map tool name → the path param that may be a LIST.
#
# Only operations where the SAME action + params apply to every id belong here
# (the id is the only thing that varies): deletes, archive/restore, move-to-
# status. NOT create/update/enrich — those carry per-item content, so a list
# makes no sense. When a caller passes the plural (e.g. card_ids) instead of
# the singular, the dispatch loops the existing single-id call N times locally,
# so the model makes ONE tool call instead of N (which used to make the chat
# sit silent for a minute while it deleted things one by one).
# ---------------------------------------------------------------------------
_BULK_TOOLS: dict[str, str] = {
    "voxyflow.card.move": "card_id",
    "voxyflow.card.archive": "card_id",
    "voxyflow.card.delete": "card_id",
    "voxyflow.card.restore": "card_id",
    "voxyflow.workspace.delete": "workspace_id",
    "voxyflow.workspace.archive": "workspace_id",
    "voxyflow.workspace.restore": "workspace_id",
    "voxyflow.doc.delete": "document_id",
    "voxyflow.wiki.delete": "page_id",
    "voxyflow.card.relation.delete": "relation_id",
    "voxyflow.card.time.delete": "entry_id",
    "voxyflow.card.checklist.delete": "item_id",
    "memory.delete": "id",
}


def _bulk_plural(param: str) -> str:
    """card_id → card_ids, page_id → page_ids, etc."""
    return param + "s"


def _bulk_array_prop(bulk_param: str) -> dict:
    """Schema for the plural ids array (shared by consolidated + flat paths)."""
    plural = _bulk_plural(bulk_param)
    return {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            f"PREFERRED for acting on multiple items: pass ALL {bulk_param}s here "
            f"in ONE call. Never call this action in a loop / repeatedly with a "
            f"single {bulk_param} — collect the ids and pass {plural} once."
        ),
    }


def _build_consolidated_tools() -> list[dict]:
    """Build consolidated MCP tool list from _TOOL_GROUPS + ungrouped tools.

    Each group becomes a single tool with an `action` enum. Properties from all
    sub-tools are merged into a flat union schema. Auto-injectable params
    (workspace_id, card_id) are stripped when env vars are set.
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
            # Bulk-capable action → expose a plural ids array alongside the
            # singular so the model can apply this action to many in one call.
            bulk_param = _BULK_TOOLS.get(tool_name)
            if bulk_param:
                plural = _bulk_plural(bulk_param)
                if plural not in all_props:
                    all_props[plural] = _bulk_array_prop(bulk_param)
                    used_by[plural] = []
                used_by[plural].append(action_name)
            for prop_name, prop_schema in tool_def["inputSchema"].get("properties", {}).items():
                if prop_name in _injectable_for_tool(tool_name, injectable):
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
                current_workspace_scope=_current_workspace_scope,
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
    tool_name: str = "",
) -> tuple[str, dict, dict]:
    """
    Returns (url, json_body, query_params) after substituting path params.
    """
    # Extract path variables from template (e.g. {workspace_id})
    import re
    path_vars = re.findall(r"\{(\w+)\}", path_template)
    path = path_template
    remaining_params = dict(params)

    env_pid = os.environ.get("VOXYFLOW_WORKSPACE_ID", "").strip()
    pid_hard_scope = bool(env_pid) and env_pid != "system-main"
    # Workspace-ENTITY tools (voxyflow.workspace.*) are exempt from the hard
    # scope below: there workspace_id IS the target entity (get/update/delete/
    # archive ANOTHER workspace), not the parent scope of a child resource.
    # Forcing the env value would silently redirect e.g. "delete workspaces A
    # and B" onto the CURRENT workspace — irreversible data loss. Explicit ids
    # are honored; an omitted id still falls back to the env (current) one.
    workspace_entity_tool = tool_name.startswith("voxyflow.workspace.")

    for var in path_vars:
        llm_value = remaining_params.pop(var, None)
        env_value = os.environ.get(f"VOXYFLOW_{var.upper()}", "").strip() or None

        # Hard boundary: in a workspace-scoped chat, env-supplied workspace_id
        # always wins over whatever the LLM passes. The schema strips it, but
        # some models re-emit it anyway — this enforces the invariant so a
        # stray/guessed UUID can't leak cards into the wrong workspace.
        if var == "workspace_id" and pid_hard_scope and not workspace_entity_tool:
            if llm_value and llm_value != env_pid:
                logger.warning(
                    f"[MCP] Ignoring LLM-supplied workspace_id={llm_value!r}; "
                    f"forcing current-workspace scope {env_pid!r}"
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

    # Bulk fan-out: a bulk-capable tool given the plural ids list runs the
    # single-id op once per id, locally, and returns an aggregate. One model
    # tool call → N fast local REST calls (no per-item model round-trips).
    bulk_param = _BULK_TOOLS.get(tool_def.get("name", ""))
    if bulk_param:
        plural = _bulk_plural(bulk_param)
        ids = params.get(plural)
        if isinstance(ids, list) and ids:
            rest = {k: v for k, v in params.items() if k != plural}
            ok_items: list[dict] = []
            errors: list[dict] = []
            for _id in ids:
                try:
                    r = await _call_api(tool_def, {**rest, bulk_param: _id})
                    succeeded = r.get("success", True) if isinstance(r, dict) else True
                    (ok_items if succeeded else errors).append({"id": _id, "result": r})
                except Exception as e:
                    errors.append({"id": _id, "error": str(e)[:200]})
            return {
                "success": len(errors) == 0,
                "bulk": True,
                "requested": len(ids),
                "succeeded": len(ok_items),
                "failed": len(errors),
                "errors": errors,
            }

    # System tools use direct async handlers
    if "_handler" in tool_def:
        handler_name = tool_def["_handler"]
        handler = _get_system_handler(handler_name)
        if handler is None:
            return {"success": False, "error": f"Handler not found: {handler_name}"}
        try:
            result = await handler(params)
            _journal_if_reversible(tool_def.get("name", ""), params, result)
            return result
        except Exception as e:
            logger.error(f"System tool handler failed: {handler_name} → {e}")
            return {"success": False, "error": str(e)}

    # Voxyflow REST API tools
    method, path_template, payload_transformer = tool_def["_http"]

    # Env-scoped ids (workspace_id/card_id) are stripped from schemas in scoped
    # chats, but only PATH template vars were injected back. Tools that take
    # them as BODY/QUERY params (e.g. voxyflow.focus.log) would silently lose
    # attribution — inject the env value when the tool's schema declares the
    # param and the model didn't (couldn't) pass it.
    injectable = _auto_injectable_params()
    if injectable:
        schema_props = (tool_def.get("inputSchema") or {}).get("properties", {})
        for var in injectable & set(schema_props):
            if not params.get(var):
                env_value = os.environ.get(f"VOXYFLOW_{var.upper()}", "").strip()
                if env_value:
                    params = {**params, var: env_value}

    url, json_body, query_params = _build_url_and_payload(
        method, path_template, payload_transformer, params,
        tool_name=tool_def.get("name", ""),
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

    # Optional response shaping — used by list tools that would otherwise
    # dump huge full-object payloads into the LLM context. Declared per-tool
    # as a `_post_process` callable on the tool def in mcp_tool_defs.py.
    post = tool_def.get("_post_process")
    if callable(post):
        try:
            data = post(data)
        except Exception as e:
            logger.warning(
                f"[MCP] _post_process for {tool_def.get('name')} failed: {e} — returning raw response"
            )

    # Ensure success flag is present so the frontend tool:executed handler
    # can distinguish successes (it checks result.success).
    if isinstance(data, dict) and "success" not in data:
        data["success"] = True
    if isinstance(data, dict) and data.get("success"):
        _journal_if_reversible(tool_def.get("name", ""), params, data)
    return data


def _journal_if_reversible(tool_name: str, params: dict, result: dict) -> None:
    """Record a reversible action in the per-chat undo journal.

    Only runs when ``VOXYFLOW_CHAT_ID`` is set, the result looks successful,
    and :func:`undo_journal.derive_inverse` knows an inverse for the tool.
    Failures are swallowed — journaling is never allowed to break the call.
    """
    try:
        from app.services import undo_journal
        import os
        chat_id = os.environ.get("VOXYFLOW_CHAT_ID", "").strip()
        if not chat_id:
            return
        if not isinstance(result, dict) or result.get("success") is False:
            return
        derived = undo_journal.derive_inverse(tool_name, params, result)
        if not derived:
            return
        inv_tool, inv_args, label = derived
        undo_journal.record(
            chat_id=chat_id,
            label=label,
            forward_tool=tool_name,
            forward_args=params or {},
            inverse_tool=inv_tool,
            inverse_args=inv_args,
        )
    except Exception as e:
        logger.debug(f"_journal_if_reversible failed (non-fatal): {e}")


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


def _allowed_tool_names_for_role(role: str) -> set[str] | None:
    """Return registry-defined tool names for dispatcher roles, or None for scope mode.

    All dispatchers — any model/provider — use the single "dispatcher" set.
    "dispatcher_codex" is a legacy alias kept only so a stray value never
    escalates to worker scope; it maps to the same dispatcher tools.
    """
    if role in ("dispatcher", "dispatcher_codex"):
        return TOOLS_DISPATCHER
    return None


def _filter_consolidated_by_names(tools: list[dict], allowed_names: set[str]) -> list[dict]:
    """Filter consolidated MCP tools using registry tool names as source of truth."""
    visible: list[dict] = []
    for tool in tools:
        candidate = dict(tool)
        dispatch = candidate.get("_dispatch") or {}
        if dispatch:
            allowed_dispatch = {
                action: tool_name
                for action, tool_name in dispatch.items()
                if tool_name in allowed_names
            }
            if not allowed_dispatch:
                continue
            schema = dict(candidate.get("inputSchema") or {})
            properties = dict(schema.get("properties") or {})
            action_schema = dict(properties.get("action") or {})
            action_schema["enum"] = [
                action for action in action_schema.get("enum", [])
                if action in allowed_dispatch
            ]
            properties["action"] = action_schema
            schema["properties"] = properties
            candidate["inputSchema"] = schema
            candidate["_dispatch"] = allowed_dispatch
            visible.append(candidate)
            continue
        if candidate.get("name") in allowed_names:
            visible.append(candidate)
    return visible


def _visible_tools_consolidated() -> list[dict]:
    """Return consolidated tool definitions visible to the current role + active scopes."""
    role = VOXYFLOW_MCP_ROLE
    allowed = _allowed_tool_names_for_role(role)
    if allowed is not None:
        return _filter_consolidated_by_names(_CONSOLIDATED_MCP_TOOLS, allowed)
    # Workers: filter by active scopes
    return [t for t in _CONSOLIDATED_MCP_TOOLS if t.get("_scope", "core") in _active_scopes]


def _visible_tools_flat() -> list[dict]:
    """Return individual (flat) tool definitions visible to the current role + active scopes."""
    role = VOXYFLOW_MCP_ROLE
    allowed = _allowed_tool_names_for_role(role)
    if allowed is not None:
        return [dict(t) for t in _TOOL_DEFINITIONS if t.get("name") in allowed]
    # Workers: filter by active scopes
    return [t for t in _TOOL_DEFINITIONS if t.get("_scope", "core") in _active_scopes]


def _public_tool_defs() -> list[dict]:
    """Return flat individual tool definitions without internal keys, with
    auto-injectable params stripped. Used by the inline/native SDK path."""
    injectable = _auto_injectable_params()
    result = []
    for t in _visible_tools_flat():
        name = t.get("name", "")
        cleaned = {k: v for k, v in t.items() if not k.startswith("_")}
        if injectable:
            cleaned["inputSchema"] = _strip_auto_injected(
                cleaned["inputSchema"], _injectable_for_tool(name, injectable)
            )
        # Bulk-capable tools advertise the plural ids array on the flat path
        # too — same contract as the consolidated builder, so native-SDK/SSE
        # dispatchers can also do one call for N ids (_call_api honors it).
        bulk_param = _BULK_TOOLS.get(name)
        if bulk_param:
            schema = dict(cleaned["inputSchema"])
            props = dict(schema.get("properties") or {})
            props[_bulk_plural(bulk_param)] = _bulk_array_prop(bulk_param)
            schema["properties"] = props
            cleaned["inputSchema"] = schema
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
                schema = _strip_auto_injected(
                    schema, _injectable_for_tool(defn["name"], injectable)
                )
            tools.append(
                Tool(
                    name=defn["name"],
                    description=defn["description"],
                    inputSchema=schema,
                )
            )
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
            original_name = name

        # Enforce registry-defined dispatcher access (defense in depth — even if list_tools filters).
        allowed_names = _allowed_tool_names_for_role(VOXYFLOW_MCP_ROLE)
        if allowed_names is not None and original_name not in allowed_names:
            logger.warning(
                "[MCP] Blocked %s from calling unavailable tool: %s",
                VOXYFLOW_MCP_ROLE, original_name,
            )
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Tool '{original_name}' is not available to {VOXYFLOW_MCP_ROLE}. Delegate this task to a worker.",
            }))]

        try:
            result = await _call_api(tool_def, args)
        except Exception as e:
            logger.error(f"MCP tool call failed: {name} → {e}")
            result = {"success": False, "error": str(e)}

        return [TextContent(type="text", text=_serialize_result(original_name, result))]

else:
    server = None
    logger.warning(
        "mcp package not installed — MCP server disabled. "
        "Install with: pip install mcp>=1.0.0"
    )


# Hard ceiling on a single tool result. Past it, the Claude CLI spills the
# result to a temp file the dispatcher has no tools to read — a dead end.
# Owning the truncation lets the notice teach the model how to recover.
MAX_TOOL_RESULT_CHARS = 20_000


def _serialize_result(tool_name: str, result) -> str:
    """JSON-serialize a tool result, truncating oversized payloads in-band.

    Compact separators (no indent) — indentation inflated payloads ~15-30%
    for zero model benefit.
    """
    payload = json.dumps(result, default=str, separators=(",", ":"))
    if len(payload) <= MAX_TOOL_RESULT_CHARS:
        return payload
    logger.warning(
        "[MCP] %s result truncated: %d chars > %d cap",
        tool_name, len(payload), MAX_TOOL_RESULT_CHARS,
    )
    return (
        payload[:MAX_TOOL_RESULT_CHARS]
        + f'\n…[TRUNCATED: full result was {len(payload)} chars. '
        "Do NOT delegate a worker and do NOT try to read any file for the rest. "
        "Re-issue a narrower call instead: fetch a single item (.get), "
        "use filters/offset/length params, or a smaller limit.]"
    )


# ---------------------------------------------------------------------------
# Helpers for the SSE route (used without mcp package for listing)
# ---------------------------------------------------------------------------

def get_tool_list() -> list[dict]:
    """Return all MCP tool definitions (public, no internal keys)."""
    return _public_tool_defs()
