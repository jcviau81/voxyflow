"""Wiki, document, AI-feature, and focus-session tool defs.

Extracted verbatim from ``app/mcp_tool_defs.py`` (H8 monolith split).
Pure data — every entry follows the schema documented in ``app.mcp_tool_defs``.
"""

from __future__ import annotations

from .postprocess import _minimize_wiki_get


WIKI_DOCS_AI_TOOLS: list[dict] = [
    # ---- Wiki --------------------------------------------------------------
    {
        "name": "voxyflow.wiki.list",
        "description": "List wiki pages for a workspace.",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string"},
            },
        },
        "_http": ("GET", "/api/workspaces/{workspace_id}/wiki", None),
    },
    {
        "name": "voxyflow.wiki.create",
        "description": "Create a new wiki page for a workspace.",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id", "title", "content"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID"},
                "title": {"type": "string", "description": "Page title"},
                "content": {"type": "string", "description": "Page content (Markdown)"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
            },
        },
        "_http": ("POST", "/api/workspaces/{workspace_id}/wiki", None),
    },
    {
        "name": "voxyflow.wiki.get",
        "description": (
            "Get a wiki page (content capped at 15k chars; "
            "content_truncated/content_total_chars flag longer pages)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id", "page_id"],
            "properties": {
                "workspace_id": {"type": "string"},
                "page_id": {"type": "string"},
            },
        },
        "_http": ("GET", "/api/workspaces/{workspace_id}/wiki/{page_id}", None),
        "_post_process": _minimize_wiki_get,
    },
    {
        "name": "voxyflow.wiki.update",
        "description": "Update an existing wiki page.",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id", "page_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID"},
                "page_id": {"type": "string", "description": "Wiki page ID"},
                "title": {"type": "string", "description": "New title"},
                "content": {"type": "string", "description": "New content (Markdown)"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Updated tags"},
            },
        },
        "_http": ("PUT", "/api/workspaces/{workspace_id}/wiki/{page_id}", None),
    },
    {
        "name": "voxyflow.wiki.delete",
        "description": "Delete a wiki page.",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id", "page_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID"},
                "page_id": {"type": "string", "description": "Wiki page ID to delete"},
            },
        },
        "_http": ("DELETE", "/api/workspaces/{workspace_id}/wiki/{page_id}", None),
    },

    # ---- AI ----------------------------------------------------------------
    {
        "name": "voxyflow.ai.standup",
        "description": "Generate an AI daily standup report for a workspace (what's done, in-progress, blocked).",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID"},
            },
        },
        "_http": ("POST", "/api/workspaces/{workspace_id}/standup", None),
    },
    {
        "name": "voxyflow.ai.brief",
        "description": "Generate a comprehensive AI workspace brief using the most capable model (Opus).",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID"},
            },
        },
        "_http": ("POST", "/api/workspaces/{workspace_id}/brief", None),
    },
    {
        "name": "voxyflow.ai.health",
        "description": "Run an AI workspace health check — assess risks, blockers, and team velocity.",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID"},
            },
        },
        "_http": ("POST", "/api/workspaces/{workspace_id}/health", None),
    },
    {
        "name": "voxyflow.ai.prioritize",
        "description": "Use AI to smart-prioritize cards in a workspace based on value, complexity, and dependencies.",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID"},
            },
        },
        "_http": ("POST", "/api/workspaces/{workspace_id}/prioritize", None),
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
                "workspace_id": {"type": "string", "description": "Optional workspace context"},
            },
        },
        "_http": ("POST", "/api/code/review", None),
    },

    # ---- Documents ---------------------------------------------------------
    {
        "name": "voxyflow.doc.list",
        "description": "List documents attached to a workspace.",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string"},
            },
        },
        "_http": ("GET", "/api/workspaces/{workspace_id}/documents", None),
    },
    {
        "name": "voxyflow.doc.delete",
        "description": "Delete a document from a workspace.",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id", "document_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID"},
                "document_id": {"type": "string", "description": "Document ID to delete"},
            },
        },
        "_http": ("DELETE", "/api/workspaces/{workspace_id}/documents/{document_id}", None),
    },

    # ---- Focus Sessions ----------------------------------------------------
    {
        "name": "voxyflow.focus.log",
        "description": "Log a completed Pomodoro/focus session for a card or workspace.",
        "inputSchema": {
            "type": "object",
            "required": ["duration_minutes", "completed", "started_at", "ended_at"],
            "properties": {
                "card_id": {"type": "string", "description": "Card ID (optional)"},
                "workspace_id": {"type": "string", "description": "Workspace ID (optional)"},
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
        "description": "Get focus session analytics for a workspace (totals, by card, by day).",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID"},
            },
        },
        "_http": ("GET", "/api/workspaces/{workspace_id}/focus", None),
    },
]
