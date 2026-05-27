"""Health check routes for Voxyflow.

GET /health               → root liveness/readiness probe (JSON, no /api prefix)
GET /api/health           → overall health status (app + services, cached)
GET /api/health/services  → detailed service status with last-check timestamps
GET /api/health/live      → active probe: DB write + scheduler + cached health
GET /api/metrics          → request latencies + system resource stats
"""

import logging
import os
import subprocess
import time as _time

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.database import async_session
from app.services.scheduler_service import SchedulerService, get_scheduler_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants for /health endpoint
# ---------------------------------------------------------------------------

_PROCESS_START: float = _time.monotonic()


def _get_git_version() -> str:
    """Return the short git SHA, falling back to VOXYFLOW_VERSION env or 'dev'."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return os.environ.get("VOXYFLOW_VERSION", "dev")


_VERSION: str = _get_git_version()

# ---------------------------------------------------------------------------
# Root /health router — no /api prefix, registered BEFORE SPA catch-all
# ---------------------------------------------------------------------------

root_health_router = APIRouter(tags=["health"])


@root_health_router.get("/health", include_in_schema=True)
async def get_root_health():
    """Root liveness/readiness probe at ``/health`` (no ``/api`` prefix).

    Performs an active SQLite probe and reads the cached ChromaDB status from
    the scheduler heartbeat.  Returns **200 ok** when all checks pass, **503
    degraded** when any check is failing.

    Response shape::

        {
          "status": "ok" | "degraded",
          "version": "<git-sha or dev>",
          "uptime_seconds": 1234,
          "checks": {"db": "ok", "chroma": "ok"}
        }
    """
    # -- DB probe (active: SELECT 1) ----------------------------------------
    db_check = "ok"
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        db_check = f"down: {str(exc)[:120]}"
        logger.warning("GET /health: DB probe failed: %s", exc)

    # -- Chroma probe (cached status from scheduler heartbeat) ---------------
    chroma_check = "ok"
    try:
        svc = get_scheduler_service()
        health_data = svc.get_health_status()
        raw_status = (
            health_data.get("services", {})
            .get("chromadb", {})
            .get("status", "unknown")
        )
        if raw_status not in ("ok", "unknown", "not_applicable"):
            chroma_check = f"down: {raw_status}"
    except Exception as exc:
        chroma_check = f"down: {str(exc)[:120]}"
        logger.warning("GET /health: Chroma status read failed: %s", exc)

    # -- Overall status ------------------------------------------------------
    all_ok = db_check == "ok" and chroma_check == "ok"
    overall = "ok" if all_ok else "degraded"
    http_status = 200 if all_ok else 503

    body = {
        "status": overall,
        "version": _VERSION,
        "uptime_seconds": int(_time.monotonic() - _PROCESS_START),
        "checks": {
            "db": db_check,
            "chroma": chroma_check,
        },
    }
    return JSONResponse(content=body, status_code=http_status)


# ---------------------------------------------------------------------------
# /api/health router (existing)
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def get_health(svc: SchedulerService = Depends(get_scheduler_service)):
    """Overall health status — ok | degraded | down.

    Reads the cached state the scheduler refreshed on its heartbeat job.
    Use ``/api/health/live`` for a fresh active probe.
    """
    return svc.get_health_status()


@router.get("/services")
async def get_services_health(svc: SchedulerService = Depends(get_scheduler_service)):
    """Detailed per-service health with last-check timestamps."""
    status = svc.get_health_status()
    return {
        "status": status["status"],
        "scheduler_running": status["scheduler_running"],
        "services": status["services"],
    }


@router.get("/live")
async def get_live_health(svc: SchedulerService = Depends(get_scheduler_service)):
    """Active liveness probe — verifies DB + scheduler inline, merges cached service state."""
    import time
    started = time.monotonic()

    db_status = "ok"
    db_error: str | None = None
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception as e:
        db_status = "down"
        db_error = str(e)[:200]
        logger.warning("live health: DB probe failed: %s", e)

    cached = svc.get_health_status()
    overall = "ok"
    if db_status != "ok" or cached["status"] == "down":
        overall = "down"
    elif cached["status"] != "ok":
        overall = "degraded"

    return {
        "status": overall,
        "probe_ms": int((time.monotonic() - started) * 1000),
        "database": {"status": db_status, "error": db_error},
        "scheduler_running": cached["scheduler_running"],
        "services": cached["services"],
    }


# ---------------------------------------------------------------------------
# /api/metrics router (existing)
# ---------------------------------------------------------------------------

metrics_router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@metrics_router.get("")
async def get_metrics():
    """
    Live performance metrics:
    - HTTP request latencies (last 200 requests), aggregated per route
    - Slow requests (>500ms)
    - System CPU/RAM (sampled every 2 min by heartbeat job)
    """
    from app.services.metrics_store import get_metrics_store
    return get_metrics_store().summary()
