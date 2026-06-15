"""Filesystem / path helper endpoints.

MUST be registered BEFORE /{workspace_id} — Starlette matches routes in
registration order, so a later static path would be captured as a
workspace_id and 404. The package ``__init__`` includes this router between
the collection routes and the /{workspace_id} item routes, mirroring the
original module layout.
"""

from pathlib import Path

from fastapi import APIRouter

from app.services.sandbox_service import get_sandbox_service

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("/suggest-path")
async def suggest_workspace_path(name: str):
    """Return the default workspace path for a workspace name (not created yet)."""
    ws = get_sandbox_service()
    path = ws.get_workspace_sandbox(name.strip() or "unnamed")
    return {"path": str(path)}


@router.get("/path-info")
async def path_info(path: str):
    """Check if a local path exists."""
    expanded = Path(path).expanduser().resolve()
    exists = expanded.exists()
    return {
        "path": str(expanded),
        "exists": exists,
        "is_dir": expanded.is_dir() if exists else False,
    }
