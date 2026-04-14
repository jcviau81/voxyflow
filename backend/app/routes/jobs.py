"""Jobs API — user-defined cron/scheduled tasks.

GET    /api/jobs          → list configured jobs
POST   /api/jobs          → create new job
PUT    /api/jobs/{id}     → update job (full)
PATCH  /api/jobs/{id}     → update job (partial — same as PUT, for frontend compat)
DELETE /api/jobs/{id}     → delete job
POST   /api/jobs/{id}/run → trigger job immediately

Jobs are persisted to ~/.voxyflow/jobs.json.
APScheduler is kept in sync on every CRUD operation.
"""

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("voxyflow.jobs")

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# ---------------------------------------------------------------------------
# Storage path
# ---------------------------------------------------------------------------

VOXYFLOW_DIR = Path(os.environ.get("VOXYFLOW_DATA_DIR", os.path.expanduser("~/.voxyflow")))
JOBS_FILE = VOXYFLOW_DIR / "jobs.json"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

JobType = Literal[
    "reminder", "github_sync", "rag_index", "custom",
    "board_run", "execute_board", "execute_card", "agent_task",
    "heartbeat", "recurrence", "session_cleanup", "chromadb_backup",
]


class JobModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: JobType = "custom"
    schedule: str  # cron expression OR "every_Xmin" / "every_Xh"
    enabled: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)
    last_run: Optional[str] = None
    next_run: Optional[str] = None


class JobCreateRequest(BaseModel):
    name: str
    type: JobType = "custom"
    schedule: str
    enabled: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)


class JobUpdateRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[JobType] = None
    schedule: Optional[str] = None
    enabled: Optional[bool] = None
    payload: Optional[dict[str, Any]] = None


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
        with open(JOBS_FILE, "w", encoding="utf-8") as f:
            json.dump(jobs, f, indent=2)
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
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_jobs():
    """List all configured jobs (enriched with live next_run from APScheduler)."""
    jobs = _load_jobs()

    # Enrich with live next_run from APScheduler (best-effort)
    try:
        from app.services.scheduler_service import get_scheduler_service
        svc = get_scheduler_service()
        for job in jobs:
            job_id = job.get("id", "")
            if job_id:
                next_run = svc.get_next_run(job_id)
                if next_run:
                    job["next_run"] = next_run
    except Exception as _e:
        logger.debug(f"[Jobs] Could not fetch next_run from scheduler: {_e}")

    # Built-in jobs first, then user jobs (preserving order within each group)
    builtin = [j for j in jobs if j.get("builtin")]
    user = [j for j in jobs if not j.get("builtin")]
    return {"jobs": builtin + user, "total": len(jobs)}


@router.post("", status_code=201)
async def create_job(req: JobCreateRequest):
    """Create a new job and register it with APScheduler."""
    jobs = _load_jobs()
    new_job = JobModel(
        name=req.name,
        type=req.type,
        schedule=req.schedule,
        enabled=req.enabled,
        payload=req.payload,
    )
    job_dict = new_job.dict()
    jobs.append(job_dict)
    _save_jobs(jobs)
    logger.info(f"[Jobs] Created job '{new_job.name}' (id={new_job.id}, schedule={new_job.schedule})")

    # Register with live APScheduler
    try:
        from app.services.scheduler_service import get_scheduler_service
        get_scheduler_service().register_user_job(job_dict)
    except Exception as e:
        logger.warning(f"[Jobs] Could not register job with APScheduler: {e}")

    return job_dict


async def _do_update_job(job_id: str, req: JobUpdateRequest):
    """Shared logic for PUT and PATCH update."""
    jobs = _load_jobs()
    idx, job = _find_job(jobs, job_id)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")

    if req.name is not None:
        job["name"] = req.name
    if req.type is not None:
        job["type"] = req.type
    if req.schedule is not None:
        job["schedule"] = req.schedule
    if req.enabled is not None:
        job["enabled"] = req.enabled
    if req.payload is not None:
        job["payload"] = req.payload

    jobs[idx] = job
    _save_jobs(jobs)
    logger.info(f"[Jobs] Updated job '{job['name']}' (id={job_id})")

    # Sync with live APScheduler (re-register to pick up schedule/enabled changes)
    try:
        from app.services.scheduler_service import get_scheduler_service
        get_scheduler_service().register_user_job(job)
    except Exception as e:
        logger.warning(f"[Jobs] Could not sync job with APScheduler: {e}")

    return job


@router.put("/{job_id}")
async def update_job(job_id: str, req: JobUpdateRequest):
    """Update an existing job (full update)."""
    return await _do_update_job(job_id, req)


@router.patch("/{job_id}")
async def patch_job(job_id: str, req: JobUpdateRequest):
    """Update an existing job (partial update — alias for PUT, for frontend compat)."""
    return await _do_update_job(job_id, req)


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str):
    """Delete a job and unregister it from APScheduler."""
    jobs = _load_jobs()
    idx, job = _find_job(jobs, job_id)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")

    jobs.pop(idx)
    _save_jobs(jobs)
    logger.info(f"[Jobs] Deleted job '{job['name']}' (id={job_id})")

    # Unregister from APScheduler
    try:
        from app.services.scheduler_service import get_scheduler_service
        get_scheduler_service().unregister_user_job(job_id)
    except Exception as e:
        logger.warning(f"[Jobs] Could not unregister job from APScheduler: {e}")

    return None


@router.post("/{job_id}/run")
async def trigger_job(job_id: str):
    """Trigger a job immediately (fire-and-forget)."""
    jobs = _load_jobs()
    _, job = _find_job(jobs, job_id)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")

    result = await _execute_job(job)
    return {"status": "triggered", "job_id": job_id, "name": job["name"], "result": result}


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
    from uuid import uuid4

    plan = await build_execution_plan(project_id, statuses)
    if not plan.cards:
        return {"status": "ok", "message": "No cards to execute"}

    from app.main import _orchestrator

    session_id = f"job-{job.get('id', str(uuid4()))}"
    chat_id = f"job:{plan.execution_id}"

    _emit_job_session(job, chat_id, project_id)

    await execute_board(
        execution_id=plan.execution_id,
        project_id=project_id,
        cards=plan.cards,
        websocket=_BroadcastWS(),
        orchestrator=_orchestrator,
        session_id=session_id,
        chat_id=chat_id,
    )

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
    from uuid import uuid4

    prompt, _project_name = await _build_card_prompt(card_id)

    session_id = f"job-{job.get('id', str(uuid4()))}"
    chat_id = f"job:{job.get('id')}-{uuid4().hex[:8]}"
    message_id = f"exec-card-{uuid4().hex[:8]}"

    _emit_job_session(job, chat_id, project_id)

    bg_tasks = await _orchestrator.handle_message(
        websocket=_BroadcastWS(),
        content=prompt,
        message_id=message_id,
        chat_id=chat_id,
        project_id=project_id,
        layers={"deep": False},
        chat_level="project" if project_id else "general",
        card_id=card_id,
        session_id=session_id,
    )

    if bg_tasks:
        results = await asyncio.gather(*bg_tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"[Jobs][ExecuteCard] Background task failed: {r}")

    return {"status": "ok", "message": f"Card {card_id} executed"}


async def _run_agent_task(job: dict, payload: dict) -> dict:
    """Execute a freeform instruction through the chat pipeline."""
    instruction = payload.get("instruction") or payload.get("instructions")
    if not instruction:
        return {"status": "error", "message": "Missing instruction in payload"}

    if isinstance(instruction, list):
        instruction = "\n".join(instruction)

    project_id = payload.get("project_id")
    use_deep = payload.get("deep", True)  # agent_tasks default to deep model
    logger.info(f"[Jobs][AgentTask] Starting agent task '{job.get('name')}' (project={project_id or 'none'}, deep={use_deep})")

    from app.main import _orchestrator
    from uuid import uuid4

    session_id = f"job-{job.get('id', str(uuid4()))}"
    chat_id = f"job:{job.get('id')}-{uuid4().hex[:8]}"
    message_id = f"agent-task-{uuid4().hex[:8]}"

    _emit_job_session(job, chat_id, project_id)

    bg_tasks = await _orchestrator.handle_message(
        websocket=_BroadcastWS(),
        content=instruction,
        message_id=message_id,
        chat_id=chat_id,
        project_id=project_id,
        layers={"deep": use_deep},
        chat_level="project" if project_id else "general",
        session_id=session_id,
    )

    if bg_tasks:
        results = await asyncio.gather(*bg_tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning(f"[Jobs][AgentTask] Background task failed: {r}")

    return {"status": "ok", "message": f"Agent task completed: {job.get('name')}"}


async def _run_custom(job: dict, payload: dict) -> dict:
    """Placeholder for custom job types."""
    logger.info(f"[Jobs][Custom] Triggered custom job '{job['name']}'")
    return {"status": "ok", "message": "Custom job triggered (no executor registered)"}
