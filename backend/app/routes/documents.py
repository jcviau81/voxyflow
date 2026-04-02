"""
Documents API — upload, list, and delete project documents for RAG indexing.

Routes:
  POST   /api/projects/{project_id}/documents        Upload file (multipart/form-data)
  GET    /api/projects/{project_id}/documents        List documents for project
  DELETE /api/projects/{project_id}/documents/{id}  Delete document + remove from index

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

from app.database import Document, Project, get_db, new_uuid, utcnow
from app.models.document import DocumentListResponse, DocumentResponse
from app.services.document_parser import UnsupportedFileType, get_document_parser_registry
from app.services.rag_service import RAGService, get_rag_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["documents"])

# Extension validation is handled by the DocumentParserRegistry.
# Supported formats are determined at runtime based on installed dependencies.


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


async def _get_project_or_404(project_id: str, db: AsyncSession) -> Project:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {project_id!r} not found")
    return project


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post(
    "/projects/{project_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a document and index it for RAG",
)
async def upload_document(
    project_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    rag: RAGService = Depends(get_rag_service),
):
    """
    Upload a file and index it into the project's RAG knowledge base.

    Supported formats: .txt, .md, .pdf, .docx, .doc, .xlsx, .xls, .csv
    (exact support depends on installed dependencies — see DocumentParserRegistry).
    """
    # Validate project exists
    await _get_project_or_404(project_id, db)

    filename = file.filename or "unknown"
    ext = Path(filename).suffix.lower()

    # Read file content
    content = await file.read()
    size_bytes = len(content)

    # Parse document
    registry = get_document_parser_registry()
    try:
        parser = registry.get_parser(filename)
        parsed = parser.parse(content, filename)
    except UnsupportedFileType as e:
        supported = ", ".join(sorted(registry.supported_extensions))
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=(
                f"Unsupported file type: {ext!r}. "
                f"Supported formats: {supported}."
            ),
        )
    except Exception as e:
        logger.error(f"Document parsing failed for {filename!r}: {e}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse document: {e}",
        )

    # Create DB record
    doc_id = new_uuid()
    now = utcnow()
    doc = Document(
        id=doc_id,
        project_id=project_id,
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
    chunks_indexed = await rag.index_document(project_id, doc_id, parsed)

    # Update indexed_at timestamp if indexing succeeded
    if chunks_indexed > 0:
        doc.indexed_at = utcnow()
        doc.chunk_count = chunks_indexed

    await db.commit()
    await db.refresh(doc)

    logger.info(
        f"upload_document: filename={filename!r}, chunks={chunks_indexed}, "
        f"project_id={project_id!r}, doc_id={doc_id!r}"
    )
    return DocumentResponse.model_validate(doc)


@router.get(
    "/projects/{project_id}/documents",
    response_model=DocumentListResponse,
    summary="List documents for a project",
)
async def list_documents(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all documents uploaded to a project."""
    await _get_project_or_404(project_id, db)

    result = await db.execute(
        select(Document)
        .where(Document.project_id == project_id)
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()

    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(d) for d in docs],
        total=len(docs),
    )


@router.delete(
    "/projects/{project_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document and remove it from the RAG index",
)
async def delete_document(
    project_id: str,
    document_id: str,
    db: AsyncSession = Depends(get_db),
    rag: RAGService = Depends(get_rag_service),
):
    """
    Delete a document record and remove its chunks from the ChromaDB index.
    """
    await _get_project_or_404(project_id, db)

    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.project_id == project_id,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id!r} not found in project {project_id!r}",
        )

    # Remove from ChromaDB index first (non-fatal)
    await rag.delete_document(project_id, document_id)

    # Remove from DB
    await db.delete(doc)
    await db.commit()

    logger.info(
        f"delete_document: deleted doc_id={document_id!r}, project_id={project_id!r}"
    )
    # 204 No Content — no body returned
