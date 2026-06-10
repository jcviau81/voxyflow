"""Kanban tool defs — workspaces, cards, relations, time tracking, checklists.

Extracted verbatim from ``app/mcp_tool_defs.py`` (H8 monolith split).
Pure data — every entry follows the schema documented in ``app.mcp_tool_defs``.
"""

from __future__ import annotations

from .postprocess import _minimize_card_list, _minimize_card_list_archived


KANBAN_TOOLS: list[dict] = [
    # ---- Main Board Cards (system-main workspace) ─
    {
        "name": "voxyflow.card.create_unassigned",
        "description": "Create a card on the Main Board (system-main workspace).",
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
        "description": "List cards on the Main Board (system-main workspace). Returns minimal fields (id, title, status, priority, position, assignee, agent_type).",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_http": ("GET", "/api/cards/unassigned", None),
        "_post_process": _minimize_card_list,
    },

    # ---- Workspaces --------------------------------------------------------
    {
        "name": "voxyflow.workspace.create",
        "description": "Create a new workspace.",
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
        "_http": ("POST", "/api/workspaces", None),
    },
    {
        "name": "voxyflow.workspace.list",
        "description": "List all workspaces.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_http": ("GET", "/api/workspaces", None),
    },
    {
        "name": "voxyflow.workspace.get",
        "description": "Get a workspace with its cards.",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string"},
            },
        },
        "_http": ("GET", "/api/workspaces/{workspace_id}", None),
    },
    {
        "name": "voxyflow.workspace.delete",
        "description": "Delete a workspace and all its cards (irreversible).",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID to delete"},
            },
        },
        "_http": ("DELETE", "/api/workspaces/{workspace_id}", None),
    },
    {
        "name": "voxyflow.workspace.update",
        "description": "Update an existing workspace (title, description, status, context, github_url, etc.).",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID to update"},
                "title": {"type": "string", "description": "New workspace title"},
                "description": {"type": "string", "description": "New workspace description"},
                "status": {"type": "string", "enum": ["active", "archived"], "description": "Workspace status"},
                "context": {"type": "string", "description": "Additional context for the AI"},
                "github_url": {"type": "string", "description": "GitHub repository URL"},
                "local_path": {"type": "string", "description": "Local filesystem path"},
            },
        },
        "_http": ("PATCH", "/api/workspaces/{workspace_id}", None),
    },
    {
        "name": "voxyflow.workspace.export",
        "description": "Export a workspace as a JSON snapshot (all cards, wiki, metadata).",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID to export"},
            },
        },
        "_http": ("GET", "/api/workspaces/{workspace_id}/export", None),
    },
    {
        "name": "voxyflow.workspace.archive",
        "description": "Archive a workspace (hide from main list, keep all data).",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID to archive"},
            },
        },
        "_http": ("POST", "/api/workspaces/{workspace_id}/archive", None),
    },
    {
        "name": "voxyflow.workspace.restore",
        "description": "Restore an archived workspace back to active status.",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id"],
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace ID to restore"},
            },
        },
        "_http": ("POST", "/api/workspaces/{workspace_id}/restore", None),
    },

    # ---- Cards -------------------------------------------------------------
    {
        "name": "voxyflow.card.create",
        "description": "Create a new card in a workspace.",
        "inputSchema": {
            "type": "object",
            "required": ["workspace_id", "title"],
            "properties": {
                "workspace_id": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["backlog", "todo", "in-progress", "done"],
                    "description": "Default: backlog",
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
        "_http": ("POST", "/api/workspaces/{workspace_id}/cards", None),
    },
    {
        "name": "voxyflow.card.list",
        "description": (
            "List active (non-archived) cards for the current workspace. "
            "workspace_id is auto-scoped from the active chat context "
            "(VOXYFLOW_WORKSPACE_ID) — omit it in workspace chats. In general chat "
            "it defaults to the Main Board. Archived cards are excluded; use "
            "card.list_archived for those. Returns minimal fields (id, title, "
            "status, priority, position, assignee, agent_type)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Optional — normally auto-injected; only pass a UUID to override.",
                },
            },
        },
        "_http": ("GET", "/api/workspaces/{workspace_id}/cards", None),
        "_post_process": _minimize_card_list,
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
                    "enum": ["backlog", "todo", "in-progress", "done", "archived"],
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
                    "enum": ["backlog", "todo", "in-progress", "done", "archived"],
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
        "description": "Duplicate a card within the same workspace.",
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
        "description": (
            "List archived cards for the current workspace. workspace_id is "
            "auto-scoped from VOXYFLOW_WORKSPACE_ID; omit it in workspace chats. "
            "Returns minimal fields only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {
                    "type": "string",
                    "description": "Optional — normally auto-injected; only pass a UUID to override.",
                },
            },
        },
        "_http": ("GET", "/api/workspaces/{workspace_id}/cards/archived", None),
        "_post_process": _minimize_card_list_archived,
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
]
