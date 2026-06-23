"""DeepWorkerPool — async worker pool that consumes ActionIntent events from a SessionEventBus.

Extracted from chat_orchestration.py.

The pool keeps its lifecycle/queue machinery here; the per-task execution
phases live in sibling modules:

- ``intent_routing``       — lightweight-intent detection + direct fast-paths
- ``result_formatting``    — previews, card-facing rendering, short titles
- ``worker_model_routing`` — model / provider / effort resolution
- ``worker_runtime``       — execution prompt, tool callback, stall monitor
- ``worker_completion``    — result fallbacks, closeout, artifacts, publication
- ``worker_events``        — ambient worker-event buffer + debounced callbacks
- ``worker_cards``         — card lifecycle + worker-ledger DB helpers
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import TYPE_CHECKING

from fastapi import WebSocket

from app.services.claude_service import ClaudeService
from app.services.event_bus import ActionIntent, SessionEventBus
from app.services.pending_results import pending_store
from app.services.worker_session_store import get_worker_session_store
from app.services.worker_supervisor import get_worker_supervisor
from app.services.settings_loader import get_default_worker_model

from app.services.orchestration import worker_events as _worker_events
from app.services.orchestration.intent_routing import (  # noqa: F401  (re-exports)
    LIGHTWEIGHT_INTENTS,
    LIGHTWEIGHT_KEYWORDS,
    _READ_FILE_RE,
    is_lightweight_intent,
    try_direct_execution,
)
from app.services.orchestration.result_formatting import (  # noqa: F401  (re-exports)
    DISPATCHER_PREVIEW_CHARS,
    PREVIEW_CHARS,
    WS_RESULT_CHARS,
    _format_result_for_card,
    _make_short_title,
    _preview,
)
from app.services.orchestration.worker_cards import (
    _TRIVIAL_INTENTS,
    _auto_create_card,
    _ledger_insert,
    _ledger_update,
    _should_auto_create_card,
    _update_card_status,
)
from app.services.orchestration.worker_completion import (
    append_result_to_card,
    extract_follow_up,
    finalize_completion_artifacts,
    publish_completion,
    record_cancellation,
    record_failure,
    resolve_result_content,
)
from app.services.orchestration.worker_model_routing import (
    resolve_execution_plan,
    resolve_worker_class,
)
from app.services.orchestration.worker_runtime import (
    build_execution_prompt,
    make_tool_callback,
    resolve_chat_level,
    stall_monitor,
)

if TYPE_CHECKING:
    from app.services.chat_orchestration import ChatOrchestrator

logger = logging.getLogger("voxyflow.orchestration")


class DeepWorkerPool:
    """Pool of async workers that consume events from a SessionEventBus
    and execute them via the Deep layer (Opus) with full tool access.

    Each session gets its own pool. Max workers controls concurrency.
    """

    MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "15"))
    # No hard task timeout — stall detector handles idle workers (30min idle = cancel)

    COMPLETED_TASK_TTL = 300  # seconds to keep completed tasks visible (5 min)

    def __init__(
        self,
        claude_service: ClaudeService,
        bus: SessionEventBus,
        websocket: WebSocket | None,
        orchestrator: ChatOrchestrator | None = None,
    ):
        self._claude = claude_service
        self._bus = bus
        self._ws = websocket
        self._orchestrator = orchestrator
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._task_meta: dict[str, dict] = {}  # task_id → {action, model, description, started_at}
        self._completed_tasks: list[dict] = []  # [{task_id, action, model, completed_at, result}]
        self._listener_task: asyncio.Task | None = None
        self._cleanup_task: asyncio.Task | None = None
        # NOTE: this semaphore is PER-POOL (one pool per session/bus), so it caps
        # MAX_WORKERS concurrent workers *per session*, not globally. With N active
        # sessions the real ceiling is N * MAX_WORKERS workers. For CLI providers
        # this is bounded by the process-global CliRateGate (CLI_WORKER_CONCURRENT),
        # but non-CLI providers (anthropic/openai/ollama/...) have NO global cap and
        # can fan out to N * MAX_WORKERS concurrent API calls.
        # TODO(concurrency): add a module-level shared semaphore as a global cap for
        # non-CLI workers. Doing it correctly requires acquiring it *after* provider
        # resolution inside _execute_event (so CLI workers skip it) while releasing
        # in _on_task_done — splitting acquire/release across methods — so it is
        # deferred to a dedicated change rather than risking a leak/deadlock here.
        # Per-session worker cap. Source of truth is config.settings.max_workers
        # (which honors the MAX_WORKERS env var via pydantic-settings); fall back
        # to the class-level env read only if settings can't be loaded. Reading
        # it here — at pool creation, after startup loaded config — rather than
        # only the import-time class attribute keeps the max_workers config field
        # from being dead-wired.
        try:
            from app.config import get_settings
            self._max_workers = get_settings().max_workers
        except Exception:  # pragma: no cover - settings always load in practice
            self._max_workers = self.MAX_WORKERS
        self._semaphore = asyncio.Semaphore(self._max_workers)
        self._result_contents: dict[str, str] = {}  # task_id → actual result content
        self._task_tool_events: dict[str, list[dict]] = {}  # task_id → bounded tool event buffer
        self._MAX_TOOL_EVENTS = 50
        # Monotone tool-call counter, unbounded. The events buffer above is trimmed
        # to the last N for the dispatcher peek; this one reflects true lifetime count.
        self._task_tool_counts: dict[str, int] = {}
        self._task_message_queues: dict[str, asyncio.Queue] = {}  # task_id → steer queue
        # task_id → the worker's cancel_event. cancel_task()/stop() set it
        # BEFORE task.cancel() so the CLI backends' _watch_cancel watcher can
        # terminate the subprocess — a bare asyncio cancel orphans it.
        self._task_cancel_events: dict[str, asyncio.Event] = {}
        # Strong refs to fire-and-forget push-notification tasks — the loop
        # holds only weak refs, so a bare create_task can be GC'd mid-flight.
        self._bg_push_tasks: set[asyncio.Task] = set()
        # Ambient worker-event buffer keyed by dispatcher_chat_id. Each entry is
        # {task_id, intent, status, finished_at, summary_line}. Drained by the
        # dispatcher on the next user-triggered turn and rendered as a small
        # reference block — NOT a re-triggered conversation turn.
        self._worker_events: dict[str, deque] = {}
        self._MAX_WORKER_EVENTS_PER_CHAT = 20
        # Debounced dispatcher-callback scheduler: coalesces multiple worker
        # completions for the same dispatcher chat into ONE re-entry turn so
        # 10 parallel workers finishing don't produce 10 dispatcher turns.
        self._callback_debouncers: dict[str, asyncio.Task] = {}
        self._CALLBACK_DEBOUNCE_SECONDS = float(
            os.environ.get("DISPATCHER_CALLBACK_DEBOUNCE_SECONDS", "3.0")
        )
        self._stopped = False

    # Regex kept as a class attribute for backwards compatibility — the
    # implementation lives in intent_routing.
    _READ_FILE_RE = _READ_FILE_RE

    async def _try_direct_execution(self, event: ActionIntent) -> str | None:
        """Fast-path: execute trivial intents directly without spawning an LLM.

        Returns the result string if handled, or None to fall through to LLM workers.
        Currently handles: file read intents.
        """
        return await try_direct_execution(event)

    def start(self) -> None:
        """Start listening on the bus for events."""
        self._listener_task = asyncio.create_task(self._listen_loop())
        self._cleanup_task = asyncio.create_task(self._stale_cleanup_loop())
        logger.info(f"[DeepWorkerPool] Started for session {self._bus.session_id}")

    def update_websocket(self, websocket: WebSocket | None) -> None:
        """Update the WebSocket reference after a client reconnect."""
        self._ws = websocket
        logger.info(f"[DeepWorkerPool] Updated WebSocket for session {self._bus.session_id}")

    async def stop(self) -> None:
        """Stop the pool and cancel all active tasks.

        Marks any pending/running worker tasks as 'cancelled' in the DB
        so they don't get auto-recovered as orphans on the next session.
        """
        self._stopped = True
        self._bus.close()
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        # Cancel any pending dispatcher-callback debouncers
        for chat_id, deb_task in list(self._callback_debouncers.items()):
            if not deb_task.done():
                deb_task.cancel()
        self._callback_debouncers.clear()
        # Cancel active asyncio tasks and update DB records
        cancelled_ids = list(self._active_tasks.keys())
        # Signal each worker's cancel_event FIRST — the CLI backends terminate
        # their subprocess via a _watch_cancel coroutine that polls this event.
        # A bare task.cancel() aborts only the asyncio task and orphans the
        # live CLI subprocess (it keeps executing MCP side effects unsupervised).
        signalled = 0
        for task_id in cancelled_ids:
            ev = self._task_cancel_events.get(task_id)
            if ev is not None and not ev.is_set():
                ev.set()
                signalled += 1
        if signalled:
            # Give the _watch_cancel watchers (0.5s poll) a beat to issue
            # proc.terminate() before the hard cancel tears the watchers down.
            await asyncio.sleep(1.0)
        for task_id, task in list(self._active_tasks.items()):
            task.cancel()
        self._active_tasks.clear()
        self._task_cancel_events.clear()
        # Mark cancelled tasks in BOTH the file-store session and the DB
        # ledger. The worker's own ``except asyncio.CancelledError`` branch
        # (run_task) normally takes care of this, but ``stop()`` does not
        # await the cancelled tasks — if the backend exits before that
        # handler runs, the session_store stays on ``status=running`` and
        # ``check_timeouts`` later flips it to ``timed_out``, which the UI
        # reports as a phantom timeout. Sync the file-store eagerly so the
        # status is always terminal once stop() returns.
        _wss_stop = get_worker_session_store()
        for task_id in cancelled_ids:
            try:
                _wss_stop.update_status(
                    task_id,
                    "cancelled",
                    result_summary="Session closed — task cancelled",
                )
            except Exception as e:
                logger.warning(f"[DeepWorkerPool] Failed to update session_store for {task_id}: {e}")
            try:
                await self._ledger_update(
                    task_id, "cancelled",
                    error="Session closed — task cancelled",
                )
            except Exception as e:
                logger.warning(f"[DeepWorkerPool] Failed to cancel task {task_id} in DB: {e}")
        # Also cancel any pending/running tasks for this session in the DB
        # (covers tasks that finished spawning but aren't in _active_tasks)
        await self._cancel_session_tasks(self._bus.session_id)
        logger.info(
            f"[DeepWorkerPool] Stopped for session {self._bus.session_id}"
            f" — cancelled {len(cancelled_ids)} active task(s)"
        )

    @staticmethod
    async def _cancel_session_tasks(session_id: str) -> int:
        """Mark all pending/running tasks for a session as cancelled in the DB."""
        try:
            from app.database import async_session, WorkerTask, utcnow
            from sqlalchemy import update, and_
            async with async_session() as db:
                result = await db.execute(
                    update(WorkerTask)
                    .where(and_(
                        WorkerTask.session_id == session_id,
                        WorkerTask.status.in_(["pending", "running"]),
                    ))
                    .values(
                        status="cancelled",
                        error="Session closed — task cancelled",
                        completed_at=utcnow(),
                    )
                )
                await db.commit()
                if result.rowcount > 0:
                    logger.info(f"[Ledger] Cancelled {result.rowcount} orphan task(s) for session {session_id}")
                return result.rowcount
        except Exception as e:
            logger.warning(f"[Ledger] Failed to cancel session tasks for {session_id}: {e}")
            return 0

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a specific running task by task_id.

        Returns True if the task was found and cancelled, False otherwise.
        If the task is not live in memory but the session store still shows it
        ``running`` (zombie from a previous backend boot), mark the session
        ``cancelled`` and emit the WS event so the UI converges.
        """
        task = self._active_tasks.get(task_id)
        if not task:
            store = get_worker_session_store()
            session = store.get_session(task_id)
            if session and session.get("status") == "running":
                logger.info(f"[DeepWorkerPool] cancel_task: task {task_id} is a zombie (not live) — reconciling")
                store.update_status(
                    task_id,
                    "cancelled",
                    result_summary="zombie — process not live",
                )
                await self._ledger_update(task_id, "cancelled", error="zombie — process not live")
                await self._send_task_event("task:cancelled", task_id, {
                    "reason": "zombie_reconciled",
                    "sessionId": self._bus.session_id,
                })
                return True
            logger.warning(f"[DeepWorkerPool] cancel_task: task {task_id} not found")
            return False

        logger.info(f"[DeepWorkerPool] Cancelling task {task_id}")

        self._active_tasks.pop(task_id, None)

        # Signal the worker's cancel_event BEFORE the asyncio cancel — the CLI
        # backends terminate their subprocess via a _watch_cancel coroutine
        # that polls this event; a bare task.cancel() aborts only the asyncio
        # task and orphans the live CLI subprocess (it keeps executing MCP
        # side effects with no supervision).
        cancel_event = self._task_cancel_events.get(task_id)
        if cancel_event is not None and not cancel_event.is_set():
            cancel_event.set()
            # Give _watch_cancel a beat to terminate the subprocess so the
            # stream loop ends naturally and the worker runs its own cleanup
            # (registry deregister, rate-gate release). shield() keeps the
            # timeout from cancelling the task itself — we do that below.
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
                pass

        task.cancel()

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass

        self._semaphore.release()

        # Sync BOTH the file-store session and the DB ledger. The worker's
        # own ``except asyncio.CancelledError`` branch handles the happy
        # path, but if ``wait_for`` above timed out (worker didn't process
        # the cancel within 2s) the session_store can still be on
        # ``running`` when this method returns — ``check_timeouts`` would
        # later flip it to ``timed_out`` and surface a phantom timeout.
        try:
            get_worker_session_store().update_status(
                task_id,
                "cancelled",
                result_summary="User cancelled",
            )
        except Exception as e:
            logger.warning(f"[DeepWorkerPool] Failed to update session_store for {task_id}: {e}")

        # Update DB ledger
        await self._ledger_update(task_id, "cancelled", error="User cancelled")

        await self._send_task_event("task:cancelled", task_id, {
            "reason": "user_cancelled",
            "sessionId": self._bus.session_id,
        })

        logger.info(f"[DeepWorkerPool] Task {task_id} cancelled successfully")
        return True

    async def steer_task(self, task_id: str, message: str) -> bool:
        """Inject a steering message into a running worker task.

        Puts the message into the task's message_queue.  If the worker is
        using the steerable CLI path, the message will be forwarded to the
        subprocess stdin in real time.  If the task is not found or already
        complete, returns False.
        """
        queue = self._task_message_queues.get(task_id)
        if not queue:
            logger.warning(f"[DeepWorkerPool] steer_task: no queue for task {task_id}")
            return False
        await queue.put(message)
        logger.info(f"[DeepWorkerPool] Steered task {task_id}: {message[:100]!r}")
        return True

    def peek(self, task_id: str) -> dict | None:
        """Return tool activity summary for a specific task."""
        events = self._task_tool_events.get(task_id)
        meta = self._task_meta.get(task_id)
        if not meta:
            return None
        return {
            "task_id": task_id,
            "action": meta["action"],
            "model": meta["model"],
            "status": "running" if task_id in self._active_tasks else "completed",
            "tool_count": self._task_tool_counts.get(task_id, 0),
            "last_tool": events[-1]["tool"] if events else None,
            "last_tool_at": events[-1]["at"] if events else None,
            "recent_tools": [e["tool"] for e in (events or [])[-5:]],
            "running_seconds": int(time.time() - meta["started_at"]),
        }

    def get_active_tasks(self) -> dict:
        """Return active and recently completed tasks for dispatcher context injection."""
        now = time.time()

        self._completed_tasks = [
            t for t in self._completed_tasks
            if now - t["completed_at"] < self.COMPLETED_TASK_TTL
        ]

        active = []
        for task_id, meta in self._task_meta.items():
            if task_id in self._active_tasks:
                elapsed = int(now - meta["started_at"])
                tool_events = self._task_tool_events.get(task_id)
                active.append({
                    # Full id, verbatim — task.peek / cancel / read_artifact
                    # lookups are exact-match, so a truncated id sent to the
                    # dispatcher would make every follow-up call 404.
                    "task_id": task_id,
                    "action": meta["action"],
                    "model": meta["model"],
                    "description": meta["description"],
                    "card_id": meta.get("card_id"),
                    "running_seconds": elapsed,
                    "tool_count": self._task_tool_counts.get(task_id, 0),
                    "last_tool": tool_events[-1]["tool"] if tool_events else None,
                })

        completed = []
        for t in self._completed_tasks:
            ago = int(now - t["completed_at"])
            completed.append({
                "task_id": t["task_id"],
                "action": t["action"],
                "model": t["model"],
                "description": t.get("description", ""),
                "seconds_ago": ago,
                "result": t["result"],
                "success": t.get("success", True),
            })

        return {"active": active, "completed": completed}

    # ------------------------------------------------------------------
    # Ambient worker-event buffer — drained by the dispatcher at the start
    # of the NEXT user-triggered turn. Worker completions are no longer
    # turns themselves; they're ambient references. (Implementation lives
    # in orchestration/worker_events.py — these delegates keep the public
    # surface for layer_runners / orchestrator callers.)
    # ------------------------------------------------------------------

    def record_worker_event(
        self,
        dispatcher_chat_id: str,
        *,
        task_id: str,
        intent: str,
        status: str,
        summary_line: str,
        completion: dict | None = None,
    ) -> None:
        """Record a worker completion/failure against a dispatcher chat."""
        _worker_events.record_worker_event(
            self,
            dispatcher_chat_id,
            task_id=task_id,
            intent=intent,
            status=status,
            summary_line=summary_line,
            completion=completion,
        )

    def peek_worker_events(
        self, dispatcher_chat_id: str, *, max_items: int = 10,
    ) -> list[dict]:
        """Return pending worker events without consuming them."""
        return _worker_events.peek_worker_events(
            self, dispatcher_chat_id, max_items=max_items,
        )

    def ack_worker_events(
        self, dispatcher_chat_id: str, *, count: int,
    ) -> None:
        """Remove the first ``count`` worker events for a dispatcher chat."""
        _worker_events.ack_worker_events(self, dispatcher_chat_id, count=count)

    def drain_worker_events(
        self, dispatcher_chat_id: str, *, max_items: int = 10,
    ) -> list[dict]:
        """Pop pending worker events for a dispatcher chat (oldest first)."""
        return _worker_events.drain_worker_events(
            self, dispatcher_chat_id, max_items=max_items,
        )

    # ------------------------------------------------------------------
    # Debounced dispatcher callback — see orchestration/worker_events.py.
    # ------------------------------------------------------------------

    def _schedule_dispatcher_callback(
        self, dispatcher_chat_id: str, event: ActionIntent,
    ) -> None:
        """Arm (or re-arm) a debounced callback turn for this chat."""
        _worker_events.schedule_dispatcher_callback(self, dispatcher_chat_id, event)

    async def _run_debounced_callback(
        self, dispatcher_chat_id: str, event: ActionIntent,
    ) -> None:
        await _worker_events.run_debounced_callback(self, dispatcher_chat_id, event)

    def count_active_for_chat(self, dispatcher_chat_id: str) -> int:
        """How many active worker tasks are currently tied to this dispatcher chat?"""
        return _worker_events.count_active_for_chat(self, dispatcher_chat_id)

    def active_intents_for_chat(self, dispatcher_chat_id: str) -> list[str]:
        """Return a short intent/action label for each active worker tied to this chat."""
        return _worker_events.active_intents_for_chat(self, dispatcher_chat_id)

    async def _stale_cleanup_loop(self) -> None:
        """Prune old completed-task entries from memory (every 60s)."""
        try:
            while not self._stopped:
                await asyncio.sleep(60)
                try:
                    wss = get_worker_session_store()
                    removed = wss.cleanup_old()
                    if removed:
                        logger.debug(f"[DeepWorkerPool] Pruned {removed} old sessions")
                except Exception as e:
                    logger.warning(f"[DeepWorkerPool] Cleanup error: {e}")
        except asyncio.CancelledError:
            pass

    async def _listen_loop(self) -> None:
        """Listen on the bus and spawn workers for each event."""
        try:
            async for event in self._bus.listen():
                # Idempotency guard: _listen_loop is the only coroutine that
                # INSERTS into _active_tasks (cancel_task / _on_task_done / stop
                # only remove), so a task_id already present means a duplicate
                # spawn of an already-in-flight task — a literal re-emit of the
                # same ActionIntent, or an (astronomically unlikely) uuid4-prefix
                # collision (all emit paths mint fresh uuid ids). Spawning anyway
                # would orphan the in-flight task: the first task's done-callback
                # would later pop and release the slot of the SECOND task,
                # corrupting semaphore accounting. Skip BEFORE acquiring a slot.
                if event.task_id in self._active_tasks:
                    logger.warning(
                        "[DeepWorkerPool] Duplicate spawn for task_id %s — "
                        "already active; skipping",
                        event.task_id,
                    )
                    continue
                await self._semaphore.acquire()
                self._task_meta[event.task_id] = {
                    "action": event.intent or "unknown",
                    # Placeholder — _execute_event will overwrite with the
                    # authoritative model (worker_class.model or default).
                    "model": get_default_worker_model(),
                    "description": event.summary or "",
                    "started_at": time.time(),
                    "dispatcher_chat_id": event.data.get("dispatcher_chat_id"),
                    "card_id": event.data.get("card_id"),
                }
                task = asyncio.create_task(self._execute_event(event))
                self._active_tasks[event.task_id] = task
                task.add_done_callback(
                    lambda t, tid=event.task_id: self._on_task_done(tid)
                )
        except asyncio.CancelledError:
            pass

    def _on_task_done(self, task_id: str) -> None:
        """Cleanup when a task completes. Idempotent."""
        if self._stopped:
            return
        self._task_message_queues.pop(task_id, None)
        removed = self._active_tasks.pop(task_id, None)
        # Release the per-session slot ONLY when WE popped the task here. The
        # cancel path (cancel_task) pops _active_tasks and releases the
        # semaphore itself, so on that path removed is None and we must NOT
        # release again — a double release would inflate the pool's capacity.
        if removed is not None:
            self._semaphore.release()

        # Per-task bookkeeping cleanup runs UNCONDITIONALLY — even on the cancel
        # path (removed is None). Previously this was gated behind
        # `removed is not None`, so every cancelled / stalled / repetition-killed
        # task permanently leaked _task_meta / _result_contents / tool-event
        # buffer entries for the pool's lifetime.
        meta = self._task_meta.pop(task_id, None)
        if meta:
            success = True
            result = "success"
            if removed is None:
                # cancel_task already popped the task → it was cancelled.
                result = "cancelled"
                success = False
            elif removed.cancelled():
                result = "cancelled"
                success = False
            elif removed.exception():
                result = f"error: {removed.exception()}"
                success = False
            actual_result = self._result_contents.pop(task_id, result)
            self._completed_tasks.append({
                "task_id": task_id,
                "action": meta["action"],
                "model": meta["model"],
                "description": meta.get("description", ""),
                "completed_at": time.time(),
                "result": actual_result,
                "success": success,
            })
        else:
            # No meta (already cleaned by a prior call) — still drop any
            # lingering result content so it can't leak.
            self._result_contents.pop(task_id, None)

        # Schedule tool-event buffer cleanup after 60s (always — cancelled tasks
        # leak these buffers otherwise).
        def _cleanup_tool_events(tid: str = task_id) -> None:
            self._task_tool_events.pop(tid, None)
            self._task_tool_counts.pop(tid, None)

        try:
            loop = asyncio.get_running_loop()
            loop.call_later(60, _cleanup_tool_events)
        except RuntimeError:
            _cleanup_tool_events()

    async def _resolve_worker_class(self, event: ActionIntent) -> dict | None:
        """Try to resolve a worker class for this event.

        Checks event.data["worker_class_id"] first, then tries intent-based matching.
        Returns the resolved worker class dict, or None for default behavior.
        """
        return await resolve_worker_class(event)

    async def _execute_event(self, event: ActionIntent) -> None:
        """Execute a single ActionIntent via model-routed worker (haiku/sonnet/opus).

        If a matching WorkerClass is found (by explicit id or intent pattern),
        the worker class model/provider is used instead of the default layer.

        Sequences: resolve_execution_plan → card lifecycle → register/ledger/
        task:started → prompt assembly → execute via claude_service (with
        tool callback + stall monitor) → completion publication.
        """
        # Bind _wss before the try block. The except/CancelledError handlers below
        # reference it; if an exception fires before the original binding (e.g. in
        # resolve_endpoint_for_class during worker-class resolution) the handler
        # would otherwise raise UnboundLocalError and mask the real error, silently
        # dropping the task.
        _wss = get_worker_session_store()
        task_started_at = time.perf_counter()
        event.data["_worker_started_perf"] = task_started_at
        try:
            # Resolve worker class / model / endpoint / effort.
            # Precedence: worker_class.model (if matched) > default_worker_model (fallback).
            # event.model is the dispatcher's LLM-suggested hint — kept only for logging;
            # user-configured Worker Classes and Default Worker Model are authoritative.
            plan = await resolve_execution_plan(event)
            _worker_class = plan.worker_class
            _effort = plan.effort
            _effective_model = plan.effective_model
            _endpoint_config = plan.endpoint_config

            # Update task_meta so get_active_tasks reflects the actual model
            if event.task_id in self._task_meta:
                self._task_meta[event.task_id]["model"] = _effective_model

            _task_card_id = event.data.get("card_id")

            # --- Card lifecycle: auto-create if missing, move to in-progress ---
            if not _task_card_id and self._should_auto_create_card(event, _worker_class):
                _task_card_id = await self._auto_create_card(
                    workspace_id=event.data.get("workspace_id"),
                    intent=event.intent or "unknown",
                    summary=event.summary or "",
                )
                if _task_card_id:
                    event.data["card_id"] = _task_card_id

            if _task_card_id:
                await self._update_card_status(
                    _task_card_id, "in-progress",
                    workspace_id=event.data.get("workspace_id"),
                )

            _wss.register(
                task_id=event.task_id,
                session_id=event.session_id or self._bus.session_id,
                chat_id=event.data.get("dispatcher_chat_id"),
                workspace_id=event.data.get("workspace_id"),
                card_id=_task_card_id,
                model=_effective_model,
                intent=event.intent or "unknown",
                summary=event.summary or "",
                worker_class=(_worker_class.get("name") if _worker_class else None),
            )

            await self._ledger_insert(
                task_id=event.task_id,
                session_id=event.session_id or self._bus.session_id,
                workspace_id=event.data.get("workspace_id"),
                card_id=_task_card_id,
                action=event.intent or "unknown",
                description=(event.summary or "")[:500],
                model=_effective_model,
            )

            await self._send_task_event("task:started", event.task_id, {
                "intent": event.intent,
                "summary": event.summary,
                "complexity": event.complexity,
                "model": _effective_model,
                "workerClass": (_worker_class.get("name") if _worker_class else None),
                "sessionId": event.session_id,
                "chatId": event.data.get("dispatcher_chat_id"),
                "cardId": _task_card_id,
                "workspaceId": event.data.get("workspace_id"),
            })

            _wc_name = (_worker_class or {}).get("name")
            logger.info(
                f"[DeepWorker] Executing task {event.task_id}: {event.intent} "
                f"(model={_effective_model}"
                + (f", class={_wc_name}" if _wc_name else "")
                + (f", requested={event.model}" if event.model and event.model != _effective_model else "")
                + (f", endpoint={_endpoint_config.get('url')}" if _endpoint_config else "")
                + ")"
            )

            execution_prompt = build_execution_prompt(event)

            task_chat_id = f"task-{event.task_id}"

            await self._send_task_event("task:progress", event.task_id, {
                "status": "executing",
                "sessionId": event.session_id,
                "toolCount": self._task_tool_counts.get(event.task_id, 0),
            })

            chat_level = resolve_chat_level(event)

            supervisor = get_worker_supervisor()
            supervisor.register_task(event.task_id)
            cancel_event = asyncio.Event()
            # Expose the cancel_event so cancel_task()/stop() can signal the
            # CLI backends' _watch_cancel watcher (which terminates the
            # subprocess) — a bare task.cancel() would orphan it.
            self._task_cancel_events[event.task_id] = cancel_event
            message_queue: asyncio.Queue[str] = asyncio.Queue()
            self._task_message_queues[event.task_id] = message_queue

            # Accumulate raw tool output — the LLM's text response is often
            # a summary; the real content lives in tool_results from file.read,
            # system.exec, etc.
            _captured_tool_outputs: list[str] = []

            tool_callback = make_tool_callback(
                self, event, supervisor, cancel_event, _captured_tool_outputs,
            )

            stall_task = asyncio.create_task(
                stall_monitor(event, supervisor, cancel_event, message_queue)
            )

            try:
                # Fast-path: execute file reads directly without LLM
                result_content = await self._try_direct_execution(event)

                if result_content is not None:
                    logger.info(
                        f"[DirectExec] Task {event.task_id} completed via fast-path "
                        f"({len(result_content)} chars)"
                    )
                elif is_lightweight_intent(event.intent or ""):
                    logger.info(f"[LightWorker] Routing {event.task_id} to lightweight worker ({event.intent})")
                    result_content = await self._claude.execute_lightweight_task(
                        chat_id=event.data.get("dispatcher_chat_id") or task_chat_id,
                        prompt=execution_prompt,
                        model=_effective_model,
                        workspace_id=event.data.get("workspace_id"),
                        card_context=event.data.get("card_context"),
                        tool_callback=tool_callback,
                        cancel_event=cancel_event,
                        message_queue=message_queue,
                        session_id=event.session_id or "",
                        task_id=event.task_id,
                        endpoint_config=_endpoint_config,
                        effort=_effort,
                    )
                else:
                    result_content = await self._claude.execute_worker_task(
                        chat_id=event.data.get("dispatcher_chat_id") or task_chat_id,
                        prompt=execution_prompt,
                        model=_effective_model,
                        chat_level=chat_level,
                        project_context=event.data.get("project_context"),
                        card_context=event.data.get("card_context"),
                        workspace_id=event.data.get("workspace_id"),
                        tool_callback=tool_callback,
                        cancel_event=cancel_event,
                        message_queue=message_queue,
                        session_id=event.session_id or "",
                        task_id=event.task_id,
                        endpoint_config=_endpoint_config,
                        effort=_effort,
                    )
            except asyncio.CancelledError:
                logger.info(f"[DeepWorker] Task {event.task_id} was cancelled")
                _wss.update_status(event.task_id, "cancelled")
                await self._ledger_update(event.task_id, "cancelled")
                # Surface the cancel/stall to the dispatcher (ambient worker
                # event + debounced callback) — see worker_completion.
                record_cancellation(self, event)
                return
            finally:
                stall_task.cancel()
                try:
                    await stall_task
                except asyncio.CancelledError:
                    pass

            # Result fallback chain (history → event.summary → captured tool
            # outputs) + completion_summary preference.
            result_content = resolve_result_content(
                self._claude, event, result_content,
                _captured_tool_outputs, supervisor, task_chat_id,
            )

            follow_up_action, result_content = extract_follow_up(result_content)

            await append_result_to_card(self, event, result_content)

            if result_content:
                self._result_contents[event.task_id] = result_content or ""

            # Artifact write + closeout pass + fallback synthesis + sidecar.
            artifact_path = await finalize_completion_artifacts(
                self._claude, event, result_content, supervisor,
            )

            # --- Secondary stores get previews; artifact is canonical ---
            result_preview = _preview(result_content, PREVIEW_CHARS) if result_content else ""

            _wss.update_status(
                event.task_id,
                "completed",
                result_preview,
                artifact_path=artifact_path,
            )

            await self._ledger_update(
                event.task_id, "done",
                result_summary=result_content or "",
            )

            await publish_completion(
                self, event,
                result_content=result_content,
                result_preview=result_preview,
                artifact_path=artifact_path,
                supervisor=supervisor,
                follow_up_action=follow_up_action,
                task_chat_id=task_chat_id,
            )

        except Exception as e:
            logger.error(f"[DeepWorker] Task {event.task_id} failed: {e}")
            _wss.update_status(event.task_id, "failed", str(e)[:500])
            await self._ledger_update(event.task_id, "failed", error=str(e)[:500])
            await record_failure(self, event, e)
        finally:
            self._task_cancel_events.pop(event.task_id, None)
            try:
                supervisor = get_worker_supervisor()
                supervisor.cleanup_task(event.task_id)
            except Exception:
                pass

    async def _send_task_event(self, event_type: str, task_id: str, payload: dict) -> None:
        """Send a task event to the frontend via WebSocket.

        If the WebSocket is closed, store the result in pending_results
        for delivery on the next connection.
        """
        message = {
            "type": event_type,
            "payload": {"taskId": task_id, **payload},
            "timestamp": int(time.time() * 1000),
        }
        from app.services.ws_broadcast import ws_broadcast
        ws = self._ws
        delivered = False
        if ws is not None:
            try:
                await ws.send_json(message)
                await ws_broadcast.emit_to_others(ws, event_type, {"taskId": task_id, **payload})
                delivered = True
            except Exception:
                # WS may have been replaced by session:sync — retry once with current ref
                retry_ws = self._ws
                if retry_ws is not None and retry_ws is not ws:
                    try:
                        await retry_ws.send_json(message)
                        await ws_broadcast.emit_to_others(retry_ws, event_type, {"taskId": task_id, **payload})
                        logger.info(f"[DeepWorkerPool] Retried {event_type} on reconnected WS for task {task_id}")
                        delivered = True
                    except Exception as e:
                        logger.warning(f"[DeepWorkerPool] Failed to send {event_type} via WS for task {task_id}: {e}")
                else:
                    logger.warning(f"[DeepWorkerPool] Failed to send {event_type} via WS for task {task_id} (socket dead)")
        else:
            # Headless / background pool — no bound WS. Best-effort live broadcast
            # to any client currently connected to this session...
            try:
                ws_broadcast.emit_sync(event_type, {"taskId": task_id, **payload})
            except Exception as e:
                logger.warning(f"[DeepWorkerPool] emit_sync failed for {event_type}: {e}")
            # ...but emit_sync can't confirm receipt and there's no bound socket
            # to retry on, so fall through and ALWAYS persist for redelivery.

        # Persist for redelivery whenever live delivery wasn't confirmed. This
        # covers a dead bound socket AND the headless (ws=None) case, which
        # previously dropped task:* events whenever no client was listening.
        if not delivered:
            # `or` (not dict.get's default) so an explicitly-passed empty
            # sessionId still falls back to the bus id instead of dropping.
            session_id = payload.get("sessionId") or self._bus.session_id
            if session_id:
                try:
                    await pending_store.store(session_id, message)
                    logger.info(f"[DeepWorkerPool] Stored pending {event_type} for task {task_id}")
                except Exception as store_err:
                    logger.error(f"[DeepWorkerPool] Failed to store pending {event_type}: {store_err}")

    # ------------------------------------------------------------------
    # Card Lifecycle helpers (system-managed) — implementations live in
    # orchestration/worker_cards.py + result_formatting.py; kept as class
    # attributes for backwards compatibility (tests + historical callers).
    # ------------------------------------------------------------------

    _make_short_title = staticmethod(_make_short_title)

    # Trivial delegate intents that should never produce a tracking card —
    # see worker_cards._TRIVIAL_INTENTS.
    _TRIVIAL_INTENTS = _TRIVIAL_INTENTS

    _should_auto_create_card = staticmethod(_should_auto_create_card)
    _auto_create_card = staticmethod(_auto_create_card)
    _update_card_status = staticmethod(_update_card_status)

    # ------------------------------------------------------------------
    # Worker Ledger DB helpers — implementations in worker_cards.py.
    # ------------------------------------------------------------------

    _ledger_insert = staticmethod(_ledger_insert)
    _ledger_update = staticmethod(_ledger_update)
