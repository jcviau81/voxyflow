"""Async document ingestion — the single entry point the upload route uses.

Decides, per file, how to turn bytes into searchable text and ALWAYS returns a
``ParsedDocument`` (best-effort): nothing here raises for a "bad" file, so an
upload is never rejected — at worst it is stored with zero chunks.

Routing:
  * image (png/jpg/…)         → vision model transcribes + describes it
  * .pdf with a text layer    → pypdf text extraction (sync parser)
  * .pdf with no text layer   → pypdf-extract embedded page images → vision (capped)
  * .docx/.xlsx/.csv/.pptx/…  → dedicated sync parser
  * unknown but text-like     → best-effort decode (source code, json, yaml, logs…)
  * unknown binary            → stored, zero chunks (no crash, no 415)

Env overrides:
  RAG_VISION_ENABLED      — "false" disables all vision passes (default: enabled)
  RAG_PDF_OCR_MAX_PAGES   — max scanned-PDF pages sent to vision (default: 5)
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
from pathlib import Path

from app.services.document_parser import (
    ParsedDocument,
    UnsupportedFileType,
    _split_into_chunks,
    best_effort_text,
    get_document_parser_registry,
)
from app.services.llm import vision_service

logger = logging.getLogger(__name__)

# Below this many non-whitespace chars, a PDF is treated as scanned (no text layer)
# and we fall back to vision on its embedded page images.
_PDF_TEXT_MIN_CHARS = 20


def _vision_enabled() -> bool:
    return os.environ.get("RAG_VISION_ENABLED", "true").strip().lower() not in ("false", "0", "no")


def _pdf_ocr_max_pages() -> int:
    try:
        return max(0, int(os.environ.get("RAG_PDF_OCR_MAX_PAGES", "5")))
    except (TypeError, ValueError):
        return 5


def _make_parsed(text: str, filename: str, *, extraction: str, **extra) -> ParsedDocument:
    text = text or ""
    chunks = _split_into_chunks(text) if text.strip() else []
    meta = {
        "filename": filename,
        "filetype": Path(filename).suffix.lower(),
        "size_bytes": extra.pop("size_bytes", None),
        "chunk_count": len(chunks),
        "extraction": extraction,
    }
    meta.update(extra)
    # Drop None values (Chroma metadata rejects them).
    meta = {k: v for k, v in meta.items() if v is not None}
    return ParsedDocument(text=text, chunks=chunks, metadata=meta)


def _sniff_image_suffix(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:2] == b"BM":
        return ".bmp"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tif"
    return ".png"


def _extract_pdf_images(content: bytes, max_pages: int) -> list[bytes]:
    """Pull embedded images from the first ``max_pages`` PDF pages (pure pypdf).

    Scanned PDFs carry one full-page image per page; this recovers them without
    needing poppler/pdf2image. Returns image bytes; never raises.
    """
    images: list[bytes] = []
    try:
        from pypdf import PdfReader  # type: ignore[import]

        reader = PdfReader(io.BytesIO(content))
        for page in reader.pages[:max_pages]:
            try:
                page_imgs = list(getattr(page, "images", []))
            except Exception as e:  # pragma: no cover - pypdf image edge cases
                logger.debug("pdf image extraction: page failed: %s", e)
                continue
            for img in page_imgs:
                try:
                    data = img.data
                except Exception:
                    continue
                if data:
                    images.append(data)
                if len(images) >= max_pages:
                    return images
    except Exception as e:
        logger.warning("pdf image extraction failed: %s", e)
    return images


async def _ocr_scanned_pdf(content: bytes, filename: str, size_bytes: int) -> ParsedDocument:
    """Vision fallback for PDFs with no extractable text layer."""
    max_pages = _pdf_ocr_max_pages()
    if not _vision_enabled() or max_pages == 0:
        return _make_parsed("", filename, extraction="pdf-no-text", size_bytes=size_bytes,
                            page_count=None)

    images = await asyncio.to_thread(_extract_pdf_images, content, max_pages)
    if not images:
        logger.info("scanned PDF %r: no embedded images recoverable", filename)
        return _make_parsed("", filename, extraction="pdf-no-text", size_bytes=size_bytes)

    parts: list[str] = []
    for i, data in enumerate(images, start=1):
        suffix = _sniff_image_suffix(data)
        desc = await vision_service.describe_image_bytes(data, f"page{i}{suffix}")
        if desc.strip():
            parts.append(f"[Page {i}]\n{desc.strip()}")

    text = "\n\n".join(parts)
    return _make_parsed(
        text, filename,
        extraction="pdf-vision-ocr", size_bytes=size_bytes,
        pages_ocred=len(images), vision=True,
    )


async def _ingest_image(content: bytes, filename: str, size_bytes: int) -> ParsedDocument:
    if not _vision_enabled():
        return _make_parsed("", filename, extraction="image-stored", size_bytes=size_bytes)
    desc = await vision_service.describe_image_bytes(content, filename)
    return _make_parsed(
        desc, filename,
        extraction="image-vision" if desc.strip() else "image-stored",
        size_bytes=size_bytes, vision=bool(desc.strip()),
    )


def _best_effort_sync(content: bytes, filename: str, size_bytes: int) -> ParsedDocument:
    """Decode-as-text fallback for unknown types; store-only for true binaries."""
    text = best_effort_text(content)
    if text is not None and text.strip():
        return _make_parsed(text, filename, extraction="text-decode", size_bytes=size_bytes)
    return _make_parsed("", filename, extraction="stored-binary", size_bytes=size_bytes)


async def ingest_document(content: bytes, filename: str) -> ParsedDocument:
    """Turn uploaded bytes into a ParsedDocument. Never raises."""
    size_bytes = len(content)
    ext = Path(filename).suffix.lower()

    # 1) Images → vision
    if vision_service.is_image_filename(filename):
        return await _ingest_image(content, filename, size_bytes)

    # 2) Dedicated sync parsers (pdf/docx/xlsx/csv/pptx/html/txt/md)
    registry = get_document_parser_registry()
    try:
        parser = registry.get_parser(filename)
    except UnsupportedFileType:
        parser = None

    if parser is not None:
        try:
            parsed = await asyncio.to_thread(parser.parse, content, filename)
        except Exception as e:
            logger.warning("parser %s failed for %r: %s — falling back to text decode",
                           type(parser).__name__, filename, e)
            return await asyncio.to_thread(_best_effort_sync, content, filename, size_bytes)

        # PDF with no usable text layer → vision OCR on page images.
        if ext == ".pdf" and len((parsed.text or "").strip()) < _PDF_TEXT_MIN_CHARS:
            logger.info("PDF %r has no text layer — attempting vision OCR", filename)
            return await _ocr_scanned_pdf(content, filename, size_bytes)

        # Stamp extraction marker for observability without losing parser metadata.
        parsed.metadata.setdefault("extraction", "parser")
        parsed.metadata.setdefault("size_bytes", size_bytes)
        return parsed

    # 3) Unknown type → best-effort text decode / store-as-binary
    return await asyncio.to_thread(_best_effort_sync, content, filename, size_bytes)
