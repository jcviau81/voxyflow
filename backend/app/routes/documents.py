"""
Documents API — upload, list, and delete workspace documents for RAG indexing.

Routes:
  POST   /api/workspaces/{workspace_id}/documents        Upload file (multipart/form-data)
  GET    /api/workspaces/{workspace_id}/documents        List documents for workspace
  DELETE /api/workspaces/{workspace_id}/documents/{id}  Delete document + remove from index

Phase 1: .txt and .md files.
Phase 2: .pdf, .docx, .xlsx, .xls, .csv (registered via DocumentParserRegistry).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Document, Workspace, get_db, new_uuid, utcnow
from app.models.document import DocumentListResponse, DocumentResponse
from app.services.document_ingest import ingest_document
from app.services.document_parser import ParsedDocument
from app.services.rag_service import RAGService, get_rag_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["documents"])

# Extension validation is handled by the DocumentParserRegistry.
# Supported formats are determined at runtime based on installed dependencies.


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _get_project_or_404(workspace_id: str, db: AsyncSession) -> Workspace:
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise HTTPException(status_code=404, detail=f"Workspace {workspace_id!r} not found")
    return workspace


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/workspaces/{workspace_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document and index it for RAG",
)
async def upload_document(
    workspace_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    rag: RAGService = Depends(get_rag_service),
):
    """
    Upload a file and index it into the workspace's RAG knowledge base.

    Supported formats: .txt, .md, .pdf, .docx, .doc, .xlsx, .xls, .csv
    (exact support depends on installed dependencies — see DocumentParserRegistry).
    """
    # Validate workspace exists
    await _get_project_or_404(workspace_id, db)

    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()

    # Read file content
    content = await file.read()
    size_bytes = len(content)

    # Extract text (best-effort — never rejects a file). Images/scanned PDFs go
    # through the vision pipeline; unknown text-like files are decoded; true
    # binaries are stored with zero chunks. See services/document_ingest.py.
    try:
        parsed = await ingest_document(content, filename)
    except Exception as e:  # defensive — ingest_document is contracted not to raise
        logger.error(f"Document ingest failed for {filename!r}: {e}")
        parsed = ParsedDocument(
            text="",
            chunks=[],
            metadata={
                "filename": filename,
                "filetype": ext,
                "size_bytes": size_bytes,
                "chunk_count": 0,
                "extraction": "error",
            },
        )

    # Create DB record
    doc_id = new_uuid()
    now = utcnow()
    doc = Document(
        id=doc_id,
        workspace_id=workspace_id,
        filename=filename,
        filetype=ext,
        size_bytes=size_bytes,
        chunk_count=len(parsed.chunks),
        created_at=now,
        indexed_at=None,
    )
    db.add(doc)
    await db.flush()  # Get ID without committing yet

    # Index into ChromaDB (failure is non-fatal)
    chunks_indexed = await rag.index_document(workspace_id, doc_id, parsed)

    # Update indexed_at timestamp if indexing succeeded
    if chunks_indexed > 0:
        doc.indexed_at = utcnow()
        doc.chunk_count = chunks_indexed

    await db.commit()
    await db.refresh(doc)

    logger.info(
        f"upload_document: filename={filename!r}, chunks={chunks_indexed}, "
        f"workspace_id={workspace_id!r}, doc_id={doc_id!r}"
    )
    return DocumentResponse.model_validate(doc)


@router.get(
    "/workspaces/{workspace_id}/documents",
    response_model=DocumentListResponse,
    summary="List documents for a workspace",
)
async def list_documents(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all documents uploaded to a workspace."""
    await _get_project_or_404(workspace_id, db)

    result = await db.execute(
        select(Document)
        .where(Document.workspace_id == workspace_id)
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()

    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(d) for d in docs],
        total=len(docs),
    )


@router.delete(
    "/workspaces/{workspace_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and remove it from the RAG index",
)
async def delete_document(
    workspace_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db),
    rag: RAGService = Depends(get_rag_service),
):
    """
    Delete a document record and remove its chunks from the ChromaDB index.
    """
    await _get_project_or_404(workspace_id, db)

    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.workspace_id == workspace_id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id!r} not found in workspace {workspace_id!r}",
        )

    # Remove from ChromaDB index first (non-fatal)
    await rag.delete_document(workspace_id, document_id)

    # Remove from DB
    await db.delete(doc)
    await db.commit()

    logger.info(
        f"delete_document: deleted doc_id={document_id!r}, workspace_id={workspace_id!r}"
    )
    # 204 No Content — no body returned
