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
from app.services.personality_service import (
    build_live_state_block,
    build_session_handoff_block,
    build_worker_events_block,
)
from app.services.ws_broadcast import ws_broadcast

if TYPE_CHECKING:
    pass

logger = logging.getLogger("voxyflow.orchestration")


async def _count_cards_updated_today(workspace_id: str) -> int | None:
    """How many cards in this workspace were created/updated since local midnight?

    Returns None on error (caller suppresses the line). Ignores the system-main
    workspace because "today" is a workspace-scoped signal; global rollups aren't
    meaningful for Voxy's heartbeat.
    """
    from datetime import datetime, timezone
    from sqlalchemy import select, func
    from app.database import async_session, Card, SYSTEM_MAIN_WORKSPACE_ID

    if not workspace_id or workspace_id == SYSTEM_MAIN_WORKSPACE_ID:
        return None
    # Local midnight in server TZ (use UTC — servers typically run UTC; a few
    # hours skew here is acceptable for a heartbeat signal).
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    async with async_session() as db:
        result = await db.execute(
            select(func.count(Card.id)).where(
                Card.workspace_id == workspace_id,
                Card.updated_at >= midnight,
            )
        )
        return int(result.scalar_one() or 0)


async def _compute_ambient_blocks(
    worker_pools: dict,
    session_id: str | None,
    chat_id: str,
    workspace_id: str | None = None,
) -> tuple[str, str, str, int]:
    """Build Live state + Worker activity blocks for the next user turn.

    Worker activity peeks the per-chat completion buffer (see
    DeepWorkerPool.peek_worker_events). The caller is responsible for
    acknowledging those events after the callback turn has been persisted and
    broadcast successfully. Live state reports active workers for this chat,
    their intents, the next scheduled job globally, and today's card activity
    (if ``workspace_id`` given). Both blocks silently omit unavailable data.
    """
    live_state = ""
    worker_events = ""
    pool = worker_pools.get(session_id) if session_id else None

    events: list = []
    peeked_event_count = 0
    active_workers = 0
    running_intents: list[str] = []
    if pool is not None:
        try:
            events = pool.peek_worker_events(chat_id)
            peeked_event_count = len(events)
        except Exception as e:
            logger.debug("peek_worker_events failed: %s", e)
            events = []
            peeked_event_count = 0
        try:
            active_workers = pool.count_active_for_chat(chat_id)
        except Exception as e:
            logger.debug("count_active_for_chat failed: %s", e)
            active_workers = 0
        try:
            running_intents = pool.active_intents_for_chat(chat_id) if active_workers else []
        except Exception as e:
            logger.debug("active_intents_for_chat failed: %s", e)
            running_intents = []

    next_job = None
    try:
        from app.services.scheduler_service import get_scheduler_service
        sched = get_scheduler_service()
        if sched is not None:
            next_job = sched.get_next_upcoming_job()
    except Exception as e:
        logger.debug("get_next_upcoming_job failed: %s", e)
        next_job = None

    cards_updated_today = None
    if workspace_id:
        try:
            cards_updated_today = await _count_cards_updated_today(workspace_id)
        except Exception as e:
            logger.debug("count_cards_updated_today failed: %s", e)
            cards_updated_today = None

    try:
        live_state = build_live_state_block(
            active_workers=active_workers,
            next_job=next_job,
            pending_actions=None,
            cards_updated_today=cards_updated_today,
            running_worker_intents=running_intents or None,
        )
    except Exception as e:
        logger.debug("build_live_state_block failed: %s", e)
        live_state = ""

    if events:
        try:
            worker_events = build_worker_events_block(events)
        except Exception as e:
            logger.debug("build_worker_events_block failed: %s", e)
            worker_events = ""

    session_handoff = ""
    try:
        from app.services.session_store import session_store
        recent = session_store.get_recent_messages(chat_id, limit=10)
        session_handoff = build_session_handoff_block(recent)
    except Exception as e:
        logger.debug("build_session_handoff_block failed: %s", e)
        session_handoff = ""

    return live_state, worker_events, session_handoff, peeked_event_count


def _ack_peeked_worker_events(worker_pools: dict, session_id: str | None, chat_id: str, count: int) -> None:
    """Acknowledge ambient worker events after a callback turn emits successfully."""
    if count <= 0 or not session_id:
        return
    pool = worker_pools.get(session_id)
    if pool is None:
        return
    try:
        pool.ack_worker_events(chat_id, count=count)
    except Exception as e:
        logger.debug("ack_worker_events failed: %s", e)


class LayerRunnersMixin:
    """Mixin providing _run_fast_layer, _run_deep_chat_layer."""

    async def _run_fast_layer(
        self,
        websocket: WebSocket,
        content: str,
        message_id: str,
        chat_id: str,
        workspace_name: str | None,
        workspace_id: str | None,
        chat_level: str,
        project_context: dict | None,
        card_context: dict | None,
        project_names: list[str],
        session_id: str | None,
        send_model_status,
        active_workers_context: str = "",
        is_callback: bool = False,
        role: str = "dispatcher",
        autonomy_directive_path: str = "",
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
        fast_model_label = self._claude.fast_model or "fast"

        try:
            first_token_sent = False
            # For callbacks: buffer tokens to check for [SILENT] before sending
            buffered_tokens: list[str] = [] if is_callback else []

            live_state_block, worker_events_block, session_handoff_block, peeked_event_count = await _compute_ambient_blocks(
                self._worker_pools, session_id, chat_id,
                workspace_id=workspace_id,
            )

            async for token in self._claude.chat_fast_stream(
                chat_id=chat_id,
                user_message=content,
                workspace_name=workspace_name,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                workspace_id=workspace_id,
                project_names=project_names,
                active_workers_context=active_workers_context,
                session_id=session_id or "",
                live_state_block=live_state_block,
                worker_events_block=worker_events_block,
                session_handoff_block=session_handoff_block,
                role=role,
                autonomy_directive_path=autonomy_directive_path,
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
                    await ws_broadcast.send_and_fanout_chat(
                        websocket, chat_id, "chat:response",
                        {
                            "messageId": message_id,
                            "content": token,
                            "model": fast_model_label,
                            "streaming": True,
                            "done": False,
                            "sessionId": session_id,
                            "chatId": chat_id,
                        },
                    )

            # [SILENT] / transient backend-error suppression for callback responses.
            # Worker results are already persisted; a saturated dispatcher model should
            # not turn a successful worker completion into a visible chat error.
            if is_callback and fast_full_response.strip() == "[SILENT]":
                logger.info("[Orchestrator] Callback response is [SILENT] — suppressing; ambient events stay queued")
                await send_model_status("fast", "idle")
                return True
            if is_callback and "[Codex CLI error:" in fast_full_response and "model is at capacity" in fast_full_response.lower():
                logger.warning("[Orchestrator] Suppressing Codex capacity error during worker callback; ambient events stay queued")
                await send_model_status("fast", "idle")
                return True

            # For callbacks: flush buffered tokens now that we know it's not suppressed
            if is_callback and buffered_tokens:
                for tok in buffered_tokens:
                    await ws_broadcast.send_and_fanout_chat(
                        websocket, chat_id, "chat:response",
                        {
                            "messageId": message_id,
                            "content": tok,
                            "model": fast_model_label,
                            "streaming": True,
                            "done": False,
                            "sessionId": session_id,
                            "chatId": chat_id,
                        },
                    )

            # Check for <tool_call> text blocks and handle them
            if TOOL_CALL_PATTERN.search(fast_full_response):
                await self._handle_tool_call_fallback(
                    full_response=fast_full_response,
                    websocket=websocket,
                    message_id=message_id,
                    chat_id=chat_id,
                    model_label="fast",
                    session_id=session_id,
                    workspace_name=workspace_name,
                    workspace_id=workspace_id,
                    chat_level=chat_level,
                    project_context=project_context,
                    card_context=card_context,
                    project_names=project_names,
                )

            # Send stream-done signal
            latency = int((time.time() - start) * 1000)
            logger.info(f"[Layer1-Fast] stream complete in {latency}ms")
            done_payload = {
                "messageId": message_id,
                "content": "",
                "model": fast_model_label,
                "streaming": True,
                "done": True,
                "latency_ms": latency,
                "sessionId": session_id,
                "chatId": chat_id,
            }
            usage = self._claude.consume_last_chat_usage(chat_id, layer="fast")
            if usage:
                done_payload["usage"] = usage
            await ws_broadcast.send_and_fanout_chat(
                websocket, chat_id, "chat:response", done_payload,
            )
            if is_callback:
                _ack_peeked_worker_events(self._worker_pools, session_id, chat_id, peeked_event_count)
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
        workspace_name: str | None,
        workspace_id: str | None,
        chat_level: str,
        project_context: dict | None,
        card_context: dict | None,
        project_names: list[str],
        session_id: str | None,
        send_model_status,
        active_workers_context: str = "",
        is_callback: bool = False,
    ) -> bool:
        """Run the Deep layer as the primary chat responder (streaming).

        Used when deep_enabled=True. Opus streams directly to chat using the
        same delegate-first pattern as Fast layer: NO direct tool execution.
        The model responds conversationally and emits <delegate> blocks for actions,
        which are parsed by _parse_and_emit_delegates → DeepWorkerPool executes in background.
        Returns True on success, False on failure.
        For callback responses (is_callback=True), buffers tokens and suppresses
        sending if the full response is exactly [SILENT].
        """
        await send_model_status("deep", "active")
        start = time.time()
        deep_full_response = ""
        deep_model_label = self._claude.deep_model or "deep"

        try:
            first_token_sent = False
            buffered_tokens: list[str] = [] if is_callback else []
            live_state_block, worker_events_block, session_handoff_block, peeked_event_count = await _compute_ambient_blocks(
                self._worker_pools, session_id, chat_id,
                workspace_id=workspace_id,
            )

            async for token in self._claude.chat_deep_stream(
                chat_id=chat_id,
                user_message=content,
                workspace_name=workspace_name,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                workspace_id=workspace_id,
                project_names=project_names,
                active_workers_context=active_workers_context,
                session_id=session_id or "",
                live_state_block=live_state_block,
                worker_events_block=worker_events_block,
                session_handoff_block=session_handoff_block,
            ):
                deep_full_response += token
                if not first_token_sent:
                    first_token_latency = int((time.time() - start) * 1000)
                    logger.info(f"[Layer-Deep-Chat] first token in {first_token_latency}ms")
                    first_token_sent = True

                if is_callback:
                    buffered_tokens.append(token)
                else:
                    await ws_broadcast.send_and_fanout_chat(
                        websocket, chat_id, "chat:response",
                        {
                            "messageId": message_id,
                            "content": token,
                            "model": deep_model_label,
                            "streaming": True,
                            "done": False,
                            "sessionId": session_id,
                            "chatId": chat_id,
                        },
                    )

            if is_callback and deep_full_response.strip() == "[SILENT]":
                logger.info("[Orchestrator] Deep callback response is [SILENT] — suppressing; ambient events stay queued")
                await send_model_status("deep", "idle")
                return True
            if is_callback and "[Codex CLI error:" in deep_full_response and "model is at capacity" in deep_full_response.lower():
                logger.warning("[Orchestrator] Suppressing Codex capacity error during deep worker callback; ambient events stay queued")
                await send_model_status("deep", "idle")
                return True

            if is_callback and buffered_tokens:
                for tok in buffered_tokens:
                    await ws_broadcast.send_and_fanout_chat(
                        websocket, chat_id, "chat:response",
                        {
                            "messageId": message_id,
                            "content": tok,
                            "model": deep_model_label,
                            "streaming": True,
                            "done": False,
                            "sessionId": session_id,
                            "chatId": chat_id,
                        },
                    )

            # Check for <tool_call> text blocks and handle them
            if TOOL_CALL_PATTERN.search(deep_full_response):
                await self._handle_tool_call_fallback(
                    full_response=deep_full_response,
                    websocket=websocket,
                    message_id=message_id,
                    chat_id=chat_id,
                    model_label="deep",
                    session_id=session_id,
                    workspace_name=workspace_name,
                    workspace_id=workspace_id,
                    chat_level=chat_level,
                    project_context=project_context,
                    card_context=card_context,
                    project_names=project_names,
                )

            # Send stream-done signal
            latency = int((time.time() - start) * 1000)
            logger.info(f"[Layer-Deep-Chat] stream complete in {latency}ms")
            done_payload = {
                "messageId": message_id,
                "content": "",
                "model": deep_model_label,
                "streaming": True,
                "done": True,
                "latency_ms": latency,
                "sessionId": session_id,
                "chatId": chat_id,
            }
            usage = self._claude.consume_last_chat_usage(chat_id, layer="deep")
            if usage:
                done_payload["usage"] = usage
            await ws_broadcast.send_and_fanout_chat(
                websocket, chat_id, "chat:response", done_payload,
            )
            if is_callback:
                _ack_peeked_worker_events(self._worker_pools, session_id, chat_id, peeked_event_count)
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

