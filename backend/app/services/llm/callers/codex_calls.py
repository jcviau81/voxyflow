"""Codex CLI subprocess call paths for ApiCallerMixin.

Extracted verbatim from api_caller.py. See app.services.llm.callers package
docstring for the self-attribute contract required from the host class
(notably self._codex_backend — lazily created here — and self._last_stream_usage).
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Callable, Optional

from app.services.llm.callers.token_log import _log_token_usage

logger = logging.getLogger(__name__)


class CodexCallsMixin:
    """Codex CLI subprocess call paths (non-streaming + streaming)."""

    # ------------------------------------------------------------------
    # Codex CLI subprocess path
    # ------------------------------------------------------------------

    async def _call_api_codex(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        use_tools: bool = False,
        mcp_role: str = "worker",
        layer: str = "fast",
        chat_id: str = "",
        cancel_event: Optional[asyncio.Event] = None,
        message_queue: Optional[asyncio.Queue] = None,
        tool_callback: Optional[Callable] = None,
        session_id: str = "",
        workspace_id: str = "",
        card_id: str = "",
        session_type: str = "worker",
        task_id: str = "",
        cwd: str = "",
        effort: str = "",
    ) -> str:
        if not getattr(self, "_codex_backend", None):
            from app.services.llm.codex_backend import CodexCliBackend
            self._codex_backend = CodexCliBackend()
        text, usage = await self._codex_backend.call(
            model=model,
            system=system,
            messages=messages,
            use_tools=use_tools,
            mcp_role=mcp_role,
            cancel_event=cancel_event,
            message_queue=message_queue,
            tool_callback=tool_callback,
            session_id=session_id,
            chat_id=chat_id,
            workspace_id=workspace_id,
            card_id=card_id,
            session_type=session_type,
            task_id=task_id,
            cwd=cwd,
            effort=effort,
        )
        _log_token_usage(
            layer=layer,
            model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            chat_id=chat_id,
            cache_creation_tokens=0,
            cache_read_tokens=usage.get("cached_input_tokens", 0),
        )
        return text

    async def _call_api_stream_codex(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        use_tools: bool = False,
        mcp_role: str = "worker",
        layer: str = "fast",
        chat_id: str = "",
        session_id: str = "",
        workspace_id: str = "",
        card_id: str = "",
        session_type: str = "chat",
        cwd: str = "",
    ) -> AsyncIterator[str]:
        if not getattr(self, "_codex_backend", None):
            from app.services.llm.codex_backend import CodexCliBackend
            self._codex_backend = CodexCliBackend()
        # Per-call usage holder — backend.last_usage is a shared snapshot that
        # concurrent calls overwrite, misattributing tokens across chat_ids.
        usage_holder: dict = {}
        async for token in self._codex_backend.stream(
            model=model,
            system=system,
            messages=messages,
            usage_holder=usage_holder,
            use_tools=use_tools,
            mcp_role=mcp_role,
            session_id=session_id,
            chat_id=chat_id,
            workspace_id=workspace_id,
            card_id=card_id,
            session_type=session_type,
            cwd=cwd,
        ):
            yield token
        usage = usage_holder
        if usage:
            _log_token_usage(
                layer=layer,
                model=model,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                chat_id=chat_id,
                cache_creation_tokens=0,
                cache_read_tokens=usage.get("cached_input_tokens", 0),
            )
            if chat_id:
                self._last_stream_usage[chat_id] = dict(usage)
