"""Workspace core CRUD endpoints.

Two routers so the package ``__init__`` can reproduce the original
registration order exactly: the collection routes (``POST ""`` / ``GET ""``)
register before the static path helpers (``paths.py``), and the
``/{workspace_id}`` item routes register after them — Starlette matches in
registration order, so a later static path would be captured as a
workspace_id and 404.
"""

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import (
    get_db, Workspace, Card, Chat, WorkerTask, KGEntity,
    new_uuid, utcnow,
)
from app.models.workspace import WorkspaceCreate, WorkspaceUpdate, WorkspaceResponse, WorkspaceWithCards
from app.services import workspace_autonomy
from app.services.sandbox_service import get_sandbox_service

logger = logging.getLogger(__name__)

collection_router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])
item_router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@collection_router.post("", response_model=WorkspaceResponse, status_code=201)
async def create_workspace(body: WorkspaceCreate, db: AsyncSession = Depends(get_db)):
    # Prevent duplicate workspace names (case-insensitive, active workspaces only)
    existing = await db.execute(
        select(Workspace).where(
            func.lower(Workspace.title) == body.title.strip().lower(),
            Workspace.status != "archived",
        )
    )
    if existing.scalar_one_or_none():
        logger.warning("Duplicate workspace name rejected: %s", body.title.strip())
        raise HTTPException(
            status_code=409,
            detail=f"A workspace named '{body.title.strip()}' already exists."
        )

    # Auto-create workspace directory for the workspace
    ws = get_sandbox_service()
    if body.local_path:
        # User specified a custom path — use it and ensure it exists
        workspace_dir = Path(body.local_path).expanduser()
        workspace_dir.mkdir(parents=True, exist_ok=True)
        local_path = str(workspace_dir)
    else:
        # Default: ~/.voxyflow/workspace/<workspace-slug>/
        workspace_dir = ws.ensure_workspace_sandbox(body.title.strip())
        local_path = str(workspace_dir)

    workspace = Workspace(
        id=new_uuid(),
        title=body.title.strip(),
        description=body.description or "",
        context=body.context or "",
        emoji=body.emoji,
        color=body.color,
        github_repo=body.github_repo,
        github_url=body.github_url,
        github_branch=body.github_branch,
        github_language=body.github_language,
        local_path=local_path,
    )
    db.add(workspace)
    await db.commit()
    await db.refresh(workspace)
    return workspace


@collection_router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    status: str | None = None,
    archived: bool | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Workspace).order_by(Workspace.updated_at.desc())
    if status:
        stmt = stmt.where(Workspace.status == status)
    elif archived is not None:
        if archived:
            stmt = stmt.where(Workspace.status == "archived")
        else:
            stmt = stmt.where(Workspace.status == "active")
    else:
        # Default: only active workspaces
        stmt = stmt.where(Workspace.status == "active")
    result = await db.execute(stmt)
    return result.scalars().all()


@item_router.get("/{workspace_id}", response_model=WorkspaceWithCards)
async def get_workspace(workspace_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Workspace)
        .options(selectinload(Workspace.cards))
        .where(Workspace.id == workspace_id)
    )
    result = await db.execute(stmt)
    workspace = result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(404, "Workspace not found.")
    return workspace


@item_router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a workspace and every trace of it — DB rows, ChromaDB collections,
    chat/worker session files, workspace dir, worker artifacts. Irreversible;
    users should rely on Archive for recoverability."""
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    # Prevent deletion of system/non-deletable workspaces
    if getattr(workspace, 'deletable', True) is False or getattr(workspace, 'is_system', False):
        raise HTTPException(403, "Cannot delete system workspace.")

    # Capture card ids before the cascade delete — needed to wipe per-card
    # session files and worker artifacts on disk after the DB is gone.
    card_ids = [
        cid for cid, in (
            await db.execute(select(Card.id).where(Card.workspace_id == workspace_id))
        ).all()
    ]
    task_ids = [
        tid for tid, in (
            await db.execute(select(WorkerTask.id).where(WorkerTask.workspace_id == workspace_id))
        ).all()
    ]
    # Capture before the row is deleted — accessing the ORM object after
    # commit would try to refresh a dead row.
    local_path = workspace.local_path

    # Delete all cards belonging to this workspace (cascades to checklist items,
    # attachments, relations, history via ORM relationships).
    for card in (await db.execute(select(Card).where(Card.workspace_id == workspace_id))).scalars().all():
        await db.delete(card)

    # Workspace.chats relationship has no cascade — wipe chats (and their
    # messages via cascade="all, delete-orphan" on Chat.messages) explicitly.
    for chat in (await db.execute(select(Chat).where(Chat.workspace_id == workspace_id))).scalars().all():
        await db.delete(chat)

    # WorkerTask and KGEntity use plain string workspace_id (no FK) — bulk delete.
    # KGEntity cascades to triples/attributes via the entity FK.
    for task in (await db.execute(select(WorkerTask).where(WorkerTask.workspace_id == workspace_id))).scalars().all():
        await db.delete(task)
    for ent in (await db.execute(select(KGEntity).where(KGEntity.workspace_id == workspace_id))).scalars().all():
        await db.delete(ent)

    await db.delete(workspace)
    await db.commit()

    # ------------------------------------------------------------------
    # Best-effort cleanup of out-of-DB state. Each step is isolated so a
    # single failure can't leave the caller with a half-deleted workspace.
    # ------------------------------------------------------------------

    # ChromaDB: RAG collections (docs/history/workspace) + memory collection.
    try:
        from app.services.rag_service import get_rag_service
        get_rag_service().delete_workspace(workspace_id)
    except Exception as e:
        logger.warning("RAG cleanup failed for workspace %s: %s", workspace_id, e)
    try:
        from app.services.memory_service import get_memory_service
        get_memory_service().drop_workspace_collection(workspace_id)
    except Exception as e:
        logger.warning("Memory collection cleanup failed for workspace %s: %s", workspace_id, e)

    # Filesystem: session files (workspace + per-card), workspace dir, worker
    # sessions whose JSON carries this workspace_id, and worker artifacts for
    # every task that belonged to the workspace.
    data_root = Path(os.environ.get("VOXYFLOW_DATA_DIR", os.path.expanduser("~/.voxyflow")))
    sessions_dir = data_root / "sessions"
    sandbox_dir = data_root / "sandbox" / "workspaces" / workspace_id
    worker_sessions_dir = data_root / "worker_sessions"
    worker_artifacts_dir = data_root / "worker_artifacts"

    def _rmtree(path: Path):
        try:
            if path.exists():
                shutil.rmtree(path)
        except Exception as e:
            logger.warning("Could not remove %s: %s", path, e)

    def _cleanup_filesystem():
        from app.routes.cards import ATTACHMENTS_BASE

        _rmtree(sessions_dir / "workspace" / workspace_id)
        for cid in card_ids:
            _rmtree(sessions_dir / "card" / cid)
            _rmtree(ATTACHMENTS_BASE / cid)
        _rmtree(sandbox_dir)

        # Slug-keyed workspace dir created by create_workspace (workspace.local_path).
        # Only removed when it lies strictly inside the sandbox root — a
        # user-specified external path is never touched.
        if local_path:
            try:
                sandbox_root = get_sandbox_service().sandbox_root.resolve()
                resolved = Path(local_path).expanduser().resolve()
                if resolved != sandbox_root and resolved.is_relative_to(sandbox_root):
                    _rmtree(resolved)
            except Exception as e:
                logger.warning("Could not remove workspace dir %s: %s", local_path, e)

        if worker_sessions_dir.exists():
            for fp in worker_sessions_dir.glob("*.json"):
                try:
                    data = json.loads(fp.read_text())
                    if data.get("workspace_id") == workspace_id:
                        fp.unlink(missing_ok=True)
                except Exception as e:
                    logger.debug("worker_sessions prune skipped %s: %s", fp.name, e)

        if worker_artifacts_dir.exists():
            for tid in task_ids:
                try:
                    (worker_artifacts_dir / f"{tid}.md").unlink(missing_ok=True)
                    (worker_artifacts_dir / f"{tid}.completion.json").unlink(missing_ok=True)
                except Exception as e:
                    logger.debug("worker_artifacts prune skipped %s: %s", tid, e)

    # Recursive deletes (sandbox may hold a cloned repo) must not block the
    # event loop — run the whole best-effort sweep off-thread.
    await asyncio.to_thread(_cleanup_filesystem)

    # Tear down the autonomy heartbeat (if any) last — the directive file
    # lived under sandbox_dir, which we just removed.
    try:
        workspace_autonomy.disable(workspace_id)
    except Exception as e:
        logger.warning("Could not disable autonomy for deleted workspace %s: %s", workspace_id, e)


@item_router.post("/{workspace_id}/archive", response_model=WorkspaceResponse)
async def archive_workspace(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """Archive a workspace (hide from main list, keep all data)."""
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    # Prevent archiving system workspaces
    if getattr(workspace, 'is_system', False):
        raise HTTPException(403, "Cannot archive system workspace.")

    workspace.status = "archived"
    workspace.updated_at = utcnow()
    await db.commit()
    await db.refresh(workspace)
    return workspace


@item_router.post("/{workspace_id}/restore", response_model=WorkspaceResponse)
async def restore_workspace(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """Restore an archived workspace back to active."""
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")
    workspace.status = "active"
    workspace.updated_at = utcnow()
    await db.commit()
    await db.refresh(workspace)
    return workspace


@item_router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    body: WorkspaceUpdate,
    db: AsyncSession = Depends(get_db),
):
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")

    update_data = body.model_dump(exclude_unset=True)

    # System workspaces cannot be archived (mirror archive_workspace/delete_workspace).
    if update_data.get("status") == "archived" and getattr(workspace, "is_system", False):
        raise HTTPException(403, "Cannot archive system workspace.")

    for field, value in update_data.items():
        setattr(workspace, field, value)
    workspace.updated_at = utcnow()

    await db.commit()
    await db.refresh(workspace)
    return workspace


@item_router.patch("/{workspace_id}/favorite", response_model=WorkspaceResponse)
async def toggle_favorite(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Toggle the is_favorite flag on a workspace."""
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")
    workspace.is_favorite = not workspace.is_favorite
    workspace.updated_at = utcnow()
    await db.commit()
    await db.refresh(workspace)
    return workspace


async def _require_workspace(workspace_id: str, db: AsyncSession) -> Workspace:
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")
    return workspace
