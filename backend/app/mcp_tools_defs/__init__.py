"""MCP tool definitions, split by domain.

Each submodule exports plain ``list[dict]`` tool-def lists; the aggregated
catalog lives in ``app.mcp_tool_defs._TOOL_DEFINITIONS`` (the facade), which
concatenates them in the original order. Add new tools to the submodule whose
domain matches — and remember the role-set invariant in
``app/tools/registry.py`` (CLAUDE.md is the source of truth).
"""

from __future__ import annotations

from .kanban import KANBAN_TOOLS
from .memory_kg import MEMORY_KG_TOOLS
from .ops_jobs import OPS_JOBS_TOOLS
from .postprocess import (
    _CARD_LIST_KEEP,
    _minimal_card,
    _minimize_card_list,
    _minimize_card_list_archived,
)
from .script import SCRIPT_TOOLS
from .skills import SKILL_TOOLS
from .system_tools import SYSTEM_TOOLS
from .wiki_docs_ai import WIKI_DOCS_AI_TOOLS
from .workers_tasks import (
    DELEGATE_TOOLS,
    ENDPOINT_TOOLS,
    TASK_STEER_TOOLS,
    WORKER_LIFECYCLE_TOOLS,
    WORKERS_MONITOR_TOOLS,
)

__all__ = [
    "KANBAN_TOOLS",
    "WIKI_DOCS_AI_TOOLS",
    "WORKERS_MONITOR_TOOLS",
    "OPS_JOBS_TOOLS",
    "SYSTEM_TOOLS",
    "WORKER_LIFECYCLE_TOOLS",
    "MEMORY_KG_TOOLS",
    "TASK_STEER_TOOLS",
    "ENDPOINT_TOOLS",
    "DELEGATE_TOOLS",
    "SKILL_TOOLS",
    "SCRIPT_TOOLS",
    "_CARD_LIST_KEEP",
    "_minimal_card",
    "_minimize_card_list",
    "_minimize_card_list_archived",
]
