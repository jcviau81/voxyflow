"""DeepWorkerPool — async worker pool that consumes ActionIntent events from a SessionEventBus.

Extracted from chat_orchestration.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import WebSocket

from app.services.claude_service import ClaudeService
from app.services.event_bus import ActionIntent, SessionEventBus, event_bus_registry
from app.services.pending_results import pending_store
from app.services.worker_session_store import get_worker_session_store
from app.services.worker_supervisor import get_worker_supervisor
from app.routes.settings import get_default_worker_model

if TYPE_CHECKING:
    from app.services.chat_orchestration import ChatOrchestrator

# Intents that use lightweight worker (minimal prompt, no personality/context)
LIGHTWEIGHT_INTENTS = {
    "enrich", "enrich_card", "card.enrich",
    "summarize", "summarize_card",
    "research", "web_search", "search",
    "code_review", "review",
}

logger = logging.getLogger("voxyflow.orchestration")


def _format_result_for_card(text: str) -> str:
    """Convert raw LLM result to clean human-readable text for card injection.

    If the result is a JSON object/array, flatten it into readable key: value lines
    instead of injecting raw JSON into the card description.
    """
    stripped = text.strip()
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
        return text

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


class DeepWorkerPool:
    """Pool of async workers that consume events from a SessionEventBus
    and execute them via the Deep layer (Opus) with full tool access.

    Each session gets its own pool. Max workers controls concurrency.
    """

    MAX_WORKERS = 3
    # No hard task timeout — stall detector handles idle workers (30min idle = cancel)

    COMPLETED_TASK_TTL = 300  # seconds to keep completed tasks visible (5 min)

    def __init__(
        self,
        claude_service: ClaudeService,
        bus: SessionEventBus,
        websocket: WebSocket,
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
        self._semaphore = asyncio.Semaphore(self.MAX_WORKERS)
        self._result_contents: dict[str, str] = {}  # task_id → actual result content
        self._callback_lock = asyncio.Lock()  # Serialize worker→dispatcher callbacks
        self._task_tool_events: dict[str, list[dict]] = {}  # task_id → bounded tool event buffer
        self._MAX_TOOL_EVENTS = 50
        self._task_message_queues: dict[str, asyncio.Queue] = {}  # task_id → steer queue
        self._stopped = False

    def start(self) -> None:
        """Start listening on the bus for events."""
        self._listener_task = asyncio.create_task(self._listen_loop())
        self._cleanup_task = asyncio.create_task(self._stale_cleanup_loop())
        logger.info(f"[DeepWorkerPool] Started for session {self._bus.session_id}")

    def update_websocket(self, websocket: WebSocket) -> None:
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
        # Cancel active asyncio tasks and update DB records
        cancelled_ids = list(self._active_tasks.keys())
        for task_id, task in list(self._active_tasks.items()):
            task.cancel()
        self._active_tasks.clear()
        # Mark cancelled tasks in the DB ledger
        for task_id in cancelled_ids:
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
        """
        task = self._active_tasks.get(task_id)
        if not task:
            logger.warning(f"[DeepWorkerPool] cancel_task: task {task_id} not found")
            return False

        logger.info(f"[DeepWorkerPool] Cancelling task {task_id}")

        self._active_tasks.pop(task_id, None)
        task.cancel()

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass

        self._semaphore.release()

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
            "tool_count": len(events) if events else 0,
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
                    "task_id": task_id[:8],
                    "action": meta["action"],
                    "model": meta["model"],
                    "description": meta["description"],
                    "running_seconds": elapsed,
                    "tool_count": len(tool_events) if tool_events else 0,
                    "last_tool": tool_events[-1]["tool"] if tool_events else None,
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
                "success": t.get("success", True),
            })

        return {"active": active, "completed": completed}

    async def _summarize_result(self, result: str, intent: str, max_chars: int = 2000) -> str:
        """Summarize a large worker result for dispatcher injection.

        Results <= max_chars pass through unchanged.
        Larger results are summarized via Haiku with truncation fallback.
        """
        if len(result) <= max_chars:
            return result

        try:
            summary = await self._claude._call_api(
                model=self._claude.haiku_model,
                system=(
                    "Summarize this worker task result concisely. "
                    "Preserve key facts, IDs, names, and outcomes. "
                    "Output only the summary, max 500 chars."
                ),
                messages=[{
                    "role": "user",
                    "content": f"Task: {intent}\n\nResult:\n{result[:8000]}",
                }],
                client=self._claude.haiku_client,
                client_type=self._claude.haiku_client_type,
                use_tools=False,
                layer="analyzer",
                chat_level="general",
            )
            if summary and len(summary.strip()) > 20:
                return summary.strip()
        except Exception as e:
            logger.warning(f"[DeepWorker] Haiku summarization failed: {e}")

        # Fallback: smart truncation
        return (
            result[:500]
            + f"\n\n[... {len(result) - 800} chars omitted ...]\n\n"
            + result[-300:]
        )

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
                await self._semaphore.acquire()
                self._task_meta[event.task_id] = {
                    "action": event.intent or "unknown",
                    "model": event.model or get_default_worker_model(),
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
        """Cleanup when a task completes. Idempotent."""
        if self._stopped:
            return
        self._task_message_queues.pop(task_id, None)
        removed = self._active_tasks.pop(task_id, None)
        if removed is not None:
            self._semaphore.release()
            meta = self._task_meta.pop(task_id, None)
            if meta:
                success = True
                result = "success"
                if removed.cancelled():
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
                    "completed_at": time.time(),
                    "result": actual_result,
                    "success": success,
                })

            # Schedule tool event buffer cleanup after 60s
            def _cleanup_tool_events(tid: str = task_id) -> None:
                self._task_tool_events.pop(tid, None)

            try:
                loop = asyncio.get_running_loop()
                loop.call_later(60, _cleanup_tool_events)
            except RuntimeError:
                _cleanup_tool_events()

    async def _execute_event(self, event: ActionIntent) -> None:
        """Execute a single ActionIntent via model-routed worker (haiku/sonnet/opus)."""
        try:
            _wss = get_worker_session_store()
            _task_card_id = event.data.get("card_id")
            _wss.register(
                task_id=event.task_id,
                session_id=event.session_id or self._bus.session_id,
                chat_id=event.data.get("dispatcher_chat_id"),
                project_id=event.data.get("project_id"),
                card_id=_task_card_id,
                model=event.model or get_default_worker_model(),
                intent=event.intent or "unknown",
                summary=event.summary or "",
            )

            await self._ledger_insert(
                task_id=event.task_id,
                session_id=event.session_id or self._bus.session_id,
                project_id=event.data.get("project_id"),
                card_id=_task_card_id,
                action=event.intent or "unknown",
                description=(event.summary or "")[:500],
                model=event.model or get_default_worker_model(),
            )

            await self._send_task_event("task:started", event.task_id, {
                "intent": event.intent,
                "summary": event.summary,
                "complexity": event.complexity,
                "model": event.model,
                "sessionId": event.session_id,
                "chatId": event.data.get("dispatcher_chat_id"),
                "cardId": _task_card_id,
                "projectId": event.data.get("project_id"),
            })

            logger.info(f"[DeepWorker] Executing task {event.task_id}: {event.intent} (model={event.model})")

            intent_lower = (event.intent or "unknown").lower()
            is_move_or_update = any(kw in intent_lower for kw in [
                "move", "update", "change_status", "complete", "finish",
                "start_work", "mark_done", "mark_complete"
            ])

            execution_prompt = (
                f"Execute this action:\n"
                f"Intent: {event.intent}\n"
                f"Summary: {event.summary}\n"
                f"Task ID: {event.task_id}\n"
                f"\nWhen done, call task.complete(task_id=\"{event.task_id}\", summary=\"<ACTUAL RESULTS HERE>\", status=\"success|partial|failed\").\n"
                f"CRITICAL: The summary MUST contain the concrete output — full stdout from commands, "
                f"actual data retrieved, real values returned. Never write just 'Done' or 'Task complete'. "
                f"The user only sees the summary, so include everything they need.\n"
            )

            if is_move_or_update:
                execution_prompt += (
                    "\n⚠️ IMPORTANT: This is a MOVE/UPDATE operation on EXISTING cards.\n"
                    "1. First call card.list to find the existing card(s) by name\n"
                    "2. Then call card.move (for status change) or card.update (for content change)\n"
                    "3. Do NOT create new cards — the cards already exist\n\n"
                )
            if event.data:
                action_data = {k: v for k, v in event.data.items()
                               if k not in ("project_context", "card_context")}
                execution_prompt += f"Data: {json.dumps(action_data)}\n"

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

            task_chat_id = f"task-{event.task_id}"

            tool_events = self._task_tool_events.get(event.task_id)
            await self._send_task_event("task:progress", event.task_id, {
                "status": "executing",
                "sessionId": event.session_id,
                "toolCount": len(tool_events) if tool_events else 0,
            })

            chat_level = event.data.get("chat_level", "general")
            if chat_level == "general":
                intent_lower = (event.intent or "unknown").lower()
                if (
                    event.data.get("project_id")
                    or "project" in intent_lower
                    or "card" in intent_lower
                    or "main_board" in intent_lower
                    or "mainboard" in intent_lower
                ):
                    chat_level = "project"

            supervisor = get_worker_supervisor()
            supervisor.register_task(event.task_id)
            cancel_event = asyncio.Event()
            message_queue: asyncio.Queue[str] = asyncio.Queue()
            self._task_message_queues[event.task_id] = message_queue

            async def _tool_callback(tool_name: str, arguments: dict, result: dict):
                supervisor.record_tool_call(event.task_id, tool_name, arguments)

                # Buffer tool event for dispatcher peek
                tool_buf = self._task_tool_events.setdefault(event.task_id, [])
                tool_buf.append({"tool": tool_name, "at": time.time()})
                if len(tool_buf) > self._MAX_TOOL_EVENTS:
                    tool_buf[:] = tool_buf[-self._MAX_TOOL_EVENTS:]

                if supervisor.check_repetition(event.task_id):
                    logger.warning(f"[Supervisor] Cancelling task {event.task_id} — repetitive loop detected")
                    supervisor.mark_problem(event.task_id, "repetitive_loop")
                    cancel_event.set()

                tool_count = len(self._task_tool_events.get(event.task_id, []))
                await self._send_task_event("tool:executed", event.task_id, {
                    "tool": tool_name,
                    "args": arguments,
                    "result": result,
                    "sessionId": event.session_id,
                    "toolCount": tool_count,
                })

            tool_callback = _tool_callback

            async def _stall_monitor():
                STALL_THRESHOLD = 1800   # 30 minutes idle before cancel
                WARNING_THRESHOLD = 1500  # 25 minutes idle before warning
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

            try:
                # Route to lightweight or full worker based on intent
                is_lightweight = (event.intent or "").lower() in LIGHTWEIGHT_INTENTS
                if is_lightweight:
                    logger.info(f"[LightWorker] Routing {event.task_id} to lightweight worker ({event.intent})")
                    result_content = await self._claude.execute_lightweight_task(
                        chat_id=event.data.get("dispatcher_chat_id") or task_chat_id,
                        prompt=execution_prompt,
                        model=event.model,
                        project_id=event.data.get("project_id"),
                        tool_callback=tool_callback,
                        cancel_event=cancel_event,
                        message_queue=message_queue,
                        session_id=event.session_id or "",
                        task_id=event.task_id,
                    )
                else:
                    result_content = await self._claude.execute_worker_task(
                        chat_id=event.data.get("dispatcher_chat_id") or task_chat_id,
                        prompt=execution_prompt,
                        model=event.model,
                        chat_level=chat_level,
                        project_context=event.data.get("project_context"),
                        card_context=event.data.get("card_context"),
                        project_id=event.data.get("project_id"),
                        tool_callback=tool_callback,
                        cancel_event=cancel_event,
                        message_queue=message_queue,
                        session_id=event.session_id or "",
                        task_id=event.task_id,
                    )
            except asyncio.CancelledError:
                logger.info(f"[DeepWorker] Task {event.task_id} was cancelled")
                _wss.update_status(event.task_id, "cancelled")
                await self._ledger_update(event.task_id, "cancelled")
                return
            finally:
                stall_task.cancel()

            if not result_content:
                try:
                    task_history = self._claude.get_history(task_chat_id)
                    for msg in reversed(task_history):
                        if msg.get("role") == "assistant":
                            raw = msg.get("content", "")
                            if isinstance(raw, list):
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
                result_content = event.summary
                logger.warning(
                    f"[DeepWorker] result_content was empty for task "
                    f"{event.task_id} — fell back to event.summary"
                )

            if not supervisor.is_completed(event.task_id):
                # Auto-complete: worker finished but forgot to call task.complete
                auto_summary = result_content or event.summary or "Task completed (auto-closed)"
                supervisor.mark_completed(event.task_id, auto_summary, "success")
                logger.info(
                    f"[Supervisor] Task {event.task_id} auto-completed (worker did not call task.complete)"
                )
            else:
                task_status = supervisor.get_status(event.task_id)
                completion_summary = task_status.get("completion_summary") if task_status else None
                if completion_summary and len(completion_summary) > len(result_content or ""):
                    logger.info(
                        f"[DeepWorker] Using completion_summary ({len(completion_summary)} chars) "
                        f"over result_content ({len(result_content or '')} chars)"
                    )
                    result_content = completion_summary

            follow_up_action = None
            try:
                parsed_result = json.loads(result_content.strip())
                if isinstance(parsed_result, dict) and "follow_up" in parsed_result:
                    follow_up_action = parsed_result["follow_up"]
                    result_content = parsed_result.get("result", result_content)
                    logger.info(f"[DeepWorker] follow_up extracted from structured result: '{follow_up_action[:80]}'")
            except (json.JSONDecodeError, ValueError):
                pass  # Not JSON, no follow_up

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
                            await self._send_task_event("tool:executed", event.task_id, {
                                "tool": "voxyflow.card.update",
                                "args": {"card_id": card_id, "project_id": event.data.get("project_id")},
                                "result": {"success": True},
                                "sessionId": event.session_id,
                            })
                            # Broadcast card change so all frontends refresh
                            from app.services.ws_broadcast import ws_broadcast
                            ws_broadcast.emit_sync("cards:changed", {
                                "projectId": event.data.get("project_id"),
                                "cardId": card_id,
                            })
                except Exception as append_err:
                    logger.warning(f"[DeepWorker] Failed to auto-append result to card: {append_err}")

            if result_content:
                self._result_contents[event.task_id] = result_content or ""

            # Persist the full raw result to a .md artifact so the dispatcher
            # can retrieve verbatim output via workers_read_artifact, even
            # though the callback only carries a Haiku summary.
            artifact_path: str | None = None
            if result_content:
                from app.services.worker_artifact_store import write_artifact
                artifact_path = write_artifact(
                    event.task_id,
                    result_content,
                    intent=event.intent,
                    model=event.model,
                    project_id=event.data.get("project_id"),
                    card_id=event.data.get("card_id"),
                    session_id=event.session_id,
                    status="success",
                )

            _wss.update_status(
                event.task_id,
                "completed",
                result_content or "",
                artifact_path=artifact_path,
            )

            await self._ledger_update(
                event.task_id, "done",
                result_summary=result_content or "",
            )

            # Record completion in session timeline
            if event.session_id:
                from app.services.orchestration.session_timeline import get_timeline
                get_timeline().record(
                    event.session_id, "completed", event.intent or "unknown",
                    task_id=event.task_id, model=event.model,
                    summary=(result_content or "")[:120],
                )

            await self._send_task_event("task:completed", event.task_id, {
                "intent": event.intent,
                "summary": event.summary,
                "result": result_content,
                "success": True,
                "sessionId": event.session_id,
                "projectId": event.data.get("project_id"),
                "cardId": event.data.get("card_id"),
                "artifactPath": artifact_path,
            })

            # --- Persist worker result to session store (survives page refresh) ---
            if result_content and event.session_id:
                try:
                    from app.services.session_store import session_store as _ss
                    _ss.save_message(event.session_id, {
                        "role": "assistant",
                        "content": result_content,
                        "model": "worker",
                        "type": "worker_result",
                        "task_id": event.task_id,
                        "intent": event.intent,
                    })
                except Exception as _persist_err:
                    logger.warning(f"[DeepWorker] Failed to persist worker result: {_persist_err}")

            # --- Notify dispatcher: embed result in a single user message ---
            # Previously injected result as role="assistant" which caused consecutive
            # same-role messages (Anthropic API rejects). Now we merge the result
            # directly into the callback user message for proper role alternation.
            dispatcher_chat_id = event.data.get("dispatcher_chat_id")
            if dispatcher_chat_id and self._orchestrator:
                try:
                    from starlette.websockets import WebSocketState
                    if self._ws.client_state == WebSocketState.CONNECTED:
                        async with self._callback_lock:
                            summarized = result_content or "(no output)"
                            if result_content:
                                summarized = await self._summarize_result(result_content, event.intent or "")

                            # If the raw result is materially larger than the
                            # summary the dispatcher is about to see, advertise
                            # the artifact tool so it knows it can pull the
                            # verbatim output (file contents, command stdout,
                            # logs, etc.) when needed.
                            artifact_hint = ""
                            raw_len = len(result_content or "")
                            if artifact_path and raw_len > len(summarized) + 200:
                                artifact_hint = (
                                    f"\n[Full raw output ({raw_len} chars) available — "
                                    f"call voxyflow.workers.read_artifact(task_id=\"{event.task_id}\") "
                                    f"to retrieve verbatim. Use offset/length for paging.]"
                                )

                            callback_msg = (
                                f"[SYSTEM: Worker '{event.intent}' (task {event.task_id}) completed successfully.]\n\n"
                                f"--- Worker Result ---\n"
                                f"{summarized}\n"
                                f"--- End Result ---{artifact_hint}\n\n"
                                f"Present this result to the user naturally and decide if follow-up actions are needed."
                            )
                            callback_message_id = f"worker-cb-{uuid4().hex[:8]}"
                            logger.info(f"[DeepWorker] Re-triggering dispatcher after {event.intent}")

                            await self._orchestrator.handle_message(
                                websocket=self._ws,
                                content=callback_msg,
                                message_id=callback_message_id,
                                chat_id=dispatcher_chat_id,
                                project_id=event.data.get("project_id"),
                                chat_level="project" if event.data.get("project_id") else "general",
                                session_id=event.session_id,
                                is_callback=True,
                                callback_depth=1,
                            )
                except Exception as cb_err:
                    logger.warning(f"[DeepWorker] Dispatcher callback failed: {cb_err}", exc_info=True)

            if follow_up_action and self._orchestrator and event.session_id:
                try:
                    follow_up_intent = ActionIntent(
                        task_id=f"followup-{uuid4().hex[:8]}",
                        session_id=event.session_id,
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
                    await event_bus_registry.get_or_create(event.session_id).emit(follow_up_intent)
                    logger.info(f"[DeepWorker] follow_up chaining: '{follow_up_action[:80]}'")
                except Exception as fu_err:
                    logger.warning(f"[DeepWorker] follow_up emit failed: {fu_err}")

            logger.info(f"[DeepWorker] Task {event.task_id} completed: {event.intent}")

            try:
                from app.services.session_store import session_store as _ss
                _ss.delete_session(task_chat_id)
                self._claude._histories.pop(task_chat_id, None)
                logger.info(f"[DeepWorker] Cleaned up worker session {task_chat_id}")
            except Exception as _cleanup_err:
                logger.warning(f"[DeepWorker] Session cleanup failed: {_cleanup_err}")

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
                    "cardId": event.data.get("card_id"),
                })
            except Exception:
                pass

            # Record failure in session timeline
            if event.session_id:
                from app.services.orchestration.session_timeline import get_timeline
                get_timeline().record(
                    event.session_id, "failed", event.intent or "unknown",
                    task_id=event.task_id, model=event.model,
                    summary=str(e)[:120],
                )

            # Notify dispatcher about failure so it can inform the user
            dispatcher_chat_id = event.data.get("dispatcher_chat_id")
            if dispatcher_chat_id and self._orchestrator:
                try:
                    from starlette.websockets import WebSocketState
                    if self._ws.client_state == WebSocketState.CONNECTED:
                        async with self._callback_lock:
                            error_msg = str(e)[:500]
                            callback_msg = (
                                f"[SYSTEM: Worker '{event.intent}' (task {event.task_id}) FAILED.]\n\n"
                                f"Error: {error_msg}\n\n"
                                f"Inform the user about the failure and suggest alternatives if appropriate."
                            )
                            callback_message_id = f"worker-err-{uuid4().hex[:8]}"
                            logger.info(f"[DeepWorker] Notifying dispatcher about failed task {event.task_id}")

                            await self._orchestrator.handle_message(
                                websocket=self._ws,
                                content=callback_msg,
                                message_id=callback_message_id,
                                chat_id=dispatcher_chat_id,
                                project_id=event.data.get("project_id"),
                                chat_level="project" if event.data.get("project_id") else "general",
                                session_id=event.session_id,
                                is_callback=True,
                                callback_depth=1,
                            )
                except Exception as cb_err:
                    logger.warning(f"[DeepWorker] Failed to notify dispatcher about error: {cb_err}")
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
            from app.services.ws_broadcast import ws_broadcast
            await ws_broadcast.emit_to_others(self._ws, event_type, {"taskId": task_id, **payload})
        except Exception as e:
            logger.warning(f"[DeepWorkerPool] Failed to send {event_type} via WS: {e}")
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
        card_id: str | None = None,
    ) -> None:
        """Insert a new row into worker_tasks with status='running'."""
        try:
            from app.database import async_session, WorkerTask, utcnow
            async with async_session() as db:
                row = WorkerTask(
                    id=task_id,
                    session_id=session_id,
                    project_id=project_id,
                    card_id=card_id,
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
                        row.result_summary = result_summary
                    if error is not None:
                        row.error = error
                    if status in ("done", "failed", "cancelled", "timed_out"):
                        row.completed_at = utcnow()
                    await db.commit()
                    logger.debug(f"[Ledger] Updated task {task_id} → {status}")
        except Exception as e:
            logger.warning(f"[Ledger] Failed to update task {task_id}: {e}")
