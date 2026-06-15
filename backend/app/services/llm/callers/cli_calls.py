"""Claude CLI subprocess call paths for ApiCallerMixin.

Extracted verbatim from api_caller.py. See app.services.llm.callers package
docstring for the self-attribute contract required from the host class
(notably self._cli_backend and self._last_stream_usage).
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Callable, Optional

from app.services.llm.callers.token_log import _log_token_usage

logger = logging.getLogger(__name__)


class CliCallsMixin:
    """Claude CLI subprocess call paths (non-streaming + streaming)."""

    # ------------------------------------------------------------------
    # Claude CLI subprocess path
    # ------------------------------------------------------------------

    async def _call_api_cli(
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
        """Non-streaming call via Claude CLI subprocess.

        When *task_id* is provided (worker context) and *message_queue* is
        set, uses the steerable path (--input-format stream-json) so mid-
        execution steering messages can be injected via the queue.

        ``effort`` (canonical worker reasoning-effort level) is forwarded to the
        steerable worker path only; "" = model default.
        """
        if task_id and tool_callback and use_tools:
            # Steerable worker path: keeps stdin open for mid-execution steering
            text, usage = await self._cli_backend.call_steerable(
                model=model,
                system=system,
                messages=messages,
                use_tools=use_tools,
                mcp_role=mcp_role,
                cancel_event=cancel_event,
                tool_callback=tool_callback,
                session_id=session_id,
                chat_id=chat_id,
                workspace_id=workspace_id,
                card_id=card_id,
                session_type=session_type,
                task_id=task_id,
                steer_queue=message_queue,
                cwd=cwd,
                effort=effort,
            )
        else:
            text, usage = await self._cli_backend.call(
                model=model,
                system=system,
                messages=messages,
                use_tools=use_tools,
                mcp_role=mcp_role,
                cancel_event=cancel_event,
                tool_callback=tool_callback,
                session_id=session_id,
                chat_id=chat_id,
                workspace_id=workspace_id,
                card_id=card_id,
                session_type=session_type,
                cwd=cwd,
            )
            # Drain message_queue if anything was queued (non-steerable path)
            if message_queue:
                while not message_queue.empty():
                    try:
                        msg = message_queue.get_nowait()
                        logger.warning(f"[CLI] Drained queued message (not injectable): {str(msg)[:100]}")
                    except asyncio.QueueEmpty:
                        break
        # Log token usage
        _log_token_usage(
            layer=layer,
            model=model,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            chat_id=chat_id,
            cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
            cache_read_tokens=usage.get("cache_read_input_tokens", 0),
        )
        return text

    async def _call_api_stream_cli(
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
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
    ) -> AsyncIterator[str]:
        """Streaming call via Claude CLI subprocess.

        Chat sessions use persistent processes (kept alive across turns).
        Workers and other session types use one-shot processes.
        """
        if session_type == "chat" and chat_id:
            async for token in self._cli_backend.stream_persistent(
                model=model, system=system, messages=messages,
                chat_id=chat_id, use_tools=use_tools, mcp_role=mcp_role,
                session_id=session_id, workspace_id=workspace_id, card_id=card_id,
                session_type=session_type, cwd=cwd, tool_callback=tool_callback,
            ):
                yield token
        else:
            async for token in self._cli_backend.stream(
                model=model, system=system, messages=messages,
                use_tools=use_tools, mcp_role=mcp_role,
                session_id=session_id, chat_id=chat_id,
                workspace_id=workspace_id, card_id=card_id,
                session_type=session_type, cwd=cwd, tool_callback=tool_callback,
            ):
                yield token
        # Log token usage from the completed stream
        usage = self._cli_backend.last_usage
        if usage:
            _log_token_usage(
                layer=layer,
                model=model,
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                chat_id=chat_id,
                cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                cache_read_tokens=usage.get("cache_read_input_tokens", 0),
            )
            if chat_id:
                self._last_stream_usage[chat_id] = dict(usage)
