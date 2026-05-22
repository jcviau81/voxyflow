"""Codex CLI provider."""

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

logger = logging.getLogger("voxyflow.providers.codex")

_KNOWN_MODELS = [
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex",
    "gpt-5.2",
]



class CodexProvider(LLMProvider):
    """Provider backed by ``codex exec``."""

    provider_label = "Codex CLI"
    provider_type = "codex"

    def __init__(self, cli_path: str = "codex"):
        from app.services.llm.codex_backend import CodexCliBackend
        self._backend = CodexCliBackend(cli_path=cli_path)

    @property
    def backend(self):
        return self._backend

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
            supports_tools=True,
            supports_vision=entry.supports_vision,
            supports_streaming=False,
            context_window=entry.context_window,
            max_output_tokens=entry.max_output_tokens,
        )

    async def list_models(self) -> list[str]:
        return list(_KNOWN_MODELS)

    async def is_reachable(self) -> bool:
        return bool(self._backend.cli_path)
