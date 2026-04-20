"""Abstract base class for all LLM providers.

Every provider (Anthropic, OpenAI, Ollama, Groq, CLI…) must implement
this interface so the orchestration layer stays provider-agnostic.

Stream surface: `stream()` yields `StreamEvent` variants — a tagged union
that models text deltas, completed tool-use blocks (providers buffer
partial tool_use args internally and only emit the complete block), tool
results (CLI only, where the subprocess executes tools itself), and a
terminal `StreamDone` with stop_reason + usage.

Starting minimal on purpose: additional variants (ThinkingDelta,
PermissionRequest, etc.) should be added only when a real consumer needs
them. Every variant expansion touches all providers and all consumers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Union


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


@dataclass
class CompletionResponse:
    """Normalised completion response — provider-agnostic."""

    content: str                                    # Full text content
    tool_calls: list[dict] | None = None            # Tool calls (OpenAI format)
    stop_reason: str = ""                           # Why the model stopped
    usage: dict | None = None                       # Token usage info


# ──────────────────────────────────────────────────────────────────────────────
# Streaming event union
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class TextDelta:
    """Incremental text chunk from the model."""

    text: str


@dataclass
class ToolUseBlock:
    """A completed tool-use request from the model.

    Providers buffer partial tool_use args internally (Anthropic's
    `input_json_delta`, OpenAI's `tool_call.function.arguments` deltas) and
    emit this block only when the full request is available. `input` is
    parsed JSON when the provider could parse it, else the raw string.
    """

    id: str
    name: str
    input: dict


@dataclass
class ToolResult:
    """Result of a tool invocation.

    Only emitted by providers that execute tools themselves — currently
    the CLI provider, where the subprocess runs MCP tools internally and
    streams back the results. SDK providers never emit this; the caller
    is expected to execute tools and inject results into the next request.
    """

    tool_use_id: str
    content: str       # JSON-encoded or raw string
    is_error: bool = False


@dataclass
class StreamDone:
    """Terminal event — must be the last item yielded by every `stream()`."""

    stop_reason: str = ""
    usage: dict | None = None


StreamEvent = Union[TextDelta, ToolUseBlock, ToolResult, StreamDone]


# ──────────────────────────────────────────────────────────────────────────────
# LLMProvider ABC
# ──────────────────────────────────────────────────────────────────────────────


class LLMProvider(ABC):
    """Abstract base class — implement one subclass per provider.

    Subclasses must implement:
        complete()        — single-shot, returns full text
        stream()          — async generator yielding StreamEvent variants
        get_capabilities()— returns ProviderCapabilities for a model
        list_models()     — returns available model names (empty list if unsupported)
    """

    # Friendly name shown in the UI ("Ollama", "OpenAI", …)
    provider_label: str = "Unknown"

    # Provider identifier used in settings.json ("ollama", "openai", …)
    provider_type: str = "unknown"

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        """Execute a completion and return a structured response."""

    @abstractmethod
    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        """Stream a completion, yielding StreamEvent variants.

        Must end with a `StreamDone` event (stop_reason + usage). `ToolUseBlock`
        emissions buffer partial args inside the provider — consumers only see
        complete blocks.
        """

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
