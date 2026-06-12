"""Worker / task tool defs — sessions, worker ledger, lifecycle, steer, endpoints, delegate.

Extracted verbatim from ``app/mcp_tool_defs.py`` (H8 monolith split).
Pure data — every entry follows the schema documented in ``app.mcp_tool_defs``.
"""

from __future__ import annotations


WORKERS_MONITOR_TOOLS: list[dict] = [
    # ---- CLI Sessions ------------------------------------------------------
    {
        "name": "voxyflow.sessions.list",
        "description": "List active CLI subprocess sessions (chat and worker processes). Auto-scoped to the current workspace — pass scope='all' for a system-wide view.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                    "description": "Session visibility scope. 'current' (default) shows only this workspace's sessions; 'all' shows every active CLI subprocess. Ignored in general chat, which always sees all.",
                },
            },
        },
        "_handler": "sessions_list",
        "_scope": "voxyflow",
    },

    # ---- Worker Ledger -----------------------------------------------------
    {
        "name": "voxyflow.workers.list",
        "description": "List recent worker tasks (auto-scoped to current workspace; scope='all' for system-wide).",
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
        "description": "Get full details of a worker task by task_id (workspace-scoped; scope='all' to bypass). Returns a `completion` object with the structured worker.complete payload (status, summary, findings, pointers, next_step) when available — that's the dispatcher-facing deliverable, not the raw narration in result_summary.",
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string"},
                "offset": {"type": "integer", "description": "result_summary page start (default 0)"},
                "length": {"type": "integer", "description": "result_summary page size (default and max 15000)"},
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
                "length": {"type": "integer", "description": "Default and max 15000 — page with growing offsets"},
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
        "name": "voxyflow.workers.ack_artifact",
        "description": (
            "Acknowledge a worker artifact: delete the .md file from disk, mark acked_at. "
            "Call this after consuming the artifact content (read, memory.save, wiki, card updates). "
            "Keeps metadata sidecar as audit trace. "
            "Returns {success, acked_at, size_bytes_freed} on success, "
            "{success: false, error} if already acked or unknown task."
        ),
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
        "_handler": "workers_ack_artifact",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.workers.list_unread",
        "description": (
            "List worker artifacts that have not yet been acked (acked_at is null), "
            "sorted by created_at desc. Each entry: {task_id, created_at, read_at, "
            "size_bytes, summary_preview (first 200 chars)}. "
            "Use at session start to find pending deliverables from previous workers. "
            "Auto-scoped to the current workspace; pass scope='all' for system-wide."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Default 50"},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                    "description": "Artifact visibility scope. 'current' (default) shows only this workspace's artifacts; 'all' shows every unread artifact. Ignored in general chat, which always sees all.",
                },
            },
        },
        "_handler": "workers_list_unread",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.task.peek",
        "description": "Monitor a running worker task in real time. Returns the recent tools called, tool count, running duration, and current status. Strict workspace scope — pass scope='all' to peek at tasks from other workspaces.",
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string", "description": "Worker task ID (full ID, exact match)"},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                    "description": "Workspace-ownership enforcement. 'current' (default) rejects tasks from other workspaces; 'all' bypasses the check.",
                },
            },
        },
        "_handler": "task_peek",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.task.cancel",
        "description": "Cancel a running worker task immediately. Strict workspace scope — tasks from other workspaces cannot be cancelled unless scope='all' is passed.",
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string", "description": "Worker task ID to cancel"},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                    "description": "Workspace-ownership enforcement. 'current' (default) rejects tasks from other workspaces; 'all' bypasses the check.",
                },
            },
        },
        "_handler": "task_cancel",
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.session.read",
        "description": (
            "Read the current chat session history and return a condensed timeline of key events. "
            "Use this when you need to recall what happened earlier in the session — decisions made, "
            "tasks delegated, plans agreed, go signals given. Returns user instructions, delegate blocks, "
            "worker completions, and key assistant decisions in chronological order. "
            "Much more reliable than relying on context window alone for long sessions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "chat_id": {
                    "type": "string",
                    "description": "Chat session ID (e.g. 'workspace:uuid'). Defaults to current session if omitted.",
                },
                "last_n_messages": {
                    "type": "integer",
                    "description": "How many recent messages to scan (default 200, max 500). Increase if session is very long.",
                    "default": 200,
                },
                "focus": {
                    "type": "string",
                    "enum": ["decisions", "delegates", "all"],
                    "description": "What to focus on: 'decisions' (user instructions + go signals), 'delegates' (spawned workers), 'all' (everything notable). Default: 'all'",
                    "default": "all",
                },
            },
        },
        "_handler": "session_read",
        "_scope": "voxyflow",
    },
]


WORKER_LIFECYCLE_TOOLS: list[dict] = [
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
                        "Dispatcher-facing brief. This is the ONLY text injected into the "
                        "dispatcher's next turn — keep it compressed, telegraphic, information-"
                        "dense. Drop articles, filler, and pleasantries. State outcome + key "
                        "facts the dispatcher needs to reason about next steps. "
                        "Target ≤500 chars; hard cap 2000. Minimum 20 chars. "
                        "Full verbose output still lands in the artifact — don't repeat it here."
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
            "Available scopes: voxyflow (cards, wiki, memory, workspaces), "
            "web (search, fetch), git (status, log, diff, commit), tmux (sessions). "
            "Base tools (file.read, file.write, file.list, system.exec, voxyflow.worker.complete) "
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
]


TASK_STEER_TOOLS: list[dict] = [
    # ---- Task Steer -----------------------------------------------------------
    {
        "name": "task.steer",
        "description": "Inject a steering message into a running worker task. Use this to redirect a worker mid-execution. Strict workspace scope — tasks from other workspaces are rejected unless scope='all'.",
        "inputSchema": {
            "type": "object",
            "required": ["task_id", "message"],
            "properties": {
                "task_id": {"type": "string", "description": "Worker task ID to steer"},
                "message": {"type": "string", "description": "Steering instruction to inject into the worker's conversation"},
                "scope": {
                    "type": "string",
                    "enum": ["current", "all"],
                    "description": "Workspace-ownership enforcement. 'current' (default) rejects tasks from other workspaces; 'all' bypasses the check.",
                },
            },
        },
        "_handler": "task_steer",
        "_scope": "voxyflow",
    },
]


ENDPOINT_TOOLS: list[dict] = [
    # ---- Endpoint / My Providers management --------------------------------
    {
        "name": "voxyflow.endpoint.list",
        "description": "List all saved LLM endpoints (My Providers) configured in Voxyflow settings.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
        "_http": ("GET", "/api/settings/endpoints", None),
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.endpoint.add",
        "description": "Add or update a named LLM endpoint (My Providers). If the id already exists it is replaced. Use provider_type 'ollama' for Ollama instances.",
        "inputSchema": {
            "type": "object",
            "required": ["name", "provider_type", "url"],
            "properties": {
                "id": {"type": "string", "description": "Optional UUID — auto-generated if omitted"},
                "name": {"type": "string", "description": "Display name, e.g. 'Brain', 'M5Max'"},
                "provider_type": {
                    "type": "string",
                    "enum": ["ollama", "openai", "lmstudio", "groq", "mistral", "gemini", "anthropic"],
                    "description": "LLM provider type",
                },
                "url": {"type": "string", "description": "Base URL, e.g. 'http://10.0.0.1:11434'"},
                "api_key": {"type": "string", "description": "API key — leave empty for local providers like Ollama"},
            },
        },
        "_http": ("POST", "/api/settings/endpoints", None),
        "_scope": "voxyflow",
    },
    {
        "name": "voxyflow.endpoint.remove",
        "description": "Remove a saved LLM endpoint (My Providers) by its id.",
        "inputSchema": {
            "type": "object",
            "required": ["endpoint_id"],
            "properties": {
                "endpoint_id": {"type": "string", "description": "UUID of the endpoint to remove"},
            },
        },
        "_http": ("DELETE", "/api/settings/endpoints/{endpoint_id}", None),
        "_scope": "voxyflow",
    },
]


DELEGATE_TOOLS: list[dict] = [
    # -----------------------------------------------------------------------
    # voxyflow.delegate — dispatch a background worker task
    # Canonical MCP tool: schema is strict (additionalProperties: false).
    # Available to dispatchers (Claude CLI / Codex MCP) and workers (tools.load).
    # The handler validates the payload and queues it for orchestrator pickup.
    # -----------------------------------------------------------------------
    {
        "name": "voxyflow.delegate",
        "description": (
            "Dispatch a task to a background worker subprocess. Use for work that "
            "needs an OS subprocess: shell commands, file changes, web research, "
            "git, tests, heavy AI/coding. When the user asked for such work, call "
            "this immediately — no confirmation, one call per task, with a 1-2 "
            "sentence acknowledgment in your reply. NEVER delegate kanban/memory/KG "
            "CRUD (do those inline with your own tools — bulk id lists handle many "
            "items in one call), never delegate reading another worker's output, "
            "and never delegate because a tool result was large (refine the call instead)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "The action or intent to perform. Use concise English verbs. "
                        "Examples: complex_coding, web_research, create_card, analyze_code, "
                        "write_file, run_tests, summarize, translate, debug."
                    ),
                    "minLength": 1,
                },
                "description": {
                    "type": "string",
                    "description": (
                        "Full task description for the background worker. Be explicit: "
                        "what to do, what files/cards/resources to touch, and the expected outcome."
                    ),
                    "minLength": 1,
                },
                "complexity": {
                    "type": "string",
                    "enum": ["simple", "standard", "complex"],
                    "description": (
                        "Task complexity hint: simple (≤30 s), standard (default), complex (>5 min)."
                    ),
                },
                "card_id": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                    "description": "UUID of the Voxyflow card this task belongs to (if applicable).",
                },
                "context": {
                    "type": "string",
                    "description": "Extra runtime context to pass to the worker.",
                },
            },
            "required": ["action", "description"],
            "additionalProperties": False,
        },
        "_handler": "voxyflow_delegate",
        "_scope": "voxyflow",
        # Available to dispatchers and workers; NOT filtered out of dispatcher role
        # (the dispatcher needs to call this to spawn workers)
        "_role": "all",
    },
]
