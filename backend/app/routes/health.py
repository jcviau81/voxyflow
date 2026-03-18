"""Health check routes for Voxyflow.

GET /api/health          → overall health status (app + services)
GET /api/health/services → detailed service status with last-check timestamps
"""

from fastapi import APIRouter

from app.services.scheduler_service import get_scheduler_service

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def get_health():
    """Overall health status — ok | degraded | down."""
    svc = get_scheduler_service()
    status = svc.get_health_status()
    return status


@router.get("/services")
async def get_services_health():
    """Detailed per-service health with last-check timestamps."""
    svc = get_scheduler_service()
    status = svc.get_health_status()
    return {
        "status": status["status"],
        "scheduler_running": status["scheduler_running"],
        "services": status["services"],
    }
