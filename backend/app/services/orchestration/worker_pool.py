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
    # No hard task timeout — stall detector handles idle workers (120s idle = cancel)

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

        self._active_tasks.pop(task_id, None)
        task.cancel()

        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass

        self._semaphore.release()

        await self._send_task_event("task:cancelled", task_id, {
            "reason": "user_cancelled",
            "sessionId": self._bus.session_id,
        })

        logger.info(f"[DeepWorkerPool] Task {task_id} cancelled successfully")
        return True

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
        removed = self._active_tasks.pop(task_id, None)
        if removed is not None:
            self._semaphore.release()
            meta = self._task_meta.pop(task_id, None)
            if meta:
                result = "success"
                if removed.cancelled():
                    result = "cancelled"
                elif removed.exception():
                    result = f"error: {removed.exception()}"
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
            _wss = get_worker_session_store()
            _wss.register(
                task_id=event.task_id,
                session_id=event.session_id or self._bus.session_id,
                project_id=event.data.get("project_id"),
                model=event.model or get_default_worker_model(),
                intent=event.intent or "unknown",
                summary=event.summary or "",
            )

            await self._ledger_insert(
                task_id=event.task_id,
                session_id=event.session_id or self._bus.session_id,
                project_id=event.data.get("project_id"),
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
            })

            logger.info(f"[DeepWorker] Executing task {event.task_id}: {event.intent} (model={event.model})")

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

            await self._send_task_event("task:progress", event.task_id, {
                "status": "executing",
                "sessionId": event.session_id,
            })

            chat_level = event.data.get("chat_level", "general")
            if chat_level == "general":
                intent_lower = event.intent.lower()
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

            async def _tool_callback(tool_name: str, arguments: dict, result: dict):
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

            async def _stall_monitor():
                STALL_THRESHOLD = 120
                WARNING_THRESHOLD = 90
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
                result_content = await self._claude.execute_worker_task(
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
                supervisor.mark_problem(event.task_id, "missing_task_complete")
                logger.warning(
                    f"[Supervisor] Task {event.task_id} finished without calling task.complete"
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

            _wss.update_status(event.task_id, "completed", result_content or "")

            await self._ledger_update(
                event.task_id, "done",
                result_summary=(result_content or "")[:500],
            )

            await self._send_task_event("task:completed", event.task_id, {
                "intent": event.intent,
                "summary": event.summary,
                "result": result_content,
                "success": True,
                "sessionId": event.session_id,
                "projectId": event.data.get("project_id"),
                "cardId": event.data.get("card_id"),
            })

            dispatcher_chat_id = event.data.get("dispatcher_chat_id")
            if dispatcher_chat_id and result_content:
                try:
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
