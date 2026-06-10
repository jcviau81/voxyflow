"""Programmatic tool calling — voxyflow.script (worker-only).

Pure data — the execution logic lives in ``app.mcp_system_handlers.script_run``.
This tool runs arbitrary Python in the MCP subprocess, so it must NEVER be
added to a dispatcher role set (see app/tools/registry.py — worker extras only).
"""

from __future__ import annotations


SCRIPT_TOOLS: list[dict] = [
    {
        "name": "voxyflow.script",
        "description": (
            "Run a short Python script that chains multiple Voxyflow tool calls "
            "in ONE turn via `await call_tool(name, args)`. Use this instead of "
            "issuing 3+ sequential tool calls — e.g. list cards then act on each "
            "one, or cross-reference memory with the board. The script body runs "
            "inside an async function: `await call_tool(\"voxyflow.card.list\", "
            "{\"workspace_id\": ...})` returns the tool's result dict. `json`, "
            "`re` and `asyncio` are pre-imported. print() for progress; set "
            "`result` to a value (or `return` one) for the final output. Same "
            "tool permissions as calling tools directly — no escalation."
        ),
        "inputSchema": {
            "type": "object",
            "required": ["code"],
            "properties": {
                "code": {
                    "type": "string",
                    "description": (
                        "Python source. Runs as the body of an async function, so "
                        "`await call_tool(...)` works at top level. Set `result` "
                        "for the final value."
                    ),
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Wall-clock limit for the script (default 120, max 600)",
                },
            },
        },
        "_handler": "script_run",
        "_scope": "voxyflow",
        "_role": "worker",
    },
]
