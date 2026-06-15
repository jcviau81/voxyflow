"""API caller mixin for ClaudeService — Anthropic, OpenAI-compat, CLI, and server-tools paths.

Extracted from claude_service.py. Relies on self attributes from ClaudeService:
  self.deep_model, self.fast_model, self.haiku_model
  self.max_tokens, self.max_tokens_opus, self.max_tokens_sonnet, self.max_tokens_haiku
  self.fast_client, self.fast_client_type
  self._infer_layer(), self._load_tool_settings(), self._should_use_server_tools()
  self._pending_delegates
  self._cli_backend (when client_type == "cli")
  self._codex_backend (when client_type == "codex")

The per-backend call methods live in app.services.llm.callers (one mixin per
backend family); this module composes them into ApiCallerMixin and keeps the
_call_api / _call_api_stream dispatch hub.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Callable, Optional

from app.services.llm.model_utils import _flatten_system

# Re-exported for backward compatibility (these lived here before the split).
from app.services.llm.callers.token_log import (  # noqa: F401
    TOKEN_LOG_PATH,
    _log_token_usage,
    _CONTEXT_1M_HEADER,
    _supports_1m_context,
)
from app.services.llm.callers import (
    AnthropicCallsMixin,
    OpenAICallsMixin,
    ServerToolsCallsMixin,
    CliCallsMixin,
    CodexCallsMixin,
)


class ApiCallerMixin(
    AnthropicCallsMixin,
    OpenAICallsMixin,
    ServerToolsCallsMixin,
    CliCallsMixin,
    CodexCallsMixin,
):
    """Mixin providing all _call_api_* methods for ClaudeService."""

    # ------------------------------------------------------------------
    # Dispatcher: routes to native, CLI, or fallback based on client_type
    # ------------------------------------------------------------------

    async def _call_api(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        client=None,
        client_type: str | None = None,
        use_tools: bool = True,
        mcp_role: str = "worker",
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
        layer: str = "fast",
        chat_id: str = "",
        cancel_event: Optional[asyncio.Event] = None,
        message_queue: Optional[asyncio.Queue] = None,
        session_id: str = "",
        workspace_id: str = "",
        card_id: str = "",
        session_type: str = "worker",
        task_id: str = "",
        cwd: str = "",
        effort: str = "",
    ) -> str:
        """Dispatch to native Anthropic SDK, CLI subprocess, OpenAI-compat, or server-side tools.

        ``effort`` is a canonical Voxyflow worker reasoning-effort level
        (low/medium/high/max; "" = model default). Honored by the CLI subprocess
        paths (Claude ``--effort`` / Codex ``model_reasoning_effort``); ignored
        by the HTTP/SDK paths for now.
        """
        api_client = client or self.fast_client
        # Honor explicit client_type even when client is None — CLI mode legitimately
        # passes client=None with client_type="cli", and inferring from fast_client_type
        # would mis-route (e.g. Haiku summarization → Ollama 404 when Fast layer = Qwen).
        ct = client_type if client_type is not None else self.fast_client_type

        if ct == "codex":
            return await self._call_api_codex(
                model=model, system=system, messages=messages,
                use_tools=use_tools, mcp_role=mcp_role, layer=layer, chat_id=chat_id,
                cancel_event=cancel_event, message_queue=message_queue,
                tool_callback=tool_callback,
                session_id=session_id, workspace_id=workspace_id, card_id=card_id,
                session_type=session_type, task_id=task_id, cwd=cwd, effort=effort,
            )
        if ct == "cli":
            return await self._call_api_cli(
                model=model, system=system, messages=messages,
                use_tools=use_tools, mcp_role=mcp_role, layer=layer, chat_id=chat_id,
                cancel_event=cancel_event, message_queue=message_queue,
                tool_callback=tool_callback,
                session_id=session_id, workspace_id=workspace_id, card_id=card_id,
                session_type=session_type, task_id=task_id, cwd=cwd, effort=effort,
            )
        if ct == "anthropic":
            return await self._call_api_anthropic(
                model=model, system=system, messages=messages, client=api_client,
                use_tools=use_tools, tool_callback=tool_callback, chat_level=chat_level,
                layer=layer, chat_id=chat_id, cancel_event=cancel_event,
                message_queue=message_queue, client_type=ct,
            )
        # Non-Anthropic paths need a plain string for system
        flat_system = _flatten_system(system)
        if use_tools and self._should_use_server_tools(ct):
            return await self._call_api_server_tools(
                model=model, system=flat_system, messages=messages, client=api_client,
                layer=layer, chat_level=chat_level, tool_callback=tool_callback,
                chat_id=chat_id,
            )
        else:
            return await self._call_api_openai(
                model=model, system=flat_system, messages=messages, client=api_client,
                use_tools=use_tools, tool_callback=tool_callback, chat_level=chat_level,
                layer=layer, chat_id=chat_id,
            )

    async def _call_api_stream(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        client=None,
        client_type: str | None = None,
        use_tools: bool = True,
        mcp_role: str = "worker",
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
        layer: str = "fast",
        chat_id: str = "",
        session_id: str = "",
        workspace_id: str = "",
        card_id: str = "",
        session_type: str = "chat",
        cwd: str = "",
    ) -> AsyncIterator[str]:
        """Dispatch streaming to CLI subprocess, native Anthropic SDK, OpenAI-compat, or server-side tools."""
        api_client = client or self.fast_client
        ct = client_type if client_type is not None else self.fast_client_type

        if ct == "codex":
            # TODO(M20): wire tool_callback into the Codex streaming path for
            # tool-visibility parity with the Claude CLI path (out of scope this pass).
            async for token in self._call_api_stream_codex(
                model=model, system=system, messages=messages,
                use_tools=use_tools, mcp_role=mcp_role, layer=layer, chat_id=chat_id,
                session_id=session_id, workspace_id=workspace_id, card_id=card_id,
                session_type=session_type, cwd=cwd,
            ):
                yield token
            return

        if ct == "cli":
            async for token in self._call_api_stream_cli(
                model=model, system=system, messages=messages,
                use_tools=use_tools, mcp_role=mcp_role, layer=layer, chat_id=chat_id,
                session_id=session_id, workspace_id=workspace_id, card_id=card_id,
                session_type=session_type, cwd=cwd, tool_callback=tool_callback,
            ):
                yield token
            return

        if ct == "anthropic":
            async for token in self._call_api_stream_anthropic(
                model=model, system=system, messages=messages, client=api_client,
                use_tools=use_tools, tool_callback=tool_callback, chat_level=chat_level,
                layer=layer, chat_id=chat_id,
            ):
                yield token
        else:
            # Non-Anthropic paths need a plain string for system
            flat_system = _flatten_system(system)
            if use_tools and self._should_use_server_tools(ct):
                async for token in self._call_api_stream_server_tools(
                    model=model, system=flat_system, messages=messages, client=api_client,
                    layer=layer, chat_level=chat_level, tool_callback=tool_callback,
                ):
                    yield token
            else:
                async for token in self._call_api_stream_openai(
                    model=model, system=flat_system, messages=messages, client=api_client,
                    use_tools=use_tools, tool_callback=tool_callback, chat_level=chat_level,
                    layer=layer,
                ):
                    yield token
