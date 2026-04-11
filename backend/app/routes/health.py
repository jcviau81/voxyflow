"""Health check routes for Voxyflow.

GET /api/health          → overall health status (app + services)
GET /api/health/services → detailed service status with last-check timestamps
GET /api/metrics         → request latencies + system resource stats
"""

from fastapi import APIRouter, Depends

from app.services.scheduler_service import SchedulerService, get_scheduler_service

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def get_health(svc: SchedulerService = Depends(get_scheduler_service)):
    """Overall health status — ok | degraded | down."""
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
