"""_TOOL_DEFINITIONS — the MCP tool catalog (aggregator facade).

Extracted from ``app/mcp_server.py`` in H8 — this module is pure data.
The actual tool defs now live in the ``app/mcp_tools_defs/`` package, split
by domain; this module concatenates them in the original order so
``from app.mcp_tool_defs import _TOOL_DEFINITIONS`` keeps working unchanged.

Each entry describes one MCP tool:

* ``name``           — tool ID used by MCP ``call_tool``
* ``description``    — LLM-facing doc
* ``inputSchema``    — JSON Schema for arguments
* ``_http``          — ``(method, path, payload_fn)`` for REST-backed tools
* ``_handler``       — name of an async handler for non-HTTP tools (``system.*``, ``web.*``, memory, KG, etc.)
* ``_scope`` / ``_role`` / ``_cat`` — optional metadata used by the consolidator / role filter

All runtime behavior stays in ``mcp_server.py``; this module only holds the list.

Adding a tool? Put the def in the matching ``app/mcp_tools_defs/`` submodule
(kanban / wiki_docs_ai / workers_tasks / ops_jobs / system_tools / memory_kg)
and update the role sets in ``app/tools/registry.py`` per the CLAUDE.md invariant.
"""

from __future__ import annotations

from app.mcp_tools_defs import (
    DELEGATE_TOOLS,
    ENDPOINT_TOOLS,
    KANBAN_TOOLS,
    MEMORY_KG_TOOLS,
    OPS_JOBS_TOOLS,
    SYSTEM_TOOLS,
    TASK_STEER_TOOLS,
    WIKI_DOCS_AI_TOOLS,
    WORKER_LIFECYCLE_TOOLS,
    WORKERS_MONITOR_TOOLS,
    _CARD_LIST_KEEP,
    _minimal_card,
    _minimize_card_list,
    _minimize_card_list_archived,
)

__all__ = [
    "_TOOL_DEFINITIONS",
    "_CARD_LIST_KEEP",
    "_minimal_card",
    "_minimize_card_list",
    "_minimize_card_list_archived",
]

# Concatenation order matches the original monolithic list exactly — anything
# order-sensitive (display, first-match lookups) stays byte-identical.
_TOOL_DEFINITIONS: list[dict] = [
    *KANBAN_TOOLS,
    *WIKI_DOCS_AI_TOOLS,
    *WORKERS_MONITOR_TOOLS,
    *OPS_JOBS_TOOLS,
    *SYSTEM_TOOLS,
    *WORKER_LIFECYCLE_TOOLS,
    *MEMORY_KG_TOOLS,
    *TASK_STEER_TOOLS,
    *ENDPOINT_TOOLS,
    *DELEGATE_TOOLS,
]
