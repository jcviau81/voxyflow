"""Static capability registry for known LLM models.

Maps model name patterns to their capabilities. Used when a provider
cannot dynamically report capabilities (most can't).

Entries use prefix matching — the longest matching prefix wins.
Unknown models get conservative defaults (no tools, no vision).

Sources:
  - Anthropic: https://docs.anthropic.com/en/docs/about-claude/models
  - OpenAI:    https://platform.openai.com/docs/models
  - Ollama:    https://ollama.com/library (tool support varies by version)
  - Groq:      https://console.groq.com/docs/models
  - Mistral:   https://docs.mistral.ai/getting-started/models/
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass
class _ModelEntry:
    supports_tools: bool
    supports_vision: bool
    context_window: int       # tokens
    max_output_tokens: int    # tokens


# ---------------------------------------------------------------------------
# Registry — longest prefix match. Keys are lowercased model name prefixes.
# ---------------------------------------------------------------------------
_REGISTRY: dict[str, _ModelEntry] = {
    # ── Anthropic Claude ────────────────────────────────────────────────────
    "claude-opus-4":    _ModelEntry(True,  True,  200_000, 32_000),
    "claude-sonnet-4":  _ModelEntry(True,  True,  200_000, 16_000),
    "claude-haiku-4":   _ModelEntry(True,  True,  200_000,  8_192),
    "claude-3-5-sonnet":_ModelEntry(True,  True,  200_000,  8_192),
    "claude-3-5-haiku": _ModelEntry(True,  True,  200_000,  8_192),
    "claude-3-opus":    _ModelEntry(True,  True,  200_000,  4_096),
    "claude-3-sonnet":  _ModelEntry(True,  True,  200_000,  4_096),
    "claude-3-haiku":   _ModelEntry(True,  True,  200_000,  4_096),

    # ── OpenAI ──────────────────────────────────────────────────────────────
    "gpt-4o":           _ModelEntry(True,  True,  128_000, 16_384),
    "gpt-4-turbo":      _ModelEntry(True,  True,  128_000,  4_096),
    "gpt-4":            _ModelEntry(True,  False, 128_000,  4_096),
    "gpt-3.5-turbo":    _ModelEntry(True,  False,  16_384,  4_096),
    "o1":               _ModelEntry(False, True,  200_000, 100_000),
    "o3":               _ModelEntry(True,  True,  200_000, 100_000),

    # ── Ollama / local models ────────────────────────────────────────────────
    "llama3.3":         _ModelEntry(True,  False, 131_072,  8_192),
    "llama3.2":         _ModelEntry(True,  False, 131_072,  8_192),
    "llama3.1":         _ModelEntry(True,  False, 131_072,  8_192),
    "llama3":           _ModelEntry(False, False,   8_192,  4_096),
    "llama2":           _ModelEntry(False, False,   4_096,  4_096),
    "llama":            _ModelEntry(False, False,   4_096,  4_096),
    "mistral":          _ModelEntry(True,  False,  32_768,  8_192),
    "mixtral":          _ModelEntry(True,  False,  32_768,  8_192),
    "qwen2.5":          _ModelEntry(True,  False, 131_072,  8_192),
    "qwen3":            _ModelEntry(True,  False, 131_072,  8_192),
    "qwen":             _ModelEntry(True,  False,  32_768,  8_192),
    "deepseek-r1":      _ModelEntry(True,  False, 128_000,  8_192),
    "deepseek-v3":      _ModelEntry(True,  False, 128_000,  8_192),
    "deepseek":         _ModelEntry(False, False,  32_768,  4_096),
    "phi4":             _ModelEntry(True,  True,  131_072,  8_192),
    "phi3":             _ModelEntry(True,  False, 131_072,  4_096),
    "phi":              _ModelEntry(False, False,   4_096,  4_096),
    "gemma3":           _ModelEntry(True,  True,  131_072,  8_192),
    "gemma2":           _ModelEntry(False, False,   8_192,  4_096),
    "gemma":            _ModelEntry(False, False,   8_192,  4_096),
    "codellama":        _ModelEntry(False, False,  16_384,  4_096),
    "codegemma":        _ModelEntry(False, False,   8_192,  4_096),
    "nomic-embed":      _ModelEntry(False, False,   8_192,      0),
    "mxbai-embed":      _ModelEntry(False, False,  512,        0),

    # ── Groq ────────────────────────────────────────────────────────────────
    "llama-3.3-70b":    _ModelEntry(True,  False, 131_072,  8_192),
    "llama-3.1-70b":    _ModelEntry(True,  False, 131_072,  8_192),
    "llama-3.1-8b":     _ModelEntry(True,  False, 131_072,  8_192),
    "mixtral-8x7b":     _ModelEntry(True,  False,  32_768,  8_192),
    "gemma2-9b":        _ModelEntry(True,  False,   8_192,  8_192),

    # ── Mistral AI ──────────────────────────────────────────────────────────
    "mistral-large":    _ModelEntry(True,  True,  131_072,  8_192),
    "mistral-small":    _ModelEntry(True,  True,  131_072,  8_192),
    "mistral-nemo":     _ModelEntry(True,  False, 131_072,  8_192),
    "codestral":        _ModelEntry(True,  False,  32_768,  8_192),
    "pixtral":          _ModelEntry(True,  True,  131_072,  4_096),

    # ── Google Gemini (via API) ──────────────────────────────────────────────
    "gemini-2.5":       _ModelEntry(True,  True, 1_048_576, 65_536),
    "gemini-2.0":       _ModelEntry(True,  True, 1_048_576, 65_536),
    "gemini-1.5-pro":   _ModelEntry(True,  True, 1_048_576,  8_192),
    "gemini-1.5-flash": _ModelEntry(True,  True, 1_048_576,  8_192),
    "gemini-1.0-pro":   _ModelEntry(True,  False,  32_760,  8_192),
}

# Conservative default for unknown models
_DEFAULT = _ModelEntry(
    supports_tools=False,
    supports_vision=False,
    context_window=4_096,
    max_output_tokens=4_096,
)

# Pre-sort keys by length descending so the first match is the longest prefix
_SORTED_KEYS = sorted(_REGISTRY.keys(), key=len, reverse=True)


@lru_cache(maxsize=256)
def lookup(model: str) -> _ModelEntry:
    """Return capability entry for *model*, using longest-prefix matching."""
    lower = model.lower().strip()
    for key in _SORTED_KEYS:
        if lower.startswith(key):
            return _REGISTRY[key]
    return _DEFAULT


def supports_tools(model: str) -> bool:
    return lookup(model).supports_tools


def supports_vision(model: str) -> bool:
    return lookup(model).supports_vision


def context_window(model: str) -> int:
    return lookup(model).context_window


def max_output_tokens(model: str) -> int:
    return lookup(model).max_output_tokens
