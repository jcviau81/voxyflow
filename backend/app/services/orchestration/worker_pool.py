"""DeepWorkerPool — async worker pool that consumes ActionIntent events from a SessionEventBus.

Extracted from chat_orchestration.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import WebSocket

from app.services.claude_service import ClaudeService
from app.services.event_bus import ActionIntent, SessionEventBus, event_bus_registry
from app.services.pending_results import pending_store
from app.services.worker_session_store import get_worker_session_store
from app.services.worker_supervisor import get_worker_supervisor
from app.services.settings_loader import get_default_worker_model

if TYPE_CHECKING:
    from app.services.chat_orchestration import ChatOrchestrator

# Intents that use lightweight worker (minimal prompt, no personality/context)
LIGHTWEIGHT_INTENTS = {
    "enrich", "enrich_card", "card.enrich",
    "summarize", "summarize_card",
    "research", "web_search", "search",
    "code_review", "review",
}

# Keywords that signal a lightweight task when found anywhere in the intent.
# Used for natural-language intents like "Read the file X and return its content".
LIGHTWEIGHT_KEYWORDS = {
    "read", "list", "get", "fetch", "show", "display", "cat", "print",
    "enrich", "summarize", "search", "review",
}


def is_lightweight_intent(intent: str) -> bool:
    """Check if an intent is lightweight — either exact match or keyword match."""
    lower = intent.lower()
    if lower in LIGHTWEIGHT_INTENTS:
        return True
    words = set(lower.split())
    return bool(words & LIGHTWEIGHT_KEYWORDS)

logger = logging.getLogger("voxyflow.orchestration")

# ---------------------------------------------------------------------------
# Result preview helpers — the artifact file is the canonical blob store;
# everything else gets a short preview + artifact_path reference.
# ---------------------------------------------------------------------------
PREVIEW_CHARS = 500          # for DB ledger, worker session store, session store
DISPATCHER_PREVIEW_CHARS = 10_000  # legacy truncation bound (raw-text fallback path)
WS_RESULT_CHARS = 2_000     # for the task:completed WS event to the frontend

# Per-callback bound on the structured dispatcher message — summary + findings
# + pointers. The raw artifact is always out of band (read_artifact).
MAX_DISPATCHER_PAYLOAD_CHARS = 15_000


def _preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    """Return the first *limit* chars of *text*, with a truncation marker if cut."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... truncated — {len(text):,} chars total ...]"


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
        self._semaphore = asyncio.Semaphore(self.MAX_WORKERS)
        self._result_contents: dict[str, str] = {}  # task_id → actual result content
        self._task_tool_events: dict[str, list[dict]] = {}  # task_id → bounded tool event buffer
        self._MAX_TOOL_EVENTS = 50
        self._task_message_queues: dict[str, asyncio.Queue] = {}  # task_id → steer queue
        # Rolling log of recent dispatcher callback sizes per dispatcher_chat_id.
        # Used to clip burst completions so simultaneous workers can't flood the
        # dispatcher in a single turn window.
        self._recent_callback_chars: dict[str, list[tuple[float, int]]] = {}
        self._stopped = False

    # Regex to extract file path from read-file intents
    _READ_FILE_RE = re.compile(
        r"^read\s+(?:the\s+)?(?:file\s+|content\s+of\s+)?([^\s]+)",
        re.IGNORECASE,
    )

    async def _try_direct_execution(self, event: ActionIntent) -> str | None:
        """Fast-path: execute trivial intents directly without spawning an LLM.

        Returns the result string if handled, or None to fall through to LLM workers.
        Currently handles: file read intents.
        """
        intent = (event.intent or "").strip()
        m = self._READ_FILE_RE.match(intent)
        if not m:
            return None

        from app.tools.system_tools import file_read

        path = m.group(1).strip("\"'")
        result = await file_read({"path": path})

        if not result.get("success"):
            return f"Error reading file: {result.get('error', 'unknown error')}"

        content = result.get("content", "")
        total = result.get("total_lines", 0)
        truncated = result.get("truncated", False)
        header = f"File: {path} ({total} lines"
        if truncated:
            header += ", truncated"
        header += ")\n\n"
        return header + content

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
                "description": t.get("description", ""),
                "seconds_ago": ago,
                "result": t["result"],
                "success": t.get("success", True),
            })

        return {"active": active, "completed": completed}

    async def _summarize_result(self, result: str, intent: str, max_chars: int = 0) -> str:
        """Return a dispatcher-sized preview of the worker result.

        The full output lives in the artifact file.  The dispatcher gets the
        first DISPATCHER_PREVIEW_CHARS here and can call read_artifact for more.
        No LLM summarization — just mechanical truncation.
        """
        limit = max_chars or DISPATCHER_PREVIEW_CHARS
        if len(result) <= limit:
            return result
        return result[:limit] + f"\n[... truncated — {len(result):,} chars total ...]"

    # ------------------------------------------------------------------
    # Worker lifecycle: closeout pass + local fallback
    # ------------------------------------------------------------------

    async def _closeout_pass(
        self,
        event: ActionIntent,
        artifact_path: str | None,
        fallback_text: str | None,
    ) -> bool:
        """Spawn a lightweight subprocess that reads the artifact and emits
        voxyflow.worker.complete for the given task.

        Runs only when the main worker did not deliver a structured completion.
        Returns True if a structured completion now exists, False otherwise.
        """
        if os.environ.get("VOXYFLOW_CLOSEOUT_PASS", "1") != "1":
            return False

        from app.services.worker_supervisor import get_worker_supervisor
        supervisor = get_worker_supervisor()

        if supervisor.is_structured_complete(event.task_id):
            return True
        if not artifact_path and not (fallback_text and fallback_text.strip()):
            logger.info(
                f"[Closeout] Skipping task {event.task_id} — no artifact and no output"
            )
            return False

        closeout_model = os.environ.get("VOXYFLOW_CLOSEOUT_MODEL", "fast")
        closeout_timeout = int(os.environ.get("VOXYFLOW_CLOSEOUT_TIMEOUT", "90"))

        status = supervisor.get_status(event.task_id) or {}
        source_hint = status.get("completion_source")
        if source_hint == "task.complete":
            context_hint = " The worker called the legacy task.complete — upgrade the result."
        elif source_hint == "auto":
            context_hint = " The worker exited without calling any completion tool."
        else:
            context_hint = ""

        closeout_prompt = (
            f"You are a closeout agent. Worker task {event.task_id} "
            f"(intent \"{event.intent}\") just finished.{context_hint}\n\n"
            "Your job is ONE thing: produce a structured dispatcher-facing completion.\n\n"
            "Steps:\n"
            f"1. Call voxyflow.workers.read_artifact(task_id=\"{event.task_id}\") "
            "to read the artifact. If the artifact is very large, page with offset/length.\n"
            "2. Call voxyflow.worker.complete exactly once with:\n"
            "   - status: \"success\" if the task looks complete, \"partial\" otherwise\n"
            "   - summary: 2–4 sentences in plain prose — what was done, what the dispatcher needs to know\n"
            "   - findings: 3–7 short bullets of the most important results\n"
            "   - pointers: list of {label, offset, length} into the artifact for notable sections\n"
            "   - next_step: optional one-liner the dispatcher could act on\n"
            "3. Stop after voxyflow.worker.complete — do not do anything else."
        )

        closeout_cancel = asyncio.Event()
        closeout_mq: asyncio.Queue[str] = asyncio.Queue()

        async def _closeout_cb(tool_name: str, arguments: dict, result: dict):
            # Claude CLI's MCP bridge flattens dots → underscores on the wire,
            # and our cli_steerable normalizer only restores the first dot. So
            # "voxyflow.worker.complete" may arrive as "voxyflow.worker_complete".
            # Match on the underscore-normalized form to cover every variant.
            norm = tool_name.replace(".", "_")
            logger.debug(f"[Closeout] cb tool={tool_name!r} (norm={norm!r}) task={event.task_id}")
            if norm == "voxyflow_worker_complete" or norm == "worker_complete":
                wc_summary = (arguments.get("summary") or "").strip()
                wc_status = arguments.get("status", "success")
                wc_findings = arguments.get("findings") or []
                wc_pointers = arguments.get("pointers") or []
                wc_next = arguments.get("next_step") or None
                if wc_summary and wc_status in ("success", "partial", "failed"):
                    supervisor.mark_completed(
                        event.task_id, wc_summary, wc_status,
                        findings=wc_findings if isinstance(wc_findings, list) else None,
                        pointers=wc_pointers if isinstance(wc_pointers, list) else None,
                        next_step=wc_next,
                        source="closeout",
                    )
                    closeout_cancel.set()

        try:
            await asyncio.wait_for(
                self._claude.execute_lightweight_task(
                    chat_id=f"closeout-{event.task_id}",
                    prompt=closeout_prompt,
                    model=closeout_model,
                    project_id=event.data.get("project_id"),
                    card_context=None,
                    tool_callback=_closeout_cb,
                    cancel_event=closeout_cancel,
                    message_queue=closeout_mq,
                    session_id=event.session_id or "",
                    task_id=event.task_id,
                ),
                timeout=closeout_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"[Closeout] Timed out after {closeout_timeout}s for task {event.task_id}")
            closeout_cancel.set()
        except Exception as e:
            logger.warning(f"[Closeout] Failed for task {event.task_id}: {e}")

        ok = supervisor.is_structured_complete(event.task_id)
        if ok:
            logger.info(f"[Closeout] Produced structured completion for task {event.task_id}")
        else:
            logger.warning(f"[Closeout] Did not produce structured completion for task {event.task_id}")
        return ok

    def _synthesize_fallback_completion(
        self,
        event: ActionIntent,
        result_content: str | None,
    ) -> None:
        """Last-resort: synthesize a minimal structured completion locally.

        Used when the worker did not call voxyflow.worker.complete AND the
        closeout pass did not produce a structured payload either. Keeps the
        dispatcher path uniform — everything downstream reads from the same
        structured payload shape.
        """
        from app.services.worker_supervisor import get_worker_supervisor
        supervisor = get_worker_supervisor()
        if supervisor.is_structured_complete(event.task_id):
            return

        text = (result_content or event.summary or "").strip()
        if len(text) > 1500:
            summary = text[:1500] + "…"
        elif text:
            summary = text
        else:
            summary = f"Worker for intent '{event.intent}' finished without output."

        if len(summary) < 20:
            summary = f"Worker for intent '{event.intent}' finished. Output: {summary}"

        supervisor.mark_completed(
            event.task_id, summary, "partial",
            findings=[], pointers=[], next_step=None,
            source="auto",
        )
        logger.warning(
            f"[DeepWorker] Task {event.task_id}: synthesized fallback completion "
            "(no worker.complete + closeout did not run or failed)"
        )

    def _build_dispatcher_callback(
        self,
        task_id: str,
        intent: str,
        payload: dict | None,
        artifact_path: str | None,
        raw_len: int,
        fallback_text: str | None,
    ) -> str:
        """Render the structured completion payload as the dispatcher-facing
        callback message. Keeps total length under MAX_DISPATCHER_PAYLOAD_CHARS.
        """
        status = (payload or {}).get("status") or "success"
        header = (
            f"[SYSTEM: Worker '{intent}' (task {task_id}) completed with status: {status}.]"
        )

        # Degraded path — no structured payload at all (closeout + fallback disabled).
        # Fall back to the legacy truncated-raw behaviour so the dispatcher still
        # gets something coherent.
        if not payload or not (payload.get("summary") or "").strip():
            body_text = fallback_text or "(no output)"
            if len(body_text) > DISPATCHER_PREVIEW_CHARS:
                body_text = (
                    body_text[:DISPATCHER_PREVIEW_CHARS]
                    + f"\n[... truncated — {len(body_text):,} chars total ...]"
                )
            hint = ""
            if artifact_path and raw_len > len(body_text):
                hint = (
                    f"\n[Full raw output ({raw_len:,} chars) available — "
                    f"call voxyflow.workers.read_artifact(task_id=\"{task_id}\") to page.]"
                )
            return (
                f"{header}\n\n"
                f"--- Worker Result ---\n{body_text}\n--- End Result ---{hint}\n\n"
                "Present this to the user naturally and decide if follow-up actions are needed."
            )

        summary = (payload.get("summary") or "").strip()
        findings = payload.get("findings") or []
        pointers = payload.get("pointers") or []
        next_step = (payload.get("next_step") or "").strip()

        parts: list[str] = [header, "", "## Summary", summary]
        if findings:
            parts.append("")
            parts.append("## Key findings")
            for f in findings:
                parts.append(f"- {f}")
        if pointers:
            parts.append("")
            parts.append("## Detail pointers (artifact)")
            for p in pointers:
                label = p.get("label", "detail")
                off = p.get("offset")
                length = p.get("length")
                call = f"voxyflow.workers.read_artifact(task_id=\"{task_id}\""
                if isinstance(off, int):
                    call += f", offset={off}"
                if isinstance(length, int):
                    call += f", length={length}"
                call += ")"
                parts.append(f"- **{label}** — {call}")
        elif artifact_path and raw_len > 0:
            parts.append("")
            parts.append(
                f"## Artifact\nFull output available ({raw_len:,} chars). "
                f"Call voxyflow.workers.read_artifact(task_id=\"{task_id}\") only if you need detail."
            )
        if next_step:
            parts.append("")
            parts.append(f"## Worker's suggested next step\n{next_step}")

        parts.append("")
        parts.append(
            "Present the summary to the user. Only fetch pointers if you genuinely need the detail."
        )
        msg = "\n".join(parts)

        # Per-message hard cap — keeps any single worker from blowing up one turn.
        if len(msg) > MAX_DISPATCHER_PAYLOAD_CHARS:
            # Drop detail pointers first (easy to re-fetch), then trim findings,
            # then trim the summary. Always keep header + summary prefix.
            msg = msg[:MAX_DISPATCHER_PAYLOAD_CHARS] + "\n[... callback truncated — call read_artifact for detail ...]"
        return msg

    def _clip_against_recent_bursts(self, dispatcher_chat_id: str, msg: str) -> str:
        """If multiple workers just completed against the same dispatcher chat,
        clip this callback further so the dispatcher turn doesn't receive an
        aggregate flood of text. Uses a 60s rolling window.
        """
        window_seconds = int(os.environ.get("VOXYFLOW_CALLBACK_WINDOW_S", "60"))
        burst_cap = int(os.environ.get("VOXYFLOW_CALLBACK_BURST_CAP_CHARS", "40000"))
        now = time.time()
        log = self._recent_callback_chars.setdefault(dispatcher_chat_id, [])
        log[:] = [(t, n) for (t, n) in log if now - t < window_seconds]
        cumulative = sum(n for _, n in log)
        budget = max(2000, burst_cap - cumulative)
        if len(msg) > budget:
            clipped = msg[:budget]
            msg = (
                clipped
                + f"\n[... clipped: dispatcher burst cap ({burst_cap:,} chars / {window_seconds}s) "
                f"hit across recent completions. Use read_artifact for full detail. ...]"
            )
        log.append((now, len(msg)))
        return msg

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
                    # Placeholder — _execute_event will overwrite with the
                    # authoritative model (worker_class.model or default).
                    "model": get_default_worker_model(),
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
                    "description": meta.get("description", ""),
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

    async def _resolve_worker_class(self, event: ActionIntent) -> dict | None:
        """Try to resolve a worker class for this event.

        Checks event.data["worker_class_id"] first, then tries intent-based matching.
        Returns the resolved worker class dict, or None for default behavior.
        """
        try:
            from app.services.llm.worker_class_resolver import resolve_by_id, resolve_by_intent

            # Explicit worker_class_id takes priority
            wc_id = event.data.get("worker_class_id", "")
            if wc_id:
                wc = await resolve_by_id(wc_id)
                if wc:
                    logger.info(
                        "[DeepWorkerPool] Task %s routed to worker class %r (explicit id)",
                        event.task_id, wc.get("name"),
                    )
                    return wc

            # Try intent-based keyword matching
            wc = await resolve_by_intent(event.intent or "")
            if wc:
                logger.info(
                    "[DeepWorkerPool] Task %s routed to worker class %r (intent match: %r)",
                    event.task_id, wc.get("name"), event.intent,
                )
                return wc
        except Exception as e:
            logger.warning("[DeepWorkerPool] Worker class resolution failed: %s", e)

        return None

    async def _execute_event(self, event: ActionIntent) -> None:
        """Execute a single ActionIntent via model-routed worker (haiku/sonnet/opus).

        If a matching WorkerClass is found (by explicit id or intent pattern),
        the worker class model/provider is used instead of the default layer.
        """
        try:
            # Resolve worker class (if any) before registering, so we log the right model.
            # Precedence: worker_class.model (if matched) > default_worker_model (fallback).
            # event.model is the dispatcher's LLM-suggested hint — kept only for logging;
            # user-configured Worker Classes and Default Worker Model are authoritative.
            _worker_class = await self._resolve_worker_class(event)
            if _worker_class and _worker_class.get("model"):
                _effective_model = _worker_class["model"]
                event.data["_resolved_worker_class"] = _worker_class
            else:
                _effective_model = get_default_worker_model()
            # Update task_meta so get_active_tasks reflects the actual model
            if event.task_id in self._task_meta:
                self._task_meta[event.task_id]["model"] = _effective_model

            _wss = get_worker_session_store()
            _task_card_id = event.data.get("card_id")

            # --- Card lifecycle: auto-create if missing, move to in-progress ---
            if not _task_card_id:
                _task_card_id = await self._auto_create_card(
                    project_id=event.data.get("project_id"),
                    intent=event.intent or "unknown",
                    summary=event.summary or "",
                )
                if _task_card_id:
                    event.data["card_id"] = _task_card_id

            if _task_card_id:
                await self._update_card_status(
                    _task_card_id, "in-progress",
                    project_id=event.data.get("project_id"),
                )

            _wss.register(
                task_id=event.task_id,
                session_id=event.session_id or self._bus.session_id,
                chat_id=event.data.get("dispatcher_chat_id"),
                project_id=event.data.get("project_id"),
                card_id=_task_card_id,
                model=_effective_model,
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
                model=_effective_model,
            )

            await self._send_task_event("task:started", event.task_id, {
                "intent": event.intent,
                "summary": event.summary,
                "complexity": event.complexity,
                "model": _effective_model,
                "sessionId": event.session_id,
                "chatId": event.data.get("dispatcher_chat_id"),
                "cardId": _task_card_id,
                "projectId": event.data.get("project_id"),
            })

            _wc_name = (_worker_class or {}).get("name")
            logger.info(
                f"[DeepWorker] Executing task {event.task_id}: {event.intent} "
                f"(model={_effective_model}"
                + (f", class={_wc_name}" if _wc_name else "")
                + (f", requested={event.model}" if event.model and event.model != _effective_model else "")
                + ")"
            )

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
                f"\nLifecycle (strict):\n"
                f"1. FIRST call voxyflow.worker.claim(task_id=\"{event.task_id}\", plan=\"<one sentence plan>\").\n"
                f"2. Then do the work — use any MCP tools you need. All raw output is captured "
                f"automatically to an artifact; don't try to keep it in your reply.\n"
                f"3. LAST call voxyflow.worker.complete(task_id=\"{event.task_id}\", status=\"success|partial|failed\", "
                f"summary=\"<2-4 sentences in your own words>\", findings=[...], pointers=[{{label, offset, length}}], "
                f"next_step=\"...\"). Stop immediately after.\n"
                f"\nThe summary is the ONLY thing the dispatcher sees. Write it for a reader who has "
                f"not seen the raw output. Use pointers to flag important sections of the artifact.\n"
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

            # Accumulate raw tool output — the LLM's text response is often
            # a summary; the real content lives in tool_results from file.read,
            # system.exec, etc.
            _CONTENT_TOOLS = frozenset({"file.read", "file_read", "system.exec", "system_exec"})
            _captured_tool_outputs: list[str] = []

            async def _tool_callback(tool_name: str, arguments: dict, result: dict):
                supervisor.record_tool_call(event.task_id, tool_name, arguments)

                # Lifecycle interception — the MCP handlers run in a subprocess
                # with their own supervisor instance, so we must propagate
                # claim/complete into the main-process supervisor here.
                # Claude CLI's MCP bridge flattens dots → underscores, and our
                # cli_steerable only restores the first dot, so match against
                # the fully-underscored form.
                _norm = tool_name.replace(".", "_")
                if _norm in ("voxyflow_worker_claim", "worker_claim"):
                    wc_task_id = arguments.get("task_id", event.task_id)
                    wc_plan = arguments.get("plan", "")
                    if wc_plan:
                        supervisor.mark_claimed(wc_task_id, wc_plan)
                elif _norm in ("voxyflow_worker_complete", "worker_complete"):
                    wc_task_id = arguments.get("task_id", event.task_id)
                    wc_summary = (arguments.get("summary") or "").strip()
                    wc_status = arguments.get("status", "success")
                    wc_findings = arguments.get("findings") or []
                    wc_pointers = arguments.get("pointers") or []
                    wc_next = arguments.get("next_step") or None
                    if wc_summary and wc_status in ("success", "partial", "failed"):
                        supervisor.mark_completed(
                            wc_task_id, wc_summary, wc_status,
                            findings=wc_findings if isinstance(wc_findings, list) else None,
                            pointers=wc_pointers if isinstance(wc_pointers, list) else None,
                            next_step=wc_next,
                            source="worker.complete",
                        )
                elif _norm == "task_complete":
                    tc_task_id = arguments.get("task_id", event.task_id)
                    tc_summary = arguments.get("summary", "")
                    tc_status = arguments.get("status", "success")
                    if tc_summary:
                        supervisor.mark_completed(
                            tc_task_id, tc_summary, tc_status,
                            source="task.complete",
                        )
                        logger.info(
                            f"[Supervisor] Task {tc_task_id} explicitly completed via "
                            f"task.complete (status={tc_status}, "
                            f"summary_len={len(tc_summary)})"
                        )

                # Capture raw output from content-producing tools.
                # tool_result from CLI is {"content": "<json_string>"} where
                # the json_string is the MCP tool's serialized response.
                if tool_name in _CONTENT_TOOLS and isinstance(result, dict):
                    raw = result.get("content", "")
                    # Try to parse the JSON to extract the actual content
                    parsed = None
                    if isinstance(raw, str):
                        try:
                            parsed = json.loads(raw)
                        except (json.JSONDecodeError, ValueError):
                            pass
                    if isinstance(parsed, dict):
                        output = (
                            parsed.get("content")   # file.read
                            or parsed.get("stdout")  # system.exec
                            or parsed.get("output")
                            or ""
                        )
                    else:
                        output = raw  # fallback to raw text
                    if isinstance(output, str) and len(output) > 200:
                        _captured_tool_outputs.append(output)

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
                import os
                from app.services.cli_session_registry import get_cli_session_registry

                stall_timeout = int(os.environ.get("WORKER_STALL_TIMEOUT", "1800"))
                stall_warning = int(os.environ.get("WORKER_STALL_WARNING", str(stall_timeout - 300)))
                claim_nudge_after = int(os.environ.get("WORKER_CLAIM_NUDGE_AFTER", "5"))
                warned = False
                claim_nudged = False
                while not cancel_event.is_set():
                    await asyncio.sleep(15)

                    # Claim watchdog: nudge the worker once if it has called
                    # several tools without first calling voxyflow.worker.claim.
                    if (
                        not claim_nudged
                        and not supervisor.is_claimed(event.task_id)
                        and supervisor.tool_calls_since_register(event.task_id) >= claim_nudge_after
                    ):
                        claim_nudged = True
                        message_queue.put_nowait(
                            "PROTOCOL REMINDER: you have not called voxyflow.worker.claim yet. "
                            "Call it NOW with a one-sentence plan before any further actions."
                        )
                        logger.info(
                            f"[Supervisor] Claim nudge sent to task {event.task_id} "
                            f"(tool_calls={supervisor.tool_calls_since_register(event.task_id)})"
                        )

                    # Check supervisor's tool-call-based activity
                    stall_secs = supervisor.check_stall(event.task_id)

                    # Also check CLI subprocess liveness — the stream loop
                    # touches the session registry every ~10s while producing output
                    cli_session = get_cli_session_registry().get_by_task_id(event.task_id)
                    if cli_session and cli_session.last_activity > 0:
                        cli_idle = time.time() - cli_session.last_activity
                        if cli_idle < 60:
                            # Process is actively producing output — reset stall counter
                            supervisor.record_activity(event.task_id)
                            stall_secs = min(stall_secs, cli_idle)

                    if stall_secs > stall_warning and not warned:
                        warned = True
                        message_queue.put_nowait(
                            f"WARNING: You have been idle for {stall_secs:.0f}s. "
                            "Wrap up now and call voxyflow.worker.complete (with a real summary, "
                            "findings, and pointers) or you will be cancelled."
                        )
                    if stall_secs > stall_timeout:
                        logger.warning(
                            f"[Supervisor] Task {event.task_id} stalled for {stall_secs:.0f}s — cancelling"
                        )
                        supervisor.mark_problem(event.task_id, f"stalled_{stall_secs:.0f}s")
                        cancel_event.set()
                        break

            stall_task = asyncio.create_task(_stall_monitor())

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
                        project_id=event.data.get("project_id"),
                        card_context=event.data.get("card_context"),
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
                        model=_effective_model,
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

            # If the LLM returned a short summary but tool calls captured
            # substantial raw output, use the tool output instead.
            if _captured_tool_outputs:
                captured_total = sum(len(o) for o in _captured_tool_outputs)
                llm_len = len(result_content or "")
                if captured_total > llm_len * 2 and captured_total > 500:
                    logger.info(
                        f"[DeepWorker] Using captured tool output ({captured_total} chars) "
                        f"over LLM text ({llm_len} chars) for task {event.task_id}"
                    )
                    result_content = "\n\n".join(_captured_tool_outputs)

            if not supervisor.is_completed(event.task_id):
                # Auto-complete: worker finished but forgot to call any completion tool.
                # A closeout pass (below, after artifact write) will try to upgrade
                # this to a structured voxyflow.worker.complete payload.
                auto_summary = result_content or event.summary or "Task completed (auto-closed)"
                supervisor.mark_completed(
                    event.task_id, auto_summary, "success", source="auto",
                )
                logger.info(
                    f"[Supervisor] Task {event.task_id} auto-completed "
                    "(no worker.complete — closeout pass will attempt structured upgrade)"
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
            if card_id:
                try:
                    from app.database import async_session, Card, CardHistory, new_uuid, utcnow
                    from sqlalchemy import select
                    from datetime import datetime, timezone
                    async with async_session() as db:
                        result = await db.execute(select(Card).where(Card.id == card_id))
                        card = result.scalar_one_or_none()
                        if card:
                            # Append result to card description
                            if result_content:
                                timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                                separator = "\n\n---\n"
                                clean_result = _format_result_for_card(result_content)
                                result_block = f"📋 **Execution Result** ({timestamp})\n{clean_result}"
                                card.description = (card.description or "") + separator + result_block

                            # Move card to done (system-managed lifecycle)
                            old_status = card.status
                            if old_status not in ("done", "archived"):
                                card.status = "done"
                                card.updated_at = utcnow()
                                db.add(CardHistory(
                                    id=new_uuid(),
                                    card_id=card_id,
                                    field_changed="status",
                                    old_value=old_status,
                                    new_value="done",
                                    changed_at=utcnow(),
                                    changed_by="System",
                                ))

                            await db.commit()
                            logger.info(f"[CardLifecycle] Card {card_id}: result appended + status -> done")
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
                    logger.warning(f"[CardLifecycle] Failed card completion update for {card_id}: {append_err}")

            if result_content:
                self._result_contents[event.task_id] = result_content or ""

            # Persist the full raw result to a .md artifact so the dispatcher
            # can retrieve verbatim output via workers_read_artifact for
            # paged reading of very large outputs.
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

            # Closeout pass — if the worker did not deliver a structured
            # voxyflow.worker.complete, spawn a lightweight subprocess whose
            # only job is to read the artifact and emit one. This upgrades the
            # dispatcher-facing payload from raw truncated text to structured
            # summary / findings / pointers.
            if not supervisor.is_structured_complete(event.task_id):
                await self._closeout_pass(event, artifact_path, result_content)

            # Local synthesis fallback — if closeout also failed, synthesize
            # a minimal structured payload from what we have. Keeps the
            # dispatcher path uniform even when both tiers above missed.
            if not supervisor.is_structured_complete(event.task_id):
                self._synthesize_fallback_completion(event, result_content)

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
                result_summary=result_preview,
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
                "result": _preview(result_content, WS_RESULT_CHARS) if result_content else "",
                "totalChars": len(result_content or ""),
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
                        "content": result_preview,
                        "model": "worker",
                        "type": "worker_result",
                        "task_id": event.task_id,
                        "intent": event.intent,
                        "artifactPath": artifact_path,
                        "totalChars": len(result_content),
                    })
                except Exception as _persist_err:
                    logger.warning(f"[DeepWorker] Failed to persist worker result: {_persist_err}")

            # --- Notify dispatcher: embed structured completion in one user msg ---
            # The dispatcher receives the worker.complete payload (summary, findings,
            # pointers, next_step) — NOT the raw artifact. Full artifact stays on
            # disk and is fetched on demand via voxyflow.workers.read_artifact.
            dispatcher_chat_id = event.data.get("dispatcher_chat_id")
            if dispatcher_chat_id and self._orchestrator:
                try:
                    from starlette.websockets import WebSocketState
                    _ws_state = getattr(self._ws, "client_state", WebSocketState.CONNECTED)
                    if _ws_state == WebSocketState.CONNECTED:
                        payload = supervisor.get_completion_payload(event.task_id)
                        raw_len = len(result_content or "")
                        callback_msg = self._build_dispatcher_callback(
                            task_id=event.task_id,
                            intent=event.intent or "",
                            payload=payload,
                            artifact_path=artifact_path,
                            raw_len=raw_len,
                            fallback_text=result_content,
                        )
                        # Track per-dispatcher-turn aggregate; clip further if a
                        # burst of completions would flood the dispatcher.
                        callback_msg = self._clip_against_recent_bursts(
                            dispatcher_chat_id, callback_msg,
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
                    _ws_state = getattr(self._ws, "client_state", WebSocketState.CONNECTED)
                    if _ws_state == WebSocketState.CONNECTED:
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
            from app.services.ws_broadcast import ws_broadcast
            if self._ws is not None:
                await self._ws.send_json(message)
                await ws_broadcast.emit_to_others(self._ws, event_type, {"taskId": task_id, **payload})
            else:
                ws_broadcast.emit_sync(event_type, {"taskId": task_id, **payload})
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
    # Card Lifecycle helpers (system-managed)
    # ------------------------------------------------------------------

    @staticmethod
    def _make_short_title(intent: str, summary: str) -> str:
        """Derive a concise card title (≤80 chars) from intent and summary.

        Uses the first sentence of summary if available, otherwise shortens intent.
        """
        # If intent is a short action keyword, use it as prefix
        source = summary or intent
        if not source:
            return "Worker task"

        # Take the first sentence, clause, or line
        for sep in (".", "\n", ":", "—", " - ", ","):
            idx = source.find(sep)
            if 10 < idx < 80:
                source = source[:idx]
                break

        # Truncate to 80 chars at a word boundary
        if len(source) > 80:
            source = source[:77].rsplit(" ", 1)[0] + "…"

        return source.strip() or "Worker task"

    @staticmethod
    async def _auto_create_card(
        project_id: str | None,
        intent: str,
        summary: str,
    ) -> str | None:
        """Auto-create a card for a worker task when no card_id was provided.

        Returns the new card_id, or None if creation fails.
        """
        try:
            from app.database import async_session, Card, CardHistory, new_uuid, utcnow, SYSTEM_MAIN_PROJECT_ID
            from app.services.agent_router import get_agent_router
            from app.services.agent_personas import AgentType, get_persona
            from app.services.ws_broadcast import ws_broadcast

            effective_project_id = project_id or SYSTEM_MAIN_PROJECT_ID

            # Auto-route agent type from intent/summary
            router = get_agent_router()
            detected_type, _confidence = router.route(title=intent, description=summary)
            agent_type = detected_type.value
            persona = get_persona(AgentType(agent_type))
            agent_display = f"{persona.emoji} {persona.name}"

            # Build a short title and a full description.
            # intent = action name or full directive; summary = description/instruction
            full_text = summary or intent
            short_title = DeepWorkerPool._make_short_title(intent, summary)

            card_id = new_uuid()
            async with async_session() as db:
                card = Card(
                    id=card_id,
                    project_id=effective_project_id,
                    title=short_title,
                    description=full_text[:2000] if full_text else "",
                    status="todo",
                    auto_generated=True,
                    agent_type=agent_type,
                    agent_assigned=agent_display,
                )
                db.add(card)
                db.add(CardHistory(
                    id=new_uuid(),
                    card_id=card_id,
                    field_changed="status",
                    old_value=None,
                    new_value="todo",
                    changed_at=utcnow(),
                    changed_by="System",
                ))
                await db.commit()

            ws_broadcast.emit_sync("cards:changed", {
                "projectId": effective_project_id,
                "cardId": card_id,
            })
            logger.info(f"[CardLifecycle] Auto-created card {card_id} for \"{intent[:60]}\"")
            return card_id
        except Exception as e:
            logger.warning(f"[CardLifecycle] Failed to auto-create card: {e}")
            return None

    @staticmethod
    async def _update_card_status(
        card_id: str,
        new_status: str,
        project_id: str | None = None,
    ) -> None:
        """Move a card to a new status with CardHistory tracking.

        Guards against backward transitions from 'done' or 'archived'.
        No-ops if the card is already at the target status.
        """
        try:
            from app.database import async_session, Card, CardHistory, new_uuid, utcnow
            from sqlalchemy import select
            from app.services.ws_broadcast import ws_broadcast

            async with async_session() as db:
                result = await db.execute(select(Card).where(Card.id == card_id))
                card = result.scalar_one_or_none()
                if not card:
                    logger.warning(f"[CardLifecycle] Card {card_id} not found for status update")
                    return

                old_status = card.status
                logger.info(f"[CardLifecycle] Card {card_id}: current={old_status}, target={new_status}")
                if old_status == new_status:
                    logger.info(f"[CardLifecycle] Card {card_id}: already at {new_status}, skipping")
                    return
                if old_status in ("done", "archived"):
                    logger.info(
                        f"[CardLifecycle] Skipping {old_status} -> {new_status} "
                        f"for card {card_id} (no backward transitions)"
                    )
                    return

                card.status = new_status
                card.updated_at = utcnow()
                db.add(CardHistory(
                    id=new_uuid(),
                    card_id=card_id,
                    field_changed="status",
                    old_value=old_status,
                    new_value=new_status,
                    changed_at=utcnow(),
                    changed_by="System",
                ))
                await db.commit()

            _effective_pid = project_id or "system-main"
            ws_broadcast.emit_sync("cards:changed", {
                "projectId": _effective_pid,
                "cardId": card_id,
            })
            logger.info(f"[CardLifecycle] Card {card_id}: {old_status} -> {new_status}")
        except Exception as e:
            logger.warning(f"[CardLifecycle] Failed to update card {card_id} status: {e}")

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
