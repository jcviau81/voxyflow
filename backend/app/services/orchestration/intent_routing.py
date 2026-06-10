"""Intent routing helpers — lightweight-intent detection + direct fast-paths.

Extracted verbatim from worker_pool.py.
"""

from __future__ import annotations

import logging
import re

from app.services.event_bus import ActionIntent

logger = logging.getLogger("voxyflow.orchestration")

# Intents that use lightweight worker (minimal prompt, no personality/context)
LIGHTWEIGHT_INTENTS = {
    "enrich", "enrich_card", "card.enrich",
    "summarize", "summarize_card",
    "research", "web_search", "search",
    "code_review", "review",
}

# Keywords that signal a lightweight task when found anywhere in the intent.
# Used for natural-language intents like "Read the file X and return its content".
LIGHTWEIGHT_KEYWORDS = {
    "read", "list", "get", "fetch", "show", "display", "cat", "print",
    "enrich", "summarize", "search", "review",
}


def is_lightweight_intent(intent: str) -> bool:
    """Check if an intent is lightweight — either exact match or keyword match."""
    lower = intent.lower()
    if lower in LIGHTWEIGHT_INTENTS:
        return True
    words = set(lower.split())
    return bool(words & LIGHTWEIGHT_KEYWORDS)


# Regex to extract file path from read-file intents
_READ_FILE_RE = re.compile(
    r"^read\s+(?:the\s+)?(?:file\s+|content\s+of\s+)?([^\s]+)",
    re.IGNORECASE,
)


async def try_direct_execution(event: ActionIntent) -> str | None:
    """Fast-path: execute trivial intents directly without spawning an LLM.

    Returns the result string if handled, or None to fall through to LLM workers.
    Currently handles: file read intents.
    """
    intent = (event.intent or "").strip()
    m = _READ_FILE_RE.match(intent)
    if not m:
        return None

    from app.tools.system_tools import file_read

    path = m.group(1).strip("\"'")
    result = await file_read({"path": path})

    if not result.get("success"):
        return f"Error reading file: {result.get('error', 'unknown error')}"

    content = result.get("content", "")
    total = result.get("total_lines", 0)
    truncated = result.get("truncated", False)
    header = f"File: {path} ({total} lines"
    if truncated:
        header += ", truncated"
    header += ")\n\n"
    return header + content
