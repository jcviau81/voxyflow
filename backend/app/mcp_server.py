"""Voxyflow MCP Server — wraps all Voxyflow REST API endpoints as MCP tools.

This module is a thin HTTP client over the Voxyflow REST API (localhost:8000).
It does NOT access the database directly; every tool call goes through the API.

Transport modes:
  - SSE  → imported by routes/mcp.py  (web clients)
  - Stdio → imported by backend/mcp_stdio.py  (Claude Code, Cursor, etc.)
"""

import json
import logging
import os
from typing import Any

import httpx

try:
    from mcp.server import Server
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
# MCP Tool definitions
# ---------------------------------------------------------------------------

_TOOL_DEFINITIONS: list[dict] = [
    # ---- Notes (Main Board / FreeBoard) ------------------------------------
    {
        "name": "voxyflow.note.add",
        "description": "Add a sticky note or reminder to the Voxyflow main board (FreeBoard).",
        "inputSchema": {
            "type": "object",
            "required": ["content"],
            "properties": {
                "content": {"type": "string", "description": "Text content of the note"},
                "color": {
                    "type": "string",
                    "enum": ["yellow", "blue", "green", "pink", "purple", "orange"],
                    "description": "Background color of the note",
                },
            },
        },
        "_http": ("POST", "/api/notes", lambda p: p),
    },
    {
        "name": "voxyflow.note.list",
        "description": "List all notes on the Voxyflow main board.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_http": ("GET", "/api/tools/definitions", None),
    },

    # ---- Projects ----------------------------------------------------------
    {
        "name": "voxyflow.project.create",
        "description": "Create a new project in Voxyflow.",
        "inputSchema": {
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {"type": "string", "description": "Project name"},
                "description": {"type": "string", "description": "Project description"},
                "tech_stack": {"type": "string", "description": "Technology stack (comma-separated)"},
                "github_url": {"type": "string", "description": "GitHub repository URL"},
                "github_repo": {"type": "string", "description": "GitHub repo in owner/repo format"},
                "local_path": {"type": "string", "description": "Local filesystem path to project"},
            },
        },
        "_http": ("POST", "/api/projects", None),
    },
    {
        "name": "voxyflow.project.list",
        "description": "List all projects in Voxyflow.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_http": ("GET", "/api/projects", None),
    },
    {
        "name": "voxyflow.project.get",
        "description": "Get details of a specific project including its cards.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
        },
        "_http": ("GET", "/api/projects/{project_id}", None),
    },
    {
        "name": "voxyflow.project.delete",
        "description": "Delete a project and all its cards (irreversible).",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID to delete"},
            },
        },
        "_http": ("DELETE", "/api/projects/{project_id}", None),
    },
    {
        "name": "voxyflow.project.export",
        "description": "Export a project as a JSON snapshot (all cards, wiki, metadata).",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID to export"},
            },
        },
        "_http": ("GET", "/api/projects/{project_id}/export", None),
    },

    # ---- Cards -------------------------------------------------------------
    {
        "name": "voxyflow.card.create",
        "description": "Create a new card/task in a project.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id", "title"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "title": {"type": "string", "description": "Card title"},
                "description": {"type": "string", "description": "Card description"},
                "status": {
                    "type": "string",
                    "enum": ["idea", "todo", "in_progress", "done"],
                    "description": "Initial status (default: idea)",
                },
                "priority": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 4,
                    "description": "Priority: 0=none, 1=low, 2=medium, 3=high, 4=critical",
                },
                "agent_type": {
                    "type": "string",
                    "enum": ["ember", "researcher", "coder", "designer", "architect", "writer", "qa"],
                    "description": "Agent type to assign (auto-routed if omitted)",
                },
            },
        },
        "_http": ("POST", "/api/projects/{project_id}/cards", None),
    },
    {
        "name": "voxyflow.card.list",
        "description": "List all cards for a project.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
        },
        "_http": ("GET", "/api/projects/{project_id}/cards", None),
    },
    {
        "name": "voxyflow.card.get",
        "description": "Get details of a specific card.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
            },
        },
        "_http": ("GET", "/api/cards/{card_id}", None),
    },
    {
        "name": "voxyflow.card.update",
        "description": "Update a card's title, description, priority, or status.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID to update"},
                "title": {"type": "string", "description": "New title"},
                "description": {"type": "string", "description": "New description"},
                "priority": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 4,
                    "description": "New priority (0=none, 1=low, 2=medium, 3=high, 4=critical)",
                },
                "status": {
                    "type": "string",
                    "enum": ["idea", "todo", "in_progress", "done", "archived"],
                    "description": "New status",
                },
            },
        },
        "_http": ("PATCH", "/api/cards/{card_id}", None),
    },
    {
        "name": "voxyflow.card.move",
        "description": "Move a card to a different status column on the kanban board.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id", "new_status"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID to move"},
                "new_status": {
                    "type": "string",
                    "enum": ["idea", "todo", "in_progress", "done", "archived"],
                    "description": "Target status column",
                },
            },
        },
        "_http": ("PATCH", "/api/cards/{card_id}", lambda p: {"status": p["new_status"]}),
    },
    {
        "name": "voxyflow.card.delete",
        "description": "Delete a card (irreversible).",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID to delete"},
            },
        },
        "_http": ("DELETE", "/api/cards/{card_id}", None),
    },
    {
        "name": "voxyflow.card.duplicate",
        "description": "Duplicate a card within the same project.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID to duplicate"},
            },
        },
        "_http": ("POST", "/api/cards/{card_id}/duplicate", None),
    },
    {
        "name": "voxyflow.card.enrich",
        "description": "Use AI to enrich a card with better description, tags, and acceptance criteria.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID to enrich"},
            },
        },
        "_http": ("POST", "/api/cards/{card_id}/enrich", None),
    },

    # ---- Wiki --------------------------------------------------------------
    {
        "name": "voxyflow.wiki.list",
        "description": "List all wiki pages for a project.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
        },
        "_http": ("GET", "/api/projects/{project_id}/wiki", None),
    },
    {
        "name": "voxyflow.wiki.create",
        "description": "Create a new wiki page for a project.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id", "title", "content"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "title": {"type": "string", "description": "Page title"},
                "content": {"type": "string", "description": "Page content (Markdown)"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
            },
        },
        "_http": ("POST", "/api/projects/{project_id}/wiki", None),
    },
    {
        "name": "voxyflow.wiki.get",
        "description": "Get the content of a specific wiki page.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id", "page_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "page_id": {"type": "string", "description": "Wiki page ID"},
            },
        },
        "_http": ("GET", "/api/projects/{project_id}/wiki/{page_id}", None),
    },
    {
        "name": "voxyflow.wiki.update",
        "description": "Update an existing wiki page.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id", "page_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "page_id": {"type": "string", "description": "Wiki page ID"},
                "title": {"type": "string", "description": "New title"},
                "content": {"type": "string", "description": "New content (Markdown)"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Updated tags"},
            },
        },
        "_http": ("PUT", "/api/projects/{project_id}/wiki/{page_id}", None),
    },

    # ---- AI ----------------------------------------------------------------
    {
        "name": "voxyflow.ai.standup",
        "description": "Generate an AI daily standup report for a project (what's done, in-progress, blocked).",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
        },
        "_http": ("POST", "/api/projects/{project_id}/standup", None),
    },
    {
        "name": "voxyflow.ai.brief",
        "description": "Generate a comprehensive AI project brief using the most capable model (Opus).",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
        },
        "_http": ("POST", "/api/projects/{project_id}/brief", None),
    },
    {
        "name": "voxyflow.ai.health",
        "description": "Run an AI project health check — assess risks, blockers, and team velocity.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
        },
        "_http": ("POST", "/api/projects/{project_id}/health", None),
    },
    {
        "name": "voxyflow.ai.prioritize",
        "description": "Use AI to smart-prioritize cards in a project based on value, complexity, and dependencies.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
        },
        "_http": ("POST", "/api/projects/{project_id}/prioritize", None),
    },
    {
        "name": "voxyflow.ai.review_code",
        "description": "Ask AI to review a code snippet and provide feedback.",
        "inputSchema": {
            "type": "object",
            "required": ["code"],
            "properties": {
                "code": {"type": "string", "description": "Code snippet to review"},
                "language": {"type": "string", "description": "Programming language (optional)"},
                "context": {"type": "string", "description": "Additional context for the review"},
                "project_id": {"type": "string", "description": "Optional project context"},
            },
        },
        "_http": ("POST", "/api/code/review", None),
    },

    # ---- Documents ---------------------------------------------------------
    {
        "name": "voxyflow.doc.list",
        "description": "List all documents attached to a project.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
        },
        "_http": ("GET", "/api/documents/projects/{project_id}/documents", None),
    },
    {
        "name": "voxyflow.doc.delete",
        "description": "Delete a document from a project.",
        "inputSchema": {
            "type": "object",
            "required": ["document_id"],
            "properties": {
                "document_id": {"type": "string", "description": "Document ID to delete"},
            },
        },
        "_http": ("DELETE", "/api/documents/documents/{document_id}", None),
    },

    # ---- System ------------------------------------------------------------
    {
        "name": "voxyflow.health",
        "description": "Get the overall health status of the Voxyflow system and services.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_http": ("GET", "/api/health", None),
    },
    {
        "name": "voxyflow.jobs.list",
        "description": "List all scheduled jobs in Voxyflow.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_http": ("GET", "/api/jobs", None),
    },
    {
        "name": "voxyflow.jobs.create",
        "description": "Create a new scheduled job in Voxyflow.",
        "inputSchema": {
            "type": "object",
            "required": ["name", "type", "cron"],
            "properties": {
                "name": {"type": "string", "description": "Job name"},
                "type": {
                    "type": "string",
                    "enum": ["reminder", "github_sync", "rag_index", "custom"],
                    "description": "Job type",
                },
                "cron": {"type": "string", "description": "Cron expression (e.g. '0 9 * * 1-5')"},
                "enabled": {"type": "boolean", "description": "Whether the job is enabled (default: true)"},
                "config": {"type": "object", "description": "Job-specific configuration"},
            },
        },
        "_http": ("POST", "/api/jobs", None),
    },
]


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

    for var in path_vars:
        value = remaining_params.pop(var, None)
        if value is None:
            raise ValueError(f"Missing required path parameter: {var}")
        path = path.replace(f"{{{var}}}", str(value))

    url = f"{VOXYFLOW_API_BASE}{path}"

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
    """Make the actual HTTP call to the Voxyflow REST API."""
    method, path_template, payload_transformer = tool_def["_http"]

    url, json_body, query_params = _build_url_and_payload(
        method, path_template, payload_transformer, params
    )

    logger.debug(f"MCP → {method} {url} body={json_body} query={query_params}")

    async with httpx.AsyncClient(timeout=30.0) as client:
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

    return data


# ---------------------------------------------------------------------------
# Build MCP tool list (without _http internal key)
# ---------------------------------------------------------------------------

def _public_tool_defs() -> list[dict]:
    """Return tool definitions without the internal _http key."""
    return [
        {k: v for k, v in t.items() if k != "_http"}
        for t in _TOOL_DEFINITIONS
    ]


def _find_tool(name: str) -> dict | None:
    for t in _TOOL_DEFINITIONS:
        if t["name"] == name:
            return t
    return None


# ---------------------------------------------------------------------------
# MCP Server (only instantiated if mcp package is available)
# ---------------------------------------------------------------------------

if MCP_AVAILABLE:
    server = Server("voxyflow")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """Expose all Voxyflow tools as MCP tools."""
        tools = []
        for defn in _TOOL_DEFINITIONS:
            tools.append(
                Tool(
                    name=defn["name"],
                    description=defn["description"],
                    inputSchema=defn["inputSchema"],
                )
            )
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """Route an MCP tool call to the Voxyflow REST API."""
        tool_def = _find_tool(name)
        if tool_def is None:
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Unknown tool: {name}",
            }))]

        try:
            result = await _call_api(tool_def, arguments or {})
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
