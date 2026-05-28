"""Chat Orchestration Service — Multi-Model Chat Pipeline.

Extracted from main.py to separate WebSocket transport from orchestration logic.

Mode Fast (deep_enabled=False, default):
  Sonnet streams response directly to chat.
  voxyflow.delegate tool_use → EventBus → DeepWorkerPool (silent execution, task WS events only).

Mode Deep (deep_enabled=True):
  Opus streams response directly to chat (Fast layer skipped).
  voxyflow.delegate tool_use → EventBus → DeepWorkerPool (same delegate flow).

Key constraint: Fast and Deep are MUTUALLY EXCLUSIVE for chat output.
Only one model streams to chat per message — never two simultaneous responses.

Event Bus Architecture:
  Chat response (Fast or Deep) emits ActionIntent events via the voxyflow.delegate MCP tool.
  Deep workers listen on the per-session bus and execute actions in background.
  Frontend receives task:started → task:progress → task:completed via WebSocket.
"""

import asyncio
import json
import logging
import threading
import time
from collections import OrderedDict
from uuid import uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.services.claude_service import ClaudeService
from app.services.direct_executor import DirectExecutor, READ_ACTIONS
from app.services.session_store import session_store
from app.services.event_bus import ActionIntent, event_bus_registry
from app.services.pending_results import pending_store
from app.services.worker_session_store import get_worker_session_store
from app.services.worker_supervisor import get_worker_supervisor
from app.services.orchestration.worker_pool import DeepWorkerPool, LIGHTWEIGHT_INTENTS, is_lightweight_intent, _format_result_for_card
from app.services.orchestration.layer_runners import LayerRunnersMixin
from app.services.orchestration.delegate_dispatch import DelegateDispatchMixin
from app.services.orchestration.tool_call_fallback import ToolCallFallbackMixin
from app.services.orchestration.session_timeline import get_timeline

logger = logging.getLogger("voxyflow.orchestration")

# _format_result_for_card, DeepWorkerPool → app.services.orchestration.worker_pool
# _run_fast_layer, _run_deep_chat_layer → app.services.orchestration.layer_runners


class ChatOrchestrator(LayerRunnersMixin, DelegateDispatchMixin, ToolCallFallbackMixin):
    """Orchestrates the multi-layer AI chat pipeline over a WebSocket connection.

    This class owns the *flow* — which layers to call, how to combine results,
    and what WebSocket events to emit.  The actual AI calls are delegated to
    ClaudeService.

    Event Bus: After the Fast layer streams, native voxyflow.delegate tool_use
    blocks are emitted onto the session's event bus. Deep workers pick them up
    and execute them asynchronously.
    """

    def __init__(
        self,
        claude_service: ClaudeService,
    ):
        self._claude = claude_service
        self._worker_pools: dict[str, DeepWorkerPool] = {}
        # Pending confirmations for destructive direct actions (taskId → delegate data)
        self._pending_confirms: dict[str, dict] = {}
        self._pending_confirms_lock = threading.Lock()
        # Per-chat lock to serialize user messages and worker callbacks.
        # Bounded LRU — oldest idle chats get evicted once we're over the cap so
        # long-lived servers don't grow this dict without bound.
        self._chat_locks: "OrderedDict[str, asyncio.Lock]" = OrderedDict()

    MAX_CALLBACK_DEPTH = 5  # Prevent infinite dispatcher↔worker re-trigger loops
    _CHAT_LOCKS_CAP = 512  # evict oldest unlocked entries past this

    def _get_chat_lock(self, chat_id: str) -> asyncio.Lock:
        """Get or create a per-chat asyncio.Lock to serialize responses."""
        lock = self._chat_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._chat_locks[chat_id] = lock
            # Evict oldest *unlocked* entries if we're over cap. Never evict a
            # locked entry — that would create a second lock for the same chat.
            while len(self._chat_locks) > self._CHAT_LOCKS_CAP:
                oldest_id, oldest_lock = next(iter(self._chat_locks.items()))
                if oldest_lock.locked():
                    break
                self._chat_locks.pop(oldest_id, None)
        else:
            self._chat_locks.move_to_end(chat_id)
        return lock

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def handle_message(
        self,
        websocket: WebSocket | None,
        content: str,
        message_id: str,
        chat_id: str,
        workspace_id: str | None,
        layers: dict[str, bool] | None = None,
        chat_level: str = "general",
        is_callback: bool = False,
        callback_depth: int = 0,
        card_id: str | None = None,
        session_id: str | None = None,
        role: str = "dispatcher",
        autonomy_directive_path: str = "",
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
                chat_id=chat_id, workspace_id=workspace_id, layers=layers,
                chat_level=chat_level, is_callback=is_callback,
                callback_depth=callback_depth, card_id=card_id, session_id=session_id,
                role=role, autonomy_directive_path=autonomy_directive_path,
            )

    async def _handle_message_inner(
        self,
        websocket: WebSocket | None,
        content: str,
        message_id: str,
        chat_id: str,
        workspace_id: str | None,
        layers: dict[str, bool] | None = None,
        chat_level: str = "general",
        is_callback: bool = False,
        callback_depth: int = 0,
        card_id: str | None = None,
        session_id: str | None = None,
        role: str = "dispatcher",
        autonomy_directive_path: str = "",
    ) -> list[asyncio.Task]:
        """Inner implementation of handle_message (called under per-chat lock)."""
        _bg_tasks: list[asyncio.Task] = []

        # Resolve workspace/card context from the database
        project_context, card_context, project_names = await self._resolve_context(
            workspace_id=workspace_id,
            card_id=card_id,
            chat_level=chat_level,
        )

        workspace_name = project_context.get("title") if project_context else None

        # Resolve layer toggles
        # deep_enabled=False (default): Fast streams to chat, Deep only for delegate workers
        # deep_enabled=True: Deep streams to chat directly, Fast is skipped
        if layers is None:
            layers = {}
        deep_enabled = layers.get("deep", layers.get("opus", False))

        # Helper to send model status updates
        async def send_model_status(model: str, state: str) -> None:
            await websocket.send_json({
                "type": "model:status",
                "payload": {"model": model, "state": state, "sessionId": session_id},
                "timestamp": int(time.time() * 1000),
            })

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
                workspace_name=workspace_name,
                workspace_id=workspace_id,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_names=project_names,
                session_id=session_id,
                send_model_status=send_model_status,
                active_workers_context=active_workers_context,
                is_callback=is_callback,
            )
        else:
            # Mode Fast (default): Sonnet streams to chat
            chat_success = await self._run_fast_layer(
                websocket=websocket,
                content=content,
                message_id=message_id,
                chat_id=chat_id,
                workspace_name=workspace_name,
                workspace_id=workspace_id,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_names=project_names,
                session_id=session_id,
                send_model_status=send_model_status,
                active_workers_context=active_workers_context,
                is_callback=is_callback,
                role=role,
                autonomy_directive_path=autonomy_directive_path,
            )

        if not chat_success:
            return _bg_tasks

        # --- Parse delegates and emit to event bus (BACKGROUND — non-blocking) ---
        if session_id and callback_depth < self.MAX_CALLBACK_DEPTH:
            # Check for native tool_use delegates FIRST (collected by claude_service)
            native_delegates = self._claude.pop_pending_delegates(chat_id)

            # Also check for delegates queued via the voxyflow.delegate MCP tool
            # (in-process / SSE mode): the MCP handler writes to ClaudeService._pending_delegates,
            # so they're already included above. For stdio mode, check the module-level store.
            try:
                from app.mcp_server import pop_mcp_pending_delegates
                mcp_delegates = pop_mcp_pending_delegates(chat_id)
                if mcp_delegates:
                    logger.info(f"[Orchestrator] MCP stdio delegates: {len(mcp_delegates)} delegate(s)")
                    native_delegates = native_delegates + mcp_delegates
            except Exception as _mcp_err:
                logger.debug(f"[Orchestrator] pop_mcp_pending_delegates failed (non-fatal): {_mcp_err}")

            # Workers spawned from a callback response carry incremented depth
            child_callback_depth = callback_depth + 1 if is_callback else callback_depth

            if native_delegates:
                # Native path: structured voxyflow.delegate tool_use blocks
                logger.info(f"[Orchestrator] Native delegate path: {len(native_delegates)} delegate(s) from tool_use")
                _t = asyncio.create_task(
                    self._emit_native_delegates_safe(
                        delegates=native_delegates,
                        session_id=session_id,
                        websocket=websocket,
                        workspace_name=workspace_name,
                        chat_level=chat_level,
                        project_context=project_context,
                        card_context=card_context,
                        workspace_id=workspace_id,
                        chat_id=chat_id,
                        callback_depth=child_callback_depth,
                    )
                )
                _bg_tasks.append(_t)

        # --- Memory auto-extraction (BACKGROUND — non-blocking) ---
        # Skip for callbacks and autonomy ticks — neither is user conversation.
        if not is_callback and role != "autonomy":
            _t = asyncio.create_task(
                self._auto_extract_memories_safe(
                    chat_id=chat_id,
                    user_message=content,
                    workspace_name=workspace_name,
                    workspace_id=workspace_id,
                )
            )
            _bg_tasks.append(_t)

        # handle_message returns HERE — WS handler is free for next message
        logger.debug("[Orchestrator] handle_message returning (delegates in background)")
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
        """Cancel a worker task searching across all active pools.

        Also checks the autonomy tick registry — autonomy heartbeats aren't
        real workers (no pool) but we register them in WorkerSessionStore and
        stream them through the same Worker Panel, so users expect the cancel
        button to stop them too.
        """
        # Autonomy ticks first — they share the cancel button path but live
        # outside worker pools.
        if task_id.startswith("autonomy-"):
            try:
                from app.services.job_runner import cancel_autonomy_task
                if await cancel_autonomy_task(task_id):
                    logger.info(
                        f"[ChatOrchestrator] cancel_worker_task_global: cancelled "
                        f"autonomy tick {task_id}"
                    )
                    return True
            except Exception as e:
                logger.warning(f"[ChatOrchestrator] autonomy cancel failed: {e}")

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
        workspace_name: str | None = None,
        workspace_id: str | None = None,
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
                workspace_id=workspace_id,
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
    ) -> tuple[list[dict], list[dict]]:
        """Deduplicate delegates against currently active workers.

        Two collision rules:
        - (action, description_prefix) — catches identical re-runs.
        - card_id — same card already has a worker in flight: refuse the
          parallel spawn entirely. Why: a dispatcher that re-runs an audit
          on the same card while the first one is still working creates
          ghost double-execution and wastes the user's CLI quota.

        Returns (deduped, skipped) so the caller can surface a notice to
        Voxy explaining which delegates were dropped and why.
        """
        if not pool:
            return worker_delegates, []

        existing = pool.get_active_tasks()
        active_tasks = existing.get("active", [])

        def _key(action: str, desc: str) -> tuple[str, str]:
            return (action.lower(), desc.lower()[:200].strip())

        already = {
            _key(t["action"], t.get("description", ""))
            for t in active_tasks
        }
        active_by_card: dict[str, dict] = {}
        for t in active_tasks:
            cid = t.get("card_id")
            if cid and cid not in active_by_card:
                active_by_card[cid] = t

        deduped: list[dict] = []
        skipped: list[dict] = []
        for data in worker_delegates:
            action = data.get("action") or data.get("intent") or "unknown"
            summary = data.get("summary") or data.get("description") or ""
            card_id = data.get("card_id")
            k = _key(action, summary)

            collision = None
            if k in already:
                collision = "duplicate_summary"
            elif card_id and card_id in active_by_card:
                collision = "card_busy"

            if collision:
                blocking = active_by_card.get(card_id) if card_id else None
                logger.warning(
                    f"[Orchestrator] Dedup ({collision}): skipping delegate "
                    f"'{action}' card_id={card_id} — "
                    f"blocking task={blocking.get('task_id') if blocking else None}"
                )
                skipped.append({
                    "action": action,
                    "summary": summary,
                    "card_id": card_id,
                    "reason": collision,
                    "blocking_task_id": blocking.get("task_id") if blocking else None,
                    "blocking_running_seconds": blocking.get("running_seconds") if blocking else None,
                })
            else:
                deduped.append(data)
                already.add(k)
                if card_id:
                    active_by_card.setdefault(card_id, {
                        "task_id": "(pending)",
                        "running_seconds": 0,
                    })

        if not deduped:
            logger.info("[Orchestrator] All delegates deduplicated — nothing to emit")
        return deduped, skipped

    # ------------------------------------------------------------------
    # Event Bus: Native delegate emission (tool_use path)
    # ------------------------------------------------------------------

    async def _emit_native_delegates(
        self,
        delegates: list[dict],
        session_id: str,
        websocket: "WebSocket",
        workspace_name: str | None = None,
        chat_level: str = "general",
        project_context: dict | None = None,
        card_context: dict | None = None,
        workspace_id: str | None = None,
        chat_id: str | None = None,
        callback_depth: int = 0,
    ) -> None:
        """Convert native voxyflow.delegate tool_use blocks to ActionIntent events.

        Input is already parsed JSON from Claude's tool_use (no regex needed).
        This is the only active delegate emission path since 2026-05-27.
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
                    workspace_id=workspace_id,
                    chat_id=chat_id,
                )
            else:
                worker_delegates.append(data)

        if not worker_delegates:
            return

        # Ensure worker pool is running (also updates WS on reconnect)
        self.start_worker_pool(session_id, websocket)

        # --- Deduplication ---
        worker_delegates, skipped = self._dedup_delegates(
            worker_delegates, self._worker_pools.get(session_id)
        )
        if skipped:
            await self._notify_delegates_skipped(
                websocket=websocket,
                session_id=session_id,
                chat_id=chat_id,
                skipped=skipped,
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
                # Keep None if delegate didn't specify a model — lets worker_pool apply
                # the worker class default. Only normalize when explicitly set.
                model = data.get("model") or None
                if model:
                    _lower_model = model.lower()
                    if "opus" in _lower_model:
                        model = "opus"
                    elif "haiku" in _lower_model:
                        model = "haiku"
                    elif "sonnet" in _lower_model:
                        model = "sonnet"
                    elif model not in ("haiku", "sonnet", "opus"):
                        model = None  # unrecognised → let worker class decide

                # Card-level model override (preferred_model set in card modal)
                # preferred_model is either a legacy name (haiku/sonnet/opus) or a worker class UUID
                card_preferred = card_context.get("preferred_model") if card_context else None
                _worker_class_id_override: str | None = None
                if card_preferred:
                    if card_preferred in ("haiku", "sonnet", "opus"):
                        logger.info(f"[ModelOverride] Card preferred_model={card_preferred} (was {model})")
                        model = card_preferred
                    else:
                        # Treat as worker class UUID — let worker_pool resolve it
                        _worker_class_id_override = card_preferred
                        logger.info(f"[ModelOverride] Card preferred_model is worker class id={card_preferred}")

                # Auto-upgrade model for coding tasks (skip if worker class override is set)
                _CODING_KEYWORDS = {"fix", "implement", "refactor", "write", "code", "debug", "build", "create function", "add feature", "patch"}
                description_lower = (data.get("description") or "").lower()
                if not _worker_class_id_override and any(kw in description_lower for kw in _CODING_KEYWORDS):
                    if model == "haiku":
                        original_model = model
                        model = "sonnet"
                        logger.info(f"[ModelUpgrade] Upgraded {original_model} → sonnet (coding task detected: {intent})")

                # Haiku is restricted to the lightweight-intent bucket (enrich /
                # summarize / research / review). For any other intent, upgrade to
                # sonnet — Haiku is not reliable enough to pick the right MCP tool
                # and would end up writing files named after shell commands
                # (see GitHub issue #4).
                if not _worker_class_id_override and model == "haiku" and intent.lower() not in LIGHTWEIGHT_INTENTS:
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

                event_data = {
                    "workspace_name": workspace_name,
                    "chat_level": chat_level,
                    "project_context": project_context,
                    "card_context": card_context,
                    "card_id": card_id,
                    "dispatcher_chat_id": chat_id,
                    **data,  # Include all fields from delegate_action
                    # Fallback chain: delegate.data['workspace_id'] → session workspace_id → None
                    "workspace_id": data.get("workspace_id") or workspace_id,
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
    # Fast-Path: Direct execution for whitelisted CRUD actions
    # ------------------------------------------------------------------

    async def _execute_direct_action(
        self,
        data: dict,
        websocket: "WebSocket",
        session_id: str,
        workspace_id: str | None = None,
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
                "workspace_id": workspace_id,
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
        result = await DirectExecutor.execute(data, workspace_id=workspace_id)

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
                    "workspaceId": workspace_id or "system-main",
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
                    workspace_id=workspace_id,
                    chat_level="workspace" if workspace_id else "general",
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
        elif action in ("workspace.list", "list_workspaces"):
            if isinstance(api_result, list):
                count = len(api_result)
                parts = ["Found {} workspace(s):".format(count)]
                for p in api_result[:10]:
                    t = p.get("title", "Untitled")
                    pid = p.get("id", "")
                    parts.append("- {} (id: {})".format(t, pid))
                return "\n".join(parts)
            return "workspace.list completed ({} ms)".format(duration)
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
        workspace_id = pending["workspace_id"]
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
        result = await DirectExecutor.execute(data, workspace_id=workspace_id)

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
                    "workspaceId": workspace_id or "system-main",
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
        workspace_id: str | None,
        card_id: str | None,
        chat_level: str,
    ) -> tuple[dict | None, dict | None, list[str]]:
        """Resolve workspace context and card context from the database.

        Returns (project_context, card_context, project_names).
        project_names is always an empty list — the dispatcher calls
        voxyflow.workspace.list on demand instead of receiving the full roll.
        """
        project_context = None
        card_context = None
        project_names: list[str] = []

        # #8 card_id inherit: if we have a card but no workspace_id, look up
        # the parent workspace so the card chat gets workspace-level context too
        # (board state, tech stack, github). Without this, Voxy in card chat
        # sees only the card and hallucinates the surrounding world.
        if card_id and not workspace_id:
            try:
                from app.database import async_session, Card
                from sqlalchemy import select
                async with async_session() as db:
                    r = await db.execute(select(Card.workspace_id).where(Card.id == card_id))
                    parent = r.scalar_one_or_none()
                    if parent:
                        workspace_id = parent
            except Exception as e:
                logger.warning(f"_resolve_context: card->workspace lookup failed: {e}")

        if workspace_id:
            try:
                from app.database import async_session, Workspace, Card
                from sqlalchemy import select
                async with async_session() as db:
                    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
                    proj = result.scalar_one_or_none()
                    if proj:
                        # Fetch non-archived cards for this workspace (for dynamic state counts)
                        cards_result = await db.execute(
                            select(Card).where(
                                Card.workspace_id == workspace_id,
                                Card.archived_at.is_(None),
                            )
                        )
                        proj_cards = cards_result.scalars().all()
                        cards_list = [
                            {
                                "title": c.title,
                                "status": c.status or "backlog",
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
                                "status": c.status or "backlog",
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
                logger.warning(f"Failed to resolve workspace/card context: {e}")

        return project_context, card_context, project_names

