"""Health check routes for Voxyflow.

GET /api/health          → overall health status (app + services)
GET /api/health/services → detailed service status with last-check timestamps
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
