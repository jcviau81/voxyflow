"""_TOOL_DEFINITIONS — the MCP tool catalog.

Extracted from ``app/mcp_server.py`` in H8 — this module is pure data.
Each entry describes one MCP tool:

* ``name``           — tool ID used by MCP ``call_tool``
* ``description``    — LLM-facing doc
* ``inputSchema``    — JSON Schema for arguments
* ``_http``          — ``(method, path, payload_fn)`` for REST-backed tools
* ``_handler``       — name of an async handler for non-HTTP tools (``system.*``, ``web.*``, memory, KG, etc.)
* ``_scope`` / ``_role`` / ``_cat`` — optional metadata used by the consolidator / role filter

All runtime behavior stays in ``mcp_server.py``; this module only holds the list.
"""

from __future__ import annotations

_TOOL_DEFINITIONS: list[dict] = [
    # ---- Main Board Cards (system-main project, backward-compatible aliases) ─
    {
        "name": "voxyflow.card.create_unassigned",
        "description": "Create a card on the Main Board (system-main project).",
        "inputSchema": {
            "type": "object",
            "required": ["content"],
            "properties": {
                "content": {"type": "string", "description": "Card title"},
                "color": {
                    "type": "string",
                    "enum": ["yellow", "blue", "green", "pink", "purple", "orange"],
                },
                "description": {"type": "string"},
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
        "description": "List cards on the Main Board (system-main project).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_http": ("GET", "/api/cards/unassigned", None),
    },

    # ---- Projects ----------------------------------------------------------
    {
        "name": "voxyflow.project.create",
        "description": "Create a new project.",
        "inputSchema": {
            "type": "object",
            "required": ["title"],
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string"},
                "tech_stack": {"type": "string", "description": "Comma-separated"},
                "github_url": {"type": "string"},
                "github_repo": {"type": "string", "description": "owner/repo format"},
                "local_path": {"type": "string"},
            },
        },
        "_http": ("POST", "/api/projects", None),
    },
    {
        "name": "voxyflow.project.list",
        "description": "List all projects.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_http": ("GET", "/api/projects", None),
    },
    {
        "name": "voxyflow.project.get",
        "description": "Get a project with its cards.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string"},
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
        "description": "Create a new card in a project.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id", "title"],
            "properties": {
                "project_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["card", "todo", "in-progress", "done"],
                    "description": "Default: card",
                },
                "priority": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 4,
                    "description": "0=none 1=low 2=medium 3=high 4=critical",
                },
                "agent_type": {
                    "type": "string",
                    "enum": ["general", "researcher", "coder", "designer", "architect", "writer", "qa"],
                },
            },
        },
        "_http": ("POST", "/api/projects/{project_id}/cards", None),
    },
    {
        "name": "voxyflow.card.list",
        "description": "List cards for a project.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string"},
            },
        },
        "_http": ("GET", "/api/projects/{project_id}/cards", None),
    },
    {
        "name": "voxyflow.card.get",
        "description": "Get a card.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string"},
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
                "card_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "priority": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 4,
                },
                "status": {
                    "type": "string",
                    "enum": ["card", "todo", "in-progress", "done", "archived"],
                },
            },
        },
        "_http": ("PATCH", "/api/cards/{card_id}", None),
    },
    {
        "name": "voxyflow.card.move",
        "description": "Move a card to a different status column.",
        "inputSchema": {
            "type": "object",
            "required": ["card_id", "new_status"],
            "properties": {
                "card_id": {"type": "string"},
                "new_status": {
                    "type": "string",
                    "enum": ["card", "todo", "in-progress", "done", "archived"],
                },
            },
        },
        "_http": ("PATCH", "/api/cards/{card_id}", lambda p: {"status": p.get("new_status") or p["status"]}),
    },
    {
        "name": "voxyflow.card.archive",
        "description": "Archive a card (recoverable soft-delete).",
        "inputSchema": {
            "type": "object",
            "required": ["card_id"],
            "properties": {
                "card_id": {"type": "string"},
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
        "description": "List wiki pages for a project.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string"},
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
        "description": "Get a wiki page.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id", "page_id"],
            "properties": {
                "project_id": {"type": "string"},
                "page_id": {"type": "string"},
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
        "description": "List documents attached to a project.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id"],
            "properties": {
                "project_id": {"type": "string"},
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
        "description": "List recent worker tasks (auto-scoped to current project; scope='all' for system-wide).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["running", "done", "failed", "timed_out", "cancelled"],
                },
                "limit": {"type": "integer", "description": "Default 10", "default": 10},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                },
            },
        },
        "_handler": "workers_list",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.workers.get_result",
        "description": "Get full details of a worker task by task_id (project-scoped; scope='all' to bypass).",
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string"},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                },
            },
        },
        "_handler": "workers_get_result",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.workers.read_artifact",
        "description": "Read the raw on-disk artifact of a finished worker (full verbatim output; paginated via offset/length).",
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string"},
                "offset": {"type": "integer", "description": "Default 0"},
                "length": {"type": "integer", "description": "Default 50000"},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
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
        "description": "System health status.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_http": ("GET", "/api/health", None),
    },
    {
        "name": "voxyflow.jobs.list",
        "description": "List scheduled jobs.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_http": ("GET", "/api/jobs", None),
    },
    {
        "name": "voxyflow.jobs.create",
        "description": (
            "Create a scheduled job. Types & payloads: "
            "agent_task {instruction, project_id?}; "
            "execute_board {project_id, statuses?}; "
            "execute_card {card_id, project_id?}; "
            "reminder {message}; "
            "rag_index {project_id?, path?}. "
            "Schedule: cron or shorthand (every_5min, every_1h, every_day)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["name", "type", "schedule"],
            "properties": {
                "name": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["agent_task", "execute_card", "execute_board", "reminder", "rag_index", "custom"],
                },
                "schedule": {"type": "string", "description": "cron or shorthand"},
                "enabled": {"type": "boolean", "description": "Default true"},
                "payload": {"type": "object", "description": "See description for per-type fields"},
            },
        },
        "_http": ("POST", "/api/jobs", None),
    },
    {
        "name": "voxyflow.jobs.update",
        "description": "Update a scheduled job (pass only fields to change).",
        "inputSchema": {
            "type": "object",
            "required": ["job_id"],
            "properties": {
                "job_id": {"type": "string"},
                "name": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["agent_task", "execute_card", "execute_board", "reminder", "rag_index", "custom"],
                },
                "schedule": {"type": "string"},
                "enabled": {"type": "boolean"},
                "payload": {"type": "object"},
            },
        },
        "_http": ("PATCH", "/api/jobs/{job_id}", None),
    },
    {
        "name": "voxyflow.jobs.delete",
        "description": "Delete a scheduled job.",
        "inputSchema": {
            "type": "object",
            "required": ["job_id"],
            "properties": {
                "job_id": {"type": "string"},
            },
        },
        "_http": ("DELETE", "/api/jobs/{job_id}", None),
    },

    # ======================================================================
    # HEARTBEAT — read/write ~/.voxyflow/workspace/heartbeat.md
    # ======================================================================

    {
        "name": "voxyflow.heartbeat.read",
        "description": "Read the Agent Heartbeat file (~/.voxyflow/workspace/heartbeat.md).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_handler": "heartbeat_read",
    },
    {
        "name": "voxyflow.heartbeat.write",
        "description": "Write the full Heartbeat file content. The agent polls every 5 min and follows instructions below the --- separator.",
        "inputSchema": {
            "type": "object",
            "required": ["content"],
            "properties": {
                "content": {"type": "string", "description": "Full file content"},
            },
        },
        "_handler": "heartbeat_write",
    },

    # ======================================================================
    # SYSTEM TOOLS — direct execution, no REST API
    # ======================================================================

    {
        "name": "system.exec",
        "description": "Run a shell command on the local machine. Returns stdout, stderr, exit_code, and duration. cwd defaults to the workspace and must stay under it.",
        "inputSchema": {
            "type": "object",
            "required": ["command"],
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory (optional; must be under ~/.voxyflow/workspace). Defaults to the workspace root."},
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
        "description": "Legacy completion signal. Prefer voxyflow.worker.complete.",
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

    # ---- Strict Worker Lifecycle: claim + complete -------------------------
    {
        "name": "voxyflow.worker.claim",
        "description": (
            "Claim your assigned task and declare a plan. You MUST call this "
            "as your first action before any other tool use."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["task_id", "plan"],
            "properties": {
                "task_id": {"type": "string", "description": "Your assigned task ID"},
                "plan": {
                    "type": "string",
                    "description": (
                        "One or two sentences: what you understand the task to be "
                        "and how you intend to approach it."
                    ),
                },
            },
        },
        "_handler": "worker_claim",
        "_role": "worker",
        "_scope": "core",
    },
    {
        "name": "voxyflow.worker.complete",
        "description": (
            "Finalize your task and deliver a structured, dispatcher-facing summary. "
            "This is the ONLY way to return results — no other output reaches the dispatcher. "
            "Call this exactly once, as your last action."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["task_id", "status", "summary"],
            "properties": {
                "task_id": {"type": "string", "description": "Your assigned task ID"},
                "status": {
                    "type": "string",
                    "enum": ["success", "partial", "failed"],
                    "description": "Outcome",
                },
                "summary": {
                    "type": "string",
                    "description": (
                        "What you did and what the dispatcher needs to know, in your own words. "
                        "Not the raw output — a real summary. Minimum 20 chars."
                    ),
                },
                "findings": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: 3–7 short bullet points highlighting key results.",
                },
                "pointers": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["label"],
                        "properties": {
                            "label": {"type": "string"},
                            "offset": {"type": "integer"},
                            "length": {"type": "integer"},
                        },
                    },
                    "description": (
                        "Optional: labelled offsets into the full artifact the dispatcher "
                        "can fetch via voxyflow.workers.read_artifact for detail."
                    ),
                },
                "next_step": {
                    "type": "string",
                    "description": "Optional: one-line suggestion of what should happen next.",
                },
            },
        },
        "_handler": "worker_complete",
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
        "description": (
            "Search long-term memory. Default scope is the current project only "
            "(isolation preserved). Pass `scope='global'` for the shared global "
            "collection or `scope='other:<project_id>'` to query a specific other "
            "project explicitly — only use a cross-project scope when the user "
            "asks for it (e.g. \"check what was said in project X about Y\")."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "description": "Default 10"},
                "offset": {"type": "integer", "description": "Default 0"},
                "scope": {
                    "type": "string",
                    "description": (
                        "Retrieval scope. 'current' (default) = this project only. "
                        "'global' = shared cross-project memory. "
                        "'other:<project_id>' = one specific other project. "
                        "'current+global' = this project plus global."
                    ),
                },
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
        "description": (
            "Save a fact, decision, preference, lesson, or procedure to long-term "
            "memory (auto-scoped to current project). Use `type='procedure'` for "
            "reusable 'how to do X' workflows — the content should start with "
            "\"How to {task}:\" and list ≥2 ordered steps. Procedures are surfaced "
            "in a dedicated block above regular retrieval."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["text"],
            "properties": {
                "text": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["decision", "preference", "lesson", "fact", "context", "procedure"],
                },
                "importance": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
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
        "description": "Search the current project's knowledge base (RAG) for background context.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
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

    # ---- Undo journal (reversible actions taken this chat) -------------------
    {
        "name": "voxyflow.undo.list",
        "description": (
            "List recent reversible actions taken during this chat (card.create, "
            "card.archive, card.duplicate, memory.save). Each entry carries an "
            "id you can pass to voxyflow.undo.apply to revert it. Entries TTL "
            "after 30 minutes. Use when the user asks 'annule ça' or before "
            "offering a revert option."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max entries to return (default 5, max 20)"},
            },
        },
        "_handler": "undo_list",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.undo.apply",
        "description": (
            "Undo a recent reversible action by replaying its inverse. If `id` "
            "is omitted, undoes the most recent action. On success the entry "
            "is consumed (a re-do is not automatic)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Undo entry id from voxyflow.undo.list (omit for most recent)"},
            },
        },
        "_handler": "undo_apply",
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
