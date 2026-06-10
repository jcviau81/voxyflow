"""Prompt-caching helpers — builds the ``system`` parameter for Claude API calls.

Extracted verbatim from app.services.claude_service. The original module
re-exports ``_make_cached_system`` so existing importers (routes/debug.py,
orchestration/tool_call_fallback.py) keep working unchanged.
"""


def _make_cached_system(
    base_prompt: str,
    dynamic_parts: list[str] | None = None,
    is_anthropic: bool = True,
) -> str | list[dict]:
    """Build the system parameter for Claude API calls with prompt caching.

    For Anthropic native SDK: returns a list of content blocks where the static
    base prompt is marked with cache_control={'type': 'ephemeral'} so Anthropic
    caches it across calls in the same session (~5 min TTL).

    For OpenAI-compatible proxy: returns a plain concatenated string (no caching).

    Args:
        base_prompt: The static personality/instruction prompt (cacheable).
        dynamic_parts: Optional list of dynamic context strings (RAG, workers, etc.)
                       that change per-call and should NOT be cached.
        is_anthropic: Whether we're using the native Anthropic SDK.
    """
    dynamic_text = ""
    if dynamic_parts:
        dynamic_text = "\n\n".join(p for p in dynamic_parts if p)

    if not is_anthropic:
        # Proxy path — plain string, no caching support
        if dynamic_text:
            return base_prompt + "\n\n" + dynamic_text
        return base_prompt

    # Anthropic native path — use content blocks with cache_control
    blocks = [
        {
            "type": "text",
            "text": base_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    if dynamic_text:
        blocks.append({"type": "text", "text": dynamic_text})
    return blocks


# Public alias — prefer this name in new code.
make_cached_system = _make_cached_system
