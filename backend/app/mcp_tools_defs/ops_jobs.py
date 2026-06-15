"""Ops tool defs — health, scheduled jobs, heartbeat, workspace autonomy.

Extracted verbatim from ``app/mcp_tool_defs.py`` (H8 monolith split).
Pure data — every entry follows the schema documented in ``app.mcp_tool_defs``.
"""

from __future__ import annotations


OPS_JOBS_TOOLS: list[dict] = [
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
            "agent_task {instruction, workspace_id?}; "
            "execute_board {workspace_id, statuses?}; "
            "execute_card {card_id, workspace_id?}; "
            "reminder {message}; "
            "rag_index {workspace_id?, path?}. "
            "Schedule: cron or shorthand (every_5min, every_1h, every_day)."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["name", "type", "schedule"],
            "properties": {
                "name": {"type": "string"},
                "type": {
                    "type": "string",
                    "enum": ["agent_task", "execute_card", "execute_board", "reminder", "rag_index"],
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
                    "enum": ["agent_task", "execute_card", "execute_board", "reminder", "rag_index"],
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
    {
        "name": "voxyflow.jobs.schedule_nl",
        "description": (
            "Schedule a recurring natural-language task ('every Friday at 5pm review "
            "stalled cards and message me'). Each run executes the prompt through the "
            "agent pipeline (workers do the heavy lifting) and delivers the result to "
            "chat and/or web push. Workspace scope is taken from the current chat "
            "automatically. Use this whenever the user asks for something recurring."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["prompt", "schedule"],
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The task in natural language — self-contained instruction executed on every run",
                },
                "schedule": {
                    "description": (
                        "Cron string ('0 17 * * fri'), shorthand ('every_30min', 'every_1h', "
                        "'every_day'), or object {every: 'minute'|'hour'|'day'|'week'|'weekdays', "
                        "at: 'HH:MM', weekday: 'mon'..'sun'}"
                    ),
                },
                "deliver": {
                    "type": "string",
                    "enum": ["chat", "push", "both"],
                    "description": "Where to deliver each run's result (default both)",
                },
                "name": {
                    "type": "string",
                    "description": "Short job name shown in the Jobs panel (defaults to the prompt's first words)",
                },
            },
        },
        "_handler": "jobs_schedule_nl",
        "_scope": "voxyflow",
    },

    # ======================================================================
    # HEARTBEAT — read/write ~/.voxyflow/sandbox/heartbeat.md
    # ======================================================================

    {
        "name": "voxyflow.heartbeat.read",
        "description": "Read the Agent Heartbeat file (~/.voxyflow/sandbox/heartbeat.md).",
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
    # WORKSPACE AUTONOMY — per-workspace heartbeat (distinct from the GLOBAL one)
    # Reads/writes ~/.voxyflow/sandbox/workspaces/{workspace_id}/heartbeat.md and
    # manages a dedicated ``agent_task`` job that runs on its own schedule with
    # workspace-scoped memory / KG / MCP. In a workspace chat, workspace_id is
    # auto-injected from VOXYFLOW_WORKSPACE_ID — Voxy does not need to pass it.
    # ======================================================================

    {
        "name": "voxyflow.autonomy.status",
        "description": (
            "Return the workspace's autonomy state: {enabled, schedule, next_run, "
            "directive, file_path, actionable}. In a workspace chat, workspace_id is "
            "injected from the current workspace and must not be passed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace UUID (only needed from general chat)"},
            },
        },
        "_http": ("GET", "/api/workspaces/{workspace_id}/autonomy", None),
    },
    {
        "name": "voxyflow.autonomy.enable",
        "description": (
            "Enable or update per-workspace autonomy. Creates/updates the heartbeat job and, "
            "when ``directive`` is provided, rewrites the content below the '---' divider "
            "in the workspace's heartbeat.md. Use this to hand Voxy the next step for the "
            "workspace to execute on the next cycle. Pass directive='' to pause without "
            "disabling the job. Schedule shorthand: every_5min / every_15min / every_1h / cron."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace UUID (only needed from general chat)"},
                "enabled": {"type": "boolean", "description": "Default true"},
                "schedule": {"type": "string", "description": "Cron or shorthand (default every_5min)"},
                "directive": {"type": "string", "description": "Content written below the '---' divider. Empty string clears it."},
            },
        },
        "_http": ("PUT", "/api/workspaces/{workspace_id}/autonomy", None),
    },
    {
        "name": "voxyflow.autonomy.disable",
        "description": "Remove the workspace's autonomy heartbeat job entirely. The directive file is kept on disk for reference.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace UUID (only needed from general chat)"},
            },
        },
        "_http": ("DELETE", "/api/workspaces/{workspace_id}/autonomy", None),
    },
    {
        "name": "voxyflow.autonomy.run_now",
        "description": "Trigger the workspace's autonomy heartbeat immediately, bypassing the schedule. Same gate still applies — no directive, no LLM call.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string", "description": "Workspace UUID (only needed from general chat)"},
            },
        },
        "_http": ("POST", "/api/workspaces/{workspace_id}/autonomy/run", None),
    },
]
