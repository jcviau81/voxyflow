"""Jobs API — user-defined cron/scheduled tasks.

GET    /api/jobs          → list configured jobs
POST   /api/jobs          → create new job
PUT    /api/jobs/{id}     → update job (full)
PATCH  /api/jobs/{id}     → update job (partial — same as PUT, for frontend compat)
DELETE /api/jobs/{id}     → delete job
POST   /api/jobs/{id}/run → trigger job immediately

Jobs are persisted to ~/.voxyflow/jobs.json.
APScheduler is kept in sync on every CRUD operation.

The on-disk store and per-type execution handlers live in
``app.services.job_runner``; this module is a thin HTTP adapter.
"""

import asyncio
import logging
import uuid
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.job_runner import (
    JOBS_FILE,
    VOXYFLOW_DIR,
    _execute_job,
    _find_job,
    _load_jobs,
    _save_jobs,
)

logger = logging.getLogger("voxyflow.jobs")

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


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
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_jobs():
    """List all configured jobs (enriched with live next_run from APScheduler)."""
    jobs = await asyncio.to_thread(_load_jobs)

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
    jobs = await asyncio.to_thread(_load_jobs)
    new_job = JobModel(
        name=req.name,
        type=req.type,
        schedule=req.schedule,
        enabled=req.enabled,
        payload=req.payload,
    )
    job_dict = new_job.dict()
    jobs.append(job_dict)
    await asyncio.to_thread(_save_jobs, jobs)
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
    jobs = await asyncio.to_thread(_load_jobs)
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
    await asyncio.to_thread(_save_jobs, jobs)
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
    jobs = await asyncio.to_thread(_load_jobs)
    idx, job = _find_job(jobs, job_id)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")

    jobs.pop(idx)
    await asyncio.to_thread(_save_jobs, jobs)
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
    jobs = await asyncio.to_thread(_load_jobs)
    _, job = _find_job(jobs, job_id)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")

    result = await _execute_job(job)
    return {"status": "triggered", "job_id": job_id, "name": job["name"], "result": result}


__all__ = [
    "router",
    "JobType",
    "JobModel",
    "JobCreateRequest",
    "JobUpdateRequest",
    # Re-exports for any caller still importing execution helpers from this
    # module; the authoritative home is now ``app.services.job_runner``.
    "JOBS_FILE",
    "VOXYFLOW_DIR",
    "_execute_job",
    "_find_job",
    "_load_jobs",
    "_save_jobs",
]
