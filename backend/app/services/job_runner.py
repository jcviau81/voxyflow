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
    """Run a RAG index job for a specific project or all active projects."""
    project_id = payload.get("project_id")

    from app.services.scheduler_service import get_scheduler_service

    svc = get_scheduler_service()
    await svc._rag_index_job()
    return {"status": "ok", "message": f"RAG index triggered (project_id={project_id or 'all active'})"}


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
    """Execute a freeform instruction through the chat pipeline."""
    instruction = payload.get("instruction") or payload.get("instructions")
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


async def _run_custom(job: dict, payload: dict) -> dict:
    """Placeholder for custom job types."""
    logger.info(f"[Jobs][Custom] Triggered custom job '{job['name']}'")
    return {"status": "ok", "message": "Custom job triggered (no executor registered)"}
