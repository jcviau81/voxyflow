"""Abstract base class for all LLM providers.

Every provider (Anthropic, OpenAI, Ollama, Groq, CLI…) must implement
this interface so the orchestration layer stays provider-agnostic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class ProviderCapabilities:
    """Model capabilities reported by a provider for a specific model."""

    provider_name: str          # "anthropic" | "openai" | "ollama" | "groq" | …
    model: str                  # Exact model identifier
    supports_tools: bool        # Function / tool calling
    supports_vision: bool       # Image inputs
    supports_streaming: bool    # Token-by-token streaming
    context_window: int         # Max input tokens
    max_output_tokens: int      # Max tokens the model can generate
    extra: dict = field(default_factory=dict)  # Provider-specific metadata


@dataclass
class CompletionRequest:
    """Normalised completion request — provider-agnostic."""

    messages: list[dict]                   # OpenAI-format message list
    model: str                             # Model identifier
    system: str = ""                       # System prompt (pre-pended or injected)
    tools: list[dict] | None = None        # Tool definitions (None = no tools)
    max_tokens: int = 4096
    temperature: float | None = None       # None = use provider default
    stream: bool = False


class LLMProvider(ABC):
    """Abstract base class — implement one subclass per provider.

    Subclasses must implement:
        complete()        — single-shot, returns full text
        stream()          — async generator yielding text chunks
        get_capabilities()— returns ProviderCapabilities for a model
        list_models()     — returns available model names (empty list if unsupported)
    """

    # Friendly name shown in the UI ("Ollama", "OpenAI", …)
    provider_label: str = "Unknown"

    # Provider identifier used in settings.json ("ollama", "openai", …)
    provider_type: str = "unknown"

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> str:
        """Execute a completion and return the full response text."""

    @abstractmethod
    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        """Stream a completion, yielding text chunks as they arrive."""

    @abstractmethod
    def get_capabilities(self, model: str) -> ProviderCapabilities:
        """Return capability info for the given model."""

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Return available model names. Return [] if the provider
        does not support model enumeration."""

    def supports_tools(self, model: str) -> bool:
        """Convenience helper — True if the model supports tool/function calling."""
        return self.get_capabilities(model).supports_tools

    def supports_vision(self, model: str) -> bool:
        """Convenience helper — True if the model supports image inputs."""
        return self.get_capabilities(model).supports_vision

    async def is_reachable(self) -> bool:
        """Quick connectivity check. Override for a faster probe if available."""
        try:
            await self.list_models()
            return True
        except Exception:
            return False
