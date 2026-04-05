"""Layer runner mixins for ChatOrchestrator.

Extracted from chat_orchestration.py — do not import ChatOrchestrator here
(circular import). These methods rely on self attributes set in ChatOrchestrator:
  self._claude  — ClaudeService instance
  self._handle_tool_call_fallback()  — method on ChatOrchestrator
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from fastapi import WebSocket

from app.tools.response_parser import TOOL_CALL_PATTERN

if TYPE_CHECKING:
    pass

logger = logging.getLogger("voxyflow.orchestration")


class LayerRunnersMixin:
    """Mixin providing _run_fast_layer, _run_deep_chat_layer, _run_analyzer_layer."""

    async def _run_fast_layer(
        self,
        websocket: WebSocket,
        content: str,
        message_id: str,
        chat_id: str,
        project_name: str | None,
        project_id: str | None,
        chat_level: str,
        project_context: dict | None,
        card_context: dict | None,
        project_names: list[str],
        session_id: str | None,
        send_model_status,
        active_workers_context: str = "",
        is_callback: bool = False,
    ) -> bool:
        """Run the fast layer, streaming tokens to the WebSocket.

        Returns True on success, False on failure.
        Chat layers have zero tools — clean streaming only.
        For callback responses (is_callback=True), buffers tokens and suppresses
        sending if the full response is exactly [SILENT].
        """
        await send_model_status("fast", "active")
        start = time.time()
        fast_full_response = ""

        try:
            first_token_sent = False
            # For callbacks: buffer tokens to check for [SILENT] before sending
            buffered_tokens: list[str] = [] if is_callback else []

            async for token in self._claude.chat_fast_stream(
                chat_id=chat_id,
                user_message=content,
                project_name=project_name,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_id=project_id,
                project_names=project_names,
                active_workers_context=active_workers_context,
                session_id=session_id or "",
            ):
                fast_full_response += token
                if not first_token_sent:
                    first_token_latency = int((time.time() - start) * 1000)
                    logger.info(f"[Layer1-Fast] first token in {first_token_latency}ms")
                    first_token_sent = True

                if is_callback:
                    # Buffer — don't send yet, check for [SILENT] at end
                    buffered_tokens.append(token)
                else:
                    await websocket.send_json({
                        "type": "chat:response",
                        "payload": {
                            "messageId": message_id,
                            "content": token,
                            "model": "fast",
                            "streaming": True,
                            "done": False,
                            "sessionId": session_id,
                        },
                        "timestamp": int(time.time() * 1000),
                    })

            # [SILENT] suppression for callback responses
            if is_callback and fast_full_response.strip() == "[SILENT]":
                logger.info(f"[Orchestrator] Callback response is [SILENT] — suppressing")
                await send_model_status("fast", "idle")
                return True

            # For callbacks: flush buffered tokens now that we know it's not [SILENT]
            if is_callback and buffered_tokens:
                for tok in buffered_tokens:
                    await websocket.send_json({
                        "type": "chat:response",
                        "payload": {
                            "messageId": message_id,
                            "content": tok,
                            "model": "fast",
                            "streaming": True,
                            "done": False,
                            "sessionId": session_id,
                        },
                        "timestamp": int(time.time() * 1000),
                    })

            # Check for <tool_call> text blocks and handle them
            if TOOL_CALL_PATTERN.search(fast_full_response):
                await self._handle_tool_call_fallback(
                    full_response=fast_full_response,
                    websocket=websocket,
                    message_id=message_id,
                    chat_id=chat_id,
                    model_label="fast",
                    session_id=session_id,
                    project_name=project_name,
                    project_id=project_id,
                    chat_level=chat_level,
                    project_context=project_context,
                    card_context=card_context,
                    project_names=project_names,
                )

            # Send stream-done signal
            latency = int((time.time() - start) * 1000)
            logger.info(f"[Layer1-Fast] stream complete in {latency}ms")
            await websocket.send_json({
                "type": "chat:response",
                "payload": {
                    "messageId": message_id,
                    "content": "",
                    "model": "fast",
                    "streaming": True,
                    "done": True,
                    "latency_ms": latency,
                    "sessionId": session_id,
                },
                "timestamp": int(time.time() * 1000),
            })
            await send_model_status("fast", "idle")
            return True

        except Exception as e:
            logger.error(f"[Layer1-Fast] error: {e}")
            try:
                await send_model_status("fast", "error")
            except Exception as e:
                logger.debug("Best-effort send failed (WS likely closed): %s", e)
            try:
                await websocket.send_json({
                    "type": "chat:error",
                    "payload": {"messageId": message_id, "error": str(e), "sessionId": session_id},
                    "timestamp": int(time.time() * 1000),
                })
            except Exception as e:
                logger.debug("Best-effort send failed (WS likely closed): %s", e)
            return False
        finally:
            # Safety net: always reset to idle even if WS is closed
            try:
                await send_model_status("fast", "idle")
            except Exception:
                logger.debug("[Layer1-Fast] Could not send final idle status (WS likely closed)")

    async def _run_deep_chat_layer(
        self,
        websocket: WebSocket,
        content: str,
        message_id: str,
        chat_id: str,
        project_name: str | None,
        project_id: str | None,
        chat_level: str,
        project_context: dict | None,
        card_context: dict | None,
        project_names: list[str],
        session_id: str | None,
        send_model_status,
        active_workers_context: str = "",
    ) -> bool:
        """Run the Deep layer as the primary chat responder (streaming).

        Used when deep_enabled=True. Opus streams directly to chat using the
        same delegate-first pattern as Fast layer: NO direct tool execution.
        The model responds conversationally and emits <delegate> blocks for actions,
        which are parsed by _parse_and_emit_delegates → DeepWorkerPool executes in background.
        Returns True on success, False on failure.
        """
        await send_model_status("deep", "active")
        start = time.time()
        deep_full_response = ""

        try:
            first_token_sent = False
            async for token in self._claude.chat_deep_stream(
                chat_id=chat_id,
                user_message=content,
                project_name=project_name,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_id=project_id,
                project_names=project_names,
                active_workers_context=active_workers_context,
                session_id=session_id or "",
            ):
                deep_full_response += token
                if not first_token_sent:
                    first_token_latency = int((time.time() - start) * 1000)
                    logger.info(f"[Layer-Deep-Chat] first token in {first_token_latency}ms")
                    first_token_sent = True

                await websocket.send_json({
                    "type": "chat:response",
                    "payload": {
                        "messageId": message_id,
                        "content": token,
                        "model": "deep",
                        "streaming": True,
                        "done": False,
                        "sessionId": session_id,
                    },
                    "timestamp": int(time.time() * 1000),
                })

            # Check for <tool_call> text blocks and handle them
            if TOOL_CALL_PATTERN.search(deep_full_response):
                await self._handle_tool_call_fallback(
                    full_response=deep_full_response,
                    websocket=websocket,
                    message_id=message_id,
                    chat_id=chat_id,
                    model_label="deep",
                    session_id=session_id,
                    project_name=project_name,
                    project_id=project_id,
                    chat_level=chat_level,
                    project_context=project_context,
                    card_context=card_context,
                    project_names=project_names,
                )

            # Send stream-done signal
            latency = int((time.time() - start) * 1000)
            logger.info(f"[Layer-Deep-Chat] stream complete in {latency}ms")
            await websocket.send_json({
                "type": "chat:response",
                "payload": {
                    "messageId": message_id,
                    "content": "",
                    "model": "deep",
                    "streaming": True,
                    "done": True,
                    "latency_ms": latency,
                    "sessionId": session_id,
                },
                "timestamp": int(time.time() * 1000),
            })
            await send_model_status("deep", "idle")
            return True

        except Exception as e:
            logger.error(f"[Layer-Deep-Chat] error: {e}")
            try:
                await send_model_status("deep", "error")
            except Exception as e:
                logger.debug("Best-effort send failed (WS likely closed): %s", e)
            try:
                await websocket.send_json({
                    "type": "chat:error",
                    "payload": {"messageId": message_id, "error": str(e), "sessionId": session_id},
                    "timestamp": int(time.time() * 1000),
                })
            except Exception as e:
                logger.debug("Best-effort send failed (WS likely closed): %s", e)
            return False
        finally:
            # Safety net: always reset to idle even if WS is closed
            try:
                await send_model_status("deep", "idle")
            except Exception:
                logger.debug("[Layer-Deep-Chat] Could not send final idle status (WS likely closed)")

    async def _run_analyzer_layer(
        self,
        websocket: WebSocket,
        analyzer_enabled: bool,
        analyzer_task: asyncio.Task | None,
        project_id: str | None,
        session_id: str | None,
        send_model_status,
    ) -> None:
        """Await the analyzer result and send card suggestions if any."""
        if not analyzer_enabled or analyzer_task is None:
            logger.debug("[Layer3-Analyzer] skipped (disabled by user)")
            return

        try:
            cards = await asyncio.wait_for(analyzer_task, timeout=15.0)
            if cards:
                for card in cards:
                    logger.info(f"[Layer3-Analyzer] card suggestion: {card['title']}")
                    await websocket.send_json({
                        "type": "card:suggestion",
                        "payload": {
                            "title": card["title"],
                            "description": card.get("description", ""),
                            "agentType": card.get("agent_type", "general"),
                            "agentName": card.get("agent_name", "Ember"),
                            "projectId": project_id or "",
                            "sessionId": session_id,
                        },
                        "timestamp": int(time.time() * 1000),
                    })
            await send_model_status("analyzer", "idle")
        except asyncio.TimeoutError:
            logger.warning("[Layer3-Analyzer] timed out after 15s, skipping")
            await send_model_status("analyzer", "idle")
        except asyncio.CancelledError:
            await send_model_status("analyzer", "idle")
        except Exception as e:
            logger.error(f"[Layer3-Analyzer] error: {e}")
            await send_model_status("analyzer", "error")
