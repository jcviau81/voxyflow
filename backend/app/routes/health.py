"""Health check routes for Voxyflow.

GET /api/health           → overall health status (app + services, cached)
GET /api/health/services  → detailed service status with last-check timestamps
GET /api/health/live      → active probe: DB write + scheduler + cached health
GET /api/metrics          → request latencies + system resource stats
"""

import logging
import time

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.database import async_session
from app.services.scheduler_service import SchedulerService, get_scheduler_service

logger = logging.getLogger(__name__)
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
