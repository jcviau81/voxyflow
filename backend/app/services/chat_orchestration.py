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

logger = logging.getLogger("voxyflow.orchestration")

def _format_result_for_card(text: str) -> str:
    """Convert raw LLM result to clean human-readable text for card injection.

    If the result is a JSON object/array, flatten it into readable key: value lines
    instead of injecting raw JSON into the card description.
    """
    stripped = text.strip()
    # Strip markdown code fences if present
    if stripped.startswith('```'):
        inner = stripped.split('```', 2)
        if len(inner) >= 2:
            block = inner[1]
            if block.startswith('json'):
                block = block[4:]
            stripped = block.strip()

    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return text  # Not JSON — return as-is

    if isinstance(parsed, dict):
        lines = []
        for k, v in parsed.items():
            if isinstance(v, list):
                lines.append(f'**{k}:**')
                for item in v:
                    lines.append(f'  - {item}')
            elif isinstance(v, dict):
                lines.append(f'**{k}:** {json.dumps(v)}')
            else:
                lines.append(f'**{k}:** {v}')
        return '\n'.join(lines)
    elif isinstance(parsed, list):
        return '\n'.join(f'- {item}' for item in parsed)
    else:
        return str(parsed)


# ---------------------------------------------------------------------------
# Deep Worker Pool — consumes ActionIntent events from the event bus
# ---------------------------------------------------------------------------

class DeepWorkerPool:
    """Pool of async workers that consume events from a SessionEventBus
    and execute them via the Deep layer (Opus) with full tool access.

    Each session gets its own pool. Max workers controls concurrency.
    """

    MAX_WORKERS = 3
    TASK_TIMEOUT_SECONDS = 300  # 5 minutes

    COMPLETED_TASK_TTL = 300  # seconds to keep completed tasks visible (5 min)

    def __init__(
        self,
        claude_service: ClaudeService,
        bus: SessionEventBus,
        websocket: WebSocket,
        orchestrator: "ChatOrchestrator | None" = None,
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
        self._semaphore = asyncio.Semaphore(self.MAX_WORKERS)
        self._callback_lock = asyncio.Lock()  # Prevents overlapping callback streams
        self._result_contents: dict[str, str] = {}  # task_id → actual result content
        self._stopped = False

    def start(self) -> None:
        """Start listening on the bus for events."""
        self._listener_task = asyncio.create_task(self._listen_loop())
        self._cleanup_task = asyncio.create_task(self._stale_cleanup_loop())
        logger.info(f"[DeepWorkerPool] Started for session {self._bus.session_id}")

    def update_websocket(self, websocket: WebSocket) -> None:
        """Update the WebSocket reference after a client reconnect.

        Called when the frontend reconnects with the same session_id so that
        in-progress workers can still send events to the live socket.
        """
        self._ws = websocket
        logger.info(f"[DeepWorkerPool] Updated WebSocket for session {self._bus.session_id}")

    async def stop(self) -> None:
        """Stop the pool and cancel all active tasks."""
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
        for task_id, task in list(self._active_tasks.items()):
            task.cancel()
        self._active_tasks.clear()
        logger.info(f"[DeepWorkerPool] Stopped for session {self._bus.session_id}")

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a specific running task by task_id.

        Returns True if the task was found and cancelled, False otherwise.
        """
        task = self._active_tasks.get(task_id)
        if not task:
            logger.warning(f"[DeepWorkerPool] cancel_task: task {task_id} not found")
            return False

        logger.info(f"[DeepWorkerPool] Cancelling task {task_id}")

        # Remove from active_tasks BEFORE cancelling so _on_task_done
        # (the done callback) won't double-release the semaphore.
        self._active_tasks.pop(task_id, None)
        task.cancel()

        # Wait briefly for cancellation to propagate
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass

        # Release semaphore exactly once (done callback won't since we
        # already popped the task from _active_tasks above).
        self._semaphore.release()

        # Notify frontend
        await self._send_task_event("task:cancelled", task_id, {
            "reason": "user_cancelled",
            "sessionId": self._bus.session_id,
        })

        logger.info(f"[DeepWorkerPool] Task {task_id} cancelled successfully")
        return True

    def get_active_tasks(self) -> dict:
        """Return active and recently completed tasks for dispatcher context injection.

        Returns a dict with 'active' and 'completed' lists. Automatically
        prunes completed tasks older than COMPLETED_TASK_TTL seconds.
        """
        now = time.time()

        # Prune expired completed tasks
        self._completed_tasks = [
            t for t in self._completed_tasks
            if now - t["completed_at"] < self.COMPLETED_TASK_TTL
        ]

        active = []
        for task_id, meta in self._task_meta.items():
            if task_id in self._active_tasks:
                elapsed = int(now - meta["started_at"])
                active.append({
                    "task_id": task_id[:8],
                    "action": meta["action"],
                    "model": meta["model"],
                    "description": meta["description"],
                    "running_seconds": elapsed,
                })

        completed = []
        for t in self._completed_tasks:
            ago = int(now - t["completed_at"])
            completed.append({
                "task_id": t["task_id"][:8],
                "action": t["action"],
                "model": t["model"],
                "seconds_ago": ago,
                "result": t["result"],
            })

        return {"active": active, "completed": completed}

    async def _stale_cleanup_loop(self) -> None:
        """Prune old completed-task entries from memory (every 60s).

        cleanup_stale(120s) was removed: it killed Opus workers after 120s of
        elapsed time regardless of activity. Timeout handling is done correctly
        by check_timeouts() with a 600s threshold in WorkerSessionStore.
        """
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
                # Enforce concurrency limit
                await self._semaphore.acquire()
                # Track task metadata for active workers registry
                self._task_meta[event.task_id] = {
                    "action": event.intent or "unknown",
                    "model": event.model or "sonnet",
                    "description": event.summary or "",
                    "started_at": time.time(),
                }
                task = asyncio.create_task(self._execute_event(event))
                self._active_tasks[event.task_id] = task
                task.add_done_callback(
                    lambda t, tid=event.task_id: self._on_task_done(tid)
                )
        except asyncio.CancelledError:
            pass

    def _on_task_done(self, task_id: str) -> None:
        """Cleanup when a task completes. Idempotent — only releases
        the semaphore if this task hadn't already been cleaned up
        (e.g. by cancel_task)."""
        if self._stopped:
            return
        removed = self._active_tasks.pop(task_id, None)
        if removed is not None:
            self._semaphore.release()
            # Move to completed registry for dispatcher context
            meta = self._task_meta.pop(task_id, None)
            if meta:
                # Determine result from the task's exception state
                result = "success"
                if removed.cancelled():
                    result = "cancelled"
                elif removed.exception():
                    result = f"error: {removed.exception()}"
                # Use actual worker result content if available
                actual_result = self._result_contents.pop(task_id, result)
                self._completed_tasks.append({
                    "task_id": task_id,
                    "action": meta["action"],
                    "model": meta["model"],
                    "completed_at": time.time(),
                    "result": actual_result,
                })

    async def _execute_event(self, event: ActionIntent) -> None:
        """Execute a single ActionIntent via model-routed worker (haiku/sonnet/opus)."""
        try:
            # Register in persistent worker session store
            _wss = get_worker_session_store()
            _wss.register(
                task_id=event.task_id,
                session_id=event.session_id or self._bus.session_id,
                project_id=event.data.get("project_id"),
                model=event.model or "sonnet",
                intent=event.intent or "unknown",
                summary=event.summary or "",
            )

            # --- Worker Ledger: insert row with status='running' ---
            await self._ledger_insert(
                task_id=event.task_id,
                session_id=event.session_id or self._bus.session_id,
                project_id=event.data.get("project_id"),
                action=event.intent or "unknown",
                description=(event.summary or "")[:500],
                model=event.model or "sonnet",
            )

            # Notify frontend: task started (include model for badge)
            await self._send_task_event("task:started", event.task_id, {
                "intent": event.intent,
                "summary": event.summary,
                "complexity": event.complexity,
                "model": event.model,
                "sessionId": event.session_id,
            })

            logger.info(f"[DeepWorker] Executing task {event.task_id}: {event.intent} (model={event.model})")

            # Build a focused prompt for the executor
            intent_lower = event.intent.lower()
            is_move_or_update = any(kw in intent_lower for kw in [
                "move", "update", "change_status", "complete", "finish",
                "start_work", "mark_done", "mark_complete"
            ])
            
            execution_prompt = (
                f"Execute this action:\n"
                f"Intent: {event.intent}\n"
                f"Summary: {event.summary}\n"
                f"Task ID: {event.task_id}\n"
                f"\nWhen done, call task.complete(task_id=\"{event.task_id}\", summary=\"...\", status=\"success|partial|failed\").\n"
            )
            
            if is_move_or_update:
                execution_prompt += (
                    "\n⚠️ IMPORTANT: This is a MOVE/UPDATE operation on EXISTING cards.\n"
                    "1. First call card.list to find the existing card(s) by name\n"
                    "2. Then call card.move (for status change) or card.update (for content change)\n"
                    "3. Do NOT create new cards — the cards already exist\n\n"
                )
            if event.data:
                # Pass relevant data but exclude internal context objects
                action_data = {k: v for k, v in event.data.items()
                               if k not in ("project_context", "card_context")}
                execution_prompt += f"Data: {json.dumps(action_data)}\n"

            # Inject explicit card/project context so the worker knows
            # exactly which card/project it is operating on.
            _project_ctx = event.data.get("project_context")
            _card_ctx = event.data.get("card_context")
            if _card_ctx and _project_ctx:
                execution_prompt += (
                    f"\n## Current Context\n"
                    f"You are operating in the context of card \"{_card_ctx.get('title', '?')}\" "
                    f"(card_id: {_card_ctx.get('id', '?')}) in project \"{_project_ctx.get('title', '?')}\" "
                    f"(project_id: {_project_ctx.get('id', '?')}).\n"
                    f"Card status: {_card_ctx.get('status', '?')} | "
                    f"Priority: {_card_ctx.get('priority', '?')}\n"
                )
                if _card_ctx.get("description"):
                    execution_prompt += f"Card description: {_card_ctx['description'][:500]}\n"
                execution_prompt += (
                    f"Use card_id={_card_ctx.get('id', '?')} for any card operations. "
                    f"Use project_id={_project_ctx.get('id', '?')} for any project operations.\n"
                )
            elif _project_ctx:
                execution_prompt += (
                    f"\n## Current Context\n"
                    f"You are operating in the context of project \"{_project_ctx.get('title', '?')}\" "
                    f"(project_id: {_project_ctx.get('id', '?')}).\n"
                    f"Use project_id={_project_ctx.get('id', '?')} for any project/card operations.\n"
                )

            # Use a dedicated chat_id for this task to avoid polluting main history
            task_chat_id = f"task-{event.task_id}"

            # Notify progress
            await self._send_task_event("task:progress", event.task_id, {
                "status": "executing",
                "sessionId": event.session_id,
            })

            # Infer chat_level from context — workers always operate at project
            # level since Main is now a real project (system-main).
            chat_level = event.data.get("chat_level", "general")
            if chat_level == "general":
                # General is now the system-main project — upgrade to project
                # level so workers get project-scoped tools.
                intent_lower = event.intent.lower()
                if (
                    event.data.get("project_id")
                    or "project" in intent_lower
                    or "card" in intent_lower
                    or "main_board" in intent_lower
                    or "mainboard" in intent_lower
                ):
                    chat_level = "project"

            # --- Worker Supervisor: register task and create cancel_event ---
            supervisor = get_worker_supervisor()
            supervisor.register_task(event.task_id)
            cancel_event = asyncio.Event()
            message_queue: asyncio.Queue[str] = asyncio.Queue()

            # Build an async tool_callback that forwards tool:executed events
            # to the frontend AND records tool calls with the supervisor.
            async def _tool_callback(tool_name: str, arguments: dict, result: dict):
                # Record with supervisor for repetition/stall detection
                supervisor.record_tool_call(event.task_id, tool_name, arguments)
                if supervisor.check_repetition(event.task_id):
                    logger.warning(f"[Supervisor] Cancelling task {event.task_id} — repetitive loop detected")
                    supervisor.mark_problem(event.task_id, "repetitive_loop")
                    cancel_event.set()

                try:
                    await self._ws.send_json({
                        "type": "tool:executed",
                        "payload": {
                            "tool": tool_name,
                            "args": arguments,
                            "result": result,
                            "sessionId": event.session_id,
                            "taskId": event.task_id,
                        },
                        "timestamp": int(time.time() * 1000),
                    })
                    logger.info(f"[DeepWorker] Sent tool:executed for {tool_name}")
                except Exception as e:
                    logger.warning(f"[DeepWorker] Failed to send tool:executed event: {e}")

            tool_callback = _tool_callback

            # --- Background stall detector ---
            async def _stall_monitor():
                """Periodically check for stalled tasks and cancel if idle too long."""
                STALL_THRESHOLD = 120  # seconds
                WARNING_THRESHOLD = 90  # warn before killing
                warned = False
                while not cancel_event.is_set():
                    await asyncio.sleep(15)
                    stall_secs = supervisor.check_stall(event.task_id)
                    if stall_secs > WARNING_THRESHOLD and not warned:
                        warned = True
                        message_queue.put_nowait(
                            f"WARNING: You have been idle for {stall_secs:.0f}s. "
                            "Wrap up now and call task.complete or you will be cancelled."
                        )
                    if stall_secs > STALL_THRESHOLD:
                        logger.warning(
                            f"[Supervisor] Task {event.task_id} stalled for {stall_secs:.0f}s — cancelling"
                        )
                        supervisor.mark_problem(event.task_id, f"stalled_{stall_secs:.0f}s")
                        cancel_event.set()
                        break

            stall_task = asyncio.create_task(_stall_monitor())

            # Route to model-specific worker (with timeout)
            try:
                result_content = await asyncio.wait_for(
                    self._claude.execute_worker_task(
                        chat_id=task_chat_id,
                        prompt=execution_prompt,
                        model=event.model,
                        chat_level=chat_level,
                        project_context=event.data.get("project_context"),
                        card_context=event.data.get("card_context"),
                        project_id=event.data.get("project_id"),
                        tool_callback=tool_callback,
                        cancel_event=cancel_event,
                        message_queue=message_queue,
                    ),
                    timeout=self.TASK_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                logger.warning(f"[DeepWorker] Task {event.task_id} timed out after {self.TASK_TIMEOUT_SECONDS}s")
                supervisor.mark_problem(event.task_id, f"timeout_{self.TASK_TIMEOUT_SECONDS}s")
                _wss.update_status(event.task_id, "timed_out", f"Timed out after {self.TASK_TIMEOUT_SECONDS}s")
                await self._ledger_update(event.task_id, "failed", error=f"Timed out after {self.TASK_TIMEOUT_SECONDS}s")
                await self._send_task_event("task:timeout", event.task_id, {
                    "intent": event.intent,
                    "summary": event.summary,
                    "timeout_seconds": self.TASK_TIMEOUT_SECONDS,
                    "sessionId": event.session_id,
                })
                return
            except asyncio.CancelledError:
                logger.info(f"[DeepWorker] Task {event.task_id} was cancelled")
                _wss.update_status(event.task_id, "cancelled")
                await self._ledger_update(event.task_id, "cancelled")
                # task:cancelled is sent by cancel_task() — just return
                return
            finally:
                # Always stop the stall monitor
                stall_task.cancel()

            # ------------------------------------------------------------------
            # Fallback: ensure result_content is populated
            # ------------------------------------------------------------------
            if not result_content:
                # Fallback 1: last assistant message from the task's conversation
                try:
                    task_history = await self._claude._load_history_async(task_chat_id)
                    for msg in reversed(task_history):
                        if msg.get("role") == "assistant":
                            raw = msg.get("content", "")
                            if isinstance(raw, list):
                                # Content block list — find the first text block
                                text = " ".join(
                                    b.get("text", "") for b in raw if isinstance(b, dict) and b.get("type") == "text"
                                ).strip()
                            else:
                                text = str(raw).strip()
                            if text:
                                result_content = text
                                logger.warning(
                                    f"[DeepWorker] result_content was empty for task "
                                    f"{event.task_id} — fell back to last assistant message"
                                )
                                break
                except Exception as _fallback_err:
                    logger.warning(f"[DeepWorker] result_content fallback (history) failed: {_fallback_err}")

            if not result_content and event.summary:
                # Fallback 2: use the task summary from the event itself
                result_content = event.summary
                logger.warning(
                    f"[DeepWorker] result_content was empty for task "
                    f"{event.task_id} — fell back to event.summary"
                )

            # --- Supervisor: check if worker signalled completion ---
            if not supervisor.is_completed(event.task_id):
                # Worker finished without calling task.complete — mark as problem
                supervisor.mark_problem(event.task_id, "missing_task_complete")
                logger.warning(
                    f"[Supervisor] Task {event.task_id} finished without calling task.complete"
                )
            else:
                # Prefer the completion_summary from task.complete — it's what the
                # worker explicitly chose to return, and is the full result, not just
                # the final LLM text response (which may be "Done." or empty).
                task_status = supervisor.get_status(event.task_id)
                completion_summary = task_status.get("completion_summary") if task_status else None
                if completion_summary and len(completion_summary) > len(result_content or ""):
                    logger.info(
                        f"[DeepWorker] Using completion_summary ({len(completion_summary)} chars) "
                        f"over result_content ({len(result_content or '')} chars)"
                    )
                    result_content = completion_summary

            # Check for follow_up in structured worker result (must be before _format_result_for_card)
            follow_up_action = None
            try:
                parsed_result = json.loads(result_content.strip())
                if isinstance(parsed_result, dict) and "follow_up" in parsed_result:
                    follow_up_action = parsed_result["follow_up"]
                    # Use the non-follow_up content as the actual result for display
                    result_content = parsed_result.get("result", result_content)
                    logger.info(f"[DeepWorker] follow_up extracted from structured result: '{follow_up_action[:80]}'")
            except (json.JSONDecodeError, ValueError):
                pass  # Not JSON, no follow_up

            # Auto-append execution result to card description
            card_id = event.data.get("card_id")
            if card_id and result_content:
                try:
                    from app.database import async_session, Card
                    from sqlalchemy import select
                    from datetime import datetime, timezone
                    async with async_session() as db:
                        result = await db.execute(select(Card).where(Card.id == card_id))
                        card = result.scalar_one_or_none()
                        if card:
                            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                            separator = "\n\n---\n"
                            clean_result = _format_result_for_card(result_content)
                            result_block = f"📋 **Execution Result** ({timestamp})\n{clean_result}"
                            card.description = (card.description or "") + separator + result_block
                            await db.commit()
                            logger.info(f"[DeepWorker] Auto-appended result to card {card_id}")
                            # Notify frontend to re-sync this card
                            await self._send_task_event("tool:executed", event.task_id, {
                                "tool": "voxyflow.card.update",
                                "args": {"card_id": card_id, "project_id": event.data.get("project_id")},
                                "result": {"success": True},
                                "sessionId": event.session_id,
                            })
                except Exception as append_err:
                    logger.warning(f"[DeepWorker] Failed to auto-append result to card: {append_err}")

            # Store result content for _on_task_done to pick up
            if result_content:
                self._result_contents[event.task_id] = result_content or ""

            # Update session store: completed
            _wss.update_status(event.task_id, "completed", result_content or "")

            # --- Worker Ledger: mark done ---
            await self._ledger_update(
                event.task_id, "done",
                result_summary=(result_content or "")[:500],
            )

            # Notify frontend: task completed
            await self._send_task_event("task:completed", event.task_id, {
                "intent": event.intent,
                "summary": event.summary,
                "result": result_content,
                "success": True,
                "sessionId": event.session_id,
                "projectId": event.data.get("project_id"),
                "cardId": event.data.get("card_id"),
            })

            # Inject worker result into dispatcher conversation history
            # so Voxy can see and react to it on the next user message.
            dispatcher_chat_id = event.data.get("dispatcher_chat_id")
            if dispatcher_chat_id and result_content:
                try:
                    # Raised limit from 2000 to 20000 chars to avoid truncating worker summaries
                    MAX_RESULT_CHARS = 20000
                    truncated = result_content[:MAX_RESULT_CHARS]
                    if len(result_content) > MAX_RESULT_CHARS:
                        truncated += f"\n\n[... truncated, {len(result_content) - MAX_RESULT_CHARS} chars omitted]"

                    worker_msg = (
                        f"[Worker Result — {event.intent}]\n"
                        f"{truncated}"
                    )
                    await self._claude._append_and_persist_async(
                        chat_id=dispatcher_chat_id,
                        role="assistant",
                        content=worker_msg,
                        model=event.model,
                        msg_type="worker_result",
                    )
                    logger.info(f"[DeepWorker] Injected result into dispatcher history for {dispatcher_chat_id}")
                except Exception as inject_err:
                    logger.warning(f"[DeepWorker] Failed to inject result into history: {inject_err}")

            # Callback removed: task:completed delivers full result directly to frontend.
            # Chaining is handled deterministically via follow_up in structured worker responses.

            # follow_up chaining: if set, emit as new ActionIntent
            if follow_up_action and self._orchestrator and session_id:
                try:
                    follow_up_intent = ActionIntent(
                        task_id=f"followup-{uuid4().hex[:8]}",
                        session_id=session_id,
                        intent="follow_up",
                        summary=follow_up_action,
                        model=event.model,
                        data={
                            **event.data,
                            "follow_up_prompt": follow_up_action,
                            "parent_task_id": event.task_id,
                            "dispatcher_chat_id": dispatcher_chat_id,
                        },
                        callback_depth=event.callback_depth + 1,
                    )
                    await event_bus_registry.get_or_create(session_id).emit(follow_up_intent)
                    logger.info(f"[DeepWorker] follow_up chaining: '{follow_up_action[:80]}'")
                except Exception as fu_err:
                    logger.warning(f"[DeepWorker] follow_up emit failed: {fu_err}")

            logger.info(f"[DeepWorker] Task {event.task_id} completed: {event.intent}")

        except Exception as e:
            logger.error(f"[DeepWorker] Task {event.task_id} failed: {e}")
            _wss.update_status(event.task_id, "failed", str(e)[:500])
            await self._ledger_update(event.task_id, "failed", error=str(e)[:500])
            try:
                await self._send_task_event("task:completed", event.task_id, {
                    "intent": event.intent,
                    "summary": event.summary,
                    "result": str(e),
                    "success": False,
                    "sessionId": event.session_id,
                    "projectId": event.data.get("project_id"),
                })
            except Exception:
                pass
        finally:
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
        try:
            await self._ws.send_json(message)
            # Broadcast to other devices for cross-device worker visibility
            from app.services.ws_broadcast import ws_broadcast
            await ws_broadcast.emit_to_others(self._ws, event_type, {"taskId": task_id, **payload})
        except Exception as e:
            logger.warning(f"[DeepWorkerPool] Failed to send {event_type} via WS: {e}")
            # Store final results for later delivery (skip started/progress — only final matters)
            if event_type in ("task:completed", "task:cancelled", "task:timeout"):
                session_id = payload.get("sessionId", self._bus.session_id)
                if session_id:
                    try:
                        await pending_store.store(session_id, message)
                        logger.info(f"[DeepWorkerPool] Stored pending result for task {task_id}")
                    except Exception as store_err:
                        logger.error(f"[DeepWorkerPool] Failed to store pending result: {store_err}")


    # ------------------------------------------------------------------
    # Worker Ledger DB helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _ledger_insert(
        task_id: str,
        session_id: str,
        project_id: str | None,
        action: str,
        description: str,
        model: str,
    ) -> None:
        """Insert a new row into worker_tasks with status='running'."""
        try:
            from app.database import async_session, WorkerTask, utcnow
            async with async_session() as db:
                row = WorkerTask(
                    id=task_id,
                    session_id=session_id,
                    project_id=project_id,
                    action=action,
                    description=description[:500],
                    model=model,
                    status="running",
                    started_at=utcnow(),
                    created_at=utcnow(),
                )
                db.add(row)
                await db.commit()
                logger.debug(f"[Ledger] Inserted task {task_id} status=running")
        except Exception as e:
            logger.warning(f"[Ledger] Failed to insert task {task_id}: {e}")

    @staticmethod
    async def _ledger_update(
        task_id: str,
        status: str,
        result_summary: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update a worker_tasks row with final status."""
        try:
            from app.database import async_session, WorkerTask, utcnow
            from sqlalchemy import select
            async with async_session() as db:
                result = await db.execute(
                    select(WorkerTask).where(WorkerTask.id == task_id)
                )
                row = result.scalar_one_or_none()
                if row:
                    row.status = status
                    if result_summary is not None:
                        row.result_summary = result_summary[:500]
                    if error is not None:
                        row.error = error[:500]
                    if status in ("done", "failed", "cancelled"):
                        row.completed_at = utcnow()
                    await db.commit()
                    logger.debug(f"[Ledger] Updated task {task_id} → {status}")
        except Exception as e:
            logger.warning(f"[Ledger] Failed to update task {task_id}: {e}")


class ChatOrchestrator:
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

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def handle_message(
        self,
        websocket: WebSocket,
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
        """
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
        analyzer_enabled = layers.get("analyzer", False)

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
        if session_id:
            # Guard: don't fire delegates if the response contains a question
            # (model is asking for confirmation — wait for user to answer first)
            _response_for_guard = ""
            _guard_history = self._claude.get_history(chat_id)
            for _msg in reversed(_guard_history):
                if _msg.get("role") == "assistant":
                    _response_for_guard = _msg.get("content", "")
                    break
            _QUESTION_KEYWORDS = [
                "tu veux", "veux-tu", "voulez-vous", "devrais-je",
                "want me to", "shall i", "should i", "do you want",
            ]
            _response_lower = _response_for_guard.lower()
            _has_question = "?" in _response_lower and any(
                kw in _response_lower for kw in _QUESTION_KEYWORDS
            )

            # Check for native tool_use delegates FIRST (collected by claude_service)
            native_delegates = self._claude.pop_pending_delegates(chat_id)

            if _has_question:
                logger.info("[Orchestrator] Delegate guard: question detected in response — skipping delegate emission")

            # Workers spawned from a callback response carry incremented depth
            child_callback_depth = callback_depth + 1 if is_callback else callback_depth

            if not _has_question and native_delegates:
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
            elif not _has_question:
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
                )
            )
            _bg_tasks.append(_t)

        # handle_message returns HERE — WS handler is free for next message
        logger.debug("[Orchestrator] handle_message returning (delegates + analyzer in background)")
        return _bg_tasks

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def reset_session(self, chat_id: str) -> None:
        """Clear conversation history for a given chat_id."""
        if chat_id in self._claude._histories:
            self._claude._histories[chat_id] = []
        session_store.clear_session(chat_id)

    # ------------------------------------------------------------------
    # Active Workers Context (for dispatcher system prompt injection)
    # ------------------------------------------------------------------

    def get_active_workers_context(self, session_id: str | None) -> str:
        """Build a text block describing active/recently-completed workers.

        Injected into the dispatcher's system prompt so it knows what's
        running in the background before responding.
        """
        if not session_id:
            return ""

        pool = self._worker_pools.get(session_id)
        if not pool:
            return ""

        info = pool.get_active_tasks()
        active = info["active"]
        completed = info["completed"]

        if not active and not completed:
            return ""

        lines = []
        if active:
            lines.append("[Active Workers]")
            for t in active:
                desc = f' — "{t["description"]}"' if t["description"] else ""
                lines.append(
                    f"- task-{t['task_id']}: {t['action']} ({t['model']}) "
                    f"— running {t['running_seconds']}s{desc}"
                )
        if completed:
            lines.append("[Recently Completed]")
            for t in completed:
                lines.append(
                    f"- task-{t['task_id']}: {t['action']} ({t['model']}) "
                    f"— completed {t['seconds_ago']}s ago — {t['result']}"
                )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Event Bus: Worker pool lifecycle
    # ------------------------------------------------------------------

    def start_worker_pool(self, session_id: str, websocket: WebSocket) -> DeepWorkerPool:
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
            if ws is None or ws.client_state != WebSocketState.CONNECTED:
                orphan_ids.append(sid)

        for orphan_sid in orphan_ids:
            logger.info(f"[ChatOrchestrator] Cleaning up orphan worker pool: {orphan_sid}")
            orphan_pool = self._worker_pools.pop(orphan_sid, None)
            if orphan_pool and not orphan_pool._stopped:
                asyncio.create_task(orphan_pool.stop())
            event_bus_registry.remove(orphan_sid)

        existing = self._worker_pools.get(session_id)
        if existing and not existing._stopped:
            # Pool is alive: just update the WebSocket so in-flight workers
            # can deliver results to the new connection.
            existing.update_websocket(websocket)
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

            project_slug = None
            if project_name:
                import re
                slug = project_name.lower().strip()
                slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
                project_slug = slug or None

            stored = await memory.auto_extract_memories(
                chat_id=chat_id,
                messages=recent,
                project_slug=project_slug,
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
        """Wrapper for analyzer that catches errors in background."""
        try:
            await self._run_analyzer_layer(
                websocket=websocket,
                analyzer_enabled=True,
                analyzer_task=analyzer_task,
                project_id=project_id,
                session_id=session_id,
                send_model_status=send_model_status,
            )
        except Exception as e:
            logger.error(f"[Orchestrator] Background analyzer failed: {e}", exc_info=True)

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

        bus = event_bus_registry.get_or_create(session_id)

        for data in worker_delegates:
            intent = data.get("action", "unknown")
            summary = data.get("summary", data.get("description", ""))
            complexity = data.get("complexity", "simple")
            model = data.get("model", "sonnet")
            if model not in ("haiku", "sonnet", "opus"):
                model = "sonnet"

            # Auto-upgrade model for coding tasks
            _CODING_KEYWORDS = {"fix", "implement", "refactor", "write", "code", "debug", "build", "create function", "add feature", "patch"}
            description_lower = data.get("description", "").lower()
            if any(kw in description_lower for kw in _CODING_KEYWORDS):
                if model == "haiku":
                    original_model = model
                    model = "sonnet"
                    logger.info(f"[ModelUpgrade] Upgraded {original_model} → sonnet (coding task detected: {intent})")

            task_id = f"task-{uuid4().hex[:8]}"

            # Classify intent type (same logic as XML path)
            if complexity == "complex" or model == "opus":
                intent_type = "complex"
            elif intent in ("create_card", "move_card", "update_card") or model == "haiku":
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
                    "project_id": project_id,
                    "card_id": card_id,
                    "dispatcher_chat_id": chat_id,
                    **data,  # Include all fields from delegate_action
                },
                session_id=session_id,
                complexity=complexity,
                model=model,
                callback_depth=callback_depth,
            )

            await bus.emit(event)
            logger.info(f"[Orchestrator] Emitted native delegate: {intent} → task {task_id} (model={model}, cb_depth={callback_depth})")

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
            # Safety net: detect promised actions without delegate blocks
            await self._detect_missing_delegate(
                fast_response=fast_response,
                session_id=session_id,
                websocket=websocket,
                project_name=project_name,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_id=project_id,
                chat_id=chat_id,
            )
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

        bus = event_bus_registry.get_or_create(session_id)

        for data in worker_delegates:
            try:
                intent = data.get("intent", data.get("action", "unknown"))
                summary = data.get("summary", data.get("description", ""))
                complexity = data.get("complexity", "simple")

                # Extract model from delegate JSON (haiku/sonnet/opus)
                model = data.get("model", "sonnet")
                if model not in ("haiku", "sonnet", "opus"):
                    model = "sonnet"

                # Auto-upgrade model for coding tasks (XML path)
                _CODING_KEYWORDS = {"fix", "implement", "refactor", "write", "code", "debug", "build", "create function", "add feature", "patch"}
                description_lower = data.get("description", "").lower()
                if any(kw in description_lower for kw in _CODING_KEYWORDS):
                    if model == "haiku":
                        original_model = model
                        model = "sonnet"
                        logger.info(f"[ModelUpgrade] Upgraded {original_model} → sonnet (coding task detected: {intent})")

                task_id = f"task-{uuid4().hex[:8]}"

                # Classify intent type
                if complexity == "complex" or model == "opus":
                    intent_type = "complex"
                elif intent in ("create_card", "move_card", "update_card") or model == "haiku":
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
                        "project_id": project_id,
                        "card_id": card_id,
                        "dispatcher_chat_id": chat_id,
                        **data,  # Include original delegate data
                    },
                    session_id=session_id,
                    complexity=complexity,
                    model=model,
                    callback_depth=callback_depth,
                )

                await bus.emit(event)
                logger.info(f"[Orchestrator] Emitted delegate: {intent} → task {task_id} (cb_depth={callback_depth})")

            except Exception as e:
                logger.warning(f"[Orchestrator] Failed to emit delegate: {e}")

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
            except Exception:
                pass

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

                await self.handle_message(
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
                    except Exception:
                        pass
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
        except Exception:
            pass

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
        except Exception:
            pass

        # Broadcast card change
        if result.get("success"):
            try:
                from app.services.ws_broadcast import ws_broadcast
                ws_broadcast.emit_sync("cards:changed", {
                    "projectId": project_id or "system-main",
                })
            except Exception:
                pass

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
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Safety Net: Detect missing delegates
    # ------------------------------------------------------------------

    # Action-intent phrases — if Voxy says these but no <delegate> was emitted,
    # the safety net kicks in.
    _ACTION_INTENT_PHRASES_FR = re.compile(
        r"je\s+vais|je\s+te\s+cr[ée]e|je\s+cherche|je\s+lance|laisse[- ]moi"
        r"|je\s+m['\u2019]en\s+occupe|je\s+regarde|je\s+v[ée]rifie",
        re.IGNORECASE,
    )
    _ACTION_INTENT_PHRASES_EN = re.compile(
        r"let\s+me|i['\u2019]ll\b|i\s+will\b|creating\b|searching\b"
        r"|looking\s+into|checking\b",
        re.IGNORECASE,
    )
    _ACTION_NOUNS = re.compile(
        r"carte|card|recherche|search|fichier|file|commande|command",
        re.IGNORECASE,
    )

    def _has_action_intent(self, text: str) -> bool:
        """Return True if the text contains action-intent signals."""
        if self._ACTION_INTENT_PHRASES_FR.search(text):
            return True
        if self._ACTION_INTENT_PHRASES_EN.search(text):
            return True
        return False

    async def _detect_missing_delegate(
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
    ) -> None:
        """Safety net: if no <delegate> was found but the response promises an action,
        use a quick Haiku call to generate the missing delegate and emit it."""
        from app.config import get_settings
        settings = get_settings()
        if not settings.delegate_safety_net_enabled:
            return

        if not self._has_action_intent(fast_response):
            logger.debug("[SafetyNet] No action-intent phrases detected, skipping")
            return

        logger.info("[SafetyNet] Detected action-intent without delegate — auto-generating")

        raw_json = await self._claude.safety_net_generate_delegate(fast_response)
        if not raw_json:
            logger.warning("[SafetyNet] Haiku returned empty response, aborting")
            return

        # Strip markdown fences if Haiku wraps it
        cleaned = raw_json.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as e:
            logger.warning(f"[SafetyNet] Failed to parse Haiku JSON: {e} — raw: {cleaned[:200]}")
            return

        intent = data.get("intent", data.get("action", "unknown"))
        summary = data.get("summary", data.get("description", ""))
        complexity = data.get("complexity", "simple")
        model = data.get("model", "sonnet")
        if model not in ("haiku", "sonnet", "opus"):
            model = "sonnet"

        # Auto-upgrade model for coding tasks (safety-net path)
        _CODING_KEYWORDS = {"fix", "implement", "refactor", "write", "code", "debug", "build", "create function", "add feature", "patch"}
        description_lower = data.get("description", "").lower()
        if any(kw in description_lower for kw in _CODING_KEYWORDS):
            if model == "haiku":
                original_model = model
                model = "sonnet"
                logger.info(f"[ModelUpgrade] Upgraded {original_model} → sonnet (coding task detected: {intent})")

        task_id = f"task-{uuid4().hex[:8]}"

        if complexity == "complex" or model == "opus":
            intent_type = "complex"
        elif intent in ("create_card", "move_card", "update_card") or model == "haiku":
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
                "project_id": project_id,
                "card_id": card_id,
                "dispatcher_chat_id": chat_id,
                "auto_recovered": True,
                **data,
            },
            session_id=session_id,
            complexity=complexity,
            model=model,
        )

        # Ensure worker pool is running (also updates WS on reconnect)
        self.start_worker_pool(session_id, websocket)

        bus = event_bus_registry.get_or_create(session_id)
        await bus.emit(event)
        logger.info(f"[SafetyNet] Emitted auto-recovered delegate: {intent} → task {task_id}")

        # Notify frontend about the auto-recovery
        try:
            await websocket.send_json({
                "type": "delegate:auto_recovered",
                "payload": {"intent": intent, "taskId": task_id, "summary": summary},
                "timestamp": int(time.time() * 1000),
            })
        except Exception as e:
            logger.warning(f"[SafetyNet] Failed to send auto_recovered WS event: {e}")

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
                from app.database import async_session, Project, Card, Sprint
                from sqlalchemy import select
                async with async_session() as db:
                    result = await db.execute(select(Project).where(Project.id == project_id))
                    proj = result.scalar_one_or_none()
                    if proj:
                        # Fetch cards for this project (for dynamic state counts)
                        cards_result = await db.execute(
                            select(Card).where(Card.project_id == project_id)
                        )
                        proj_cards = cards_result.scalars().all()
                        cards_list = [
                            {
                                "title": c.title,
                                "status": c.status or "idea",
                                "updated_at": str(c.updated_at) if hasattr(c, "updated_at") and c.updated_at else "",
                            }
                            for c in proj_cards
                        ]

                        # Fetch active sprint
                        sprint_result = await db.execute(
                            select(Sprint).where(
                                Sprint.project_id == project_id,
                                Sprint.status == "active",
                            )
                        )
                        active_sprint = sprint_result.scalar_one_or_none()
                        sprint_name = active_sprint.name if active_sprint else None

                        project_context = {
                            "id": proj.id,
                            "title": proj.title,
                            "description": proj.description or "",
                            "tech_stack": getattr(proj, "tech_stack", "") or "",
                            "github_url": proj.github_url or "",
                            "cards": cards_list,
                            "active_sprint_name": sprint_name,
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
                                "status": c.status or "idea",
                                "priority": str(c.priority) if c.priority is not None else "medium",
                                "agent_type": getattr(c, "agent_type", None) or "general",
                                "assignee": getattr(c, "assignee", None),
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
                except Exception:
                    pass

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
            include_long_term=False,
            include_daily=True,
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
        except Exception:
            pass

        logger.info(f"[ToolCallFallback] Async follow-up complete ({len(followup_full)} chars)")

    # ------------------------------------------------------------------
    # Internal: Layer 1 — Fast (streaming)
    # ------------------------------------------------------------------

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
            except Exception:
                pass
            try:
                await websocket.send_json({
                    "type": "chat:error",
                    "payload": {"messageId": message_id, "error": str(e), "sessionId": session_id},
                    "timestamp": int(time.time() * 1000),
                })
            except Exception:
                pass
            return False
        finally:
            # Safety net: always reset to idle even if WS is closed
            try:
                await send_model_status("fast", "idle")
            except Exception:
                logger.debug("[Layer1-Fast] Could not send final idle status (WS likely closed)")

    # ------------------------------------------------------------------
    # Internal: Layer 2 — Deep Chat (streaming, direct response)
    # ------------------------------------------------------------------

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
            except Exception:
                pass
            try:
                await websocket.send_json({
                    "type": "chat:error",
                    "payload": {"messageId": message_id, "error": str(e), "sessionId": session_id},
                    "timestamp": int(time.time() * 1000),
                })
            except Exception:
                pass
            return False
        finally:
            # Safety net: always reset to idle even if WS is closed
            try:
                await send_model_status("deep", "idle")
            except Exception:
                logger.debug("[Layer-Deep-Chat] Could not send final idle status (WS likely closed)")

    # ------------------------------------------------------------------
    # Internal: Layer 3 — Analyzer (card suggestions)
    # ------------------------------------------------------------------

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
