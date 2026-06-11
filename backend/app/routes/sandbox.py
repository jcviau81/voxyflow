"""Sandbox file API — read/write/list/delete files in Voxy's worker sandbox."""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.sandbox_service import SandboxService, get_sandbox_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


class FileWriteRequest(BaseModel):
    path: str
    content: str


@router.get("/info")
async def storage_info(sb: SandboxService = Depends(get_sandbox_service)):
    """Where Voxyflow stores things on disk (read-only, shown in Settings)."""
    from app.config import VOXYFLOW_DATA_DIR
    from app.services.memory_service import CHROMA_PERSIST_DIR

    root = sb.sandbox_root
    return {
        "data_dir": str(VOXYFLOW_DATA_DIR),
        "sandbox_root": str(root),
        "workspace_areas": str(root / "workspaces" / "<workspace-slug>"),
        "memory_dir": str(CHROMA_PERSIST_DIR),
    }


@router.get("/files")
async def list_files(
    path: str = "",
    sb: SandboxService = Depends(get_sandbox_service),
):
    """List files and directories in sandbox (or subdirectory)."""
    try:
        return await sb.list_files(path)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/file")
async def read_file(
    path: str,
    sb: SandboxService = Depends(get_sandbox_service),
):
    """Read file content from sandbox."""
    try:
        content = await sb.read_file(path)
        return {"path": path, "content": content, "size": len(content)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.post("/file")
async def write_file(
    body: FileWriteRequest,
    sb: SandboxService = Depends(get_sandbox_service),
):
    """Create or update a file in sandbox."""
    try:
        saved_path = await sb.write_file(body.path, body.content)
        return {"status": "saved", "path": saved_path, "size": len(body.content)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/file")
async def delete_file(
    path: str,
    sb: SandboxService = Depends(get_sandbox_service),
):
    """Delete a file from sandbox."""
    try:
        await sb.delete_file(path)
        return {"status": "deleted", "path": path}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@router.get("/tree")
async def get_tree(sb: SandboxService = Depends(get_sandbox_service)):
    """Get full directory tree (recursive)."""
    try:
        return await sb.get_tree()
    except ValueError as e:
        raise HTTPException(400, str(e))
