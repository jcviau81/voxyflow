"""Delegate dispatch + direct-action pipeline — extracted from chat_orchestration.

Handles the post-stream work that follows a dispatcher response:
  - Parsing <delegate> JSON blocks and native delegate_action tool_use blocks
  - Dispatching eligible read/write actions directly (DirectExecutor)
  - Deduplicating against active workers, then emitting ActionIntent events
  - Running the destructive-action confirmation gate

Split from ChatOrchestrator (April 2026 code-review pass) to keep the
top-level orchestrator file navigable. The mixin depends on instance
state set up by ChatOrchestrator.__init__ (``self._claude``,
``self._worker_pools``, ``self._pending_confirms*``, ``self.start_worker_pool``,
``self._handle_message_inner``) — it is not usable standalone.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from uuid import uuid4

from fastapi import WebSocket

from app.services.direct_executor import DirectExecutor, READ_ACTIONS
from app.services.event_bus import ActionIntent, event_bus_registry
from app.services.orchestration.model_resolution import resolve_worker_model
from app.services.orchestration.session_timeline import get_timeline

logger = logging.getLogger("voxyflow.orchestration")


class DelegateDispatchMixin:
    """Mixin: parse delegates, run direct actions, emit ActionIntent events.

    All methods assume ``self`` is a ``ChatOrchestrator`` instance with the
    usual attributes (self._claude, self._worker_pools, self._pending_confirms,
    self._pending_confirms_lock, and self._handle_message_inner).
    """

    async def _parse_and_emit_delegates_safe(self, **kwargs) -> None:
        """Wrapper that catches errors so background task doesn't crash silently."""
        try:
            await self._parse_and_emit_delegates(**kwargs)
        except Exception as e:
            logger.error(f"[Orchestrator] Background delegate parsing failed: {e}", exc_info=True)

    async def _emit_native_delegates_safe(self, **kwargs) -> None:
        """Wrapper for native delegate emission."""
        try:
            await self._emit_native_delegates(**kwargs)
        except Exception as e:
            logger.error(f"[Orchestrator] Native delegate emission failed: {e}", exc_info=True)

    async def _auto_extract_memories_safe(
        self,
        chat_id: str,
        user_message: str,
        project_name: str | None = None,
        project_id: str | None = None,
    ) -> None:
        """Background-safe wrapper for memory auto-extraction."""
        try:
            from app.services.memory_service import get_memory_service
            memory = get_memory_service()
            if not memory.chromadb_enabled:
                return

            # Build a minimal messages list with the latest exchange
            history = self._claude.get_history(chat_id)
            # Take last 4 messages (2 user + 2 assistant turns) for extraction
            recent = history[-4:] if len(history) >= 4 else history

            stored = await memory.auto_extract_memories(
                chat_id=chat_id,
                messages=recent,
                project_id=project_id,
            )
            if stored:
                logger.info(f"[Orchestrator] Auto-extracted {len(stored)} memories from chat {chat_id}")
        except Exception as e:
            logger.error(f"[Orchestrator] Memory auto-extraction failed: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Deduplication helper (shared by native + XML paths)
    # ------------------------------------------------------------------

    @staticmethod
    def _dedup_delegates(
        worker_delegates: list[dict],
        pool,
    ) -> list[dict]:
        """Deduplicate delegates against currently active workers only.

        Uses (action, description_prefix) tuples instead of just the action
        name so that two unrelated ``run_command`` delegates are not falsely
        deduped.  Completed tasks are intentionally excluded — the same action
        may legitimately be redispatched after a previous run finishes.
        """
        if not pool:
            return worker_delegates

        existing = pool.get_active_tasks()

        def _key(action: str, desc: str) -> tuple[str, str]:
            return (action.lower(), desc.lower()[:200].strip())

        already = {
            _key(t["action"], t.get("description", ""))
            for t in existing.get("active", [])
        }

        deduped: list[dict] = []
        for data in worker_delegates:
            action = data.get("action") or data.get("intent") or "unknown"
            summary = data.get("summary") or data.get("description") or ""
            k = _key(action, summary)
            if k in already:
                logger.info(
                    f"[Orchestrator] Dedup: skipping delegate '{action}' "
                    f"(summary matches existing task)"
                )
            else:
                deduped.append(data)
                already.add(k)

        if not deduped:
            logger.info("[Orchestrator] All delegates deduplicated — nothing to emit")
        return deduped

    # ------------------------------------------------------------------
    # Event Bus: Native delegate emission (tool_use path)
    # ------------------------------------------------------------------

    async def _emit_native_delegates(
        self,
        delegates: list[dict],
        session_id: str,
        websocket: "WebSocket",
        project_name: str | None = None,
        chat_level: str = "general",
        project_context: dict | None = None,
        card_context: dict | None = None,
        project_id: str | None = None,
        chat_id: str | None = None,
        callback_depth: int = 0,
    ) -> None:
        """Convert native delegate_action tool_use blocks to ActionIntent events.

        This is the structured counterpart to _parse_and_emit_delegates — same output,
        but the input is already parsed JSON from Claude's tool_use (no regex needed).
        """
        if not delegates:
            return

        # Read actions now execute direct — results injected via worker feedback loop.
        # Separate direct-eligible delegates from worker delegates
        worker_delegates = []
        for data in delegates:
            if DirectExecutor.is_direct_eligible(data):
                # Fast path: execute inline, no worker needed
                logger.info(f"[Orchestrator] Fast-path direct: {data.get('action')} (skipping worker)")
                await self._execute_direct_action(
                    data=data,
                    websocket=websocket,
                    session_id=session_id,
                    project_id=project_id,
                    chat_id=chat_id,
                )
            else:
                worker_delegates.append(data)

        if not worker_delegates:
            return

        # Ensure worker pool is running (also updates WS on reconnect)
        self.start_worker_pool(session_id, websocket)

        # --- Deduplication ---
        worker_delegates = self._dedup_delegates(
            worker_delegates, self._worker_pools.get(session_id)
        )
        if not worker_delegates:
            return

        bus = event_bus_registry.get_or_create(session_id)

        # Shield the emit loop so that a WebSocket-disconnect cancel on the
        # parent background task does not interrupt mid-spawn. Without shield,
        # a refresh during delegate emission could spawn half the workers.
        async def _emit_all() -> None:
            for data in worker_delegates:
                intent = data.get("action") or "unknown"
                summary = data.get("summary") or data.get("description") or ""
                complexity = data.get("complexity") or "simple"

                resolved = resolve_worker_model(
                    data=data,
                    card_context=card_context,
                    intent=intent,
                    complexity=complexity,
                )
                model = resolved.model
                _worker_class_id_override = resolved.worker_class_id
                intent_type = resolved.intent_type

                task_id = f"task-{uuid4().hex[:8]}"

                card_id = card_context.get("id") if card_context else None

                event_data = {
                    "project_name": project_name,
                    "chat_level": chat_level,
                    "project_context": project_context,
                    "card_context": card_context,
                    "card_id": card_id,
                    "dispatcher_chat_id": chat_id,
                    **data,  # Include all fields from delegate_action
                    # Fallback chain: delegate.data['project_id'] → session project_id → None
                    "project_id": data.get("project_id") or project_id,
                }
                if _worker_class_id_override:
                    event_data["worker_class_id"] = _worker_class_id_override

                event = ActionIntent(
                    task_id=task_id,
                    intent_type=intent_type,
                    intent=intent,
                    summary=summary,
                    data=event_data,
                    session_id=session_id,
                    complexity=complexity,
                    model=model,
                    callback_depth=callback_depth,
                )

                await bus.emit(event)
                get_timeline().record(session_id, "delegated", intent, task_id=task_id, model=model, summary=summary)
                logger.info(f"[Orchestrator] Emitted native delegate: {intent} → task {task_id} (model={model}, cb_depth={callback_depth})")

        await asyncio.shield(_emit_all())

    # ------------------------------------------------------------------
    # Event Bus: Delegate parsing (XML fallback)
    # ------------------------------------------------------------------

    _DELEGATE_PATTERN = re.compile(
        r'<delegate>\s*(\{.*?\})\s*</delegate>',
        re.DOTALL,
    )

    async def _parse_and_emit_delegates(
        self,
        fast_response: str,
        session_id: str,
        websocket: WebSocket,
        project_name: str | None = None,
        chat_level: str = "general",
        project_context: dict | None = None,
        card_context: dict | None = None,
        project_id: str | None = None,
        chat_id: str | None = None,
        callback_depth: int = 0,
    ) -> None:
        """Parse <delegate> blocks from the Fast response and emit ActionIntent events."""
        # Debug: log the tail of the response to verify delegate blocks are present
        response_preview = fast_response[-300:] if len(fast_response) > 300 else fast_response
        logger.info(f"[Orchestrator] Parsing delegates from response (len={len(fast_response)}), tail: {response_preview!r}")
        matches = self._DELEGATE_PATTERN.findall(fast_response)
        if not matches:
            return

        # First pass: separate direct-eligible delegates from worker delegates
        parsed_delegates = []
        for match in matches:
            try:
                data = json.loads(match)
                parsed_delegates.append(data)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"[Orchestrator] Failed to parse delegate block: {e}")

        # Read actions now execute direct — results injected via worker feedback loop.
        worker_delegates = []
        for data in parsed_delegates:
            if DirectExecutor.is_direct_eligible(data):
                logger.info(f"[Orchestrator] Fast-path direct (XML): {data.get('action')} (skipping worker)")
                await self._execute_direct_action(
                    data=data,
                    websocket=websocket,
                    session_id=session_id,
                    project_id=project_id,
                    chat_id=chat_id,
                )
            else:
                worker_delegates.append(data)

        if not worker_delegates:
            return

        # Ensure worker pool is running (also updates WS on reconnect)
        self.start_worker_pool(session_id, websocket)

        # --- Deduplication ---
        worker_delegates = self._dedup_delegates(
            worker_delegates, self._worker_pools.get(session_id)
        )
        if not worker_delegates:
            return

        bus = event_bus_registry.get_or_create(session_id)

        # Shield the emit loop so that a WebSocket-disconnect cancel on the
        # parent background task does not interrupt mid-spawn.
        async def _emit_all() -> None:
            for data in worker_delegates:
                try:
                    intent = data.get("intent") or data.get("action") or "unknown"
                    summary = data.get("summary") or data.get("description") or ""
                    complexity = data.get("complexity") or "simple"

                    resolved = resolve_worker_model(
                        data=data,
                        card_context=card_context,
                        intent=intent,
                        complexity=complexity,
                    )
                    model = resolved.model
                    _worker_class_id_override = resolved.worker_class_id
                    intent_type = resolved.intent_type

                    task_id = f"task-{uuid4().hex[:8]}"

                    # Extract card_id from card_context for direct access
                    card_id = card_context.get("id") if card_context else None

                    event_data = {
                        "project_name": project_name,
                        "chat_level": chat_level,
                        "project_context": project_context,
                        "card_context": card_context,
                        "card_id": card_id,
                        "dispatcher_chat_id": chat_id,
                        **data,  # Include original delegate data
                        # Fallback chain: delegate.data['project_id'] → session project_id → None
                        "project_id": data.get("project_id") or project_id,
                    }
                    if _worker_class_id_override:
                        event_data["worker_class_id"] = _worker_class_id_override

                    event = ActionIntent(
                        task_id=task_id,
                        intent_type=intent_type,
                        intent=intent,
                        summary=summary,
                        data=event_data,
                        session_id=session_id,
                        complexity=complexity,
                        model=model,
                        callback_depth=callback_depth,
                    )

                    await bus.emit(event)
                    get_timeline().record(session_id, "delegated", intent, task_id=task_id, model=model, summary=summary)
                    logger.info(f"[Orchestrator] Emitted delegate: {intent} → task {task_id} (cb_depth={callback_depth})")

                except Exception as e:
                    logger.warning(f"[Orchestrator] Failed to emit delegate: {e}")

        await asyncio.shield(_emit_all())

    # ------------------------------------------------------------------
    # Fast-Path: Direct execution for whitelisted CRUD actions
    # ------------------------------------------------------------------

    async def _execute_direct_action(
        self,
        data: dict,
        websocket: "WebSocket",
        session_id: str,
        project_id: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        """Execute a direct (model='direct') action inline — no worker, no LLM.

        Sends action:started, executes via DirectExecutor, then sends
        action:completed + a brief chat confirmation message.
        """
        action = data.get("action", "unknown")
        task_id = f"direct-{uuid4().hex[:8]}"

        # --- Confirmation gate for destructive actions ---
        if DirectExecutor.needs_confirmation(data):
            # Store delegate data so we can execute after user confirms
            with self._pending_confirms_lock:
                self._pending_confirms[task_id] = {
                    "data": data,
                    "project_id": project_id,
                    "session_id": session_id,
                    "chat_id": chat_id,
                }
            try:
                await websocket.send_json({
                    "type": "action:confirm_required",
                    "payload": {
                        "taskId": task_id,
                        "action": action,
                        "params": data.get("params", {}),
                        "sessionId": session_id,
                        "message": f"This action ({action}) is irreversible. Confirm?",
                    },
                    "timestamp": int(time.time() * 1000),
                })
            except Exception as e:
                logger.warning(f"[DirectExecutor] Failed to send confirm_required: {e}")
            # Don't execute — frontend must re-send with confirmed=true
            return

        # --- Notify: action started ---
        try:
            await websocket.send_json({
                "type": "action:started",
                "payload": {
                    "taskId": task_id,
                    "action": action,
                    "sessionId": session_id,
                },
                "timestamp": int(time.time() * 1000),
            })
        except Exception as e:
            logger.warning(f"[DirectExecutor] Failed to send action:started: {e}")

        # --- Execute ---
        result = await DirectExecutor.execute(data, project_id=project_id)

        # --- Notify: action completed ---
        try:
            await websocket.send_json({
                "type": "action:completed",
                "payload": {
                    "taskId": task_id,
                    "action": action,
                    "success": result.get("success", False),
                    "result": result.get("result"),
                    "duration_ms": result.get("duration_ms", 0),
                    "sessionId": session_id,
                },
                "timestamp": int(time.time() * 1000),
            })
        except Exception as e:
            logger.warning(f"[DirectExecutor] Failed to send action:completed: {e}")

        # Record in session timeline
        if session_id:
            success = result.get("success", False)
            result_preview = str(result.get("result", ""))[:80]
            get_timeline().record(
                session_id, "direct", action, task_id=task_id,
                summary=result_preview if success else f"FAILED: {result_preview}",
            )

        # --- Build confirmation message FIRST (needed by injection and chat) ---
        confirmation_msg = self._build_direct_confirmation(action, result)

        # --- Broadcast card change so board updates in real-time ---
        if result.get("success") and action in (
            "card.create", "create_card",
            "card.update", "update_card",
            "card.move", "move_card",
            "card.delete", "delete_card",
        ):
            try:
                from app.services.ws_broadcast import ws_broadcast
                ws_broadcast.emit_sync("cards:changed", {
                    "projectId": project_id or "system-main",
                })
            except Exception as e:
                logger.debug("WS send/broadcast failed (WS likely closed): %s", e)
        # --- For READ actions: re-trigger dispatcher so Voxy sees the result ---
        is_read_action = action in READ_ACTIONS
        if is_read_action and result.get("success") and chat_id and confirmation_msg:
            # Inject result into dispatcher history as assistant message
            # (same pattern as worker auto-callback in DeepWorkerPool._execute_event)
            try:
                await self._claude._append_and_persist_async(
                    chat_id=chat_id,
                    role="assistant",
                    content=f"[Direct Result \u2014 {action}]\n{confirmation_msg}",
                    model="system",
                    msg_type="tool_result",
                )
                logger.info(f"[DirectExecutor] Injected {action} result into dispatcher history for {chat_id}")
            except Exception as e:
                logger.warning(f"[DirectExecutor] Failed to inject result into history: {e}")

            # Re-trigger dispatcher so LLM gets a new turn with the data
            try:
                callback_msg = (
                    f"[SYSTEM: Direct action '{action}' completed. "
                    f"The result is in your conversation history above. "
                    f"Present the information to the user naturally.]"
                )
                callback_message_id = f"direct-cb-{uuid4().hex[:8]}"
                logger.info(f"[DirectExecutor] Re-triggering dispatcher after {action}")

                # Call inner directly — we're already under the chat lock
                await self._handle_message_inner(
                    websocket=websocket,
                    content=callback_msg,
                    message_id=callback_message_id,
                    chat_id=chat_id,
                    project_id=project_id,
                    chat_level="project" if project_id else "general",
                    session_id=session_id,
                    is_callback=True,
                    callback_depth=0,
                )
            except Exception as cb_err:
                logger.warning(f"[DirectExecutor] Dispatcher re-trigger failed: {cb_err}", exc_info=True)
                # Fallback: send confirmation as chat message
                if confirmation_msg:
                    msg_id = f"direct-msg-{uuid4().hex[:8]}"
                    try:
                        from app.services.ws_broadcast import ws_broadcast
                        await ws_broadcast.send_and_fanout_chat(
                            websocket, chat_id or "", "chat:response",
                            {
                                "messageId": msg_id,
                                "content": confirmation_msg,
                                "model": "system",
                                "streaming": False,
                                "done": True,
                                "sessionId": session_id,
                                "chatId": chat_id,
                            },
                        )
                    except Exception as e:
                        logger.debug("WS send/broadcast failed (WS likely closed): %s", e)
        elif confirmation_msg:
            # --- WRITE actions: just send chat confirmation (no re-trigger) ---
            msg_id = f"direct-msg-{uuid4().hex[:8]}"
            try:
                from app.services.ws_broadcast import ws_broadcast
                await ws_broadcast.send_and_fanout_chat(
                    websocket, chat_id or "", "chat:response",
                    {
                        "messageId": msg_id,
                        "content": confirmation_msg,
                        "model": "system",
                        "streaming": False,
                        "done": True,
                        "sessionId": session_id,
                        "chatId": chat_id,
                    },
                )
            except Exception as e:
                logger.warning(f"[DirectExecutor] Failed to send chat confirmation: {e}")

    @staticmethod
    def _build_direct_confirmation(action: str, result: dict) -> str:
        """Build a short human-readable confirmation message."""
        success = result.get("success", False)
        duration = result.get("duration_ms", 0)
        api_result = result.get("result", {})

        if not success:
            error = result.get("error") or (api_result.get("error") if isinstance(api_result, dict) else "")
            return f"Action `{action}` failed: {error}"

        # Extract useful info from the result
        if action in ("card.create", "create_card"):
            title = api_result.get("title", "") if isinstance(api_result, dict) else ""
            return f"Card created: **{title}** ({duration}ms)"
        elif action in ("card.move", "move_card"):
            status = api_result.get("status", "") if isinstance(api_result, dict) else ""
            title = api_result.get("title", "") if isinstance(api_result, dict) else ""
            return f"Card moved: **{title}** → {status} ({duration}ms)"
        elif action in ("card.update", "update_card"):
            title = api_result.get("title", "") if isinstance(api_result, dict) else ""
            return f"Card updated: **{title}** ({duration}ms)"
        elif action in ("card.get", "get_card"):
            if isinstance(api_result, dict):
                title = api_result.get("title", "Unknown")
                description = api_result.get("description", "") or "(no description)"
                status = api_result.get("status", "")
                priority_map = {0: "none", 1: "low", 2: "medium", 3: "high", 4: "critical"}
                priority = priority_map.get(api_result.get("priority", 0), "none")
                agent_type = api_result.get("agent_type", "") or ""

                msg = f"**Card:** {title}\n**Status:** {status} | **Priority:** {priority}"
                if agent_type:
                    msg += f" | **Agent:** {agent_type}"
                msg += f"\n**Description:** {description}"

                # Include checklist progress if present
                checklist = api_result.get("checklist_progress")
                if isinstance(checklist, dict) and checklist.get("total", 0) > 0:
                    msg += f"\n**Checklist:** {checklist['completed']}/{checklist['total']} completed"

                return msg
            return f"Card retrieved ({duration}ms)"
        elif action in ("card.delete", "delete_card"):
            return f"Card deleted ({duration}ms)"
        elif action in ("card.list", "list_cards"):
            if isinstance(api_result, list):
                count = len(api_result)
                if count == 0:
                    return "No cards found."
                parts = ["Found {} card(s):".format(count)]
                for c in api_result[:20]:
                    t = c.get("title", "Untitled")
                    s = c.get("status", "?")
                    cid = c.get("id", "")
                    parts.append("- [{}] {} (id: {})".format(s, t, cid))
                return "\n".join(parts)
            return "card.list completed ({} ms)".format(duration)
        elif action in ("project.list", "list_projects"):
            if isinstance(api_result, list):
                count = len(api_result)
                parts = ["Found {} project(s):".format(count)]
                for p in api_result[:10]:
                    t = p.get("title", "Untitled")
                    pid = p.get("id", "")
                    parts.append("- {} (id: {})".format(t, pid))
                return "\n".join(parts)
            return "project.list completed ({} ms)".format(duration)
        else:
            return f"Action `{action}` completed ({duration}ms)"

    async def handle_action_confirm(
        self,
        task_id: str,
        confirmed: bool,
        websocket: "WebSocket",
    ) -> None:
        """Handle a user's confirmation response for a destructive direct action."""
        with self._pending_confirms_lock:
            pending = self._pending_confirms.pop(task_id, None)
        if not pending:
            logger.warning(f"[DirectExecutor] No pending confirmation for taskId={task_id}")
            return

        if not confirmed:
            logger.info(f"[DirectExecutor] User denied action for taskId={task_id}")
            try:
                await websocket.send_json({
                    "type": "action:completed",
                    "payload": {
                        "taskId": task_id,
                        "action": pending["data"].get("action", "unknown"),
                        "success": False,
                        "result": {"error": "Cancelled by user"},
                        "duration_ms": 0,
                        "sessionId": pending["session_id"],
                    },
                    "timestamp": int(time.time() * 1000),
                })
            except Exception as e:
                logger.warning(f"[DirectExecutor] Failed to send cancelled completion: {e}")
            return

        # User confirmed — execute the action (skip the confirmation gate this time)
        data = pending["data"]
        project_id = pending["project_id"]
        session_id = pending["session_id"]
        chat_id = pending.get("chat_id")

        # Re-use the same task_id so frontend can correlate
        action = data.get("action", "unknown")

        # Notify: action started
        try:
            await websocket.send_json({
                "type": "action:started",
                "payload": {
                    "taskId": task_id,
                    "action": action,
                    "sessionId": session_id,
                },
                "timestamp": int(time.time() * 1000),
            })
        except Exception as e:
            logger.debug("WS send/broadcast failed (WS likely closed): %s", e)
        result = await DirectExecutor.execute(data, project_id=project_id)

        # Notify: action completed
        try:
            await websocket.send_json({
                "type": "action:completed",
                "payload": {
                    "taskId": task_id,
                    "action": action,
                    "success": result.get("success", False),
                    "result": result.get("result"),
                    "duration_ms": result.get("duration_ms", 0),
                    "sessionId": session_id,
                },
                "timestamp": int(time.time() * 1000),
            })
        except Exception as e:
            logger.debug("WS send/broadcast failed (WS likely closed): %s", e)
        # Broadcast card change
        if result.get("success"):
            try:
                from app.services.ws_broadcast import ws_broadcast
                ws_broadcast.emit_sync("cards:changed", {
                    "projectId": project_id or "system-main",
                })
            except Exception as e:
                logger.debug("WS send/broadcast failed (WS likely closed): %s", e)
        # Chat confirmation
        confirmation_msg = self._build_direct_confirmation(action, result)
        if confirmation_msg:
            try:
                from app.services.ws_broadcast import ws_broadcast
                await ws_broadcast.send_and_fanout_chat(
                    websocket, chat_id or "", "chat:response",
                    {
                        "messageId": f"direct-msg-{uuid4().hex[:8]}",
                        "content": confirmation_msg,
                        "model": "system",
                        "streaming": False,
                        "done": True,
                        "sessionId": session_id,
                        "chatId": chat_id,
                    },
                )
            except Exception as e:
                logger.debug("WS send/broadcast failed (WS likely closed): %s", e)

