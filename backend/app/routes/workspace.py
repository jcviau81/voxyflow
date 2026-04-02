"""Workspace file API — read/write/list/delete files in Voxy's workspace."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.workspace_service import WorkspaceService, get_workspace_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


class FileWriteRequest(BaseModel):
    path: str
    content: str


@router.get("/files")
async def list_files(
    path: str = "",
    ws: WorkspaceService = Depends(get_workspace_service),
):
    """List files and directories in workspace (or subdirectory)."""
    try:
        return await ws.list_files(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/file")
async def read_file(
    path: str,
    ws: WorkspaceService = Depends(get_workspace_service),
):
    """Read file content from workspace."""
    try:
        content = await ws.read_file(path)
        return {"path": path, "content": content, "size": len(content)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/file")
async def write_file(
    body: FileWriteRequest,
    ws: WorkspaceService = Depends(get_workspace_service),
):
    """Create or update a file in workspace."""
    try:
        saved_path = await ws.write_file(body.path, body.content)
        return {"status": "saved", "path": saved_path, "size": len(body.content)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/file")
async def delete_file(
    path: str,
    ws: WorkspaceService = Depends(get_workspace_service),
):
    """Delete a file from workspace."""
    try:
        await ws.delete_file(path)
        return {"status": "deleted", "path": path}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.get("/tree")
async def get_tree(ws: WorkspaceService = Depends(get_workspace_service)):
    """Get full directory tree (recursive)."""
    try:
        return await ws.get_tree()
    except ValueError as e:
        raise HTTPException(400, str(e))
