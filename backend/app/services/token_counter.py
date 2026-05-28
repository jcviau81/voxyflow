"""Exact token counting for the dispatcher context-weight indicator.

Uses tiktoken's ``o200k_base`` encoding — exact for the OpenAI family and a
deterministic, offline, provider-agnostic count for everything else (Claude,
Codex, Ollama, …). No single tokenizer is exact across all providers, so this
is the de-facto standard reference count.

Falls back to a ~chars/4 estimate if tiktoken (or its encoding cache) is
unavailable, so a constrained/offline deploy never crashes — it just loses a
little precision on the context-weight badge.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("voxyflow.token_counter")

_ENCODER = None
_ENCODER_TRIED = False


def _get_encoder():
    global _ENCODER, _ENCODER_TRIED
    if _ENCODER_TRIED:
        return _ENCODER
    _ENCODER_TRIED = True
    try:
        import tiktoken
        _ENCODER = tiktoken.get_encoding("o200k_base")
    except Exception as e:  # pragma: no cover — offline / missing dep
        logger.warning("tiktoken unavailable, falling back to ~chars/4 estimate: %s", e)
        _ENCODER = None
    return _ENCODER


def count_tokens(text: str | None) -> int:
    """Exact token count for *text* (tiktoken o200k_base), or ~chars/4 fallback."""
    if not text:
        return 0
    if not isinstance(text, str):
        text = str(text)
    enc = _get_encoder()
    if enc is not None:
        try:
            return len(enc.encode(text, disallowed_special=()))
        except Exception:  # pragma: no cover — defensive
            pass
    # Fallback: rough estimate (~1 token per 4 chars).
    return max(1, len(text) // 4)


def using_exact_tokenizer() -> bool:
    """True if the exact tiktoken encoder is active (False = estimate fallback)."""
    return _get_encoder() is not None
