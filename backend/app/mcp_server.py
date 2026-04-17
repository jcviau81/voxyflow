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

_TOOL_DEFINITIONS: list[dict] = [
    # ---- Main Board Cards (system-main project, backward-compatible aliases) ─
    {
        "name": "voxyflow.card.create_unassigned",
        "description": "Create a card on the Voxyflow Main Board (system-main project). Status defaults to 'card' internally. Alias for creating a card in the Main project.",
        "inputSchema": {
            "type": "object",
            "required": ["content"],
            "properties": {
                "content": {"type": "string", "description": "Title / text content of the card"},
                "color": {
                    "type": "string",
                    "enum": ["yellow", "blue", "green", "pink", "purple", "orange"],
                    "description": "Background color of the card",
                },
                "description": {"type": "string", "description": "Optional longer description / body"},
            },
        },
        "_http": ("POST", "/api/cards/unassigned", lambda p: {
            "title": p.get("content", ""),
            "description": p.get("description", ""),
            "color": p.get("color"),
        }),
    },
    {
        "name": "voxyflow.card.list_unassigned",
        "description": "List all cards on the Voxyflow Main Board (system-main project). Alias for listing cards in the Main project.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_http": ("GET", "/api/cards/unassigned", None),
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
        "name": "voxyflow.project.update",
        "description": "Update an existing project (title, description, status, context, github_url, etc.).",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID to update"},
                "title": {"type": "string", "description": "New project title"},
                "description": {"type": "string", "description": "New project description"},
                "status": {"type": "string", "enum": ["active", "archived"], "description": "Project status"},
                "context": {"type": "string", "description": "Additional context for the AI"},
                "github_url": {"type": "string", "description": "GitHub repository URL"},
                "local_path": {"type": "string", "description": "Local filesystem path"},
            },
        },
        "_http": ("PATCH", "/api/projects/{project_id}", None),
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
    {
        "name": "voxyflow.project.archive",
        "description": "Archive a project (hide from main list, keep all data).",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID to archive"},
            },
        },
        "_http": ("POST", "/api/projects/{project_id}/archive", None),
    },
    {
        "name": "voxyflow.project.restore",
        "description": "Restore an archived project back to active status.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID to restore"},
            },
        },
        "_http": ("POST", "/api/projects/{project_id}/restore", None),
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
                    "enum": ["card", "todo", "in-progress", "done"],
                    "description": "Initial status (default: card)",
                },
                "priority": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 4,
                    "description": "Priority: 0=none, 1=low, 2=medium, 3=high, 4=critical",
                },
                "agent_type": {
                    "type": "string",
                    "enum": ["general", "researcher", "coder", "designer", "architect", "writer", "qa"],
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
                    "enum": ["card", "todo", "in-progress", "done", "archived"],
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
                    "enum": ["card", "todo", "in-progress", "done", "archived"],
                    "description": "Target status column",
                },
            },
        },
        "_http": ("PATCH", "/api/cards/{card_id}", lambda p: {"status": p.get("new_status") or p["status"]}),
    },
    {
        "name": "voxyflow.card.archive",
        "description": "Archive a card (soft-delete). Card is hidden but recoverable.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID to archive"},
            },
        },
        "_http": ("POST", "/api/cards/{card_id}/archive", None),
    },
    {
        "name": "voxyflow.card.delete",
        "description": "Permanently delete a card. Card must be archived first.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID to delete (must be archived)"},
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
    {
        "name": "voxyflow.card.restore",
        "description": "Restore an archived card back to active status.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID to restore"},
            },
        },
        "_http": ("POST", "/api/cards/{card_id}/restore", None),
    },
    {
        "name": "voxyflow.card.list_archived",
        "description": "List all archived cards for a project.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
        },
        "_http": ("GET", "/api/projects/{project_id}/cards/archived", None),
    },
    {
        "name": "voxyflow.card.history",
        "description": "Get change history for a card (max 50 entries, newest first).",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
            },
        },
        "_http": ("GET", "/api/cards/{card_id}/history", None),
    },

    # ---- Card Comments -----------------------------------------------------
    {
        "name": "voxyflow.card.comment.add",
        "description": "Add a comment to a card.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id", "content"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
                "content": {"type": "string", "description": "Comment text"},
                "author": {"type": "string", "description": "Author name (default: Voxy)", "default": "Voxy"},
            },
        },
        "_http": ("POST", "/api/cards/{card_id}/comments", None),
    },
    {
        "name": "voxyflow.card.comment.list",
        "description": "List all comments on a card (newest first).",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
            },
        },
        "_http": ("GET", "/api/cards/{card_id}/comments", None),
    },
    {
        "name": "voxyflow.card.comment.delete",
        "description": "Delete a comment from a card.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id", "comment_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
                "comment_id": {"type": "string", "description": "Comment ID to delete"},
            },
        },
        "_http": ("DELETE", "/api/cards/{card_id}/comments/{comment_id}", None),
    },

    # ---- Card Relations ----------------------------------------------------
    {
        "name": "voxyflow.card.relation.add",
        "description": "Add a relation between two cards (blocks, is_blocked_by, duplicates, relates_to, etc.).",
        "inputSchema": {
            "type": "object",
            "required": ["card_id", "target_card_id", "relation_type"],
            "properties": {
                "card_id": {"type": "string", "description": "Source card ID"},
                "target_card_id": {"type": "string", "description": "Target card ID"},
                "relation_type": {
                    "type": "string",
                    "enum": ["blocks", "is_blocked_by", "duplicates", "duplicated_by", "relates_to", "cloned_from"],
                    "description": "Type of relation",
                },
            },
        },
        "_http": ("POST", "/api/cards/{card_id}/relations", None),
    },
    {
        "name": "voxyflow.card.relation.list",
        "description": "List all relations for a card.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
            },
        },
        "_http": ("GET", "/api/cards/{card_id}/relations", None),
    },
    {
        "name": "voxyflow.card.relation.delete",
        "description": "Delete a relation from a card.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id", "relation_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
                "relation_id": {"type": "string", "description": "Relation ID to delete"},
            },
        },
        "_http": ("DELETE", "/api/cards/{card_id}/relations/{relation_id}", None),
    },

    # ---- Card Time Tracking ------------------------------------------------
    {
        "name": "voxyflow.card.time.log",
        "description": "Log time spent on a card.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id", "duration_minutes"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
                "duration_minutes": {"type": "integer", "description": "Time spent in minutes (min 1)"},
                "note": {"type": "string", "description": "Optional note about the work done"},
            },
        },
        "_http": ("POST", "/api/cards/{card_id}/time", None),
    },
    {
        "name": "voxyflow.card.time.list",
        "description": "List all time entries for a card.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
            },
        },
        "_http": ("GET", "/api/cards/{card_id}/time", None),
    },
    {
        "name": "voxyflow.card.time.delete",
        "description": "Delete a time entry from a card.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id", "entry_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
                "entry_id": {"type": "string", "description": "Time entry ID to delete"},
            },
        },
        "_http": ("DELETE", "/api/cards/{card_id}/time/{entry_id}", None),
    },

    # ---- Checklist ---------------------------------------------------------
    {
        "name": "voxyflow.card.checklist.add",
        "description": "Add a single checklist item to a card.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id", "text"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
                "text": {"type": "string", "description": "Checklist item text"},
            },
        },
        "_http": ("POST", "/api/cards/{card_id}/checklist", lambda p: {
            "text": p["text"],
        }),
    },
    {
        "name": "voxyflow.card.checklist.add_bulk",
        "description": "Add multiple checklist items to a card in one call. Use this when creating a full checklist (3-5 items).",
        "inputSchema": {
            "type": "object",
            "required": ["card_id", "items"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of checklist item texts",
                },
            },
        },
        "_http": ("POST", "/api/cards/{card_id}/checklist/bulk", lambda p: [
            {"text": t} for t in p.get("items", [])
        ]),
    },
    {
        "name": "voxyflow.card.checklist.list",
        "description": "List all checklist items for a card.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
            },
        },
        "_http": ("GET", "/api/cards/{card_id}/checklist", None),
    },
    {
        "name": "voxyflow.card.checklist.update",
        "description": "Update a checklist item (toggle completed or edit text).",
        "inputSchema": {
            "type": "object",
            "required": ["card_id", "item_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
                "item_id": {"type": "string", "description": "Checklist item ID"},
                "text": {"type": "string", "description": "New text (optional)"},
                "completed": {"type": "boolean", "description": "Mark as completed (optional)"},
            },
        },
        "_http": ("PATCH", "/api/cards/{card_id}/checklist/{item_id}", lambda p: {
            k: v for k, v in p.items() if k in ("text", "completed") and v is not None
        }),
    },
    {
        "name": "voxyflow.card.checklist.delete",
        "description": "Delete a checklist item.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id", "item_id"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID"},
                "item_id": {"type": "string", "description": "Checklist item ID"},
            },
        },
        "_http": ("DELETE", "/api/cards/{card_id}/checklist/{item_id}", None),
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
    {
        "name": "voxyflow.wiki.delete",
        "description": "Delete a wiki page.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id", "page_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "page_id": {"type": "string", "description": "Wiki page ID to delete"},
            },
        },
        "_http": ("DELETE", "/api/projects/{project_id}/wiki/{page_id}", None),
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
        "_http": ("GET", "/api/projects/{project_id}/documents", None),
    },
    {
        "name": "voxyflow.doc.delete",
        "description": "Delete a document from a project.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id", "document_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
                "document_id": {"type": "string", "description": "Document ID to delete"},
            },
        },
        "_http": ("DELETE", "/api/projects/{project_id}/documents/{document_id}", None),
    },

    # ---- Focus Sessions ----------------------------------------------------
    {
        "name": "voxyflow.focus.log",
        "description": "Log a completed Pomodoro/focus session for a card or project.",
        "inputSchema": {
            "type": "object",
            "required": ["duration_minutes", "completed", "started_at", "ended_at"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID (optional)"},
                "project_id": {"type": "string", "description": "Project ID (optional)"},
                "duration_minutes": {"type": "integer", "description": "Session duration in minutes"},
                "completed": {"type": "boolean", "description": "Whether the session was completed"},
                "started_at": {"type": "string", "description": "ISO datetime when session started"},
                "ended_at": {"type": "string", "description": "ISO datetime when session ended"},
            },
        },
        "_http": ("POST", "/api/focus-sessions", None),
    },
    {
        "name": "voxyflow.focus.analytics",
        "description": "Get focus session analytics for a project (totals, by card, by day).",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID"},
            },
        },
        "_http": ("GET", "/api/projects/{project_id}/focus", None),
    },

    # ---- CLI Sessions ------------------------------------------------------
    {
        "name": "voxyflow.sessions.list",
        "description": "List active CLI subprocess sessions (chat and worker processes). Auto-scoped to the current project — pass scope='all' for a system-wide view.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                    "description": "Session visibility scope. 'current' (default) shows only this project's sessions; 'all' shows every active CLI subprocess. Ignored in general chat, which always sees all.",
                },
            },
        },
        "_handler": "sessions_list",
        "_scope": "voxyflow",
    },

    # ---- Worker Ledger -----------------------------------------------------
    {
        "name": "voxyflow.workers.list",
        "description": "List recent worker tasks from the Worker Ledger. Auto-scoped to the current project — pass scope='all' for the full system-wide ledger.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Filter by session ID"},
                "status": {
                    "type": "string",
                    "enum": ["running", "done", "failed", "timed_out", "cancelled"],
                    "description": "Filter by status",
                },
                "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                    "description": "Project scope for results. 'current' (default) returns only workers from this project; 'all' returns every worker in the ledger. Ignored in general chat, which always sees all.",
                },
            },
        },
        "_handler": "workers_list",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.workers.get_result",
        "description": "Get the full details and result of a specific worker task by task_id. Strict project scope — tasks from other projects are rejected unless scope='all' is passed.",
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string", "description": "Worker task ID"},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                    "description": "Project-ownership enforcement. 'current' (default) rejects tasks from other projects; 'all' bypasses the check.",
                },
            },
        },
        "_handler": "workers_get_result",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.workers.read_artifact",
        "description": (
            "Read the verbatim raw output of a finished worker from its on-disk "
            "artifact (.md file under ~/.voxyflow/worker_artifacts/). Use this when "
            "you need the EXACT content the worker produced — file contents, command "
            "stdout, search results, logs — rather than the Haiku summary delivered "
            "in the worker callback. Supports pagination via offset/length for "
            "outputs larger than ~50k chars. Strict project scope — tasks from other "
            "projects are rejected unless scope='all'. Response: content, offset, "
            "length, total_chars, has_more, path."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string", "description": "Worker task ID whose artifact to read"},
                "offset": {"type": "integer", "description": "Starting char offset into the artifact body (default 0)"},
                "length": {"type": "integer", "description": "Max chars to return in this slice (default 50000)"},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                    "description": "Project-ownership enforcement. 'current' (default) rejects tasks from other projects; 'all' bypasses the check.",
                },
            },
        },
        "_handler": "workers_read_artifact",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.task.peek",
        "description": "Monitor a running worker task in real time. Returns the recent tools called, tool count, running duration, and current status. Strict project scope — pass scope='all' to peek at tasks from other projects.",
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string", "description": "Worker task ID (full or partial)"},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                    "description": "Project-ownership enforcement. 'current' (default) rejects tasks from other projects; 'all' bypasses the check.",
                },
            },
        },
        "_handler": "task_peek",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.task.cancel",
        "description": "Cancel a running worker task immediately. Strict project scope — tasks from other projects cannot be cancelled unless scope='all' is passed.",
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string", "description": "Worker task ID to cancel"},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                    "description": "Project-ownership enforcement. 'current' (default) rejects tasks from other projects; 'all' bypasses the check.",
                },
            },
        },
        "_handler": "task_cancel",
        "_scope": "voxyflow",
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
        "description": (
            "Create a new scheduled job. "
            "Job types and required payload fields:\n"
            "• agent_task — freeform AI instruction. payload: {instruction: string, project_id?: uuid}\n"
            "• execute_board — run all cards matching statuses on a board. payload: {project_id: uuid, statuses?: [\"todo\"]}\n"
            "• execute_card — run a single card. payload: {card_id: uuid, project_id?: uuid}\n"
            "• reminder — broadcast a message. payload: {message: string}\n"
            "• rag_index — re-index documents. payload: {project_id?: uuid, path?: string}\n"
            "Schedule: cron expression ('0 9 * * 1-5') or shorthand ('every_5min', 'every_30min', 'every_1h', 'every_2h', 'every_day')."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["name", "type", "schedule"],
            "properties": {
                "name": {"type": "string", "description": "Job name"},
                "type": {
                    "type": "string",
                    "enum": ["agent_task", "execute_card", "execute_board", "reminder", "rag_index", "custom"],
                    "description": "Job type — use agent_task for freeform instructions, execute_board for running board cards",
                },
                "schedule": {"type": "string", "description": "Cron expression (e.g. '0 9 * * 1-5') or shorthand ('every_5min', 'every_1h', 'every_day')"},
                "enabled": {"type": "boolean", "description": "Whether the job is enabled (default: true)"},
                "payload": {"type": "object", "description": "Job-specific payload — see tool description for required fields per type"},
            },
        },
        "_http": ("POST", "/api/jobs", None),
    },
    {
        "name": "voxyflow.jobs.update",
        "description": "Update an existing scheduled job (name, schedule, enabled, payload). Pass only the fields to change.",
        "inputSchema": {
            "type": "object",
            "required": ["job_id"],
            "properties": {
                "job_id": {"type": "string", "description": "ID of the job to update"},
                "name": {"type": "string", "description": "New job name"},
                "type": {
                    "type": "string",
                    "enum": ["agent_task", "execute_card", "execute_board", "reminder", "rag_index", "custom"],
                    "description": "New job type — use agent_task for freeform instructions",
                },
                "schedule": {"type": "string", "description": "New cron expression or interval"},
                "enabled": {"type": "boolean", "description": "Enable or disable the job"},
                "payload": {"type": "object", "description": "New job-specific configuration / payload"},
            },
        },
        "_http": ("PATCH", "/api/jobs/{job_id}", None),
    },
    {
        "name": "voxyflow.jobs.delete",
        "description": "Delete a scheduled job permanently.",
        "inputSchema": {
            "type": "object",
            "required": ["job_id"],
            "properties": {
                "job_id": {"type": "string", "description": "ID of the job to delete"},
            },
        },
        "_http": ("DELETE", "/api/jobs/{job_id}", None),
    },

    # ======================================================================
    # HEARTBEAT — read/write ~/.voxyflow/workspace/heartbeat.md
    # ======================================================================

    {
        "name": "voxyflow.heartbeat.read",
        "description": "Read the Agent Heartbeat file (~/.voxyflow/workspace/heartbeat.md). Use this to check if there are pending heartbeat instructions.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_handler": "heartbeat_read",
    },
    {
        "name": "voxyflow.heartbeat.write",
        "description": (
            "Write to the Agent Heartbeat file (~/.voxyflow/workspace/heartbeat.md). "
            "The agent checks this file every 5 minutes and follows any instructions found. "
            "Pass the full file content (header + instructions). "
            "To queue work: add instructions below the --- separator. "
            "To clear: write the file with just the header and no instructions."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["content"],
            "properties": {
                "content": {"type": "string", "description": "Full file content to write"},
            },
        },
        "_handler": "heartbeat_write",
    },

    # ======================================================================
    # SYSTEM TOOLS — direct execution, no REST API
    # ======================================================================

    {
        "name": "system.exec",
        "description": "Run a shell command on the local machine. Returns stdout, stderr, exit_code, and duration.",
        "inputSchema": {
            "type": "object",
            "required": ["command"],
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory (optional)"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 30, max 300)", "default": 30},
            },
        },
        "_handler": "system_exec",
        "_role": "worker",
        "_scope": "system",
    },
    {
        "name": "web.search",
        "description": "Search the web using Brave Search API. Returns titles, URLs, and snippets.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "count": {"type": "integer", "description": "Number of results (default 5, max 20)", "default": 5},
            },
        },
        "_handler": "web_search",
        "_role": "worker",
        "_scope": "web",
    },
    {
        "name": "web.fetch",
        "description": "Fetch a web page and extract its readable content as text/markdown.",
        "inputSchema": {
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "max_chars": {"type": "integer", "description": "Max characters to return (default 5000)", "default": 5000},
            },
        },
        "_handler": "web_fetch",
        "_role": "worker",
        "_scope": "web",
    },
    {
        "name": "file.read",
        "description": "Read a file from the filesystem. Supports offset and line limits.",
        "inputSchema": {
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
                "offset": {"type": "integer", "description": "Start line number (1-indexed)"},
                "limit": {"type": "integer", "description": "Max lines to read"},
            },
        },
        "_handler": "file_read",
        "_role": "worker",
        "_scope": "file",
    },
    {
        "name": "file.write",
        "description": "Write content to a file. Creates parent directories automatically.",
        "inputSchema": {
            "type": "object",
            "required": ["path", "content"],
            "properties": {
                "path": {"type": "string", "description": "File path to write"},
                "content": {"type": "string", "description": "Content to write"},
                "mode": {
                    "type": "string",
                    "enum": ["overwrite", "append"],
                    "description": "Write mode (default: overwrite)",
                    "default": "overwrite",
                },
            },
        },
        "_handler": "file_write",
        "_role": "worker",
        "_scope": "file",
    },
    {
        "name": "file.patch",
        "description": "Replace exact text in a file (surgical edit). Finds the first occurrence of old and replaces it with new. Use instead of rewriting entire files.",
        "inputSchema": {
            "type": "object",
            "required": ["path", "old", "new"],
            "properties": {
                "path": {"type": "string", "description": "File path to patch"},
                "old": {"type": "string", "description": "Exact text to find (must match exactly, including whitespace)"},
                "new": {"type": "string", "description": "Replacement text"},
            },
        },
        "_handler": "file_patch",
        "_role": "worker",
        "_scope": "file",
    },
    {
        "name": "file.list",
        "description": "List files and directories at a given path.",
        "inputSchema": {
            "type": "object",
            "required": ["path"],
            "properties": {
                "path": {"type": "string", "description": "Directory path to list"},
                "pattern": {"type": "string", "description": "Glob pattern (default: '*')", "default": "*"},
                "recursive": {"type": "boolean", "description": "List recursively (default: false)", "default": False},
            },
        },
        "_handler": "file_list",
        "_role": "worker",
        "_scope": "file",
    },

    # ---- Git ---------------------------------------------------------------
    {
        "name": "git.status",
        "description": "Run git status in a given path.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Git repo path (default: home dir)"},
            },
        },
        "_handler": "git_status",
        "_role": "worker",
        "_scope": "git",
    },
    {
        "name": "git.log",
        "description": "Show recent git commits (oneline format).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Git repo path"},
                "limit": {"type": "integer", "description": "Number of commits to show (default: 20)", "default": 20},
            },
        },
        "_handler": "git_log",
        "_role": "worker",
        "_scope": "git",
    },
    {
        "name": "git.diff",
        "description": "Show git diff (working tree vs HEAD, or staged changes).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Git repo path"},
                "staged": {"type": "boolean", "description": "Show staged changes only (default: false)", "default": False},
            },
        },
        "_handler": "git_diff",
        "_role": "worker",
        "_scope": "git",
    },
    {
        "name": "git.branches",
        "description": "List all git branches (local and remote).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Git repo path"},
            },
        },
        "_handler": "git_branches",
        "_role": "worker",
        "_scope": "git",
    },
    {
        "name": "git.commit",
        "description": "Stage all changes (git add -A) and commit with a message.",
        "inputSchema": {
            "type": "object",
            "required": ["message"],
            "properties": {
                "path": {"type": "string", "description": "Git repo path"},
                "message": {"type": "string", "description": "Commit message"},
            },
        },
        "_handler": "git_commit",
        "_role": "worker",
        "_scope": "git",
    },

    # ---- Tmux --------------------------------------------------------------
    {
        "name": "tmux.list",
        "description": "List all tmux sessions.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_handler": "tmux_list",
        "_role": "worker",
        "_scope": "tmux",
    },
    {
        "name": "tmux.run",
        "description": "Run a command in a named tmux session. Creates the session if it doesn't exist, or sends the command to the existing session.",
        "inputSchema": {
            "type": "object",
            "required": ["session", "command"],
            "properties": {
                "session": {"type": "string", "description": "Tmux session name"},
                "command": {"type": "string", "description": "Command to run"},
            },
        },
        "_handler": "tmux_run",
        "_role": "worker",
        "_scope": "tmux",
    },
    {
        "name": "tmux.send",
        "description": "Send keys to a tmux pane.",
        "inputSchema": {
            "type": "object",
            "required": ["session", "keys"],
            "properties": {
                "session": {"type": "string", "description": "Tmux session name"},
                "keys": {"type": "string", "description": "Keys to send"},
            },
        },
        "_handler": "tmux_send",
        "_role": "worker",
        "_scope": "tmux",
    },
    {
        "name": "tmux.capture",
        "description": "Capture the current output/content of a tmux pane.",
        "inputSchema": {
            "type": "object",
            "required": ["session"],
            "properties": {
                "session": {"type": "string", "description": "Tmux session name"},
            },
        },
        "_handler": "tmux_capture",
        "_role": "worker",
        "_scope": "tmux",
    },
    {
        "name": "tmux.new",
        "description": "Create a new named tmux session.",
        "inputSchema": {
            "type": "object",
            "required": ["session"],
            "properties": {
                "session": {"type": "string", "description": "Tmux session name"},
                "command": {"type": "string", "description": "Optional command to run in the session"},
            },
        },
        "_handler": "tmux_new",
        "_role": "worker",
        "_scope": "tmux",
    },
    {
        "name": "tmux.kill",
        "description": "Kill a tmux session.",
        "inputSchema": {
            "type": "object",
            "required": ["session"],
            "properties": {
                "session": {"type": "string", "description": "Tmux session name"},
            },
        },
        "_handler": "tmux_kill",
        "_role": "worker",
        "_scope": "tmux",
    },

    # ---- Worker Supervision ------------------------------------------------
    {
        "name": "task.complete",
        "description": "Signal that your assigned task is finished. You MUST call this when done.",
        "inputSchema": {
            "type": "object",
            "required": ["task_id", "summary"],
            "properties": {
                "task_id": {"type": "string", "description": "Your assigned task ID"},
                "summary": {"type": "string", "description": "Brief summary of what you accomplished"},
                "status": {
                    "type": "string",
                    "enum": ["success", "partial", "failed"],
                    "description": "Outcome status (default: success)",
                    "default": "success",
                },
            },
        },
        "_handler": "task_complete",
        "_role": "worker",
        "_scope": "core",
    },

    # ---- Dynamic Tool Loading ------------------------------------------------
    {
        "name": "tools.load",
        "description": (
            "Load additional tool scopes into this session. "
            "Available scopes: voxyflow (cards, wiki, memory, projects), "
            "web (search, fetch), git (status, log, diff, commit), tmux (sessions). "
            "Base tools (file.read, file.write, file.list, system.exec, task.complete) "
            "are always available. Call this BEFORE using tools from a scope."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["scopes"],
            "properties": {
                "scopes": {
                    "type": "string",
                    "description": "Comma-separated scopes to load: voxyflow, web, git, tmux",
                },
            },
        },
        "_handler": "tools_load",
        "_role": "worker",
        "_scope": "core",
    },

    # ---- Memory (semantic search across all memory) -------------------------
    {
        "name": "memory.search",
        "description": "Search Voxy's long-term memory for relevant context. Strictly scoped to the current project (or global+main only when in general chat). Project chats never see global memory. Use when you need to recall prior conversations, decisions, or stored facts within this project.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Natural language search query — describe what you're trying to remember"},
                "limit": {"type": "integer", "description": "Max results per page (default 10)"},
                "offset": {"type": "integer", "description": "Skip first N results for pagination (default 0)"},
            },
        },
        "_handler": "memory_search",
        "_scope": "voxyflow",
    },

    # ---- Memory Save (write to long-term memory) ----------------------------
    # Scope is enforced by VOXYFLOW_PROJECT_ID env var at runtime. The LLM
    # cannot override it — project_id is deliberately NOT in the schema.
    {
        "name": "memory.save",
        "description": "Save an important fact, decision, preference, or lesson to Voxy's long-term memory. Auto-scoped to the current project — use when the user shares something worth remembering across sessions.",
        "inputSchema": {
            "type": "object",
            "required": ["text"],
            "properties": {
                "text": {"type": "string", "description": "The information to remember"},
                "type": {
                    "type": "string",
                    "enum": ["decision", "preference", "lesson", "fact", "context"],
                    "description": "Memory type (default: fact)",
                },
                "importance": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Importance level (default: medium)",
                },
            },
        },
        "_handler": "memory_save",
        "_scope": "voxyflow",
    },

    # ---- Knowledge Base (on-demand RAG) ------------------------------------
    # Scope is enforced by VOXYFLOW_PROJECT_ID env var at runtime.
    {
        "name": "knowledge.search",
        "description": "Search the current project's knowledge base (RAG) for relevant context. Use when you need background information about the project that isn't in the task description.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Search query — describe what you're looking for"},
            },
        },
        "_handler": "knowledge_search",
        "_scope": "voxyflow",
    },

    # ---- Memory Delete --------------------------------------------------------
    {
        "name": "memory.delete",
        "description": "Delete a specific memory entry by ID. Use memory.search first to find the ID of the memory to delete.",
        "inputSchema": {
            "type": "object",
            "required": ["id"],
            "properties": {
                "id": {"type": "string", "description": "Memory document ID to delete"},
                "collection": {"type": "string", "description": "Collection name (optional, defaults to global)"},
            },
        },
        "_handler": "memory_delete",
        "_scope": "voxyflow",
    },

    # ---- Memory Get (recent session history) ----------------------------------
    {
        "name": "memory.get",
        "description": "List recent chat sessions with their title, last message, and message count. Use to recall what was discussed in previous conversations or find a specific past session.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Number of recent sessions to return (default 10, max 50)"},
            },
        },
        "_handler": "memory_get",
        "_scope": "voxyflow",
    },

    # ---- Knowledge Graph -----------------------------------------------------
    {
        "name": "kg.add",
        "description": "Add an entity to the project knowledge graph, optionally with relationships and attributes. Use this to record named things (people, technologies, components, decisions) and how they relate. Relationships and attributes are created as current facts (valid_from=now, valid_to=NULL). To supersede a fact later, invalidate the old one with kg.invalidate and add the new one.",
        "inputSchema": {
            "type": "object",
            "required": ["entity_name", "entity_type"],
            "properties": {
                "entity_name": {"type": "string", "description": "Name of the entity (e.g. 'Redis', 'auth-service', 'Alice')"},
                "entity_type": {
                    "type": "string",
                    "enum": ["person", "technology", "component", "concept", "decision"],
                    "description": "Category of the entity",
                },
                "relationships": {
                    "type": "array",
                    "description": "Optional relationships to other entities",
                    "items": {
                        "type": "object",
                        "required": ["predicate", "target", "target_type"],
                        "properties": {
                            "predicate": {"type": "string", "description": "Relationship verb (e.g. 'uses', 'depends_on', 'created_by')"},
                            "target": {"type": "string", "description": "Name of the target entity"},
                            "target_type": {
                                "type": "string",
                                "enum": ["person", "technology", "component", "concept", "decision"],
                                "description": "Type of the target entity",
                            },
                        },
                    },
                },
                "attributes": {
                    "type": "array",
                    "description": "Optional key-value attributes on the entity",
                    "items": {
                        "type": "object",
                        "required": ["key", "value"],
                        "properties": {
                            "key": {"type": "string", "description": "Attribute key (e.g. 'version', 'status', 'pinned')"},
                            "value": {"type": "string", "description": "Attribute value"},
                        },
                    },
                },
            },
        },
        "_handler": "kg_add",
        "_scope": "voxyflow",
    },
    {
        "name": "kg.query",
        "description": "Search entities and their relationships in the project knowledge graph. Returns entities matching the filter, optionally with their active (non-invalidated) relationships. Use as_of to see which relationships existed at a past point in time.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Filter by entity name (partial match)"},
                "entity_type": {
                    "type": "string",
                    "enum": ["person", "technology", "component", "concept", "decision"],
                    "description": "Filter by entity type",
                },
                "as_of": {"type": "string", "description": "ISO datetime — show relationships that existed at this point in time (filters to valid_from <= as_of AND still active). Default: now (current state only)"},
                "include_relationships": {"type": "boolean", "description": "Include active relationships in results (default: true)"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
        },
        "_handler": "kg_query",
        "_scope": "voxyflow",
    },
    {
        "name": "kg.timeline",
        "description": "Get chronological history of knowledge graph changes for a project or entity. Unlike kg.query (which returns only current/active facts), timeline shows ALL facts — both current (valid_to=null) and historical (valid_to set) — ordered newest-first. Use this to answer 'when did we decide X?' or 'what changed?'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_name": {"type": "string", "description": "Filter timeline to a specific entity (partial match)"},
                "limit": {"type": "integer", "description": "Max events (default 50)"},
            },
        },
        "_handler": "kg_timeline",
        "_scope": "voxyflow",
    },
    {
        "name": "kg.invalidate",
        "description": "Mark a relationship or attribute as no longer valid by setting valid_to=now(), closing the [valid_from, valid_to) interval. The fact becomes historical — it still appears in kg.timeline but is excluded from kg.query and kg.stats. Use this when a fact has changed or been superseded (e.g. 'project no longer uses Redis'). Idempotent: invalidating an already-closed fact returns success=false.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "triple_id": {"type": "string", "description": "ID of the relationship triple to invalidate"},
                "attribute_id": {"type": "string", "description": "ID of the attribute to invalidate"},
            },
        },
        "_handler": "kg_invalidate",
        "_scope": "voxyflow",
    },
    {
        "name": "kg.stats",
        "description": "Get knowledge graph statistics for the current project — entity count, active (non-invalidated) triples, and active attributes. Historical/invalidated facts are not counted.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_handler": "kg_stats",
        "_scope": "voxyflow",
    },

    # ---- Task Steer -----------------------------------------------------------
    {
        "name": "task.steer",
        "description": "Inject a steering message into a running worker task. Use this to redirect a worker mid-execution. Strict project scope — tasks from other projects are rejected unless scope='all'.",
        "inputSchema": {
            "type": "object",
            "required": ["task_id", "message"],
            "properties": {
                "task_id": {"type": "string", "description": "Worker task ID to steer"},
                "message": {"type": "string", "description": "Steering instruction to inject into the worker's conversation"},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                    "description": "Project-ownership enforcement. 'current' (default) rejects tasks from other projects; 'all' bypasses the check.",
                },
            },
        },
        "_handler": "task_steer",
        "_scope": "voxyflow",
    },
]


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
    """Lazily load and cache system tool handlers."""
    if not _SYSTEM_HANDLERS:
        from app.tools.system_tools import (
            system_exec, web_search, web_fetch,
            file_read, file_write, file_patch, file_list,
            git_status, git_log, git_diff, git_branches, git_commit,
            tmux_list, tmux_run, tmux_send, tmux_capture, tmux_new, tmux_kill,
        )
        from app.services.worker_supervisor import handle_task_complete

        async def memory_search(params: dict) -> dict:
            """Semantic search across Voxy's long-term memory, scoped to the current project."""
            from app.services.memory_service import (
                get_memory_service,
                GLOBAL_COLLECTION,
                _project_collection,
            )
            query = params.get("query", "")
            if not query:
                return {"error": "query is required"}
            limit = params.get("limit", 10)
            offset = params.get("offset", 0)

            # Project scope from runtime env (injected by cli_backend per chat).
            # STRICT ISOLATION: project chats NEVER see memory-global. Only the
            # general chat (no project / system-main) is allowed to query global.
            # - Real project UUID → that project's collection ONLY
            # - Empty or "system-main" → general chat: global + system-main
            project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip()
            if project_id and project_id != "system-main":
                collections = [_project_collection(project_id)]
            else:
                collections = [GLOBAL_COLLECTION, _project_collection("system-main")]
            logger.info(
                f"[mcp.memory.search] project_id={project_id!r} collections={collections}"
            )

            try:
                ms = get_memory_service()
                results = ms.search_memory(
                    query,
                    collections=collections,
                    limit=limit,
                    offset=offset,
                )
                if not results:
                    return {"results": [], "offset": offset, "limit": limit, "count": 0}
                formatted = []
                for r in results:
                    formatted.append({
                        "id": r.get("id", ""),
                        "text": r.get("text", ""),
                        "score": round(r.get("score", 0), 3),
                        "collection": r.get("collection", ""),
                    })
                return {
                    "results": formatted,
                    "offset": offset,
                    "limit": limit,
                    "count": len(formatted),
                    "has_more": len(formatted) == limit,
                }
            except Exception as e:
                return {"error": str(e)}

        async def knowledge_search(params: dict) -> dict:
            """RAG search on project knowledge base — on-demand tool.

            Scope is enforced by VOXYFLOW_PROJECT_ID env var. The LLM
            cannot override it; params.project_id is ignored if present
            (it was removed from the schema but defensive-coded here).
            """
            from app.services.rag_service import get_rag_service
            env_project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip()
            project_id = env_project_id or "system-main"
            query = params.get("query", "")
            if not query:
                return {"error": "query is required"}
            logger.info(f"[mcp.knowledge.search] project_id={project_id!r}")
            try:
                result = await get_rag_service().build_rag_context(project_id, query)
                return {"result": result or "No relevant knowledge found."}
            except Exception as e:
                return {"error": str(e)}

        async def memory_save(params: dict) -> dict:
            """Store a memory entry in Voxy's long-term memory (ChromaDB or file fallback).

            STRICT ISOLATION: scope is enforced by VOXYFLOW_PROJECT_ID env var.
            The LLM cannot cross-save into another project — project_id is not
            in the schema and any param value is ignored.
            """
            from app.services.memory_service import (
                get_memory_service,
                GLOBAL_COLLECTION,
                _project_collection,
            )
            text = params.get("text", "").strip()
            if not text:
                return {"error": "text is required"}
            mem_type = params.get("type", "fact")
            importance = params.get("importance", "medium")

            env_project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip()
            project_id = env_project_id

            if project_id and project_id != "system-main":
                collection = _project_collection(project_id)
            elif project_id == "system-main":
                collection = _project_collection("system-main")
            else:
                collection = GLOBAL_COLLECTION
            logger.info(
                f"[mcp.memory.save] project_id={project_id!r} collection={collection}"
            )

            from datetime import datetime, timezone
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            try:
                ms = get_memory_service()
                doc_id = ms.store_memory(
                    text=text,
                    collection=collection,
                    metadata={
                        "type": mem_type,
                        "date": date_str,
                        "source": "chat",
                        "importance": importance,
                    },
                )
                if doc_id:
                    return {"success": True, "id": doc_id, "message": f"Memory saved ({mem_type}, {importance})"}
                return {"success": False, "error": "store_memory returned None"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        async def memory_delete(params: dict) -> dict:
            """Delete a memory entry by ID."""
            from app.services.memory_service import get_memory_service, GLOBAL_COLLECTION
            doc_id = params.get("id", "").strip()
            if not doc_id:
                return {"error": "id is required"}
            collection = params.get("collection", GLOBAL_COLLECTION)
            try:
                ms = get_memory_service()
                deleted = ms.delete_memory(doc_id, collection=collection)
                if deleted:
                    return {"success": True, "message": f"Memory {doc_id} deleted from {collection}"}
                return {"success": False, "error": f"Failed to delete memory {doc_id}"}
            except Exception as e:
                return {"success": False, "error": str(e)}

        async def memory_get(params: dict) -> dict:
            """List recent chat sessions (history overview)."""
            from app.services.session_store import SessionStore
            limit = min(params.get("limit", 10), 50)
            try:
                store = SessionStore()
                sessions = store.list_active_sessions()[:limit]
                return {"count": len(sessions), "sessions": sessions}
            except Exception as e:
                return {"error": str(e)}

        async def task_steer(params: dict) -> dict:
            """Inject a steering message into a running worker task."""
            task_id = params.get("task_id", "").strip()
            message = params.get("message", "").strip()
            if not task_id:
                return {"error": "task_id is required"}
            if not message:
                return {"error": "message is required"}
            scope_err = await _enforce_task_scope(task_id, params.get("scope"))
            if scope_err is not None:
                return scope_err
            try:
                client = _get_http_client()
                resp = await client.post(
                    f"/api/worker-tasks/{task_id}/steer",
                    json={"message": message},
                    timeout=10.0,
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("queued"):
                    return {"success": True, "message": f"Steering message sent to task {task_id}"}
                return {"success": False, "error": f"No active worker found for task {task_id}. Task may have already completed."}
            except Exception as e:
                return {"success": False, "error": str(e)}

        async def task_peek(params: dict) -> dict:
            """Live peek into a running worker task, with DB fallback for finished tasks."""
            task_id = (params.get("task_id") or "").strip()
            if not task_id:
                return {"success": False, "error": "task_id is required"}
            scope_err = await _enforce_task_scope(task_id, params.get("scope"))
            if scope_err is not None:
                return scope_err
            try:
                client = _get_http_client()
                resp = await client.get(f"/api/worker-tasks/{task_id}/peek")
                if resp.status_code == 404:
                    return {"success": False, "error": f"Worker task not found: {task_id}"}
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and "success" not in data:
                    data["success"] = True
                return data
            except Exception as e:
                logger.error(f"[mcp.task.peek] failed: {e}")
                return {"success": False, "error": str(e)}

        async def task_cancel(params: dict) -> dict:
            """Cancel a running worker task across all active pools."""
            task_id = (params.get("task_id") or "").strip()
            if not task_id:
                return {"success": False, "error": "task_id is required"}
            scope_err = await _enforce_task_scope(task_id, params.get("scope"))
            if scope_err is not None:
                return scope_err
            try:
                client = _get_http_client()
                resp = await client.post(f"/api/worker-tasks/{task_id}/cancel")
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and "success" not in data:
                    data["success"] = True
                return data
            except Exception as e:
                logger.error(f"[mcp.task.cancel] failed: {e}")
                return {"success": False, "error": str(e)}

        async def sessions_list(params: dict) -> dict:
            """List active CLI subprocess sessions, scoped to the current project by default."""
            import time
            from app.services.cli_session_registry import get_cli_session_registry
            registry = get_cli_session_registry()
            current_pid, scoped = _current_project_scope()
            scope = (params.get("scope") or "").lower()
            now = time.time()

            all_sessions = registry.list_active()
            if scope == "all" or not scoped:
                filtered = all_sessions
                scope_label = "all"
            else:
                filtered = [s for s in all_sessions if (s.project_id or "") == current_pid]
                scope_label = "project"

            return {
                "success": True,
                "scope": scope_label,
                "project_id": current_pid if scope_label == "project" else None,
                "sessions": [
                    {
                        "id": s.id,
                        "pid": s.pid,
                        "sessionId": s.session_id,
                        "chatId": s.chat_id,
                        "projectId": s.project_id,
                        "model": s.model,
                        "type": s.session_type,
                        "startedAt": s.started_at,
                        "durationSeconds": round(now - s.started_at, 1),
                    }
                    for s in filtered
                ],
                "count": len(filtered),
                "total_active": registry.count(),
            }

        async def workers_list(params: dict) -> dict:
            """List active and recent worker tasks from the session store + DB.

            Defaults to the current project; pass scope='all' for system-wide.
            """
            from app.services.worker_session_store import get_worker_session_store
            try:
                store = get_worker_session_store()
                session_id = params.get("session_id")

                current_pid, scoped = _current_project_scope()
                scope = (params.get("scope") or "").lower()
                if scope == "all" or not scoped:
                    filter_pid: str | None = None
                    scope_label = "all"
                else:
                    filter_pid = current_pid
                    scope_label = "project"

                sessions = store.get_sessions(session_id=session_id)
                if filter_pid:
                    sessions = [s for s in sessions if (s.get("project_id") or "") == filter_pid]
                status_filter = params.get("status")
                if status_filter:
                    sessions = [s for s in sessions if s.get("status") == status_filter]
                limit = params.get("limit", 10)
                sessions = sessions[:limit]

                base = {
                    "success": True,
                    "scope": scope_label,
                    "project_id": filter_pid,
                    "count": len(sessions),
                }
                if not sessions:
                    return {**base, "result": "No active or recent workers found.", "workers": []}
                return {**base, "workers": sessions}
            except Exception as e:
                logger.error(f"[mcp.workers.list] failed: {e}")
                return {"success": False, "error": str(e)}

        async def workers_get_result(params: dict) -> dict:
            """Get full details and result of a worker task, reading from DB for full output."""
            from app.services.worker_session_store import get_worker_session_store
            task_id = (params.get("task_id") or "").strip()
            if not task_id:
                return {"success": False, "error": "task_id is required"}
            scope_err = await _enforce_task_scope(task_id, params.get("scope"))
            if scope_err is not None:
                return scope_err
            try:
                store = get_worker_session_store()
                session = store.get_session(task_id)

                # The session JSON only carries a 500-char preview of the result.
                # The full untruncated result lives in worker_tasks.result_summary
                # (Text column) — read it from the DB so the caller gets the
                # complete output, not the UI preview.
                full_result = None
                try:
                    from app.database import async_session, WorkerTask
                    from sqlalchemy import select
                    async with async_session() as db:
                        row = (await db.execute(
                            select(WorkerTask).where(WorkerTask.id == task_id)
                        )).scalar_one_or_none()
                        if row is not None:
                            full_result = row.result_summary
                            if session is None:
                                session = {
                                    "task_id": row.id,
                                    "session_id": row.session_id,
                                    "project_id": row.project_id,
                                    "card_id": row.card_id,
                                    "intent": row.action,
                                    "model": row.model,
                                    "status": row.status,
                                    "summary": row.description,
                                }
                except Exception as db_err:
                    logger.warning(f"[mcp.workers.get_result] DB read failed: {db_err}")

                if session is None:
                    return {"success": False, "error": f"Worker task not found: {task_id}"}

                if full_result is not None:
                    session = {**session, "result_summary": full_result}

                return {"success": True, **session}
            except Exception as e:
                logger.error(f"[mcp.workers.get_result] failed: {e}")
                return {"success": False, "error": str(e)}

        async def workers_read_artifact(params: dict) -> dict:
            """Read a slice of a finished worker's full raw output (.md artifact).

            Worker callbacks only carry a Haiku-summarized version of the result;
            the verbatim content (file dumps, command stdout, logs) is persisted
            to ~/.voxyflow/worker_artifacts/{task_id}.md by the worker pool.
            This handler reads paginated slices of that file so the dispatcher
            can retrieve exact content on demand.
            """
            from app.services.worker_artifact_store import read_artifact
            task_id = (params.get("task_id") or "").strip()
            if not task_id:
                return {"success": False, "error": "task_id is required"}
            scope_err = await _enforce_task_scope(task_id, params.get("scope"))
            if scope_err is not None:
                return scope_err
            try:
                offset = int(params.get("offset", 0) or 0)
            except (TypeError, ValueError):
                offset = 0
            try:
                length = int(params.get("length", 50_000) or 50_000)
            except (TypeError, ValueError):
                length = 50_000
            try:
                slice_data = read_artifact(task_id, offset=offset, length=length)
                if slice_data is None:
                    return {
                        "success": False,
                        "error": (
                            f"No artifact found for task {task_id}. The worker may "
                            "not have completed yet, may have produced no output, or "
                            "its artifact may have been cleaned up."
                        ),
                    }
                return {"success": True, **slice_data}
            except Exception as e:
                logger.error(f"[mcp.workers.read_artifact] failed: {e}")
                return {"success": False, "error": str(e)}

        async def tools_load(params: dict) -> dict:
            """Activate additional tool scopes dynamically."""
            raw = params.get("scopes", "")
            requested = {s.strip() for s in raw.split(",") if s.strip()}
            valid_scopes = {"voxyflow", "web", "git", "tmux", "file", "system"}
            invalid = requested - valid_scopes
            if invalid:
                return {
                    "success": False,
                    "error": f"Unknown scopes: {invalid}. Valid: {sorted(valid_scopes)}",
                }
            newly_added = requested - _active_scopes
            _active_scopes.update(requested)
            if newly_added:
                # Notify Claude Code to re-fetch tool list
                try:
                    ctx = server.request_context
                    await ctx.session.send_notification(
                        types.ToolListChangedNotification(
                            method="notifications/tools/list_changed",
                        )
                    )
                    logger.info(f"[tools.load] Activated scopes {newly_added}, sent ToolListChanged")
                except Exception as e:
                    logger.warning(f"[tools.load] Activated scopes {newly_added} but notification failed: {e}")
            else:
                logger.info(f"[tools.load] Scopes {requested} already active")
            return {
                "success": True,
                "active_scopes": sorted(_active_scopes),
                "newly_loaded": sorted(newly_added),
            }

        # ---- Knowledge Graph handlers ------------------------------------------

        # --- KG input limits ---
        _KG_MAX_NAME = 500
        _KG_MAX_VALUE = 5000
        _KG_MAX_LIMIT = 200

        def _kg_clamp_limit(raw, default: int, ceiling: int = _KG_MAX_LIMIT) -> int:
            try:
                v = int(raw)
            except (TypeError, ValueError):
                return default
            return max(1, min(v, ceiling))

        def _kg_truncate(s: str | None, maxlen: int) -> str:
            s = (s or "").strip()
            return s[:maxlen]

        async def kg_add(params: dict) -> dict:
            """Add entity + optional relationships/attributes to the KG."""
            from app.services.knowledge_graph_service import get_knowledge_graph_service
            project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip() or "system-main"
            kg = get_knowledge_graph_service()

            entity_name = _kg_truncate(params.get("entity_name"), _KG_MAX_NAME)
            entity_type = _kg_truncate(params.get("entity_type"), _KG_MAX_NAME)
            if not entity_name or not entity_type:
                return {"error": "entity_name and entity_type are required"}

            try:
                eid = await kg.add_entity(entity_name, entity_type, project_id)
                result: dict = {"success": True, "entity_id": eid, "entity_name": entity_name}

                # Relationships
                rels_added = []
                for rel in params.get("relationships", [])[:50]:
                    target = _kg_truncate(rel.get("target"), _KG_MAX_NAME)
                    target_type = _kg_truncate(rel.get("target_type"), _KG_MAX_NAME) or "concept"
                    predicate = _kg_truncate(rel.get("predicate"), _KG_MAX_NAME) or "related_to"
                    if not target:
                        continue
                    tid = await kg.add_entity(target, target_type, project_id)
                    triple_id = await kg.add_triple(eid, predicate, tid, source="chat")
                    rels_added.append({"triple_id": triple_id, "predicate": predicate, "target": target})

                # Attributes
                attrs_added = []
                for attr in params.get("attributes", [])[:50]:
                    key = _kg_truncate(attr.get("key"), _KG_MAX_NAME)
                    value = _kg_truncate(attr.get("value"), _KG_MAX_VALUE)
                    if not key:
                        continue
                    aid = await kg.add_attribute(eid, key, value)
                    attrs_added.append({"attribute_id": aid, "key": key, "value": value})

                if rels_added:
                    result["relationships"] = rels_added
                if attrs_added:
                    result["attributes"] = attrs_added

                await kg.refresh_pinned_cache(project_id)
                logger.info(f"[mcp.kg.add] project={project_id} entity={entity_name!r} rels={len(rels_added)} attrs={len(attrs_added)}")
                return result
            except Exception as e:
                logger.error(f"[mcp.kg.add] failed: {e}")
                return {"error": str(e)}

        async def kg_query(params: dict) -> dict:
            """Search entities and relationships in the KG."""
            from app.services.knowledge_graph_service import get_knowledge_graph_service
            project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip() or "system-main"
            kg = get_knowledge_graph_service()

            name = params.get("name")
            entity_type = params.get("entity_type")
            limit = _kg_clamp_limit(params.get("limit"), 20)
            include_rels = params.get("include_relationships", True)
            as_of_str = params.get("as_of")
            as_of = None
            if as_of_str:
                try:
                    as_of = datetime.fromisoformat(as_of_str)
                except (ValueError, TypeError):
                    return {"error": f"Invalid as_of datetime: {as_of_str!r}"}

            try:
                entities = await kg.query_entities(project_id, name=name, entity_type=entity_type, as_of=as_of, limit=limit)
                result: dict = {"entities": entities, "count": len(entities)}

                if include_rels and entities:
                    rels = await kg.query_relationships(project_id, entity_name=name, limit=limit)
                    result["relationships"] = rels

                logger.info(f"[mcp.kg.query] project={project_id} name={name!r} found={len(entities)}")
                return result
            except Exception as e:
                logger.error(f"[mcp.kg.query] failed: {e}")
                return {"error": str(e)}

        async def kg_timeline(params: dict) -> dict:
            """Chronological entity history."""
            from app.services.knowledge_graph_service import get_knowledge_graph_service
            project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip() or "system-main"
            kg = get_knowledge_graph_service()

            entity_name = params.get("entity_name")
            limit = _kg_clamp_limit(params.get("limit"), 50)

            try:
                events = await kg.get_timeline(project_id, entity_name=entity_name, limit=limit)
                logger.info(f"[mcp.kg.timeline] project={project_id} entity={entity_name!r} events={len(events)}")
                return {"events": events, "count": len(events)}
            except Exception as e:
                logger.error(f"[mcp.kg.timeline] failed: {e}")
                return {"error": str(e)}

        async def kg_invalidate(params: dict) -> dict:
            """Mark a triple or attribute as ended."""
            from app.services.knowledge_graph_service import get_knowledge_graph_service
            project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip() or "system-main"
            kg = get_knowledge_graph_service()

            triple_id = params.get("triple_id")
            attribute_id = params.get("attribute_id")

            if not triple_id and not attribute_id:
                return {"error": "Provide triple_id or attribute_id to invalidate"}

            try:
                ok = await kg.invalidate(triple_id=triple_id, attribute_id=attribute_id)
                await kg.refresh_pinned_cache(project_id)
                logger.info(f"[mcp.kg.invalidate] project={project_id} triple={triple_id} attr={attribute_id} ok={ok}")
                return {"success": ok, "invalidated": triple_id or attribute_id}
            except Exception as e:
                logger.error(f"[mcp.kg.invalidate] failed: {e}")
                return {"error": str(e)}

        async def kg_stats(params: dict) -> dict:
            """KG counts for the current project."""
            from app.services.knowledge_graph_service import get_knowledge_graph_service
            project_id = os.environ.get("VOXYFLOW_PROJECT_ID", "").strip() or "system-main"
            kg = get_knowledge_graph_service()

            try:
                stats = await kg.get_stats(project_id)
                logger.info(f"[mcp.kg.stats] project={project_id} stats={stats}")
                return {"success": True, "project_id": project_id, **stats}
            except Exception as e:
                logger.error(f"[mcp.kg.stats] failed: {e}")
                return {"error": str(e)}

        _heartbeat_path = Path(
            os.environ.get("VOXYFLOW_DATA_DIR", os.path.expanduser("~/.voxyflow"))
        ) / "workspace" / "heartbeat.md"

        async def heartbeat_read(params: dict) -> dict:
            try:
                if not _heartbeat_path.exists():
                    return {"content": "", "exists": False}
                return {"content": _heartbeat_path.read_text(encoding="utf-8"), "exists": True}
            except Exception as e:
                return {"error": str(e)}

        async def heartbeat_write(params: dict) -> dict:
            content = params.get("content", "")
            try:
                _heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
                _heartbeat_path.write_text(content, encoding="utf-8")
                return {"status": "ok", "bytes": len(content)}
            except Exception as e:
                return {"error": str(e)}

        _SYSTEM_HANDLERS.update({
            "heartbeat_read": heartbeat_read,
            "heartbeat_write": heartbeat_write,
            "tools_load": tools_load,
            "system_exec": system_exec,
            "web_search": web_search,
            "web_fetch": web_fetch,
            "file_read": file_read,
            "file_write": file_write,
            "file_patch": file_patch,
            "file_list": file_list,
            "git_status": git_status,
            "git_log": git_log,
            "git_diff": git_diff,
            "git_branches": git_branches,
            "git_commit": git_commit,
            "tmux_list": tmux_list,
            "tmux_run": tmux_run,
            "tmux_send": tmux_send,
            "tmux_capture": tmux_capture,
            "tmux_new": tmux_new,
            "tmux_kill": tmux_kill,
            "task_complete": handle_task_complete,
            "memory_search": memory_search,
            "memory_save": memory_save,
            "memory_delete": memory_delete,
            "memory_get": memory_get,
            "knowledge_search": knowledge_search,
            "task_steer": task_steer,
            "task_peek": task_peek,
            "task_cancel": task_cancel,
            "sessions_list": sessions_list,
            "workers_list": workers_list,
            "workers_get_result": workers_get_result,
            "workers_read_artifact": workers_read_artifact,
            "kg_add": kg_add,
            "kg_query": kg_query,
            "kg_timeline": kg_timeline,
            "kg_invalidate": kg_invalidate,
            "kg_stats": kg_stats,
        })
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

    for var in path_vars:
        value = remaining_params.pop(var, None)
        if value is None:
            # Auto-inject from environment (e.g. project_id → VOXYFLOW_PROJECT_ID)
            env_key = f"VOXYFLOW_{var.upper()}"
            value = os.environ.get(env_key, "").strip() or None
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
