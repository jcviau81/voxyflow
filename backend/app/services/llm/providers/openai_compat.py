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
import json
import logging
from typing import AsyncIterator

from app.services.llm.providers.base import (
    CompletionRequest,
    CompletionResponse,
    LLMProvider,
    ProviderCapabilities,
    StreamDone,
    StreamEvent,
    TextDelta,
    ToolUseBlock,
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

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        """Stream a completion, yielding StreamEvent variants.

        Text deltas pass through immediately. Tool-call deltas arrive in
        pieces (partial `function.arguments` JSON across many chunks) —
        buffered internally by `index` and emitted as complete
        `ToolUseBlock` events after the stream closes. Usage is requested
        via `stream_options.include_usage` (OpenAI extension; silently
        ignored by providers that don't support it).
        """
        messages = self._build_messages(request)
        kwargs = self._base_kwargs(request)

        if request.tools and caps_db.supports_tools(request.model):
            kwargs["tools"] = request.tools
            kwargs["tool_choice"] = "auto"
        kwargs.setdefault("stream_options", {"include_usage": True})

        tool_buffers: dict[int, dict] = {}
        finish_reason = ""
        usage_info: dict | None = None

        async with await self._client.chat.completions.create(
            messages=messages, stream=True, **kwargs
        ) as response:
            async for chunk in response:
                # Usage arrives in a final empty-choices chunk when enabled.
                chunk_usage = getattr(chunk, "usage", None)
                if chunk_usage:
                    usage_info = {
                        "input_tokens": getattr(chunk_usage, "prompt_tokens", 0) or 0,
                        "output_tokens": getattr(chunk_usage, "completion_tokens", 0) or 0,
                    }
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta and delta.content:
                    yield TextDelta(delta.content)
                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        buf = tool_buffers.setdefault(
                            idx, {"id": "", "name": "", "args": ""}
                        )
                        if tc_delta.id:
                            buf["id"] = tc_delta.id
                        fn = getattr(tc_delta, "function", None)
                        if fn:
                            if getattr(fn, "name", None):
                                buf["name"] += fn.name
                            if getattr(fn, "arguments", None):
                                buf["args"] += fn.arguments
                if choice.finish_reason:
                    finish_reason = choice.finish_reason

        for idx in sorted(tool_buffers.keys()):
            buf = tool_buffers[idx]
            try:
                parsed = json.loads(buf["args"]) if buf["args"] else {}
            except json.JSONDecodeError:
                logger.debug(
                    "[OpenAICompat] tool_call %r args failed JSON parse; forwarding raw",
                    buf.get("name") or f"idx{idx}",
                )
                parsed = {"_raw_args": buf["args"]}
            if not isinstance(parsed, dict):
                parsed = {"_value": parsed}
            yield ToolUseBlock(
                id=buf["id"] or f"call_{idx}",
                name=buf["name"],
                input=parsed,
            )

        yield StreamDone(stop_reason=finish_reason, usage=usage_info)

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
