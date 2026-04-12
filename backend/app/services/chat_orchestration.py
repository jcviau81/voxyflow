"""Chat Orchestration Service — Multi-Model Chat Pipeline.

Extracted from main.py to separate WebSocket transport from orchestration logic.

Mode Fast (deep_enabled=False, default):
  Sonnet streams response directly to chat.
  <delegate> blocks → EventBus → DeepWorkerPool (silent execution, task WS events only).

Mode Deep (deep_enabled=True):
  Opus streams response directly to chat (Fast layer skipped).
  <delegate> blocks → EventBus → DeepWorkerPool (same delegate flow).

Key constraint: Fast and Deep are MUTUALLY EXCLUSIVE for chat output.
Only one model streams to chat per message — never two simultaneous responses.

Analyzer (background, both modes): Detects actionable items → card suggestions.

Event Bus Architecture:
  Chat response (Fast or Deep) emits ActionIntent events (parsed from <delegate> blocks).
  Deep workers listen on the per-session bus and execute actions in background.
  Frontend receives task:started → task:progress → task:completed via WebSocket.
"""

import asyncio
import json
import logging
import re
import time
from uuid import uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.services.claude_service import ClaudeService
from app.services.analyzer_service import AnalyzerService
from app.services.session_store import session_store
from app.services.event_bus import ActionIntent, SessionEventBus, event_bus_registry
from app.services.pending_results import pending_store
from app.services.worker_session_store import get_worker_session_store
from app.services.direct_executor import DirectExecutor, READ_ACTIONS
from app.services.worker_supervisor import get_worker_supervisor
from app.tools.response_parser import ToolResponseParser, TOOL_CALL_PATTERN
from app.tools.executor import get_executor
from app.services.orchestration.worker_pool import DeepWorkerPool, LIGHTWEIGHT_INTENTS, is_lightweight_intent, _format_result_for_card
from app.services.orchestration.layer_runners import LayerRunnersMixin
from app.services.orchestration.session_timeline import get_timeline

logger = logging.getLogger("voxyflow.orchestration")

# _format_result_for_card, DeepWorkerPool → app.services.orchestration.worker_pool
# _run_fast_layer, _run_deep_chat_layer, _run_analyzer_layer → app.services.orchestration.layer_runners


class ChatOrchestrator(LayerRunnersMixin):
    """Orchestrates the 3-layer AI chat pipeline over a WebSocket connection.

    This class owns the *flow* — which layers to call, how to combine results,
    and what WebSocket events to emit.  The actual AI calls are delegated to
    ClaudeService and AnalyzerService.

    Event Bus: After the Fast layer streams, any <delegate> blocks are parsed
    and emitted onto the session's event bus. Deep workers pick them up and
    execute them asynchronously.
    """

    def __init__(
        self,
        claude_service: ClaudeService,
        analyzer_service: AnalyzerService,
    ):
        self._claude = claude_service
        self._analyzer = analyzer_service
        self._worker_pools: dict[str, DeepWorkerPool] = {}
        # Pending confirmations for destructive direct actions (taskId → delegate data)
        self._pending_confirms: dict[str, dict] = {}
        # Per-chat lock to serialize user messages and worker callbacks
        self._chat_locks: dict[str, asyncio.Lock] = {}

    MAX_CALLBACK_DEPTH = 2  # Prevent infinite dispatcher↔worker re-trigger loops

    def _get_chat_lock(self, chat_id: str) -> asyncio.Lock:
        """Get or create a per-chat asyncio.Lock to serialize responses."""
        if chat_id not in self._chat_locks:
            self._chat_locks[chat_id] = asyncio.Lock()
        return self._chat_locks[chat_id]

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def handle_message(
        self,
        websocket: WebSocket | None,
        content: str,
        message_id: str,
        chat_id: str,
        project_id: str | None,
        layers: dict[str, bool] | None = None,
        chat_level: str = "general",
        is_callback: bool = False,
        callback_depth: int = 0,
        card_id: str | None = None,
        session_id: str | None = None,
    ) -> list[asyncio.Task]:
        """Full 3-layer orchestration for a single user message.

        Returns a list of background asyncio.Task objects created during this
        invocation so the caller can cancel them on disconnect (Fix 3).

        Uses a per-chat lock to prevent race conditions between user messages
        and worker callbacks generating simultaneous responses.
        """
        async with self._get_chat_lock(chat_id):
            return await self._handle_message_inner(
                websocket=websocket, content=content, message_id=message_id,
                chat_id=chat_id, project_id=project_id, layers=layers,
                chat_level=chat_level, is_callback=is_callback,
                callback_depth=callback_depth, card_id=card_id, session_id=session_id,
            )

    async def _handle_message_inner(
        self,
        websocket: WebSocket | None,
        content: str,
        message_id: str,
        chat_id: str,
        project_id: str | None,
        layers: dict[str, bool] | None = None,
        chat_level: str = "general",
        is_callback: bool = False,
        callback_depth: int = 0,
        card_id: str | None = None,
        session_id: str | None = None,
    ) -> list[asyncio.Task]:
        """Inner implementation of handle_message (called under per-chat lock)."""
        _bg_tasks: list[asyncio.Task] = []

        # Resolve project/card context from the database
        project_context, card_context, project_names = await self._resolve_context(
            project_id=project_id,
            card_id=card_id,
            chat_level=chat_level,
        )

        project_name = project_context.get("title") if project_context else None

        # Resolve layer toggles
        # deep_enabled=False (default): Fast streams to chat, Deep only for delegate workers
        # deep_enabled=True: Deep streams to chat directly, Fast is skipped
        if layers is None:
            layers = {}
        deep_enabled = layers.get("deep", layers.get("opus", False))
        # Global gate: backend setting is the single source of truth.
        # The frontend layers['analyzer'] key is intentionally ignored — it can be
        # absent or stale from old localStorage, which would silently disable the
        # analyzer even when the backend setting is ON.
        from app.routes.settings import get_analyzer_enabled
        analyzer_enabled = get_analyzer_enabled()

        # Helper to send model status updates
        async def send_model_status(model: str, state: str) -> None:
            await websocket.send_json({
                "type": "model:status",
                "payload": {"model": model, "state": state, "sessionId": session_id},
                "timestamp": int(time.time() * 1000),
            })

        # Launch Analyzer in background (both modes)
        # Skip analyzer for callbacks — worker results don't need card suggestions
        analyzer_task = None
        if analyzer_enabled and not is_callback:
            await send_model_status("analyzer", "thinking")
            analyzer_task = asyncio.create_task(
                self._analyzer.analyze_for_cards(
                    chat_id=chat_id, message=content, project_context=""
                )
            )
            _bg_tasks.append(analyzer_task)

        # Build active workers context for dispatcher awareness
        active_workers_context = self.get_active_workers_context(session_id)

        # --- Chat response: Fast XOR Deep (mutually exclusive) ---
        if deep_enabled:
            # Mode Deep: Opus streams directly to chat
            chat_success = await self._run_deep_chat_layer(
                websocket=websocket,
                content=content,
                message_id=message_id,
                chat_id=chat_id,
                project_name=project_name,
                project_id=project_id,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_names=project_names,
                session_id=session_id,
                send_model_status=send_model_status,
                active_workers_context=active_workers_context,
            )
        else:
            # Mode Fast (default): Sonnet streams to chat
            chat_success = await self._run_fast_layer(
                websocket=websocket,
                content=content,
                message_id=message_id,
                chat_id=chat_id,
                project_name=project_name,
                project_id=project_id,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_names=project_names,
                session_id=session_id,
                send_model_status=send_model_status,
                active_workers_context=active_workers_context,
                is_callback=is_callback,
            )

        if not chat_success:
            if analyzer_task:
                analyzer_task.cancel()
            return _bg_tasks

        # --- Parse delegates and emit to event bus (BACKGROUND — non-blocking) ---
        if session_id and callback_depth < self.MAX_CALLBACK_DEPTH:
            # Check for native tool_use delegates FIRST (collected by claude_service)
            native_delegates = self._claude.pop_pending_delegates(chat_id)

            # Workers spawned from a callback response carry incremented depth
            child_callback_depth = callback_depth + 1 if is_callback else callback_depth

            if native_delegates:
                # Native path: structured delegate_action tool_use blocks
                logger.info(f"[Orchestrator] Native delegate path: {len(native_delegates)} delegate(s) from tool_use")
                _t = asyncio.create_task(
                    self._emit_native_delegates_safe(
                        delegates=native_delegates,
                        session_id=session_id,
                        websocket=websocket,
                        project_name=project_name,
                        chat_level=chat_level,
                        project_context=project_context,
                        card_context=card_context,
                        project_id=project_id,
                        chat_id=chat_id,
                        callback_depth=child_callback_depth,
                    )
                )
                _bg_tasks.append(_t)
            else:
                # Fallback: parse <delegate> XML blocks from text response
                chat_response = ""
                history = self._claude.get_history(chat_id)
                for msg in reversed(history):
                    if msg.get("role") == "assistant":
                        chat_response = msg.get("content", "")
                        break

                if chat_response:
                    _t = asyncio.create_task(
                        self._parse_and_emit_delegates_safe(
                            fast_response=chat_response,
                            session_id=session_id,
                            websocket=websocket,
                            project_name=project_name,
                            chat_level=chat_level,
                            project_context=project_context,
                            card_context=card_context,
                            project_id=project_id,
                            chat_id=chat_id,
                            callback_depth=child_callback_depth,
                        )
                    )
                    _bg_tasks.append(_t)

        # --- Layer 3: Analyzer card suggestions (BACKGROUND — non-blocking) ---
        if analyzer_enabled and analyzer_task is not None:
            _t = asyncio.create_task(
                self._run_analyzer_layer_safe(
                    websocket=websocket,
                    analyzer_task=analyzer_task,
                    project_id=project_id,
                    session_id=session_id,
                    send_model_status=send_model_status,
                )
            )
            _bg_tasks.append(_t)

        # --- Memory auto-extraction (BACKGROUND — non-blocking) ---
        # Skip for callbacks — worker results aren't user conversation
        if not is_callback:
            _t = asyncio.create_task(
                self._auto_extract_memories_safe(
                    chat_id=chat_id,
                    user_message=content,
                    project_name=project_name,
                    project_id=project_id,
                )
            )
            _bg_tasks.append(_t)

        # handle_message returns HERE — WS handler is free for next message
        logger.debug("[Orchestrator] handle_message returning (delegates + analyzer in background)")
        return _bg_tasks

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def reset_session(self, chat_id: str, session_id: str | None = None) -> None:
        """Clear conversation history, kill persistent CLI process, and clean up EventBus."""
        if chat_id in self._claude._histories:
            self._claude._histories[chat_id] = []
        session_store.clear_session(chat_id)
        # Kill persistent chat subprocess if alive
        if self._claude._cli_backend:
            asyncio.create_task(self._claude._cli_backend.kill_persistent_chat(chat_id))
        # Clean up per-session EventBus to prevent accumulation
        cleanup_id = session_id or chat_id
        event_bus_registry.remove(cleanup_id)

    # ------------------------------------------------------------------
    # Active Workers Context (for dispatcher system prompt injection)
    # ------------------------------------------------------------------

    def get_active_workers_context(self, session_id: str | None) -> str:
        """Build a text block describing active/recently-completed workers
        plus the session timeline.

        Injected into the dispatcher's system prompt so it knows what's
        running in the background and what happened so far.
        """
        if not session_id:
            return ""

        parts: list[str] = []

        # Session timeline — chronological ledger of all actions
        timeline_text = get_timeline().format(session_id)
        if timeline_text:
            parts.append("[Session Timeline]\n" + timeline_text)

        # Live worker status
        pool = self._worker_pools.get(session_id)
        if pool:
            info = pool.get_active_tasks()
            active = info["active"]
            completed = info["completed"]

            if active:
                lines = ["[Active Workers]"]
                for t in active:
                    desc = f' — "{t["description"]}"' if t["description"] else ""
                    tool_info = ""
                    if t.get("last_tool"):
                        tool_info = f" — last tool: {t['last_tool']} ({t['tool_count']} calls)"
                    lines.append(
                        f"- task-{t['task_id']}: {t['action']} ({t['model']}) "
                        f"— running {t['running_seconds']}s{desc}{tool_info}"
                    )
                parts.append("\n".join(lines))

            if completed:
                lines = ["[Recently Completed]"]
                for t in completed:
                    status = "done" if t.get("success", True) else "FAILED"
                    lines.append(
                        f"- task-{t['task_id']}: {t['action']} ({t['model']}) "
                        f"— {status} {t['seconds_ago']}s ago — {t['result']}"
                    )
                parts.append("\n".join(lines))

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Event Bus: Worker pool lifecycle
    # ------------------------------------------------------------------

    def start_worker_pool(self, session_id: str, websocket: WebSocket | None) -> DeepWorkerPool:
        """Create and start a DeepWorkerPool for a session.

        If a pool already exists for this session_id (e.g. browser reconnect),
        update its WebSocket reference instead of stopping it — workers must
        survive a page refresh.
        """
        # --- Orphan cleanup: stop pools whose WS is dead and belong to a different session ---
        orphan_ids: list[str] = []
        for sid, pool in self._worker_pools.items():
            if sid == session_id:
                continue  # current session — handled below
            if pool._stopped:
                orphan_ids.append(sid)
                continue
            ws = pool._ws
            # Background pools (ws=None) are not orphans — they're intentionally headless.
            # Only real WebSocket connections that have gone dead are orphans.
            if ws is not None and getattr(ws, "client_state", WebSocketState.CONNECTED) != WebSocketState.CONNECTED:
                orphan_ids.append(sid)

        for orphan_sid in orphan_ids:
            logger.info(f"[ChatOrchestrator] Cleaning up orphan worker pool: {orphan_sid}")
            orphan_pool = self._worker_pools.pop(orphan_sid, None)
            if orphan_pool and not orphan_pool._stopped:
                asyncio.create_task(orphan_pool.stop())
            event_bus_registry.remove(orphan_sid)

        existing = self._worker_pools.get(session_id)
        if existing and not existing._stopped:
            # Pool is alive: update the WebSocket so in-flight workers
            # can deliver results to the new connection.
            existing.update_websocket(websocket)

            # If the event bus was cleaned up (idle timeout), the listener
            # is dead. Reconnect the pool to a fresh bus and restart it.
            bus = event_bus_registry.get_or_create(session_id)
            listener_dead = (
                existing._listener_task is None
                or existing._listener_task.done()
            )
            if listener_dead or existing._bus is not bus:
                existing._bus = bus
                existing._listener_task = asyncio.create_task(existing._listen_loop())
                logger.info(f"[ChatOrchestrator] Revived listener for pool {session_id} (bus was recycled)")
            else:
                logger.info(f"[ChatOrchestrator] Reused existing pool for {session_id}, updated WS")
            return existing

        # No existing pool (or stopped): create a fresh one.
        if existing:
            self._worker_pools.pop(session_id, None)

        bus = event_bus_registry.get_or_create(session_id)
        pool = DeepWorkerPool(self._claude, bus, websocket, orchestrator=self)
        pool.start()
        self._worker_pools[session_id] = pool
        return pool

    async def stop_worker_pool(self, session_id: str) -> None:
        """Stop and cleanup a session's worker pool."""
        pool = self._worker_pools.pop(session_id, None)
        if pool:
            await pool.stop()
        event_bus_registry.remove(session_id)

    def update_pool_websocket(self, session_id: str, websocket: WebSocket) -> None:
        """Update the WebSocket reference on a surviving pool after reconnect.

        Called from session:sync so in-flight workers can deliver results
        to the newly connected client immediately.
        """
        pool = self._worker_pools.get(session_id)
        if pool and not pool._stopped:
            pool.update_websocket(websocket)
            logger.info(f"[ChatOrchestrator] WS updated for surviving pool {session_id}")

    async def cancel_worker_task(self, session_id: str, task_id: str) -> bool:
        """Cancel a specific worker task in a session's pool."""
        pool = self._worker_pools.get(session_id)
        if not pool:
            logger.warning(f"[ChatOrchestrator] cancel_worker_task: no pool for session {session_id}")
            return False
        return await pool.cancel_task(task_id)

    async def cancel_worker_task_global(self, task_id: str) -> bool:
        """Cancel a worker task searching across all active pools."""
        for sid, pool in self._worker_pools.items():
            if task_id in pool._active_tasks:
                result = await pool.cancel_task(task_id)
                logger.info(
                    f"[ChatOrchestrator] cancel_worker_task_global: found task {task_id} "
                    f"in pool {sid}, cancelled={result}"
                )
                return result
        logger.warning(f"[ChatOrchestrator] cancel_worker_task_global: task {task_id} not found in any pool")
        return False

    def peek_worker_task(self, task_id: str) -> dict | None:
        """Return peek data for a worker task, searching across all active pools."""
        for pool in self._worker_pools.values():
            result = pool.peek(task_id)
            if result is not None:
                return result
        return None

    async def steer_worker_task(self, session_id: str, task_id: str, message: str) -> bool:
        """Inject a steering message into a running worker task.

        Finds the worker pool for the session and forwards the message to the
        target task's message queue.  If the task is using the steerable CLI
        path, the message is forwarded to the subprocess stdin in real time.

        Returns True if the message was queued, False if the session or task
        was not found.
        """
        pool = self._worker_pools.get(session_id)
        if not pool:
            # Try to find task across all pools (dispatcher may not know exact session)
            for sid, p in self._worker_pools.items():
                if task_id in p._active_tasks:
                    result = await p.steer_task(task_id, message)
                    logger.info(
                        f"[ChatOrchestrator] steer_worker_task: found task {task_id} "
                        f"in pool {sid}, queued={result}"
                    )
                    return result
            logger.warning(f"[ChatOrchestrator] steer_worker_task: no pool for session {session_id}")
            return False
        return await pool.steer_task(task_id, message)

    # ------------------------------------------------------------------
    # Background-safe wrappers (fire-and-forget with error handling)
    # ------------------------------------------------------------------

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

    async def _run_analyzer_layer_safe(
        self,
        websocket: WebSocket,
        analyzer_task: asyncio.Task,
        project_id: str | None,
        session_id: str | None,
        send_model_status,
    ) -> None:
        """Wrapper for analyzer that catches errors in background.

        Note: this method is only called when analyzer_enabled=True has already
        been verified by the caller (see _handle_message_inner). The
        analyzer_enabled=True passed here is therefore always correct.
        """
        try:
            await self._run_analyzer_layer(
                websocket=websocket,
                analyzer_enabled=True,  # Verified by caller before scheduling this task
                analyzer_task=analyzer_task,
                project_id=project_id,
                session_id=session_id,
                send_model_status=send_model_status,
            )
        except Exception as e:
            logger.error(f"[Orchestrator] Background analyzer failed: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Deduplication helper (shared by native + XML paths)
    # ------------------------------------------------------------------

    @staticmethod
    def _dedup_delegates(
        worker_delegates: list[dict],
        pool,
    ) -> list[dict]:
        """Deduplicate delegates against active/completed workers.

        Uses (action, description_prefix) tuples instead of just the action
        name so that two unrelated ``run_command`` delegates are not falsely
        deduped.
        """
        if not pool:
            return worker_delegates

        existing = pool.get_active_tasks()

        def _key(action: str, desc: str) -> tuple[str, str]:
            return (action.lower(), desc.lower()[:200].strip())

        active_keys = {
            _key(t["action"], t.get("description", ""))
            for t in existing.get("active", [])
        }
        completed_keys = {
            _key(t["action"], t.get("description", ""))
            for t in existing.get("completed", [])
            if t.get("success", True)
        }
        already = active_keys | completed_keys

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
                model = data.get("model") or "sonnet"
                if model not in ("haiku", "sonnet", "opus"):
                    model = "sonnet"

                # Card-level model override (preferred_model set in card modal)
                card_preferred = card_context.get("preferred_model") if card_context else None
                if card_preferred and card_preferred in ("haiku", "sonnet", "opus"):
                    logger.info(f"[ModelOverride] Card preferred_model={card_preferred} (was {model})")
                    model = card_preferred

                # Auto-upgrade model for coding tasks
                _CODING_KEYWORDS = {"fix", "implement", "refactor", "write", "code", "debug", "build", "create function", "add feature", "patch"}
                description_lower = (data.get("description") or "").lower()
                if any(kw in description_lower for kw in _CODING_KEYWORDS):
                    if model == "haiku":
                        original_model = model
                        model = "sonnet"
                        logger.info(f"[ModelUpgrade] Upgraded {original_model} → sonnet (coding task detected: {intent})")

                # Haiku is restricted to the lightweight-intent bucket (enrich /
                # summarize / research / review). For any other intent, upgrade to
                # sonnet — Haiku is not reliable enough to pick the right MCP tool
                # and would end up writing files named after shell commands
                # (see GitHub issue #4).
                if model == "haiku" and intent.lower() not in LIGHTWEIGHT_INTENTS:
                    logger.info(f"[ModelUpgrade] Upgraded haiku → sonnet (intent '{intent}' not in LIGHTWEIGHT_INTENTS)")
                    model = "sonnet"

                task_id = f"task-{uuid4().hex[:8]}"

                # Classify intent type based on the task, not the model
                if complexity == "complex" or model == "opus":
                    intent_type = "complex"
                elif intent in ("create_card", "move_card", "update_card"):
                    intent_type = "crud_simple"
                else:
                    intent_type = "complex"

                card_id = card_context.get("id") if card_context else None

                event = ActionIntent(
                    task_id=task_id,
                    intent_type=intent_type,
                    intent=intent,
                    summary=summary,
                    data={
                        "project_name": project_name,
                        "chat_level": chat_level,
                        "project_context": project_context,
                        "card_context": card_context,
                        "card_id": card_id,
                        "dispatcher_chat_id": chat_id,
                        **data,  # Include all fields from delegate_action
                        # Fallback chain: delegate.data['project_id'] → session project_id → None
                        "project_id": data.get("project_id") or project_id,
                    },
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

                    # Extract model from delegate JSON (haiku/sonnet/opus)
                    model = data.get("model") or "sonnet"
                    if model not in ("haiku", "sonnet", "opus"):
                        model = "sonnet"

                    # Card-level model override
                    card_preferred = card_context.get("preferred_model") if card_context else None
                    if card_preferred and card_preferred in ("haiku", "sonnet", "opus"):
                        logger.info(f"[ModelOverride] Card preferred_model={card_preferred} (was {model})")
                        model = card_preferred

                    # Auto-upgrade model for coding tasks (XML path)
                    _CODING_KEYWORDS = {"fix", "implement", "refactor", "write", "code", "debug", "build", "create function", "add feature", "patch"}
                    description_lower = (data.get("description") or "").lower()
                    if any(kw in description_lower for kw in _CODING_KEYWORDS):
                        if model == "haiku":
                            original_model = model
                            model = "sonnet"
                            logger.info(f"[ModelUpgrade] Upgraded {original_model} → sonnet (coding task detected: {intent})")

                    # Haiku restricted to lightweight intents — see native path
                    # above for rationale (GitHub issue #4).
                    if model == "haiku" and intent.lower() not in LIGHTWEIGHT_INTENTS:
                        logger.info(f"[ModelUpgrade] Upgraded haiku → sonnet (intent '{intent}' not in LIGHTWEIGHT_INTENTS)")
                        model = "sonnet"

                    task_id = f"task-{uuid4().hex[:8]}"

                    # Classify intent type based on the task, not the model
                    if complexity == "complex" or model == "opus":
                        intent_type = "complex"
                    elif intent in ("create_card", "move_card", "update_card"):
                        intent_type = "crud_simple"
                    else:
                        intent_type = "complex"

                    # Extract card_id from card_context for direct access
                    card_id = card_context.get("id") if card_context else None

                    event = ActionIntent(
                        task_id=task_id,
                        intent_type=intent_type,
                        intent=intent,
                        summary=summary,
                        data={
                            "project_name": project_name,
                            "chat_level": chat_level,
                            "project_context": project_context,
                            "card_context": card_context,
                            "card_id": card_id,
                            "dispatcher_chat_id": chat_id,
                            **data,  # Include original delegate data
                            # Fallback chain: delegate.data['project_id'] → session project_id → None
                            "project_id": data.get("project_id") or project_id,
                        },
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
            self._pending_confirms[task_id] = {
                "data": data,
                "project_id": project_id,
                "session_id": session_id,
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
                        await websocket.send_json({
                            "type": "chat:response",
                            "payload": {
                                "messageId": msg_id,
                                "content": confirmation_msg,
                                "model": "system",
                                "streaming": False,
                                "done": True,
                                "sessionId": session_id,
                            },
                            "timestamp": int(time.time() * 1000),
                        })
                    except Exception as e:
                        logger.debug("WS send/broadcast failed (WS likely closed): %s", e)
        elif confirmation_msg:
            # --- WRITE actions: just send chat confirmation (no re-trigger) ---
            msg_id = f"direct-msg-{uuid4().hex[:8]}"
            try:
                await websocket.send_json({
                    "type": "chat:response",
                    "payload": {
                        "messageId": msg_id,
                        "content": confirmation_msg,
                        "model": "system",
                        "streaming": False,
                        "done": True,
                        "sessionId": session_id,
                    },
                    "timestamp": int(time.time() * 1000),
                })
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
                await websocket.send_json({
                    "type": "chat:response",
                    "payload": {
                        "messageId": f"direct-msg-{uuid4().hex[:8]}",
                        "content": confirmation_msg,
                        "model": "system",
                        "streaming": False,
                        "done": True,
                        "sessionId": session_id,
                    },
                    "timestamp": int(time.time() * 1000),
                })
            except Exception as e:
                logger.debug("WS send/broadcast failed (WS likely closed): %s", e)
    # ------------------------------------------------------------------
    # Internal: Context resolution
    # ------------------------------------------------------------------

    async def _resolve_context(
        self,
        project_id: str | None,
        card_id: str | None,
        chat_level: str,
    ) -> tuple[dict | None, dict | None, list[str]]:
        """Resolve project context, card context, and project name list from the database.

        Returns (project_context, card_context, project_names).
        """
        project_context = None
        card_context = None
        project_names: list[str] = []

        if project_id:
            try:
                from app.database import async_session, Project, Card
                from sqlalchemy import select
                async with async_session() as db:
                    result = await db.execute(select(Project).where(Project.id == project_id))
                    proj = result.scalar_one_or_none()
                    if proj:
                        # Fetch non-archived cards for this project (for dynamic state counts)
                        cards_result = await db.execute(
                            select(Card).where(
                                Card.project_id == project_id,
                                Card.archived_at.is_(None),
                            )
                        )
                        proj_cards = cards_result.scalars().all()
                        cards_list = [
                            {
                                "title": c.title,
                                "status": c.status or "card",
                                "updated_at": str(c.updated_at) if hasattr(c, "updated_at") and c.updated_at else "",
                            }
                            for c in proj_cards
                        ]

                        project_context = {
                            "id": proj.id,
                            "title": proj.title,
                            "description": proj.description or "",
                            "tech_stack": getattr(proj, "tech_stack", "") or "",
                            "github_url": proj.github_url or "",
                            "cards": cards_list,
                        }

                    if card_id:
                        result = await db.execute(select(Card).where(Card.id == card_id))
                        c = result.scalar_one_or_none()
                        if c:
                            from app.database import ChecklistItem
                            cl_result = await db.execute(
                                select(ChecklistItem).where(ChecklistItem.card_id == card_id)
                            )
                            checklist_items = cl_result.scalars().all()
                            card_context = {
                                "id": c.id,
                                "title": c.title,
                                "description": c.description or "",
                                "status": c.status or "card",
                                "priority": str(c.priority) if c.priority is not None else "medium",
                                "agent_type": getattr(c, "agent_type", None) or "general",
                                "assignee": getattr(c, "assignee", None),
                                "preferred_model": getattr(c, "preferred_model", None),
                                "checklist_items": [
                                    {"done": getattr(item, "done", False) or getattr(item, "completed", False)}
                                    for item in checklist_items
                                ],
                            }
            except Exception as e:
                logger.warning(f"Failed to resolve project/card context: {e}")

        # For general/main chat: fetch all project names for the Chat Init block
        if chat_level == "general" or not project_id:
            try:
                from app.database import async_session, Project
                from sqlalchemy import select
                async with async_session() as db:
                    all_proj_result = await db.execute(
                        select(Project.title).where(Project.status != "archived")
                    )
                    project_names = [row[0] for row in all_proj_result.fetchall()]
            except Exception as e:
                logger.warning(f"Failed to fetch project names for main chat init: {e}")

        return project_context, card_context, project_names

    # ------------------------------------------------------------------
    # Internal: <tool_call> text fallback — parse, execute, follow-up
    # ------------------------------------------------------------------

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
        _dynamic_ctx = self._claude.personality.build_dynamic_context_block(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            project_names=project_names,
            memory_context=memory_context,
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

