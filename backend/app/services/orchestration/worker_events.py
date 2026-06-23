"""Ambient worker-event buffer + debounced dispatcher callback.

Worker completions are no longer dispatcher turns themselves; they're ambient
references drained by the dispatcher at the start of the NEXT user-triggered
turn. The functions here operate on the owning ``DeepWorkerPool`` instance
(passed explicitly) — the pool's public methods delegate to them so
layer_runners / orchestrator callers don't change. Logic is verbatim from
worker_pool.py.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import TYPE_CHECKING
from uuid import uuid4

from app.services.event_bus import ActionIntent
from app.services.worker_supervisor import get_worker_supervisor

if TYPE_CHECKING:
    from app.services.orchestration.worker_pool import DeepWorkerPool

logger = logging.getLogger("voxyflow.orchestration")


# ------------------------------------------------------------------
# Ambient worker-event buffer — drained by the dispatcher at the start
# of the NEXT user-triggered turn. Worker completions are no longer
# turns themselves; they're ambient references.
# ------------------------------------------------------------------


def record_worker_event(
    pool: "DeepWorkerPool",
    dispatcher_chat_id: str,
    *,
    task_id: str,
    intent: str,
    status: str,
    summary_line: str,
    completion: dict | None = None,
) -> None:
    """Record a worker completion/failure against a dispatcher chat.

    ``completion`` is the structured ``voxyflow.worker.complete`` payload
    (findings/pointers/next_step). It's surfaced verbatim in the worker
    activity block so the dispatcher sees the deliverable up front instead
    of having to remember to call ``workers.get_result`` (which Fast-tier
    dispatchers tend to skip).

    The event is surfaced on the next user turn via peek_worker_events().
    It is only removed after the callback turn successfully emits.
    Bounded at _MAX_WORKER_EVENTS_PER_CHAT — oldest dropped on overflow.
    """
    if not dispatcher_chat_id:
        return
    now = time.time()
    buf = pool._worker_events.setdefault(
        dispatcher_chat_id,
        deque(maxlen=pool._MAX_WORKER_EVENTS_PER_CHAT),
    )
    buf.append({
        "task_id": task_id,
        "intent": intent or "unknown",
        "status": status,
        "finished_at": now,
        "summary_line": (summary_line or "")[:500],
        "completion": completion or None,
    })
    logger.info(
        "[DeepWorkerPool] worker event recorded chat_id=%s task_id=%s "
        "status=%s queue_size=%s at_ms=%s",
        dispatcher_chat_id, task_id, status, len(buf), int(now * 1000),
    )


def peek_worker_events(
    pool: "DeepWorkerPool", dispatcher_chat_id: str, *, max_items: int = 10,
) -> list[dict]:
    """Return pending worker events without consuming them.

    Call ack_worker_events() after the callback turn has been persisted
    and broadcast successfully.
    """
    buf = pool._worker_events.get(dispatcher_chat_id)
    if not buf:
        return []
    return list(buf)[:max_items]


def ack_worker_events(
    pool: "DeepWorkerPool", dispatcher_chat_id: str, *, count: int,
) -> None:
    """Remove the first ``count`` worker events for a dispatcher chat."""
    buf = pool._worker_events.get(dispatcher_chat_id)
    if not buf:
        return
    for _ in range(min(count, len(buf))):
        buf.popleft()
    if not buf:
        pool._worker_events.pop(dispatcher_chat_id, None)


def drain_worker_events(
    pool: "DeepWorkerPool", dispatcher_chat_id: str, *, max_items: int = 10,
) -> list[dict]:
    """Pop pending worker events for a dispatcher chat (oldest first).

    Backward-compatible destructive drain retained for callers that truly
    want consume-on-read semantics.
    """
    buf = pool._worker_events.get(dispatcher_chat_id)
    if not buf:
        return []
    out: list[dict] = []
    while buf and len(out) < max_items:
        out.append(buf.popleft())
    if not buf:
        pool._worker_events.pop(dispatcher_chat_id, None)
    return out


# ------------------------------------------------------------------
# Debounced dispatcher callback — re-enter the dispatcher with a thin
# signal (task_id + intent + status + one-line summary via the ambient
# worker-events block) after workers finish. Full results stay in
# artifacts; the dispatcher pulls them on demand via
# voxyflow.workers.get_result / read_artifact. Avoids the old failure
# mode where parallel worker results overwhelmed the dispatcher context.
# ------------------------------------------------------------------


def schedule_dispatcher_callback(
    pool: "DeepWorkerPool", dispatcher_chat_id: str, event: ActionIntent,
) -> None:
    """Arm (or re-arm) a debounced callback turn for this chat.

    If another worker tied to the same dispatcher_chat_id finishes within
    the debounce window, the timer resets and the completions collapse
    into one callback turn. The turn itself peeks the ambient worker-events
    block in _compute_ambient_blocks → build_worker_events_block, then
    acknowledges those events only after the callback turn emits.
    """
    if not dispatcher_chat_id or not pool._orchestrator:
        return
    if os.environ.get("DISPATCHER_WORKER_CALLBACK", "1") != "1":
        return
    if event.callback_depth >= pool._orchestrator.MAX_CALLBACK_DEPTH:
        logger.info(
            f"[DeepWorkerPool] Skipping callback for task {event.task_id} — "
            f"callback_depth={event.callback_depth} ≥ cap={pool._orchestrator.MAX_CALLBACK_DEPTH}"
        )
        return

    existing = pool._callback_debouncers.get(dispatcher_chat_id)
    if existing and not existing.done():
        if not getattr(existing, "_fired", False):
            # Still in the debounce sleep — reset the timer.
            existing.cancel()
            logger.info(
                "[DeepWorkerPool] callback debounce re-armed chat_id=%s "
                "task_id=%s depth=%s debounce_s=%s",
                dispatcher_chat_id, event.task_id, event.callback_depth,
                pool._CALLBACK_DEBOUNCE_SECONDS,
            )
        # else: the debouncer already fired and is mid-callback turn.
        # Cancelling now would truncate a live dispatcher stream. Leave
        # it running — the replacement scheduled below serializes behind
        # the per-chat lock in handle_message, and this completion's
        # ambient event is only acked once a turn actually renders it.
    else:
        logger.info(
            "[DeepWorkerPool] callback debounce armed chat_id=%s "
            "task_id=%s depth=%s debounce_s=%s",
            dispatcher_chat_id, event.task_id, event.callback_depth,
            pool._CALLBACK_DEBOUNCE_SECONDS,
        )

    pool._callback_debouncers[dispatcher_chat_id] = asyncio.create_task(
        run_debounced_callback(pool, dispatcher_chat_id, event)
    )


async def run_debounced_callback(
    pool: "DeepWorkerPool", dispatcher_chat_id: str, event: ActionIntent,
) -> None:
    scheduled_at = time.perf_counter()
    try:
        await asyncio.sleep(pool._CALLBACK_DEBOUNCE_SECONDS)
    except asyncio.CancelledError:
        logger.info(
            "[DeepWorkerPool] callback debounce cancelled chat_id=%s "
            "task_id=%s elapsed_ms=%s",
            dispatcher_chat_id, event.task_id,
            int((time.perf_counter() - scheduled_at) * 1000),
        )
        return

    # Mark this debouncer as fired — from here on the scheduler must NOT
    # cancel it (a callback turn streaming to the user is about to run).
    _me = asyncio.current_task()
    if _me is not None:
        _me._fired = True  # type: ignore[attr-defined]

    if pool._stopped or not pool._orchestrator:
        return

    from starlette.websockets import WebSocketState
    ws_alive = (
        pool._ws is not None
        and getattr(pool._ws, "client_state", WebSocketState.CONNECTED) == WebSocketState.CONNECTED
    )
    if not ws_alive:
        # pending_store already holds task:completed for redelivery on
        # reconnect; the ambient events will be drained on the user's
        # next turn. No need to fire a headless model call.
        logger.info(
            f"[DeepWorkerPool] Skipping callback for {dispatcher_chat_id} — WS not alive"
        )
        if pool._callback_debouncers.get(dispatcher_chat_id) is _me:
            pool._callback_debouncers.pop(dispatcher_chat_id, None)
        return

    callback_start = time.perf_counter()
    logger.info(
        "[DeepWorkerPool] callback dispatcher enter chat_id=%s task_id=%s "
        "depth=%s debounce_elapsed_ms=%s",
        dispatcher_chat_id, event.task_id, event.callback_depth,
        int((callback_start - scheduled_at) * 1000),
    )
    try:
        await pool._orchestrator.handle_message(
            websocket=pool._ws,
            content="[worker-callback] Workers finished — see Worker activity block.",
            message_id=f"wcb-{uuid4().hex[:8]}",
            chat_id=dispatcher_chat_id,
            workspace_id=event.data.get("workspace_id"),
            layers=None,  # default fast; cheap + [SILENT]-aware
            chat_level=event.data.get("chat_level", "general"),
            is_callback=True,
            callback_depth=event.callback_depth,
            card_id=event.data.get("card_id"),
            session_id=event.session_id,
        )
        logger.info(
            "[DeepWorkerPool] callback dispatcher exit chat_id=%s task_id=%s "
            "elapsed_ms=%s",
            dispatcher_chat_id, event.task_id,
            int((time.perf_counter() - callback_start) * 1000),
        )
    except asyncio.CancelledError:
        logger.info(
            "[DeepWorkerPool] callback dispatcher cancelled chat_id=%s "
            "task_id=%s elapsed_ms=%s",
            dispatcher_chat_id, event.task_id,
            int((time.perf_counter() - callback_start) * 1000),
        )
        raise
    except Exception as e:
        logger.warning(
            f"[DeepWorkerPool] Dispatcher callback failed for {dispatcher_chat_id}: {e}"
        )
    finally:
        # Pop ONLY our own registry entry — a replacement debouncer may
        # already occupy this slot (scheduled while we were mid-turn);
        # popping it would leave that debouncer running untracked.
        if pool._callback_debouncers.get(dispatcher_chat_id) is _me:
            pool._callback_debouncers.pop(dispatcher_chat_id, None)


def count_active_for_chat(pool: "DeepWorkerPool", dispatcher_chat_id: str) -> int:
    """How many active worker tasks are currently tied to this dispatcher chat?

    Used by the Live-state heartbeat block on each turn.
    """
    if not dispatcher_chat_id:
        return 0
    count = 0
    for task_id in pool._active_tasks:
        meta = pool._task_meta.get(task_id)
        if meta and meta.get("dispatcher_chat_id") == dispatcher_chat_id:
            count += 1
    return count


def active_intents_for_chat(pool: "DeepWorkerPool", dispatcher_chat_id: str) -> list[str]:
    """Return a short intent/action label for each active worker tied to this chat.

    Feeds the enriched Live-state heartbeat so Voxy sees *what's* running,
    not just a count. When the worker has claimed the task, its one-line
    plan (voxyflow.worker.claim) is appended so the dispatcher knows what
    each worker is actually doing. Order is not guaranteed; cap at 10.
    """
    if not dispatcher_chat_id:
        return []
    supervisor = get_worker_supervisor()
    out: list[str] = []
    for task_id in list(pool._active_tasks.keys()):
        meta = pool._task_meta.get(task_id)
        if not meta:
            continue
        if meta.get("dispatcher_chat_id") != dispatcher_chat_id:
            continue
        label = str(meta.get("action") or "unknown")[:24]
        try:
            st = supervisor.get_status(task_id) or {}
            plan = (st.get("claim_plan") or "").strip()
        except Exception:
            plan = ""
        if plan:
            plan = " ".join(plan.split())  # collapse whitespace/newlines
            if len(plan) > 80:
                plan = plan[:79].rstrip() + "…"
            out.append(f"{label} — {plan}")
        else:
            out.append(label)
        if len(out) >= 10:
            break
    return out
