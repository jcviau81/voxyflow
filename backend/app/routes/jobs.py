"""Jobs API — user-defined cron/scheduled tasks.

GET    /api/jobs          → list configured jobs
POST   /api/jobs          → create new job
PUT    /api/jobs/{id}     → update job
DELETE /api/jobs/{id}     → delete job
POST   /api/jobs/{id}/run → trigger job immediately

Jobs are persisted to ~/.voxyflow/jobs.json.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
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

JobType = Literal["reminder", "github_sync", "rag_index", "custom"]


class JobModel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    type: JobType = "custom"
    schedule: str  # cron expression OR "every_Xmin" / "every_Xh"
    enabled: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)


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
    """List all configured jobs."""
    jobs = _load_jobs()
    return {"jobs": jobs, "total": len(jobs)}


@router.post("", status_code=201)
async def create_job(req: JobCreateRequest):
    """Create a new job."""
    jobs = _load_jobs()
    new_job = JobModel(
        name=req.name,
        type=req.type,
        schedule=req.schedule,
        enabled=req.enabled,
        payload=req.payload,
    )
    jobs.append(new_job.dict())
    _save_jobs(jobs)
    logger.info(f"[Jobs] Created job '{new_job.name}' (id={new_job.id}, schedule={new_job.schedule})")
    return new_job.dict()


@router.put("/{job_id}")
async def update_job(job_id: str, req: JobUpdateRequest):
    """Update an existing job."""
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
    return job


@router.delete("/{job_id}", status_code=204)
async def delete_job(job_id: str):
    """Delete a job."""
    jobs = _load_jobs()
    idx, job = _find_job(jobs, job_id)
    if job is None:
        raise HTTPException(404, f"Job not found: {job_id}")

    jobs.pop(idx)
    _save_jobs(jobs)
    logger.info(f"[Jobs] Deleted job '{job['name']}' (id={job_id})")
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
        elif job_type == "custom":
            return await _run_custom(job, payload)
        else:
            return {"status": "error", "message": f"Unknown job type: {job_type}"}
    except Exception as e:
        logger.error(f"[Jobs] Job '{job['name']}' (type={job_type}) failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def _run_rag_index(job: dict, payload: dict) -> dict:
    """Run a RAG index job for a specific project or all active projects."""
    project_id = payload.get("project_id")

    from app.services.scheduler_service import get_scheduler_service

    svc = get_scheduler_service()
    await svc._rag_index_job()
    return {"status": "ok", "message": f"RAG index triggered (project_id={project_id or 'all active'})"}


async def _run_reminder(job: dict, payload: dict) -> dict:
    """Log a reminder (extensible — could push to Mattermost/webhook)."""
    message = payload.get("message", job.get("name", "Reminder"))
    logger.info(f"[Jobs][Reminder] {message}")
    return {"status": "ok", "message": f"Reminder logged: {message}"}


async def _run_github_sync(job: dict, payload: dict) -> dict:
    """Placeholder for GitHub sync job."""
    repo = payload.get("repo", "")
    logger.info(f"[Jobs][GithubSync] Would sync repo: {repo}")
    return {"status": "ok", "message": f"GitHub sync placeholder (repo={repo})"}


async def _run_custom(job: dict, payload: dict) -> dict:
    """Placeholder for custom job types."""
    logger.info(f"[Jobs][Custom] Triggered custom job '{job['name']}'")
    return {"status": "ok", "message": "Custom job triggered (no executor registered)"}
