"""System tool defs — shell exec, web, file, git, tmux (worker-only scopes).

Extracted verbatim from ``app/mcp_tool_defs.py`` (H8 monolith split).
Pure data — every entry follows the schema documented in ``app.mcp_tool_defs``.
"""

from __future__ import annotations


SYSTEM_TOOLS: list[dict] = [
    # ======================================================================
    # SYSTEM TOOLS — direct execution, no REST API
    # ======================================================================

    {
        "name": "system.exec",
        "description": "Run a shell command on the local machine. Returns stdout, stderr, exit_code, and duration. cwd defaults to the workspace root; any existing directory is allowed (no sandbox confinement on single-user installs).",
        "inputSchema": {
            "type": "object",
            "required": ["command"],
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "cwd": {"type": "string", "description": "Working directory (optional; defaults to the workspace root). No confinement enforced on single-user installs."},
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
]
