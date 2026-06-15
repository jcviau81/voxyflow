"""Worker completion publication — result fallbacks, closeout, artifacts, events.

Extracted verbatim from worker_pool._execute_event and the closeout helpers.
The terminal store/ledger status updates (``update_status`` + ``_ledger_update``)
deliberately STAY in ``worker_pool.py`` — the session-store sync invariant is
audited statically against that file (see
tests/test_worker_pool_session_store_sync.py).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING
from uuid import uuid4

from app.services.event_bus import ActionIntent, event_bus_registry
from app.services.orchestration.result_formatting import (
    WS_RESULT_CHARS,
    _format_result_for_card,
    _preview,
)

if TYPE_CHECKING:
    from app.services.claude_service import ClaudeService
    from app.services.orchestration.worker_pool import DeepWorkerPool

logger = logging.getLogger("voxyflow.orchestration")


# ------------------------------------------------------------------
# Worker lifecycle: closeout pass + local fallback
# ------------------------------------------------------------------


async def closeout_pass(
    claude: "ClaudeService",
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

    # Reuse the resolved worker class endpoint so closeout runs on the same
    # provider as the original worker (avoids routing closeout to whatever
    # the Fast layer points at — e.g. a local model that struggles with the
    # structured worker.complete tool-call protocol).
    closeout_endpoint_config = event.data.get("_resolved_worker_class_endpoint")
    closeout_model = os.environ.get(
        "VOXYFLOW_CLOSEOUT_MODEL",
        event.data.get("_resolved_worker_model") or "fast",
    )
    closeout_timeout = int(os.environ.get("VOXYFLOW_CLOSEOUT_TIMEOUT", "90"))

    status = supervisor.get_status(event.task_id) or {}
    source_hint = status.get("completion_source")
    if source_hint == "auto":
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
        "2. OPTIONAL skill capture: if the task involved a non-obvious multi-step "
        "procedure that would help future tasks, call voxyflow.skill.save "
        "(name: kebab-case slug, description: 1-2 sentences, instructions: concise "
        "steps distilled from the artifact). Update an existing skill instead of "
        "creating a near-duplicate. Skip this for trivial or one-off tasks.\n"
        "3. Call voxyflow.worker.complete exactly once with:\n"
        "   - status: \"success\" if the task looks complete, \"partial\" otherwise\n"
        "   - summary: 2–4 sentences in plain prose — what was done, what the dispatcher needs to know\n"
        "   - findings: 3–7 short bullets of the most important results\n"
        "   - pointers: list of {label, offset, length} into the artifact for notable sections\n"
        "   - next_step: optional one-liner the dispatcher could act on\n"
        "4. Stop after voxyflow.worker.complete — do not do anything else."
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
            claude.execute_lightweight_task(
                chat_id=f"closeout-{event.task_id}",
                prompt=closeout_prompt,
                model=closeout_model,
                workspace_id=event.data.get("workspace_id"),
                card_context=None,
                tool_callback=_closeout_cb,
                cancel_event=closeout_cancel,
                message_queue=closeout_mq,
                session_id=event.session_id or "",
                task_id=event.task_id,
                endpoint_config=closeout_endpoint_config,
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


def synthesize_fallback_completion(
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
    # Raw worker text is usually reasoning / logs / tool output with heavy
    # whitespace and newlines. Collapse it so the dispatcher-facing summary
    # reads as a single prose blurb instead of a broken multi-line dump.
    text = " ".join(text.split())
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


# ------------------------------------------------------------------
# Happy-path completion phases (called in order from _execute_event)
# ------------------------------------------------------------------


def resolve_result_content(
    claude: "ClaudeService",
    event: ActionIntent,
    result_content: str | None,
    captured_tool_outputs: list[str],
    supervisor,
    task_chat_id: str,
) -> str | None:
    """Apply the result fallback chain: history → event.summary → captured
    tool outputs, then auto-complete / completion_summary preference."""
    if not result_content:
        try:
            task_history = claude.get_history(task_chat_id)
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
    if captured_tool_outputs:
        captured_total = sum(len(o) for o in captured_tool_outputs)
        llm_len = len(result_content or "")
        if captured_total > llm_len * 2 and captured_total > 500:
            logger.info(
                f"[DeepWorker] Using captured tool output ({captured_total} chars) "
                f"over LLM text ({llm_len} chars) for task {event.task_id}"
            )
            result_content = "\n\n".join(captured_tool_outputs)

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

    return result_content


def extract_follow_up(result_content):
    """Extract a structured follow_up action from a JSON result, if present.

    Returns ``(follow_up_action, result_content)``.
    """
    follow_up_action = None
    try:
        parsed_result = json.loads(result_content.strip())
        if isinstance(parsed_result, dict) and "follow_up" in parsed_result:
            follow_up_action = parsed_result["follow_up"]
            result_content = parsed_result.get("result", result_content)
            logger.info(f"[DeepWorker] follow_up extracted from structured result: '{follow_up_action[:80]}'")
    except (json.JSONDecodeError, ValueError):
        pass  # Not JSON, no follow_up
    return follow_up_action, result_content


async def append_result_to_card(
    pool: "DeepWorkerPool",
    event: ActionIntent,
    result_content: str | None,
) -> None:
    """Append the worker result to the task's card and move it to done."""
    card_id = event.data.get("card_id")
    if not card_id:
        return
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
                await pool._send_task_event("tool:executed", event.task_id, {
                    "tool": "voxyflow.card.update",
                    "args": {"card_id": card_id, "workspace_id": event.data.get("workspace_id")},
                    "result": {"success": True},
                    "sessionId": event.session_id,
                })
                # Broadcast card change so all frontends refresh
                from app.services.ws_broadcast import ws_broadcast
                ws_broadcast.emit_sync("cards:changed", {
                    "workspaceId": event.data.get("workspace_id"),
                    "cardId": card_id,
                })
    except Exception as append_err:
        logger.warning(f"[CardLifecycle] Failed card completion update for {card_id}: {append_err}")


async def finalize_completion_artifacts(
    claude: "ClaudeService",
    event: ActionIntent,
    result_content: str | None,
    supervisor,
) -> str | None:
    """Write the artifact, run the closeout / fallback chain, persist the
    completion sidecar. Returns the artifact path (or None)."""
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
            workspace_id=event.data.get("workspace_id"),
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
        await closeout_pass(claude, event, artifact_path, result_content)

    # Local synthesis fallback — if closeout also failed, synthesize
    # a minimal structured payload from what we have. Keeps the
    # dispatcher path uniform even when both tiers above missed.
    if not supervisor.is_structured_complete(event.task_id):
        synthesize_fallback_completion(event, result_content)

    # Persist the final structured completion as a sidecar JSON.
    #
    # Do not rewrite the .md artifact here. Worker.complete pointers
    # are offsets into the raw artifact body produced above; prefixing
    # the artifact with a rendered completion block would shift those
    # offsets and make read_artifact(pointer.offset, pointer.length)
    # return the wrong slice.
    # Supervisor state is in-memory and gets GC'd; the sidecar lets
    # workers.get_result return findings/pointers across restarts.
    final_completion = supervisor.get_completion_payload(event.task_id)
    if final_completion:
        from app.services.worker_artifact_store import write_completion
        write_completion(event.task_id, final_completion)

    return artifact_path


async def publish_completion(
    pool: "DeepWorkerPool",
    event: ActionIntent,
    *,
    result_content: str | None,
    result_preview: str,
    artifact_path: str | None,
    supervisor,
    follow_up_action,
    task_chat_id: str,
) -> None:
    """Publish a successful completion: timeline, WS event, push notification,
    session-store persistence, ambient worker event, follow_up chaining and
    worker-session cleanup.

    The terminal ``update_status``/``_ledger_update`` pair runs in
    ``_execute_event`` BEFORE this is called.
    """
    # Record completion in session timeline
    if event.session_id:
        from app.services.orchestration.session_timeline import get_timeline
        get_timeline().record(
            event.session_id, "completed", event.intent or "unknown",
            task_id=event.task_id, model=event.model,
            summary=(result_content or "")[:120],
        )

    await pool._send_task_event("task:completed", event.task_id, {
        "intent": event.intent,
        "summary": event.summary,
        "result": _preview(result_content, WS_RESULT_CHARS) if result_content else "",
        "totalChars": len(result_content or ""),
        "success": True,
        "sessionId": event.session_id,
        "workspaceId": event.data.get("workspace_id"),
        "cardId": event.data.get("card_id"),
        "artifactPath": artifact_path,
    })

    # Fire-and-forget Web Push notification — gated by push.enabled in settings
    try:
        from app.services.push_service import build_deep_link, notify_user
        _pid = event.data.get("workspace_id")
        _cid = event.data.get("card_id")
        _body = (result_content or result_preview or "").strip()[:140] or "Task finished."
        _push_task = asyncio.create_task(notify_user(
            event="worker_done",
            title=f"Worker finished: {event.intent or 'task'}",
            body=_body,
            url=build_deep_link(_pid, _cid),
            tag=f"worker-{event.task_id}",
        ))
        pool._bg_push_tasks.add(_push_task)
        _push_task.add_done_callback(pool._bg_push_tasks.discard)
    except Exception as _push_err:
        logger.warning(f"[DeepWorker] Web push (success) dispatch failed: {_push_err}")

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

    # --- Record ambient worker event (NOT a dispatcher turn) ---
    # The structured worker.complete payload (findings + pointers +
    # next_step) ships with the event so it appears verbatim in the
    # next turn's worker-activity block. Fast-tier dispatchers don't
    # reliably call workers.get_result on their own — putting the
    # deliverable in front of them keeps the pull-on-demand contract
    # honest without re-introducing the parallel-flood failure mode
    # the bounded block size already prevents.
    dispatcher_chat_id = event.data.get("dispatcher_chat_id")
    if dispatcher_chat_id:
        payload = supervisor.get_completion_payload(event.task_id)
        status = (payload or {}).get("status") or "success"
        summary_source = ((payload or {}).get("summary") or result_content or "").strip()
        summary_line = " · ".join(
            ln.strip() for ln in summary_source.splitlines() if ln.strip()
        )
        pool.record_worker_event(
            dispatcher_chat_id,
            task_id=event.task_id,
            intent=event.intent or "",
            status=status,
            summary_line=summary_line,
            completion=payload,
        )
        pool._schedule_dispatcher_callback(dispatcher_chat_id, event)

    if follow_up_action and pool._orchestrator and event.session_id:
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
        pool._claude.cleanup_chat(task_chat_id)
        logger.info(f"[DeepWorker] Cleaned up worker session {task_chat_id}")
    except Exception as _cleanup_err:
        logger.warning(f"[DeepWorker] Session cleanup failed: {_cleanup_err}")


# ------------------------------------------------------------------
# Cancel / failure recording — keeps the dispatcher informed so it never
# silently re-delegates an interrupted worker.
# ------------------------------------------------------------------


def record_cancellation(pool: "DeepWorkerPool", event: ActionIntent) -> None:
    """Surface the cancel/stall to the dispatcher. Without this an
    interrupted worker is invisible in the ambient worker-events
    block (the CancelledError branch never reaches the normal recording
    path), so the dispatcher assumes it's still running or silently
    re-delegates. Distinguish a stall-timeout from a user cancel
    via the supervisor's problem reason."""
    from app.services.worker_supervisor import get_worker_supervisor
    dispatcher_chat_id = event.data.get("dispatcher_chat_id")
    if dispatcher_chat_id:
        try:
            st = get_worker_supervisor().get_status(event.task_id) or {}
            problem = (st.get("problem_reason") or "").strip()
        except Exception:
            problem = ""
        if problem.startswith("stalled"):
            status_label = "timed_out"
            reason = f"Worker stalled with no activity and was stopped ({problem})."
        elif problem:
            status_label = "failed"
            reason = f"Worker stopped — {problem}."
        else:
            status_label = "cancelled"
            reason = "Worker was cancelled before it completed."
        try:
            pool.record_worker_event(
                dispatcher_chat_id,
                task_id=event.task_id,
                intent=event.intent or "",
                status=status_label,
                summary_line=reason,
            )
            pool._schedule_dispatcher_callback(dispatcher_chat_id, event)
        except Exception as _rec_err:
            logger.warning(
                f"[DeepWorker] Failed to record cancel event for "
                f"{event.task_id}: {_rec_err}"
            )


async def record_failure(pool: "DeepWorkerPool", event: ActionIntent, e: Exception) -> None:
    """Publish a worker failure: WS event, push notification, timeline entry
    and the ambient failure event for the dispatcher's next turn.

    The terminal ``update_status``/``_ledger_update`` pair runs in
    ``_execute_event``'s exception handler BEFORE this is called.
    """
    try:
        await pool._send_task_event("task:completed", event.task_id, {
            "intent": event.intent,
            "summary": event.summary,
            "result": str(e),
            "success": False,
            "sessionId": event.session_id,
            "workspaceId": event.data.get("workspace_id"),
            "cardId": event.data.get("card_id"),
        })
    except Exception:
        pass

    # Fire-and-forget Web Push notification on failure
    try:
        from app.services.push_service import build_deep_link, notify_user
        _pid = event.data.get("workspace_id")
        _cid = event.data.get("card_id")
        _body = str(e)[:140] or "Task failed."
        _push_task = asyncio.create_task(notify_user(
            event="worker_done",
            title=f"Worker failed: {event.intent or 'task'}",
            body=_body,
            url=build_deep_link(_pid, _cid),
            tag=f"worker-{event.task_id}",
        ))
        pool._bg_push_tasks.add(_push_task)
        _push_task.add_done_callback(pool._bg_push_tasks.discard)
    except Exception as _push_err:
        logger.warning(f"[DeepWorker] Web push (failure) dispatch failed: {_push_err}")

    # Record failure in session timeline
    if event.session_id:
        from app.services.orchestration.session_timeline import get_timeline
        get_timeline().record(
            event.session_id, "failed", event.intent or "unknown",
            task_id=event.task_id, model=event.model,
            summary=str(e)[:120],
        )

    # Record ambient failure event — dispatcher will see it on its next turn.
    dispatcher_chat_id = event.data.get("dispatcher_chat_id")
    if dispatcher_chat_id:
        pool.record_worker_event(
            dispatcher_chat_id,
            task_id=event.task_id,
            intent=event.intent or "",
            status="failed",
            summary_line=str(e)[:200],
        )
        pool._schedule_dispatcher_callback(dispatcher_chat_id, event)
