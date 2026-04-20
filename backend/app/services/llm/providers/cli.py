"""CLI subprocess provider.

Wraps :class:`ClaudeCliBackend` in the :class:`LLMProvider` interface so
the `claude -p` subprocess is accessible through the same abstraction as
the SDK providers.

Phase-1 scope: `complete()` and `stream()` run non-tool conversational
turns. Tool-use, delegate collection, steerable workers, and persistent
chat sessions still go through the specialised `ClaudeCliBackend`
methods called directly from `api_caller` — wiring those through the
provider ABC is Phase 2 of M15 (see docs/CODE_REVIEW_PLAN_2026-04-17.md).
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from app.services.llm import capability_registry as caps_db
from app.services.llm.providers.base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    ProviderCapabilities,
    StreamDone,
    StreamEvent,
    TextDelta,
)

logger = logging.getLogger("voxyflow.providers.cli")

# Models available through the Claude Code CLI. The CLI talks to the
# Max-subscription backend, which exposes the same model surface as
# Anthropic direct-API, so we reuse the canonical list.
_KNOWN_MODELS = [
    "claude-opus-4-7",
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
]


class CliProvider(LLMProvider):
    """Provider backed by the `claude -p` CLI subprocess.

    Uses the user's Claude Max subscription — no API key required.
    """

    provider_label = "Claude CLI"
    provider_type = "cli"

    def __init__(self, cli_path: str = "claude"):
        # Lazy import: `cli_backend` pulls in rate-gate + session-registry
        # singletons whose init has side effects; importing at module load
        # time would run those even when the provider isn't used.
        from app.services.llm.cli_backend import ClaudeCliBackend
        self._backend = ClaudeCliBackend(cli_path=cli_path)

    @property
    def backend(self):
        """Expose the underlying `ClaudeCliBackend` for features not on the ABC
        (steerable workers, persistent chat, MCP tool events). Phase 2 will
        lift these onto the ABC; until then, callers that need them use the
        backend directly via `get_provider("cli").backend`.
        """
        return self._backend

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        text, usage = await self._backend.call(
            model=request.model,
            system=request.system,
            messages=request.messages,
            use_tools=False,
        )
        return CompletionResponse(
            content=text,
            tool_calls=None,
            stop_reason="end_turn",
            usage=dict(usage) if usage else None,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        async for token in self._backend.stream(
            model=request.model,
            system=request.system,
            messages=request.messages,
            use_tools=False,
        ):
            yield TextDelta(token)
        usage = dict(self._backend.last_usage) if self._backend.last_usage else None
        yield StreamDone(stop_reason="end_turn", usage=usage)

    def get_capabilities(self, model: str) -> ProviderCapabilities:
        entry = caps_db.lookup(model)
        return ProviderCapabilities(
            provider_name=self.provider_type,
            model=model,
            supports_tools=entry.supports_tools,
            supports_vision=entry.supports_vision,
            supports_streaming=True,
            context_window=entry.context_window,
            max_output_tokens=entry.max_output_tokens,
        )

    async def list_models(self) -> list[str]:
        return list(_KNOWN_MODELS)

    async def is_reachable(self) -> bool:
        # `ClaudeCliBackend.__init__` raises if the binary isn't on PATH, so
        # construction itself is the probe. If we got here, it's reachable.
        return bool(self._backend.cli_path)
