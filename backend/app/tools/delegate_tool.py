"""voxyflow.delegate — canonical MCP tool for dispatching background workers.

This module defines the single authoritative schema and validator for the
``voxyflow.delegate`` tool, exposed across all provider paths:

    - Anthropic API   → ``voxyflow_delegate`` tool_use (name with underscore,
                        because Anthropic names must match [a-zA-Z0-9_-]{1,64})
    - OpenAI HTTP     → ``voxyflow_delegate`` function calling
    - Claude CLI MCP  → ``voxyflow.delegate`` via MCP SSE server
    - Codex CLI MCP   → ``voxyflow.delegate`` via MCP stdio

The handler validates the JSON payload (strict schema, additionalProperties:false),
then signals the orchestrator's dispatcher singleton to spawn a background worker.
Worker spawning is NOT done directly from this handler — the api_caller layer
collects validated delegate payloads into ``self._pending_delegates[chat_id]``
and the ChatOrchestrator's DelegateDispatchMixin emits ActionIntent events.

Design decisions recorded here (locked by JC, 2026-05-27):
  - Schema strict: additionalProperties=false
  - Required: ``action`` (string), ``description`` (string)
  - Optional: ``complexity`` (enum simple|standard|complex), ``card_id`` (uuid), ``context`` (string)
  - Legacy XML markup parser: REMOVED 2026-05-27 (no fallback, no toggle)
  - Tool canonical name: ``voxyflow.delegate`` / Anthropic/OAI name: ``voxyflow_delegate``
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("voxyflow.tools.delegate")

# ---------------------------------------------------------------------------
# Canonical name
# ---------------------------------------------------------------------------

TOOL_NAME = "voxyflow.delegate"
# Name sent to providers that don't support dots (Anthropic, OpenAI)
TOOL_NAME_SAFE = "voxyflow_delegate"

# ---------------------------------------------------------------------------
# JSON Schema (strict, Draft-07)
# ---------------------------------------------------------------------------

VOXYFLOW_DELEGATE_SCHEMA: dict = {
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
                "what to do, what files/cards/resources to touch, what the expected "
                "outcome looks like. Workers read ONLY this field — context not here "
                "is context not received."
            ),
            "minLength": 1,
        },
        "complexity": {
            "type": "string",
            "enum": ["simple", "standard", "complex"],
            "description": (
                "Task complexity hint for model selection: "
                "simple=single-step CRUD (≤30 s), "
                "standard=multi-step research or code (default, ≤5 min), "
                "complex=long-running multi-phase work (>5 min)."
            ),
        },
        "card_id": {
            "type": "string",
            "pattern": "^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            "description": "UUID of the Voxyflow card this task belongs to (if applicable).",
        },
        "context": {
            "type": "string",
            "description": (
                "Extra runtime context to pass to the worker: current workspace, "
                "relevant card IDs, previous worker results, or any ambient info "
                "that doesn't fit in description."
            ),
        },
    },
    "required": ["action", "description"],
    "additionalProperties": False,
}

# ---------------------------------------------------------------------------
# Anthropic-format tool definition  (name/description/input_schema)
# ---------------------------------------------------------------------------

VOXYFLOW_DELEGATE_TOOL: dict = {
    "name": TOOL_NAME_SAFE,  # "voxyflow_delegate" — dots not allowed by Anthropic
    "description": (
        "Dispatch a task to a background worker for execution. "
        "MUST be called whenever the user asks you to DO anything beyond instant read/CRUD "
        "(research, code, multi-step ops, file changes, tests, analysis). "
        "You CANNOT execute such tasks yourself — you MUST delegate them. "
        "The worker will run autonomously and report results back to the user. "
        "Call this immediately, without asking for confirmation — one call per task."
    ),
    "input_schema": VOXYFLOW_DELEGATE_SCHEMA,
}

# ---------------------------------------------------------------------------
# OpenAI function-calling format
# ---------------------------------------------------------------------------

VOXYFLOW_DELEGATE_TOOL_OPENAI: dict = {
    "type": "function",
    "function": {
        "name": TOOL_NAME_SAFE,
        "description": VOXYFLOW_DELEGATE_TOOL["description"],
        "parameters": VOXYFLOW_DELEGATE_SCHEMA,
    },
}

# ---------------------------------------------------------------------------
# Gemini functionDeclarations format (schema pre-computed for Gemini HTTP)
# ---------------------------------------------------------------------------

VOXYFLOW_DELEGATE_TOOL_GEMINI: dict = {
    "name": TOOL_NAME_SAFE,
    "description": VOXYFLOW_DELEGATE_TOOL["description"],
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": VOXYFLOW_DELEGATE_SCHEMA["properties"]["action"]["description"],
            },
            "description": {
                "type": "STRING",
                "description": VOXYFLOW_DELEGATE_SCHEMA["properties"]["description"]["description"],
            },
            "complexity": {
                "type": "STRING",
                "description": VOXYFLOW_DELEGATE_SCHEMA["properties"]["complexity"]["description"],
                "enum": ["simple", "standard", "complex"],
            },
            "card_id": {
                "type": "STRING",
                "description": VOXYFLOW_DELEGATE_SCHEMA["properties"]["card_id"]["description"],
            },
            "context": {
                "type": "STRING",
                "description": VOXYFLOW_DELEGATE_SCHEMA["properties"]["context"]["description"],
            },
        },
        "required": ["action", "description"],
    },
}

# ---------------------------------------------------------------------------
# UUID pattern for card_id validation
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_VALID_COMPLEXITY = frozenset({"simple", "standard", "complex"})

# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def validate_delegate_input(data: dict) -> tuple[bool, str]:
    """Validate a ``voxyflow.delegate`` call payload against the strict schema.

    Returns:
        (True, "")               on success
        (False, error_message)   on validation failure

    The error message is suitable for returning as a ``tool_result`` error
    to the LLM so it can self-correct.
    """
    if not isinstance(data, dict):
        return False, f"Payload must be a JSON object, got {type(data).__name__}"

    # Unknown properties
    known = set(VOXYFLOW_DELEGATE_SCHEMA["properties"].keys())
    unknown = set(data.keys()) - known
    if unknown:
        return False, (
            f"Unknown field(s): {sorted(unknown)}. "
            f"Allowed fields: {sorted(known)}. Schema is strict (additionalProperties=false)."
        )

    # Required fields
    for field in VOXYFLOW_DELEGATE_SCHEMA["required"]:
        if field not in data:
            return False, f"Missing required field: '{field}'."
        if not isinstance(data[field], str):
            return False, f"Field '{field}' must be a string, got {type(data[field]).__name__}."
        if not data[field].strip():
            return False, f"Field '{field}' must not be empty."

    # Optional: complexity enum
    if "complexity" in data:
        if data["complexity"] not in _VALID_COMPLEXITY:
            return False, (
                f"'complexity' must be one of {sorted(_VALID_COMPLEXITY)}, "
                f"got {data['complexity']!r}."
            )

    # Optional: card_id UUID format
    if "card_id" in data:
        if not isinstance(data["card_id"], str) or not _UUID_RE.match(data["card_id"]):
            return False, (
                f"'card_id' must be a valid UUID v4 string "
                f"(xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx), got {data['card_id']!r}."
            )

    # Optional: context string
    if "context" in data and not isinstance(data["context"], str):
        return False, f"'context' must be a string, got {type(data['context']).__name__}."

    return True, ""


def normalize_delegate_data(data: dict) -> dict:
    """Normalize a delegate payload for the emit pipeline.

    - Maps ``description`` → ``summary`` alias so existing emit code works.
    - Maps ``complexity`` ``standard`` → dispatcher default (no change needed,
      the emit code already handles unknown complexity values gracefully).
    - Strips unknown fields (already caught by validate_delegate_input).
    """
    out = dict(data)
    # ``description`` is the canonical field; the emit code uses summary-or-description
    # fallback chain, so no rename needed.  Keep description as-is.
    return out


def make_tool_result_error(error_message: str) -> str:
    """Build a JSON tool_result error string to return to the LLM on validation failure."""
    return json.dumps({
        "error": "VALIDATION_FAILED",
        "message": error_message,
        "hint": (
            "Fix the payload and call voxyflow_delegate again. "
            "Required fields: action (string), description (string). "
            "Optional: complexity (simple|standard|complex), card_id (uuid), context (string). "
            "No extra fields allowed."
        ),
    }, ensure_ascii=False)
