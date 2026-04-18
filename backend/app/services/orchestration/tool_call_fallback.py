"""Tool-call text-fallback pipeline — extracted from chat_orchestration.

When the dispatcher model chooses to emit ``<tool_call>`` XML blocks inside
its streamed text (instead of native tool_use), this mixin handles the
fallback path: parse the blocks, strip them from history, execute the
tools, and stream a follow-up response that incorporates the tool output.

Split from ChatOrchestrator (April 2026 code-review pass). Depends on
instance state from ChatOrchestrator.__init__ (``self._claude``) — not
usable standalone.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from uuid import uuid4

from fastapi import WebSocket

from app.tools.executor import get_executor
from app.tools.response_parser import ToolResponseParser, TOOL_CALL_PATTERN

logger = logging.getLogger("voxyflow.orchestration")


class ToolCallFallbackMixin:
    """Mixin: parse <tool_call> blocks, execute, then stream a follow-up."""

    async def _handle_tool_call_fallback(
        self,
        full_response: str,
        websocket: WebSocket,
        message_id: str,
        chat_id: str,
        model_label: str,
        session_id: str | None,
        project_name: str | None,
        project_id: str | None,
        chat_level: str,
        project_context: dict | None,
        card_context: dict | None,
        project_names: list[str] | None,
    ) -> bool:
        """Check streamed response for <tool_call> blocks. If found:
        1. Strip <tool_call> blocks and update history with clean text
        2. Launch async background task for tool execution + follow-up
        3. Return immediately so the user sees the response right away

        Returns True if tool calls were detected (async task launched), False otherwise.
        """
        parser = ToolResponseParser()
        text_content, tool_calls = parser.parse(full_response)

        if not tool_calls:
            return False

        logger.info(f"[ToolCallFallback] Found {len(tool_calls)} <tool_call> blocks in {model_label} response — launching async execution")

        # Strip <tool_call> blocks from the original response for history
        clean_response = TOOL_CALL_PATTERN.sub("", full_response).strip()

        # Overwrite the last assistant message in history with the clean version
        history = self._claude.get_history(chat_id)
        if history and history[-1].get("role") == "assistant":
            history[-1]["content"] = clean_response

        # Fire-and-forget: launch tool execution + follow-up as background task
        asyncio.create_task(
            self._execute_tools_and_followup_safe(
                tool_calls=tool_calls,
                websocket=websocket,
                message_id=message_id,
                chat_id=chat_id,
                model_label=model_label,
                session_id=session_id,
                project_name=project_name,
                project_id=project_id,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_names=project_names,
            )
        )

        return True

    async def _execute_tools_and_followup_safe(self, **kwargs) -> None:
        """Background-safe wrapper for tool execution + follow-up."""
        try:
            await self._execute_tools_and_followup(**kwargs)
        except Exception as e:
            logger.error(f"[ToolCallFallback] Background tool execution failed: {e}", exc_info=True)
            # Try to notify the user of the failure
            ws = kwargs.get("websocket")
            session_id = kwargs.get("session_id")
            message_id = kwargs.get("message_id")
            if ws:
                try:
                    await ws.send_json({
                        "type": "chat:error",
                        "payload": {
                            "messageId": message_id,
                            "error": f"Tool execution failed: {e}",
                            "sessionId": session_id,
                        },
                        "timestamp": int(time.time() * 1000),
                    })
                except Exception as e:
                    logger.debug("WS send/broadcast failed (WS likely closed): %s", e)
    async def _execute_tools_and_followup(
        self,
        tool_calls: list,
        websocket: WebSocket,
        message_id: str,
        chat_id: str,
        model_label: str,
        session_id: str | None,
        project_name: str | None,
        project_id: str | None,
        chat_level: str,
        project_context: dict | None,
        card_context: dict | None,
        project_names: list[str] | None,
    ) -> None:
        """Background async task: execute tools, then stream a follow-up LLM response.

        This runs AFTER the initial response has already been sent to the user,
        so the chat is non-blocking. Results arrive as a new streamed message.
        """
        # Send tool:status events for each tool
        for tc in tool_calls:
            try:
                await websocket.send_json({
                    "type": "tool:status",
                    "payload": {
                        "tool": tc.name,
                        "state": "executing",
                        "sessionId": session_id,
                    },
                    "timestamp": int(time.time() * 1000),
                })
            except Exception as e:
                logger.warning(f"[ToolCallFallback] Failed to send tool:status: {e}")

        # Execute tools
        executor = get_executor()
        executed_tools: list[dict] = []

        for tc in tool_calls:
            logger.info(f"[ToolCallFallback] Executing: {tc.name}({tc.arguments})")
            result = await executor.execute(tc, timeout=30)
            executed_tools.append({
                "tool": tc.name,
                "args": tc.arguments,
                "result": result,
            })

            # Send tool:executed event to frontend
            try:
                await websocket.send_json({
                    "type": "tool:executed",
                    "payload": {
                        "messageId": message_id,
                        "tool": tc.name,
                        "args": tc.arguments,
                        "result": result,
                        "sessionId": session_id,
                    },
                    "timestamp": int(time.time() * 1000),
                })
            except Exception as e:
                logger.warning(f"[ToolCallFallback] Failed to send tool:executed event: {e}")

        # Build tool results context for follow-up
        tool_context_parts = []
        for evt in executed_tools:
            tool_context_parts.append(
                f"Tool: {evt['tool']}\n"
                f"Args: {json.dumps(evt['args'], default=str)}\n"
                f"Result: {json.dumps(evt['result'], default=str)}"
            )
        tool_context = "\n\n".join(tool_context_parts)

        # Build follow-up messages: existing history + tool results as user context
        history = self._claude.get_history(chat_id)
        followup_messages = list(history) + [
            {
                "role": "user",
                "content": (
                    f"[SYSTEM: Tool execution results — incorporate these into your response]\n\n"
                    f"{tool_context}\n\n"
                    "Now provide your response to the user incorporating the tool results above. "
                    "Do NOT mention tool calls, <tool_call> blocks, or system internals. "
                    "Just answer naturally with the information."
                ),
            }
        ]

        # Determine which client/model to use
        if model_label == "deep":
            client = self._claude.deep_client
            client_type = self._claude.deep_client_type
            model = self._claude.deep_model
        else:
            client = self._claude.fast_client
            client_type = self._claude.fast_client_type
            model = self._claude.fast_model

        # Build system prompt for the follow-up (static base + dynamic context block)
        memory_context = self._claude.memory.build_memory_context(
            project_name=project_name,
            project_id=project_id,
            include_long_term=False,
            include_daily=True,
            budget=200,
            layers=(0,),
        )
        # Static base (cacheable) — dynamic context injected separately below
        base_prompt = self._claude.personality.build_fast_prompt(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
        )
        _wc_list = await self._claude._load_worker_classes_context()
        _dynamic_ctx = self._claude.personality.build_dynamic_context_block(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            project_names=project_names,
            memory_context=memory_context,
            worker_classes=_wc_list,
        )
        _dynamic_parts = [_dynamic_ctx] if _dynamic_ctx else []
        from app.services.claude_service import _make_cached_system
        system_prompt = _make_cached_system(
            base_prompt, _dynamic_parts,
            is_anthropic=(self._claude.fast_client_type == "anthropic"),
        )

        # Generate a new message ID for the follow-up response
        followup_message_id = f"followup-{uuid4().hex[:8]}"

        # Stream follow-up response as a NEW message
        followup_full = ""
        try:
            async for token in self._claude._call_api_stream(
                model=model,
                system=system_prompt,
                messages=followup_messages,
                client=client,
                client_type=client_type,
                use_tools=False,
                chat_level=chat_level,
            ):
                followup_full += token
                await websocket.send_json({
                    "type": "chat:response",
                    "payload": {
                        "messageId": followup_message_id,
                        "content": token,
                        "model": model_label,
                        "streaming": True,
                        "done": False,
                        "sessionId": session_id,
                        "isToolFollowup": True,
                    },
                    "timestamp": int(time.time() * 1000),
                })

            # Send stream-done for the follow-up
            await websocket.send_json({
                "type": "chat:response",
                "payload": {
                    "messageId": followup_message_id,
                    "content": "",
                    "model": model_label,
                    "streaming": True,
                    "done": True,
                    "sessionId": session_id,
                    "isToolFollowup": True,
                },
                "timestamp": int(time.time() * 1000),
            })
        except Exception as e:
            logger.error(f"[ToolCallFallback] Follow-up streaming failed: {e}")

        # Persist tool results + follow-up response in session history
        if followup_full:
            # 1. Persist tool results as a hidden user message (system context)
            #    This ensures the LLM has tool context on subsequent turns.
            #    msg_type="tool_results" lets the UI filter it out.
            tool_results_msg = f"[SYSTEM: Tool execution results]\n\n{tool_context}"
            self._claude._append_and_persist(
                chat_id, "user", tool_results_msg,
                model=model_label, msg_type="tool_results",
                session_id=session_id,
            )
            # 2. Persist the assistant follow-up response
            self._claude._append_and_persist(
                chat_id, "assistant", followup_full,
                model=model_label, session_id=session_id,
            )

        # Send final tool:status complete
        try:
            await websocket.send_json({
                "type": "tool:status",
                "payload": {
                    "state": "complete",
                    "sessionId": session_id,
                },
                "timestamp": int(time.time() * 1000),
            })
        except Exception as e:
            logger.debug("WS send/broadcast failed (WS likely closed): %s", e)
        logger.info(f"[ToolCallFallback] Async follow-up complete ({len(followup_full)} chars)")


