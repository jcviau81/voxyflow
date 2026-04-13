"""Anthropic native SDK provider.

Uses the official `anthropic` Python SDK directly. Supports:
  - Tool use (native Anthropic format)
  - Vision (image blocks)
  - Streaming
  - Prompt caching (cache_control headers)
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

from app.services.llm.providers.base import (
    CompletionRequest,
    LLMProvider,
    ProviderCapabilities,
)
from app.services.llm import capability_registry as caps_db

logger = logging.getLogger("voxyflow.providers.anthropic")

# Anthropic models that are always available (no dynamic listing endpoint)
_KNOWN_MODELS = [
    "claude-opus-4-6",
    "claude-sonnet-4-6",
    "claude-haiku-4-5-20251001",
    "claude-3-5-sonnet-20241022",
    "claude-3-5-haiku-20241022",
    "claude-3-opus-20240229",
]


class AnthropicProvider(LLMProvider):
    """Provider using the native Anthropic SDK."""

    provider_label = "Anthropic (Claude)"
    provider_type = "anthropic"

    def __init__(self, api_key: str, api_base: str = ""):
        import anthropic

        self._api_key = api_key
        kwargs: dict = {"api_key": api_key}
        if api_base:
            kwargs["base_url"] = api_base
        self._client = anthropic.AsyncAnthropic(**kwargs)

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    async def complete(self, request: CompletionRequest) -> str:
        kwargs = self._build_kwargs(request, stream=False)
        response = await self._client.messages.create(**kwargs)
        return self._extract_text(response)

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        kwargs = self._build_kwargs(request, stream=True)
        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

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
        """Anthropic has no public model listing endpoint — return known models."""
        return _KNOWN_MODELS

    async def is_reachable(self) -> bool:
        try:
            # Minimal probe: list models (static, no API call needed)
            return bool(self._api_key)
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_kwargs(self, request: CompletionRequest, stream: bool) -> dict:
        """Build kwargs for anthropic.messages.create()."""
        messages = list(request.messages)
        # Strip system messages from the list — Anthropic takes system separately
        system = request.system
        filtered = []
        for msg in messages:
            if msg.get("role") == "system":
                system = msg.get("content", system)
            else:
                filtered.append(msg)

        kwargs: dict = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": filtered,
        }
        if system:
            kwargs["system"] = system
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.tools and caps_db.supports_tools(request.model):
            kwargs["tools"] = request.tools

        return kwargs

    def _extract_text(self, response) -> str:
        parts = []
        for block in response.content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "".join(parts)
