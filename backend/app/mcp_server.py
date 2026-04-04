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

# Role-based tool filtering: "dispatcher" limits tools to lightweight CRUD +
# knowledge; "worker" (or unset) exposes everything.  Set via env var
# VOXYFLOW_MCP_ROLE passed through the MCP config.
VOXYFLOW_MCP_ROLE = os.environ.get("VOXYFLOW_MCP_ROLE", "worker")

# Tools tagged _role="worker" are hidden from the dispatcher.
# Tools with no _role tag (or _role="all") are available to everyone.

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
                    "enum": ["idea", "todo", "in-progress", "done"],
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
                    "enum": ["idea", "todo", "in-progress", "done", "archived"],
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
                    "enum": ["idea", "todo", "in-progress", "done", "archived"],
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

    # ---- Worker Ledger -----------------------------------------------------
    {
        "name": "voxyflow.workers.list",
        "description": "List recent worker tasks from the Worker Ledger. Use to check if a similar task is already running before dispatching.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Filter by session ID"},
                "project_id": {"type": "string", "description": "Filter by project ID"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "running", "done", "failed", "cancelled"],
                    "description": "Filter by status",
                },
                "limit": {"type": "integer", "description": "Max results (default 10)", "default": 10},
            },
        },
        "_http": ("GET", "/api/worker-tasks", None),
    },
    {
        "name": "voxyflow.workers.get_result",
        "description": "Get the full details and result of a specific worker task by task_id.",
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string", "description": "Worker task ID"},
            },
        },
        "_http": ("GET", "/api/worker-tasks/{task_id}", None),
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
    },

    # ---- Memory (semantic search across all memory) -------------------------
    {
        "name": "memory.search",
        "description": "Search Voxy's long-term memory (global + project) for relevant context. Use when you need to recall prior conversations, decisions, user preferences, or stored facts.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Natural language search query — describe what you're trying to remember"},
                "limit": {"type": "integer", "description": "Max results to return (default 5)"},
            },
        },
        "_handler": "memory_search",
    },

    # ---- Knowledge Base (on-demand RAG) ------------------------------------
    {
        "name": "knowledge.search",
        "description": "Search the project knowledge base (RAG) for relevant context. Use when you need background information about the project that isn't in the task description.",
        "inputSchema": {
            "type": "object",
            "required": ["project_id", "query"],
            "properties": {
                "project_id": {"type": "string", "description": "Project ID to search within"},
                "query": {"type": "string", "description": "Search query — describe what you're looking for"},
            },
        },
        "_handler": "knowledge_search",
    },
]

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
            """Semantic search across Voxy's long-term memory."""
            from app.services.memory_service import get_memory_service
            query = params.get("query", "")
            if not query:
                return {"error": "query is required"}
            limit = params.get("limit", 5)
            try:
                ms = get_memory_service()
                results = ms.search_memory(query, limit=limit)
                if not results:
                    return {"result": "No matching memories found."}
                formatted = []
                for r in results:
                    formatted.append({
                        "text": r.get("text", ""),
                        "score": round(r.get("score", 0), 3),
                        "collection": r.get("collection", ""),
                    })
                return {"results": formatted}
            except Exception as e:
                return {"error": str(e)}

        async def knowledge_search(params: dict) -> dict:
            """RAG search on project knowledge base — on-demand tool."""
            from app.services.rag_service import get_rag_service
            project_id = params.get("project_id", "system-main")
            query = params.get("query", "")
            if not query:
                return {"error": "query is required"}
            try:
                result = await get_rag_service().build_rag_context(project_id, query)
                return {"result": result or "No relevant knowledge found."}
            except Exception as e:
                return {"error": str(e)}

        _SYSTEM_HANDLERS.update({
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
            "knowledge_search": knowledge_search,
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

    # Ensure success flag is present so the frontend tool:executed handler
    # can distinguish successes (it checks result.success).
    if isinstance(data, dict) and "success" not in data:
        data["success"] = True
    return data


# ---------------------------------------------------------------------------
# Build MCP tool list (without _http internal key)
# ---------------------------------------------------------------------------

def _visible_tools() -> list[dict]:
    """Return tool definitions visible to the current role."""
    role = VOXYFLOW_MCP_ROLE
    if role == "dispatcher":
        return [t for t in _TOOL_DEFINITIONS if t.get("_role", "all") != "worker"]
    return _TOOL_DEFINITIONS  # workers see everything


def _public_tool_defs() -> list[dict]:
    """Return tool definitions without internal keys (_http, _handler, _role)."""
    return [
        {k: v for k, v in t.items() if not k.startswith("_")}
        for t in _visible_tools()
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
        """Expose Voxyflow tools filtered by role (dispatcher vs worker)."""
        tools = []
        for defn in _visible_tools():
            tools.append(
                Tool(
                    name=defn["name"],
                    description=defn["description"],
                    inputSchema=defn["inputSchema"],
                )
            )
        logger.info(f"[MCP] list_tools → role={VOXYFLOW_MCP_ROLE}, {len(tools)} tools exposed")
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

        # Enforce role-based access (defense in depth — even if list_tools filters)
        if VOXYFLOW_MCP_ROLE == "dispatcher" and tool_def.get("_role") == "worker":
            logger.warning(f"[MCP] Blocked dispatcher from calling worker-only tool: {name}")
            return [TextContent(type="text", text=json.dumps({
                "success": False,
                "error": f"Tool '{name}' is not available to the dispatcher. Delegate this task to a worker.",
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


def get_tools_for_names(names: set[str]) -> list[dict]:
    """Return tool definitions (public, no internal keys) filtered to the given names."""
    return [
        {k: v for k, v in t.items() if k not in ("_http", "_handler")}
        for t in _TOOL_DEFINITIONS
        if t["name"] in names
    ]
