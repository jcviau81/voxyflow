"""Vision extraction — describe/transcribe images via the Claude CLI.

Used by the RAG document-ingest path to turn images (and scanned PDF pages,
which carry no text layer) into searchable text. Routes through ``claude -p``
with an ``@file`` reference so it works on the Claude Max subscription with no
API key — the same CLI path the rest of Voxyflow already uses.

Best-effort by contract: any failure returns ``""`` so the caller can still
store the document (with zero chunks) rather than hard-failing the upload.

Env overrides:
  RAG_VISION_MODEL      — model id/alias for the vision pass (default: Fast layer model)
  RAG_VISION_TIMEOUT_S  — per-image subprocess timeout in seconds (default: 120)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path

from app.config import get_settings
from app.services.llm.capability_registry import supports_vision
from app.services.llm.cli_backend import _find_claude_cli, _model_flag
from app.services.llm.cli_rate_gate import get_rate_gate

logger = logging.getLogger(__name__)

# Image extensions we hand to the vision model. Anything here is treated as an
# image by the ingest pipeline (handled via vision, not the text parsers).
IMAGE_EXTS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".heif"}
)

_VISION_PROMPT = (
    "You are an OCR and image-understanding engine indexing a file for search. "
    "First transcribe ALL text visible in the image verbatim. Then add a brief "
    "description of any non-text visual content (layout, charts, diagrams, photos, "
    "UI elements). Output plain text only — no preamble, no markdown headers. "
    "If the image is blank or has no discernible content, reply exactly with: "
    "[no readable content]"
)

_SENTINEL_EMPTY = "[no readable content]"


def is_image_filename(filename: str) -> bool:
    """True if the filename's extension is one we route through vision."""
    return Path(filename).suffix.lower() in IMAGE_EXTS


def _timeout_s() -> float:
    try:
        return float(os.environ.get("RAG_VISION_TIMEOUT_S", "120"))
    except (TypeError, ValueError):
        return 120.0


def _resolve_vision_model() -> str:
    """Pick a vision-capable CLI model alias.

    Prefers RAG_VISION_MODEL, then the configured Fast layer model, then Sonnet.
    Claude opus/sonnet/haiku aliases are all multimodal; only a non-Claude id
    that the registry marks text-only triggers the Sonnet fallback.
    """
    raw = (os.environ.get("RAG_VISION_MODEL") or "").strip()
    if not raw:
        cfg = get_settings()
        raw = (
            getattr(cfg, "claude_fast_model", "")
            or getattr(cfg, "claude_sonnet_model", "")
            or "claude-sonnet-4-6"
        )
    alias = _model_flag(raw)
    if alias not in ("opus", "sonnet", "haiku") and not supports_vision(raw):
        return "sonnet"
    return alias


def _parse_result(stdout: str) -> str:
    """Extract the ``result`` field from ``claude -p --output-format json`` output."""
    stdout = stdout.strip()
    if not stdout:
        return ""
    try:
        obj = json.loads(stdout)
    except json.JSONDecodeError:
        # Defensive: if multiple JSON lines slipped through, take the last parseable one.
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        else:
            return ""
    if isinstance(obj, dict):
        if obj.get("is_error"):
            return ""
        return str(obj.get("result", "") or "")
    return ""


async def describe_image_bytes(
    content: bytes, filename: str, *, prompt: str | None = None
) -> str:
    """Transcribe + describe an image. Returns extracted text, or "" on failure.

    Never raises — designed so a failed vision pass degrades to "store with no
    text" rather than failing the whole upload.
    """
    if not content:
        return ""

    suffix = Path(filename).suffix.lower()
    if suffix not in IMAGE_EXTS:
        suffix = ".png"  # default container; the CLI sniffs actual format

    model = _resolve_vision_model()
    cli = _find_claude_cli(get_settings().claude_cli_path)
    gate = get_rate_gate()

    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="voxy_vision_")
        with os.fdopen(fd, "wb") as fh:
            fh.write(content)

        # Prompt + @file reference is passed as a positional arg (NOT stdin), and
        # stdin is closed so the CLI does not wait for piped input.
        args = [
            cli, "-p",
            "--model", model,
            "--permission-mode", "bypassPermissions",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--mcp-config", '{"mcpServers":{}}',
            "--output-format", "json",
            f"{prompt or _VISION_PROMPT}\n\n@{tmp_path}",
        ]

        await gate.acquire(is_worker=True)
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=16 * 1024 * 1024,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=_timeout_s()
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
                logger.warning("vision: timed out describing %r", filename)
                return ""
        finally:
            gate.release(is_worker=True)

        if proc.returncode != 0:
            logger.warning(
                "vision: claude exited %s for %r: %s",
                proc.returncode, filename,
                stderr_b.decode("utf-8", "replace")[:300],
            )
            return ""

        text = _parse_result(stdout_b.decode("utf-8", "replace")).strip()
        if not text or text.lower() == _SENTINEL_EMPTY:
            return ""
        logger.info("vision: described %r via %s (%d chars)", filename, model, len(text))
        return text

    except Exception as e:  # never propagate — best-effort
        logger.warning("vision: describe_image_bytes failed for %r: %s", filename, e)
        return ""
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
