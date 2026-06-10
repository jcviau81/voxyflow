"""Workspace Wiki endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Workspace, WikiPage, new_uuid, utcnow

from app.routes.workspaces.schemas import (
    WikiPageCreate,
    WikiPageDetail,
    WikiPageSummary,
    WikiPageUpdate,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@router.get("/{workspace_id}/wiki", response_model=list[WikiPageSummary])
async def list_wiki_pages(workspace_id: str, db: AsyncSession = Depends(get_db)):
    """List all wiki pages for a workspace (title + id + updated_at)."""
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")
    stmt = (
        select(WikiPage)
        .where(WikiPage.workspace_id == workspace_id)
        .order_by(WikiPage.updated_at.desc())
    )
    result = await db.execute(stmt)
    pages = result.scalars().all()
    return [
        WikiPageSummary(
            id=p.id,
            title=p.title,
            updated_at=p.updated_at.isoformat() if p.updated_at else "",
        )
        for p in pages
    ]


@router.post("/{workspace_id}/wiki", response_model=WikiPageDetail, status_code=201)
async def create_wiki_page(
    workspace_id: str,
    body: WikiPageCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new wiki page for a workspace."""
    workspace = await db.get(Workspace, workspace_id)
    if not workspace:
        raise HTTPException(404, "Workspace not found.")
    page = WikiPage(
        id=new_uuid(),
        workspace_id=workspace_id,
        title=body.title,
        content=body.content,
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return WikiPageDetail(
        id=page.id,
        workspace_id=page.workspace_id,
        title=page.title,
        content=page.content,
        created_at=page.created_at.isoformat() if page.created_at else "",
        updated_at=page.updated_at.isoformat() if page.updated_at else "",
    )


@router.get("/{workspace_id}/wiki/{page_id}", response_model=WikiPageDetail)
async def get_wiki_page(workspace_id: str, page_id: str, db: AsyncSession = Depends(get_db)):
    """Get full content of a single wiki page."""
    page = await db.get(WikiPage, page_id)
    if not page or page.workspace_id != workspace_id:
        raise HTTPException(404, "Wiki page not found.")
    return WikiPageDetail(
        id=page.id,
        workspace_id=page.workspace_id,
        title=page.title,
        content=page.content,
        created_at=page.created_at.isoformat() if page.created_at else "",
        updated_at=page.updated_at.isoformat() if page.updated_at else "",
    )


@router.put("/{workspace_id}/wiki/{page_id}", response_model=WikiPageDetail)
async def update_wiki_page(
    workspace_id: str,
    page_id: str,
    body: WikiPageUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update a wiki page's title and/or content."""
    page = await db.get(WikiPage, page_id)
    if not page or page.workspace_id != workspace_id:
        raise HTTPException(404, "Wiki page not found.")
    if body.title is not None:
        page.title = body.title
    if body.content is not None:
        page.content = body.content
    page.updated_at = utcnow()
    await db.commit()
    await db.refresh(page)
    return WikiPageDetail(
        id=page.id,
        workspace_id=page.workspace_id,
        title=page.title,
        content=page.content,
        created_at=page.created_at.isoformat() if page.created_at else "",
        updated_at=page.updated_at.isoformat() if page.updated_at else "",
    )


@router.delete("/{workspace_id}/wiki/{page_id}", status_code=204)
async def delete_wiki_page(
    workspace_id: str,
    page_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a wiki page."""
    page = await db.get(WikiPage, page_id)
    if not page or page.workspace_id != workspace_id:
        raise HTTPException(404, "Wiki page not found.")
    await db.delete(page)
    await db.commit()
