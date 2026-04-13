"""Provider factory — returns the right LLMProvider for a given config.

Usage:
    provider = get_provider(
        provider_type="ollama",
        url="http://localhost:11434/v1",
        api_key="",
    )

Supported provider_type values:
    "cli"         — Claude CLI subprocess (via existing ClaudeCliBackend)
    "anthropic"   — Native Anthropic SDK
    "openai"      — OpenAI or any OpenAI-compatible endpoint
    "ollama"      — Ollama local instance
    "groq"        — Groq cloud (OpenAI-compat, api.groq.com/openai/v1)
    "mistral"     — Mistral AI (OpenAI-compat, api.mistral.ai/v1)
    "gemini"      — Google Gemini (OpenAI-compat, generativelanguage.googleapis.com)
    "lmstudio"    — LM Studio (OpenAI-compat, localhost:1234/v1)
"""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import urlparse

from app.services.llm.providers.base import LLMProvider

logger = logging.getLogger("voxyflow.provider_factory")

# Well-known provider URLs — used when provider_type is given but URL is empty
_DEFAULT_URLS: dict[str, str] = {
    "openai":   "https://api.openai.com/v1",
    "groq":     "https://api.groq.com/openai/v1",
    "mistral":  "https://api.mistral.ai/v1",
    "gemini":   "https://generativelanguage.googleapis.com/v1beta/openai",
    "lmstudio": "http://localhost:1234/v1",
    "ollama":   "http://localhost:11434",
}

# Friendly labels shown in the UI
_LABELS: dict[str, str] = {
    "openai":     "OpenAI",
    "groq":       "Groq",
    "mistral":    "Mistral AI",
    "gemini":     "Google Gemini",
    "lmstudio":   "LM Studio",
    "ollama":     "Ollama",
    "anthropic":  "Anthropic (Claude)",
    "cli":        "Claude CLI",
}


# Provider instance cache — keyed by (type, url, api_key_hash)
_provider_cache: dict[tuple, LLMProvider] = {}


def clear_provider_cache() -> None:
    """Invalidate all cached provider instances (call when settings change)."""
    _provider_cache.clear()


def get_provider(
    provider_type: str,
    url: str = "",
    api_key: str = "",
) -> LLMProvider:
    """Instantiate and return an LLMProvider.

    Args:
        provider_type: One of the supported type strings (see module docstring).
        url:           Provider base URL. Falls back to _DEFAULT_URLS if empty.
        api_key:       API key. Optional for local providers (Ollama, LM Studio).

    Returns:
        An LLMProvider instance ready to use.

    Raises:
        ValueError: If provider_type is not recognised.
    """
    from app.services.llm.providers.openai_compat import OpenAICompatProvider
    from app.services.llm.providers.ollama import OllamaProvider
    from app.services.llm.providers.anthropic_provider import AnthropicProvider

    ptype = provider_type.lower().strip()
    resolved_url = url.strip() or _DEFAULT_URLS.get(ptype, "")
    label = _LABELS.get(ptype)

    # Cache lookup
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:8] if api_key else "nokey"
    cache_key = (ptype, resolved_url, key_hash)
    if cache_key in _provider_cache:
        return _provider_cache[cache_key]

    def _cache(provider: LLMProvider) -> LLMProvider:
        _provider_cache[cache_key] = provider
        return provider

    if ptype == "ollama":
        return _cache(OllamaProvider(base_url=resolved_url or "http://localhost:11434", api_key=api_key))

    if ptype == "anthropic":
        return _cache(AnthropicProvider(api_key=api_key))

    if ptype == "cli":
        # CLI mode is handled by the existing ClaudeCliBackend — return a sentinel
        # that delegates all calls to it. The orchestration layer checks for this type
        # explicitly and bypasses the provider interface for CLI calls.
        raise ValueError(
            "CLI provider is managed by ClaudeCliBackend, not LLMProvider. "
            "Check provider_type != 'cli' before calling get_provider()."
        )

    if ptype in ("openai", "groq", "mistral", "gemini", "lmstudio", "openai_compat"):
        if not resolved_url:
            raise ValueError(f"No URL configured for provider '{ptype}'")
        return _cache(OpenAICompatProvider(
            provider_url=resolved_url,
            api_key=api_key,
            label=label,
        ))

    # Fallback: treat unknown provider_type as generic OpenAI-compat if a URL is given
    if resolved_url:
        logger.warning(
            "[ProviderFactory] Unknown provider type '%s' — treating as OpenAI-compatible at %s",
            ptype, resolved_url,
        )
        return _cache(OpenAICompatProvider(provider_url=resolved_url, api_key=api_key, label=ptype))

    raise ValueError(
        f"Unknown provider type '{provider_type}'. "
        f"Supported: {sorted(_DEFAULT_URLS.keys()) + ['anthropic', 'cli']}"
    )


def infer_provider_type(url: str, model: str = "") -> str:
    """Guess the provider type from a URL and optional model name.

    Used when migrating old configs that only have a URL (no explicit type).
    """
    lower_url = url.lower()
    lower_model = model.lower()

    parsed = urlparse(url) if url else None
    port = parsed.port if parsed else None

    if port == 11434 or "ollama" in lower_url:
        return "ollama"
    if port == 1234:
        return "lmstudio"
    if "groq.com" in lower_url:
        return "groq"
    if "mistral.ai" in lower_url:
        return "mistral"
    if "generativelanguage.googleapis" in lower_url or "gemini" in lower_url:
        return "gemini"
    if "openai.com" in lower_url:
        return "openai"
    if "anthropic.com" in lower_url or "claude" in lower_model:
        return "anthropic"
    if port == 3457:
        return "openai"   # legacy claude-max-api proxy
    return "openai"       # conservative fallback


def list_known_providers() -> list[dict]:
    """Return metadata for all known providers — used by the Settings UI."""
    return [
        {"type": "cli",        "label": "Claude CLI",        "requires_key": False, "local": True,  "default_url": ""},
        {"type": "anthropic",  "label": "Anthropic (Claude)", "requires_key": True,  "local": False, "default_url": "https://api.anthropic.com"},
        {"type": "ollama",     "label": "Ollama",             "requires_key": False, "local": True,  "default_url": "http://localhost:11434"},
        {"type": "openai",     "label": "OpenAI",             "requires_key": True,  "local": False, "default_url": "https://api.openai.com/v1"},
        {"type": "groq",       "label": "Groq",               "requires_key": True,  "local": False, "default_url": "https://api.groq.com/openai/v1"},
        {"type": "mistral",    "label": "Mistral AI",         "requires_key": True,  "local": False, "default_url": "https://api.mistral.ai/v1"},
        {"type": "gemini",     "label": "Google Gemini",      "requires_key": True,  "local": False, "default_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
        {"type": "lmstudio",   "label": "LM Studio",          "requires_key": False, "local": True,  "default_url": "http://localhost:1234/v1"},
    ]
