"""OpenAI-compatible provider.

Works with any endpoint that speaks the OpenAI chat/completions API:
  - OpenAI (api.openai.com)
  - Groq   (api.groq.com)
  - Mistral (api.mistral.ai)
  - LM Studio (localhost:1234)
  - Claude-max-api proxy (localhost:3457)
  - Any other OpenAI-compat server

Subclassed by OllamaProvider which adds Ollama-specific model listing.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from app.services.llm.providers.base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    ProviderCapabilities,
)
from app.services.llm import capability_registry as caps_db

logger = logging.getLogger("voxyflow.providers.openai_compat")


class OpenAICompatProvider(LLMProvider):
    """Provider for any OpenAI chat/completions compatible endpoint."""

    provider_label = "OpenAI-compatible"
    provider_type = "openai"

    def __init__(self, provider_url: str, api_key: str, label: str | None = None):
        from openai import AsyncOpenAI

        self._url = provider_url
        self._api_key = api_key or "local"
        if label:
            self.provider_label = label
        self._client = AsyncOpenAI(
            base_url=provider_url,
            api_key=self._api_key,
        )

    # ------------------------------------------------------------------
    # LLMProvider interface
    # ------------------------------------------------------------------

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        messages = self._build_messages(request)
        kwargs = self._base_kwargs(request)

        # Only pass tools if the model supports them and tools are provided
        if request.tools and caps_db.supports_tools(request.model):
            kwargs["tools"] = request.tools
            kwargs["tool_choice"] = "auto"

        response = await self._client.chat.completions.create(
            messages=messages, stream=False, **kwargs
        )
        msg = response.choices[0].message
        tool_calls = None
        if msg.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        usage = None
        if response.usage:
            usage = {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            }
        return CompletionResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            stop_reason=response.choices[0].finish_reason or "",
            usage=usage,
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        messages = self._build_messages(request)
        kwargs = self._base_kwargs(request)

        if request.tools and caps_db.supports_tools(request.model):
            kwargs["tools"] = request.tools
            kwargs["tool_choice"] = "auto"

        had_content = False
        had_tool_calls = False
        async with await self._client.chat.completions.create(
            messages=messages, stream=True, **kwargs
        ) as response:
            async for chunk in response:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    had_content = True
                    yield delta.content
                if delta and delta.tool_calls:
                    had_tool_calls = True

        if had_tool_calls and not had_content:
            logger.warning("[OpenAICompat] tool_call in stream — not forwarded")

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
        """Fetch model list from the /models endpoint (OpenAI standard)."""
        try:
            response = await self._client.models.list()
            return [m.id for m in response.data]
        except Exception as exc:
            logger.debug("[OpenAICompat] list_models failed: %s", exc)
            return []

    async def is_reachable(self) -> bool:
        try:
            await asyncio.wait_for(self.list_models(), timeout=3.0)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_messages(self, request: CompletionRequest) -> list[dict]:
        """Prepend system message if provided and not already in messages."""
        messages = list(request.messages)
        if request.system and (not messages or messages[0].get("role") != "system"):
            messages = [{"role": "system", "content": request.system}] + messages
        return messages

    def _base_kwargs(self, request: CompletionRequest) -> dict:
        kwargs: dict = {
            "model": request.model,
            "max_tokens": request.max_tokens,
        }
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        return kwargs
