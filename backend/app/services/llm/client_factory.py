"""LLM client factory — creates Anthropic (native) and OpenAI-compatible clients."""

from app.config import get_settings


_REDACTED_SENTINEL = "***"


def _sanitize_api_key(api_key: str | None) -> str:
    """Drop the redacted sentinel so it never reaches an SDK client.

    ``GET /api/settings`` redacts api_key fields to ``***`` before returning
    them to the frontend. If that sentinel round-trips back through a call
    site that forgot the check in ``tool_defs._get_api_key_from_settings``,
    the SDK would sign requests with the literal string ``***``. Guarding
    here makes the factory the single enforcement point.
    """
    key = (api_key or "").strip()
    return "" if key == _REDACTED_SENTINEL else key


def _make_anthropic_client(api_key: str, api_base: str = ""):
    """Create a native Anthropic SDK client (sync)."""
    import anthropic
    clean_key = _sanitize_api_key(api_key)
    kwargs = {"api_key": clean_key} if clean_key else {}
    if api_base:
        kwargs["base_url"] = api_base
    return anthropic.Anthropic(**kwargs)


def _make_async_anthropic_client(api_key: str, api_base: str = ""):
    """Create a native async Anthropic SDK client (for worker tasks)."""
    import anthropic
    clean_key = _sanitize_api_key(api_key)
    kwargs = {"api_key": clean_key} if clean_key else {}
    if api_base:
        kwargs["base_url"] = api_base
    return anthropic.AsyncAnthropic(**kwargs)


def _make_openai_client(provider_url: str, api_key: str):
    """Create an OpenAI-compatible client (proxy fallback)."""
    from openai import OpenAI
    clean_key = _sanitize_api_key(api_key)
    return OpenAI(
        base_url=provider_url or get_settings().claude_proxy_url,
        api_key=clean_key if clean_key else "not-needed",
    )
