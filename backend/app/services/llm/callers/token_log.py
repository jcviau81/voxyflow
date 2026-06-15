"""Token usage logging + Anthropic 1M-context beta helpers.

Extracted verbatim from api_caller.py.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

TOKEN_LOG_PATH = Path(os.path.expanduser("~/.voxyflow/logs/token_usage.jsonl"))


def _log_token_usage(
    *,
    layer: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    chat_id: str = "",
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> None:
    """Append a JSONL entry to the token usage log file."""
    try:
        TOKEN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "layer": layer,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "chat_id": chat_id,
            "cache_creation_tokens": cache_creation_tokens,
            "cache_read_tokens": cache_read_tokens,
        }
        with open(TOKEN_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.debug(f"Token usage logging failed: {e}")


# Anthropic beta header for Sonnet 4 1M context.
# See: https://docs.anthropic.com/en/docs/build-with-claude/context-windows#1m-context
_CONTEXT_1M_HEADER = {"anthropic-beta": "context-1m-2025-08-07"}


def _supports_1m_context(model: str) -> bool:
    """Return True if *model* is eligible for the 1M context beta."""
    # The beta is currently gated to Sonnet 4+; Opus and Haiku stay at 200K.
    return "sonnet-4" in (model or "").lower()
