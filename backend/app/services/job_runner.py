"""Job runner — pure service module for scheduled/triggered job execution.

Owns the on-disk jobs.json persistence and the per-type ``_run_*`` handlers
that used to live in ``routes/jobs.py``. Extracted so the scheduler service
no longer has to lazy-import from a routes module (services → routes was a
layering violation).

The HTTP adapter (``routes/jobs.py``) keeps Pydantic schemas and the REST
endpoints; it delegates persistence and execution here.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

logger = logging.getLogger("voxyflow.jobs")


# ---------------------------------------------------------------------------
# Storage path
# ---------------------------------------------------------------------------

VOXYFLOW_DIR = Path(os.environ.get("VOXYFLOW_DATA_DIR", os.path.expanduser("~/.voxyflow")))
JOBS_FILE = VOXYFLOW_DIR / "jobs.json"


# ---------------------------------------------------------------------------
# Gate helpers
# ---------------------------------------------------------------------------


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _file_has_directive(path: str | Path, divider: str = "---") -> bool:
    """Return True if the file has actionable content below the divider line.

    Finds the first line whose stripped value equals ``divider``, takes everything
    after it, removes HTML comments, and returns True if any non-whitespace
    content remains. Returns False if the file is missing, unreadable, or has
    no divider — the divider is the explicit marker for "directives go here".
    """
    try:
        p = Path(path).expanduser()
        if not p.is_file():
            return False
        text = p.read_text(encoding="utf-8")
    except Exception:
        return False

    lines = text.splitlines()
    below_idx: int | None = None
    for i, line in enumerate(lines):
        if line.strip() == divider:
            below_idx = i + 1
            break
    if below_idx is None:
        return False

    below = "\n".join(lines[below_idx:])
    below = _HTML_COMMENT_RE.sub("", below)
    return bool(below.strip())


def _check_payload_gate(job: dict, payload: dict) -> dict | None:
    """If ``payload['gate']`` requests a check and it fails, return a skip result.

    Supported gates:
      - ``{"type": "file_has_directive", "path": "...", "divider": "---"}``
        Skip the job unless the file has actionable content below the divider.

    Returns None when the gate passes (or no gate configured).
    """
    gate = payload.get("gate")
    if not isinstance(gate, dict):
        return None

    gate_type = gate.get("type")
    if gate_type == "file_has_directive":
        gate_path = gate.get("path")
        divider = gate.get("divider") or "---"
        if not gate_path:
            return None
        if not _file_has_directive(gate_path, divider):
            msg = f"No directive in {gate_path} — skipped"
            logger.info(f"[Jobs] '{job.get('name')}' ({job.get('id')}) {msg}")
            return {"status": "skipped", "message": msg}
    return None


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _load_jobs() -> list[dict]:
    """Load jobs from ~/.voxyflow/jobs.json. Returns [] on any error."""
    if not JOBS_FILE.exists():
        return []
    try:
        with open(JOBS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Failed to load jobs: {e}")
        return []


def _save_jobs(jobs: list[dict]) -> None:
    """Persist jobs to ~/.voxyflow/jobs.json. Creates dir if needed."""
    try:
        VOXYFLOW_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = str(JOBS_FILE) + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2)
        os.replace(tmp_path, JOBS_FILE)
    except Exception as e:
        logger.error(f"Failed to save jobs: {e}")
        raise HTTPException(500, f"Failed to persist jobs: {e}")


def _find_job(jobs: list[dict], job_id: str) -> tuple[int, dict] | tuple[None, None]:
    """Find a job by id. Returns (index, job) or (None, None)."""
    for i, j in enumerate(jobs):
        if j.get("id") == job_id:
            return i, j
    return None, None


# ---------------------------------------------------------------------------
# Shared broadcast WebSocket adapter
# ---------------------------------------------------------------------------


class _BroadcastWS:
    """WebSocket adapter that broadcasts to all connected clients."""

    async def send_json(self, data):
        from app.services.ws_broadcast import ws_broadcast
        ws_broadcast.emit_sync(data.get("type", "job:event"), data.get("payload", data))


# ---------------------------------------------------------------------------
# Job execution dispatcher
# ---------------------------------------------------------------------------


async def _execute_job(job: dict) -> dict:
    """Dispatch job execution based on type. Returns result summary."""
    job_type = job.get("type", "custom")
    payload = job.get("payload", {})

    try:
        if job_type == "rag_index":
            return await _run_rag_index(job, payload)
        elif job_type == "reminder":
            return await _run_reminder(job, payload)
        elif job_type == "github_sync":
            return await _run_github_sync(job, payload)
        elif job_type in ("board_run", "execute_board"):
            # board_run jobs with instruction(s) are really agent_tasks
            if payload.get("instruction") or payload.get("instructions"):
                logger.info(f"[Jobs] Re-routing '{job.get('name')}' (board_run with instructions) → agent_task")
                return await _run_agent_task(job, payload)
            return await _run_execute_board(job, payload)
        elif job_type == "execute_card":
            return await _run_execute_card(job, payload)
        elif job_type == "agent_task":
            return await _run_agent_task(job, payload)
        elif job_type in ("heartbeat", "recurrence", "session_cleanup", "chromadb_backup"):
            return await _run_builtin(job, job_type)
        elif job_type == "custom":
            return await _run_custom(job, payload)
        else:
            return {"status": "error", "message": f"Unknown job type: {job_type}"}
    except Exception as e:
        logger.error(f"[Jobs] Job '{job['name']}' (type={job_type}) failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def _cleanup_job_session(chat_id: str, session_id: str) -> None:
    """Kill persistent CLI process, stop worker pool, and free session resources."""
    try:
        from app.main import _orchestrator
        _orchestrator.reset_session(chat_id, session_id)
        await _orchestrator.stop_worker_pool(session_id)
        logger.info(f"[Jobs] Cleaned up session chat_id={chat_id} session_id={session_id}")
    except Exception as e:
        logger.warning(f"[Jobs] Session cleanup failed: {e}")


def _emit_job_session(job: dict, chat_id: str, project_id: str | None = None) -> None:
    """Broadcast job:session:started so the frontend can label scheduler sessions."""
    try:
        from app.services.ws_broadcast import ws_broadcast
        ws_broadcast.emit_sync("job:session:started", {
            "chatId": chat_id,
            "jobId": job.get("id"),
            "jobName": job.get("name"),
            "jobType": job.get("type"),
            "projectId": project_id,
        })
    except Exception as e:
        logger.debug(f"[Jobs] Could not emit job:session:started: {e}")


# ---------------------------------------------------------------------------
# Per-type handlers
# ---------------------------------------------------------------------------


async def _run_rag_index(job: dict, payload: dict) -> dict:
    """Run a RAG index job for specific projects or all active projects.

    Payload keys (all optional):
      - project_ids: list[str]  → scope to these projects
      - project_id:  str        → legacy single-project scope
    Neither set → reindex all projects with recent activity (builtin sweep).
    """
    project_ids: list[str] = []
    raw_ids = payload.get("project_ids")
    if isinstance(raw_ids, list):
        project_ids.extend(str(x) for x in raw_ids if x)
    single = payload.get("project_id")
    if isinstance(single, str) and single:
        project_ids.append(single)

    from app.services.scheduler_service import get_scheduler_service

    svc = get_scheduler_service()
    await svc._rag_index_job(project_ids=project_ids or None)
    scope = ", ".join(project_ids) if project_ids else "all active"
    return {"status": "ok", "message": f"RAG index triggered (scope={scope})"}


async def _run_builtin(job: dict, job_type: str) -> dict:
    """Route built-in job types to their scheduler handlers."""
    from app.services.scheduler_service import get_scheduler_service

    svc = get_scheduler_service()
    handler_map = {
        "heartbeat": svc._heartbeat_job,
        "recurrence": svc._recurrence_job,
        "session_cleanup": svc._session_cleanup_job,
        "chromadb_backup": svc._chromadb_backup_job,
    }
    handler = handler_map.get(job_type)
    if not handler:
        return {"status": "error", "message": f"No handler for built-in type: {job_type}"}
    await handler()
    return {"status": "ok", "message": f"{job_type} completed"}


async def _run_reminder(job: dict, payload: dict) -> dict:
    """Log a reminder and broadcast via WebSocket."""
    message = payload.get("message", job.get("name", "Reminder"))
    logger.info(f"[Jobs][Reminder] {message}")

    from app.services.ws_broadcast import ws_broadcast
    ws_broadcast.emit_sync("reminder:fired", {
        "jobId": job.get("id"),
        "jobName": job.get("name", "Reminder"),
        "message": message,
    })

    return {"status": "ok", "message": f"Reminder delivered: {message}"}


async def _run_github_sync(job: dict, payload: dict) -> dict:
    """Placeholder for GitHub sync job."""
    repo = payload.get("repo", "")
    logger.info(f"[Jobs][GithubSync] Would sync repo: {repo}")
    return {"status": "ok", "message": f"GitHub sync placeholder (repo={repo})"}


async def _run_execute_board(job: dict, payload: dict) -> dict:
    """Execute all matching cards from a project board."""
    project_id = payload.get("project_id")
    if not project_id:
        return {"status": "error", "message": "Missing project_id in payload"}

    statuses = payload.get("statuses", ["todo"])
    logger.info(f"[Jobs][ExecuteBoard] Starting board run for project={project_id}, statuses={statuses}")

    from app.services.board_executor import build_execution_plan, execute_board

    plan = await build_execution_plan(project_id, statuses)
    if not plan.cards:
        return {"status": "ok", "message": "No cards to execute"}

    from app.main import _orchestrator

    session_id = f"job-{job.get('id', str(uuid4()))}"
    chat_id = f"job:{plan.execution_id}"

    _emit_job_session(job, chat_id, project_id)

    try:
        await execute_board(
            execution_id=plan.execution_id,
            project_id=project_id,
            cards=plan.cards,
            websocket=_BroadcastWS(),
            orchestrator=_orchestrator,
            session_id=session_id,
            chat_id=chat_id,
        )
    finally:
        await _cleanup_job_session(chat_id, session_id)

    return {"status": "ok", "message": f"Board run completed: {plan.total} cards executed"}


async def _run_execute_card(job: dict, payload: dict) -> dict:
    """Execute a single card through the chat pipeline."""
    card_id = payload.get("card_id")
    if not card_id:
        return {"status": "error", "message": "Missing card_id in payload"}

    project_id = payload.get("project_id")
    logger.info(f"[Jobs][ExecuteCard] Executing card={card_id}, project={project_id or 'none'}")

    from app.services.board_executor import _build_card_prompt
    from app.main import _orchestrator

    prompt, _project_name = await _build_card_prompt(card_id)

    session_id = f"job-{job.get('id', str(uuid4()))}"
    chat_id = f"job:{job.get('id')}-{uuid4().hex[:8]}"
    message_id = f"exec-card-{uuid4().hex[:8]}"

    _emit_job_session(job, chat_id, project_id)

    try:
        bg_tasks = await _orchestrator.handle_message(
            websocket=_BroadcastWS(),
            content=prompt,
            message_id=message_id,
            chat_id=chat_id,
            project_id=project_id,
            chat_level="project" if project_id else "general",
            card_id=card_id,
            session_id=session_id,
        )

        if bg_tasks:
            results = await asyncio.gather(*bg_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"[Jobs][ExecuteCard] Background task failed: {r}")
    finally:
        await _cleanup_job_session(chat_id, session_id)

    return {"status": "ok", "message": f"Card {card_id} executed"}


async def _run_agent_task(job: dict, payload: dict) -> dict:
    """Execute a freeform instruction through the chat pipeline.

    Project heartbeats (jobs flagged ``project_heartbeat`` with a ``project_id``)
    are routed through the dedicated autonomy runner instead of the interactive
    dispatcher — same toolset, but without the 'wait for go' gate.
    """
    is_heartbeat = bool(
        payload.get("project_heartbeat") or job.get("project_heartbeat")
    )
    if is_heartbeat and payload.get("project_id"):
        return await _run_autonomy_tick(job, payload)

    instruction = (
        payload.get("instruction")
        or payload.get("instructions")
        or payload.get("prompt")
    )
    if not instruction:
        return {"status": "error", "message": "Missing instruction in payload"}

    if isinstance(instruction, list):
        instruction = "\n".join(instruction)

    gated = _check_payload_gate(job, payload)
    if gated is not None:
        return gated

    project_id = payload.get("project_id")
    logger.info(f"[Jobs][AgentTask] Starting agent task '{job.get('name')}' (project={project_id or 'none'})")

    from app.main import _orchestrator

    session_id = f"job-{job.get('id', str(uuid4()))}"
    chat_id = f"job:{job.get('id')}-{uuid4().hex[:8]}"
    message_id = f"agent-task-{uuid4().hex[:8]}"

    _emit_job_session(job, chat_id, project_id)

    try:
        bg_tasks = await _orchestrator.handle_message(
            websocket=_BroadcastWS(),
            content=instruction,
            message_id=message_id,
            chat_id=chat_id,
            project_id=project_id,
            chat_level="project" if project_id else "general",
            session_id=session_id,
        )

        if bg_tasks:
            results = await asyncio.gather(*bg_tasks, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"[Jobs][AgentTask] Background task failed: {r}")
    finally:
        await _cleanup_job_session(chat_id, session_id)

    return {"status": "ok", "message": f"Agent task completed: {job.get('name')}"}


# ---------------------------------------------------------------------------
# Autonomy tick registry — lets cancel_worker_task_global stop a live tick
# ---------------------------------------------------------------------------


_active_autonomy_tasks: dict[str, asyncio.Task] = {}


def get_active_autonomy_task(task_id: str) -> asyncio.Task | None:
    """Return the asyncio.Task running an autonomy tick, or None."""
    return _active_autonomy_tasks.get(task_id)


async def cancel_autonomy_task(task_id: str) -> bool:
    """Cancel a running autonomy tick by task_id. Returns True if a task was cancelled."""
    task = _active_autonomy_tasks.get(task_id)
    if task is None or task.done():
        return False
    task.cancel()
    logger.info(f"[autonomy-tick] cancel requested task_id={task_id}")
    return True


async def _emit_ws(event_type: str, payload: dict) -> None:
    try:
        from app.services.ws_broadcast import ws_broadcast
        ws_broadcast.emit_sync(event_type, payload)
    except Exception as e:
        logger.debug(f"[autonomy-tick] ws emit {event_type} failed: {e}")


async def _run_autonomy_tick(job: dict, payload: dict) -> dict:
    """Execute a project autonomy heartbeat — dispatcher-shaped, no 'go' gate.

    The tick is registered in ``WorkerSessionStore`` as a pseudo-session
    (``worker_class="autonomy"``, ``intent="autonomy"``) so it shows up in the
    Worker Panel alongside regular workers, and can be cancelled mid-run via
    the standard ``task:cancel`` WS flow.
    """
    import time
    project_id = payload.get("project_id")
    if not project_id:
        return {"status": "error", "message": "autonomy tick requires project_id"}

    gated = _check_payload_gate(job, payload)
    if gated is not None:
        return gated

    from app.services.project_autonomy import heartbeat_file, read_directive
    directive_path = str(heartbeat_file(project_id))
    directive = read_directive(project_id)

    instruction = payload.get("instruction") or "autonomy-tick"
    if isinstance(instruction, list):
        instruction = "\n".join(instruction)
    user_message = (
        f"[AUTONOMY TICK]\n\n"
        f"Directive file: {directive_path}\n\n"
        f"Current directive (below the divider):\n{directive or '(empty)'}\n\n"
        f"{instruction}"
    )

    job_id = job.get("id") or uuid4().hex
    session_id = f"autonomy-{job_id}"
    chat_id = f"autonomy:{job_id}-{uuid4().hex[:8]}"
    message_id = f"autonomy-tick-{uuid4().hex[:8]}"
    # task_id is the handle the frontend uses to cancel / peek. One per tick
    # so reruns of the same job don't collide in the session store.
    task_id = f"autonomy-{job_id}-{uuid4().hex[:8]}"

    _emit_job_session(job, chat_id, project_id)

    # Register in the worker session store so the Worker Panel sees it.
    summary = f"Heartbeat — {job.get('name') or job_id}"
    try:
        from app.services.worker_session_store import get_worker_session_store
        from app.config import settings as _settings
        model_label = getattr(_settings, "claude_fast_model", "") or "sonnet"
        get_worker_session_store().register(
            task_id=task_id,
            session_id=session_id,
            chat_id=chat_id,
            project_id=project_id,
            card_id=None,
            model=model_label,
            intent="autonomy",
            summary=summary,
            worker_class="autonomy",
        )
        await _emit_ws("task:started", {
            "taskId": task_id,
            "projectId": project_id,
            "cardId": None,
            "chatId": chat_id,
            "sessionId": session_id,
            "intent": "autonomy",
            "summary": summary,
            "model": model_label,
            "workerClass": "autonomy",
        })
    except Exception as e:
        logger.warning(f"[autonomy-tick] could not register session: {e}")

    from app.main import _orchestrator

    start = time.time()
    spawned = 0
    status = "completed"
    error_msg: str | None = None
    logger.info(
        f"[autonomy-tick] start project={project_id} job={job_id} "
        f"session={session_id} task={task_id}"
    )

    async def _run_handle_message():
        bg = await _orchestrator.handle_message(
            websocket=_BroadcastWS(),
            content=user_message,
            message_id=message_id,
            chat_id=chat_id,
            project_id=project_id,
            chat_level="project",
            session_id=session_id,
            role="autonomy",
            autonomy_directive_path=directive_path,
        )
        if bg:
            results = await asyncio.gather(*bg, return_exceptions=True)
            for r in results:
                if isinstance(r, Exception):
                    logger.warning(f"[autonomy-tick] background task failed: {r}")
        return len(bg) if bg else 0

    handle_task = asyncio.create_task(_run_handle_message())
    _active_autonomy_tasks[task_id] = handle_task
    try:
        try:
            spawned = await handle_task
        except asyncio.CancelledError:
            status = "cancelled"
            logger.info(f"[autonomy-tick] cancelled task={task_id}")
        except Exception as e:
            status = "failed"
            error_msg = str(e)
            logger.error(f"[autonomy-tick] failed task={task_id}: {e}", exc_info=True)
    finally:
        _active_autonomy_tasks.pop(task_id, None)
        await _cleanup_job_session(chat_id, session_id)

    duration = time.time() - start
    result_summary = (
        f"{spawned} delegate{'s' if spawned != 1 else ''}, {duration:.1f}s"
        if status == "completed"
        else (error_msg or status)
    )
    try:
        from app.services.worker_session_store import get_worker_session_store
        get_worker_session_store().update_status(task_id, status, result_summary=result_summary)
    except Exception as e:
        logger.debug(f"[autonomy-tick] could not update store status: {e}")

    if status == "cancelled":
        await _emit_ws("task:cancelled", {
            "taskId": task_id,
            "sessionId": session_id,
            "chatId": chat_id,
        })
    else:
        await _emit_ws("task:completed", {
            "taskId": task_id,
            "sessionId": session_id,
            "chatId": chat_id,
            "success": status == "completed",
            "result": result_summary,
        })

    logger.info(
        f"[autonomy-tick] end project={project_id} job={job_id} "
        f"duration={duration:.2f}s spawned={spawned} status={status}"
    )

    try:
        from app.services.push_service import notify_user
        body_status = "completed" if status == "completed" else status
        asyncio.create_task(notify_user(
            event="autonomy_result",
            title=f"Heartbeat: {job.get('name', 'autonomy')}",
            body=(
                f"Autonomy cycle {body_status} "
                f"({duration:.1f}s, {spawned} delegate{'s' if spawned != 1 else ''})."
            ),
            url=f"/project/{project_id}",
            tag=f"autonomy-{job_id}",
        ))
    except Exception as _push_err:
        logger.warning(f"[autonomy-tick] push dispatch failed: {_push_err}")

    return {
        "status": "ok" if status == "completed" else status,
        "message": f"Autonomy tick {status}: {job.get('name')}",
    }


async def _run_custom(job: dict, payload: dict) -> dict:
    """Placeholder for custom job types."""
    logger.info(f"[Jobs][Custom] Triggered custom job '{job['name']}'")
    return {"status": "ok", "message": "Custom job triggered (no executor registered)"}
