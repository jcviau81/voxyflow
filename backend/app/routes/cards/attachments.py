"""Card attachment endpoints (file upload/download/delete) and card file
references.

``files_router`` is separate because the file-reference endpoints were
declared after enrich_card in the original module — the package
``__init__`` includes it at that exact position.

NOTE: download_attachment serves files from disk — the path containment
check against ATTACHMENTS_BASE is defence in depth and must stay intact.
"""

import asyncio
import json
import logging
import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db, Card, CardAttachment, new_uuid, utcnow
from app.models.card import AttachmentResponse

from .serializers import ATTACHMENTS_BASE, MAX_ATTACHMENT_SIZE

logger = logging.getLogger(__name__)

router = APIRouter()

# Declared after enrich_card in the original module.
files_router = APIRouter()


# ---------------------------------------------------------------------------
# Attachment endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/cards/{card_id}/attachments",
    response_model=AttachmentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a file attachment to a card",
)
async def upload_attachment(
    card_id: str,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file and attach it to a card. Max 50 MB, any type accepted."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")

    filename = file.filename or "attachment"

    # Determine MIME type
    mime_type = file.content_type or "application/octet-stream"
    if not mime_type or mime_type == "application/octet-stream":
        guessed, _ = mimetypes.guess_type(filename)
        mime_type = guessed or "application/octet-stream"

    # Build storage path: ~/.voxyflow/attachments/{card_id}/{uuid}_{filename}
    att_id = new_uuid()
    safe_filename = Path(filename).name  # strip any directory components
    storage_filename = f"{att_id}_{safe_filename}"
    storage_dir = ATTACHMENTS_BASE / card_id
    storage_dir.mkdir(parents=True, exist_ok=True)
    storage_path = storage_dir / storage_filename

    # Stream to disk in chunks — never buffer the whole upload in memory.
    # Abort (and remove the partial file) as soon as the running total
    # exceeds the limit; disk writes happen off the event loop.
    chunk_size = 1024 * 1024
    file_size = 0
    try:
        with storage_path.open("wb") as out:
            while chunk := await file.read(chunk_size):
                file_size += len(chunk)
                if file_size > MAX_ATTACHMENT_SIZE:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File too large (>{file_size} bytes). Maximum allowed is {MAX_ATTACHMENT_SIZE} bytes (50 MB).",
                    )
                await asyncio.to_thread(out.write, chunk)
    except BaseException:
        storage_path.unlink(missing_ok=True)
        raise

    attachment = CardAttachment(
        id=att_id,
        card_id=card_id,
        filename=filename,
        file_size=file_size,
        mime_type=mime_type,
        storage_path=str(storage_path),
        created_at=utcnow(),
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)

    logger.info(f"upload_attachment: card_id={card_id!r} filename={filename!r} size={file_size}")
    return AttachmentResponse.model_validate(attachment)


@router.get(
    "/cards/{card_id}/attachments",
    response_model=list[AttachmentResponse],
    summary="List attachments for a card",
)
async def list_attachments(
    card_id: str,
    db: AsyncSession = Depends(get_db),
):
    """List all attachments for a card."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")

    stmt = (
        select(CardAttachment)
        .where(CardAttachment.card_id == card_id)
        .order_by(CardAttachment.created_at.desc())
    )
    result = await db.execute(stmt)
    attachments = result.scalars().all()
    return [AttachmentResponse.model_validate(a) for a in attachments]


@router.get(
    "/cards/{card_id}/attachments/{attachment_id}/download",
    summary="Download a card attachment",
)
async def download_attachment(
    card_id: str,
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Download a card attachment file."""
    stmt = select(CardAttachment).where(
        CardAttachment.id == attachment_id,
        CardAttachment.card_id == card_id,
    )
    result = await db.execute(stmt)
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(404, "Attachment not found.")

    storage_path = Path(attachment.storage_path)
    # Defence in depth: reject any stored path that escapes ATTACHMENTS_BASE.
    # The upload path controls this, but a compromised DB row must not let
    # FileResponse serve arbitrary files.
    try:
        resolved = storage_path.resolve()
        resolved.relative_to(ATTACHMENTS_BASE.resolve())
    except (OSError, ValueError):
        logger.warning(
            f"download_attachment: refused path outside ATTACHMENTS_BASE: {storage_path}"
        )
        raise HTTPException(404, "Attachment not found.")
    if not resolved.exists():
        raise HTTPException(404, "Attachment file not found on disk.")

    return FileResponse(
        path=str(resolved),
        media_type=attachment.mime_type,
        filename=attachment.filename,
    )


@router.delete(
    "/cards/{card_id}/attachments/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a card attachment",
)
async def delete_attachment(
    card_id: str,
    attachment_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Delete a card attachment (removes file and DB record)."""
    stmt = select(CardAttachment).where(
        CardAttachment.id == attachment_id,
        CardAttachment.card_id == card_id,
    )
    result = await db.execute(stmt)
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(404, "Attachment not found.")

    # Remove file from disk (non-fatal if missing). Canonicalise first so a
    # compromised DB row can't coax unlink into clobbering files outside
    # ATTACHMENTS_BASE.
    storage_path = Path(attachment.storage_path)
    try:
        resolved = storage_path.resolve()
        resolved.relative_to(ATTACHMENTS_BASE.resolve())
    except (OSError, ValueError):
        logger.warning(
            f"delete_attachment: refusing to unlink path outside ATTACHMENTS_BASE: {storage_path}"
        )
        resolved = None
    if resolved and resolved.exists():
        try:
            resolved.unlink()
        except OSError as e:
            logger.warning(f"delete_attachment: could not remove file {resolved}: {e}")

    await db.delete(attachment)
    await db.commit()
    logger.info(f"delete_attachment: deleted attachment_id={attachment_id!r} card_id={card_id!r}")


# ── Card File References ─────────────────────────────────────────────────────


class FileRefRequest(BaseModel):
    path: str  # relative path (e.g. "workspace/notes.md")


@files_router.get("/cards/{card_id}/files")
async def list_card_files(card_id: str, db: AsyncSession = Depends(get_db)):
    """List file references for a card."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")
    return json.loads(card.files) if card.files else []


@files_router.post("/cards/{card_id}/files")
async def add_card_file(card_id: str, body: FileRefRequest, db: AsyncSession = Depends(get_db)):
    """Add a file reference to a card."""
    raw = (body.path or "").strip()
    if not raw:
        raise HTTPException(400, "Path is required.")
    candidate = Path(raw)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise HTTPException(400, "Path traversal not allowed.")
    # Normalise ("./foo" → "foo", collapse "a//b" → "a/b") so duplicates
    # don't slip in under different string forms. pathlib already strips a
    # leading "./" — do NOT use lstrip("./"), which eats the dot of dotfiles
    # (".gitignore" → "gitignore").
    normalised = candidate.as_posix()
    if normalised == ".":
        raise HTTPException(400, "Path is required.")
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")
    files = json.loads(card.files) if card.files else []
    if normalised not in files:
        files.append(normalised)
        card.files = json.dumps(files)
        card.updated_at = utcnow()
        await db.commit()
    return files


@files_router.delete("/cards/{card_id}/files")
async def remove_card_file(card_id: str, path: str, db: AsyncSession = Depends(get_db)):
    """Remove a file reference from a card."""
    card = await db.get(Card, card_id)
    if not card:
        raise HTTPException(404, "Card not found.")
    files = json.loads(card.files) if card.files else []
    if path in files:
        files.remove(path)
        card.files = json.dumps(files)
        card.updated_at = utcnow()
        await db.commit()
    return files
