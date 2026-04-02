"""LLM client factory — creates Anthropic (native) and OpenAI-compatible clients."""

from app.config import get_settings


def _make_anthropic_client(api_key: str, api_base: str = ""):
    """Create a native Anthropic SDK client (sync)."""
    import anthropic
    kwargs = {"api_key": api_key} if api_key else {}
    if api_base:
        kwargs["base_url"] = api_base
    return anthropic.Anthropic(**kwargs)


def _make_async_anthropic_client(api_key: str, api_base: str = ""):
    """Create a native async Anthropic SDK client (for worker tasks)."""
    import anthropic
    kwargs = {"api_key": api_key} if api_key else {}
    if api_base:
        kwargs["base_url"] = api_base
    return anthropic.AsyncAnthropic(**kwargs)


def _make_openai_client(provider_url: str, api_key: str):
    """Create an OpenAI-compatible client (proxy fallback)."""
    from openai import OpenAI
    return OpenAI(
        base_url=provider_url or get_settings().claude_proxy_url,
        api_key=api_key if api_key else "not-needed",
    )
