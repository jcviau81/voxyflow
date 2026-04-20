"""Backup routes — ChromaDB backup status and manual trigger.

GET  /api/backup/status   → last backup info, count, size
POST /api/backup/trigger  → run backup now
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends

from app.services.auth_service import verify_auth

router = APIRouter(prefix="/api/backup", tags=["backup"])

BACKUP_ROOT = Path(os.path.expanduser("~/.voxyflow/backups/chromadb"))


@router.get("/status")
async def backup_status():
    """Return backup status: last backup date, count, total size."""
    if not BACKUP_ROOT.exists():
        return {
            "last_backup": None,
            "backup_count": 0,
            "total_size_mb": 0.0,
            "next_scheduled": None,
        }

    backups = sorted(
        [d for d in BACKUP_ROOT.iterdir() if d.is_dir()],
        key=lambda d: d.name,
        reverse=True,
    )

    total_size = 0
    for backup_dir in backups:
        for f in backup_dir.rglob("*"):
            if f.is_file():
                total_size += f.stat().st_size

    return {
        "last_backup": backups[0].name if backups else None,
        "backup_count": len(backups),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "next_scheduled": None,
    }


@router.post("/trigger", dependencies=[Depends(verify_auth)])
async def trigger_backup(background_tasks: BackgroundTasks):
    """Manually trigger a ChromaDB backup."""
    from app.services.scheduler_service import get_scheduler_service

    svc = get_scheduler_service()
    background_tasks.add_task(svc._chromadb_backup_job)
    return {"message": "Backup started in background"}
