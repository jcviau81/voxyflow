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
    "openrouter"  — OpenRouter (OpenAI-compat, openrouter.ai/api/v1)
"""

from __future__ import annotations

import hashlib
import logging
from urllib.parse import urlparse

from app.services.llm.providers.base import LLMProvider

logger = logging.getLogger("voxyflow.provider_factory")


class ProviderType:
    """Canonical provider-type string constants.

    Use these instead of bare strings when comparing or constructing
    provider_type values. Keeps the set discoverable and typo-proof.
    """

    CLI = "cli"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    OLLAMA = "ollama"
    GROQ = "groq"
    MISTRAL = "mistral"
    GEMINI = "gemini"
    LMSTUDIO = "lmstudio"
    OPENROUTER = "openrouter"

    # OpenAI-compat family (including OpenAI itself): any of these route
    # through OpenAICompatProvider.
    _OPENAI_COMPAT = frozenset({OPENAI, GROQ, MISTRAL, GEMINI, LMSTUDIO, OPENROUTER})

    ALL = frozenset({CLI, ANTHROPIC, OPENAI, OLLAMA, GROQ, MISTRAL, GEMINI, LMSTUDIO, OPENROUTER})

    @classmethod
    def is_openai_compat(cls, ptype: str) -> bool:
        return ptype in cls._OPENAI_COMPAT

    @classmethod
    def is_known(cls, ptype: str) -> bool:
        return ptype in cls.ALL


# Well-known provider URLs — used when provider_type is given but URL is empty
_DEFAULT_URLS: dict[str, str] = {
    ProviderType.OPENAI:     "https://api.openai.com/v1",
    ProviderType.GROQ:       "https://api.groq.com/openai/v1",
    ProviderType.MISTRAL:    "https://api.mistral.ai/v1",
    ProviderType.GEMINI:     "https://generativelanguage.googleapis.com/v1beta/openai",
    ProviderType.OPENROUTER: "https://openrouter.ai/api/v1",
    ProviderType.LMSTUDIO:   "http://localhost:1234/v1",
    ProviderType.OLLAMA:     "http://localhost:11434",
}

# Friendly labels shown in the UI
_LABELS: dict[str, str] = {
    ProviderType.OPENAI:     "OpenAI",
    ProviderType.GROQ:       "Groq",
    ProviderType.MISTRAL:    "Mistral AI",
    ProviderType.GEMINI:     "Google Gemini",
    ProviderType.OPENROUTER: "OpenRouter",
    ProviderType.LMSTUDIO:   "LM Studio",
    ProviderType.OLLAMA:     "Ollama",
    ProviderType.ANTHROPIC:  "Anthropic (Claude)",
    ProviderType.CLI:        "Claude CLI",
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

    # Cache lookup. Full SHA-256 to make collisions between differing keys
    # effectively impossible (the 8-char prefix earlier had a birthday
    # collision space of ~4B — non-trivial for long-lived processes).
    key_hash = hashlib.sha256(api_key.encode()).hexdigest() if api_key else "nokey"
    cache_key = (ptype, resolved_url, key_hash)
    if cache_key in _provider_cache:
        return _provider_cache[cache_key]

    def _cache(provider: LLMProvider) -> LLMProvider:
        _provider_cache[cache_key] = provider
        return provider

    if ptype == ProviderType.OLLAMA:
        return _cache(OllamaProvider(base_url=resolved_url or "http://localhost:11434", api_key=api_key))

    if ptype == ProviderType.ANTHROPIC:
        return _cache(AnthropicProvider(api_key=api_key))

    if ptype == ProviderType.CLI:
        from app.services.llm.providers.cli import CliProvider
        return _cache(CliProvider())

    if ProviderType.is_openai_compat(ptype) or ptype == "openai_compat":
        if not resolved_url:
            raise ValueError(f"No URL configured for provider '{ptype}'")
        return _cache(OpenAICompatProvider(
            provider_url=resolved_url,
            api_key=api_key,
            label=label,
        ))

    # Unknown provider_type. We used to silently fall back to OpenAI-compat if a
    # URL was present, but that masked typos ("ollma" → still worked) until a
    # model-specific feature failed. Require the caller to use a known type.
    raise ValueError(
        f"Unknown provider type '{provider_type}'. "
        f"Supported: {sorted(ProviderType.ALL)}"
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
        return ProviderType.OLLAMA
    if port == 1234:
        return ProviderType.LMSTUDIO
    if "groq.com" in lower_url:
        return ProviderType.GROQ
    if "mistral.ai" in lower_url:
        return ProviderType.MISTRAL
    if "generativelanguage.googleapis" in lower_url or "gemini" in lower_url:
        return ProviderType.GEMINI
    if "openrouter.ai" in lower_url:
        return ProviderType.OPENROUTER
    if "openai.com" in lower_url:
        return ProviderType.OPENAI
    if "anthropic.com" in lower_url or "claude" in lower_model:
        return ProviderType.ANTHROPIC
    if port == 3457:
        return ProviderType.OPENAI   # legacy claude-max-api proxy
    return ProviderType.OPENAI       # conservative fallback


def list_known_providers() -> list[dict]:
    """Return metadata for all known providers — used by the Settings UI."""
    return [
        {"type": ProviderType.CLI,        "label": "Claude CLI",         "requires_key": False, "local": True,  "default_url": ""},
        {"type": ProviderType.ANTHROPIC,  "label": "Anthropic (Claude)", "requires_key": True,  "local": False, "default_url": "https://api.anthropic.com"},
        {"type": ProviderType.OLLAMA,     "label": "Ollama",             "requires_key": False, "local": True,  "default_url": "http://localhost:11434"},
        {"type": ProviderType.OPENAI,     "label": "OpenAI",             "requires_key": True,  "local": False, "default_url": "https://api.openai.com/v1"},
        {"type": ProviderType.GROQ,       "label": "Groq",               "requires_key": True,  "local": False, "default_url": "https://api.groq.com/openai/v1"},
        {"type": ProviderType.MISTRAL,    "label": "Mistral AI",         "requires_key": True,  "local": False, "default_url": "https://api.mistral.ai/v1"},
        {"type": ProviderType.GEMINI,     "label": "Google Gemini",      "requires_key": True,  "local": False, "default_url": "https://generativelanguage.googleapis.com/v1beta/openai"},
        {"type": ProviderType.LMSTUDIO,   "label": "LM Studio",          "requires_key": False, "local": True,  "default_url": "http://localhost:1234/v1"},
        {"type": ProviderType.OPENROUTER, "label": "OpenRouter",         "requires_key": True,  "local": False, "default_url": "https://openrouter.ai/api/v1"},
    ]
