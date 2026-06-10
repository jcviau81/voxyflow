"""Autonomy — per-workspace heartbeat endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import workspace_autonomy

from app.routes.workspaces.crud import _require_workspace
from app.routes.workspaces.schemas import AutonomyUpsertBody

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("/{workspace_id}/autonomy")
async def get_autonomy(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """Return the current heartbeat state + directive for this workspace."""
    await _require_workspace(workspace_id, db)
    return workspace_autonomy.get_status(workspace_id)


@router.put("/{workspace_id}/autonomy")
async def put_autonomy(
    workspace_id: str,
    body: AutonomyUpsertBody,
    db: AsyncSession = Depends(get_db),
):
    """Create or update the workspace's autonomy heartbeat.

    - ``enabled=false`` keeps the job in ``jobs.json`` but unregisters it from
      APScheduler (pause). Use DELETE to remove it entirely.
    - ``directive`` overwrites the content below the ``---`` divider. Pass
      ``""`` to clear the directive (next cycle becomes a no-op via the gate).
    """
    workspace = await _require_workspace(workspace_id, db)
    job = workspace_autonomy.upsert(
        workspace_id,
        workspace.title,
        enabled=body.enabled,
        schedule=body.schedule,
        directive=body.directive,
    )
    status = workspace_autonomy.get_status(workspace_id)
    status["job"] = job
    return status


@router.delete("/{workspace_id}/autonomy", status_code=204)
async def delete_autonomy(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """Remove the autonomy heartbeat job. The directive file is kept on disk."""
    await _require_workspace(workspace_id, db)
    workspace_autonomy.disable(workspace_id)
    return None


@router.post("/{workspace_id}/autonomy/run")
async def run_autonomy_now(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """Trigger the heartbeat job immediately (fire-and-forget semantics)."""
    await _require_workspace(workspace_id, db)
    result = await workspace_autonomy.run_now(workspace_id)
    return {"workspace_id": workspace_id, "result": result}
