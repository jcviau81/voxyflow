"""Worker Artifact Store — Canonical blob store for full raw worker output.

This is the **single source of truth** for complete worker results.  All other
stores (DB ledger, worker session JSON, session store) keep only a short
preview + a reference to the artifact path.  The dispatcher gets a ~10K
inline preview and can page through the full output here via the
``workers.read_artifact`` MCP tool.

Files live at ``~/.voxyflow/worker_artifacts/{task_id}.md`` with YAML
frontmatter.

## Lifecycle (consumer-driven retention)

Each artifact has a sidecar ``{task_id}.meta.json`` tracking:
  - ``created_at``  — when the artifact was written to disk
  - ``read_at``     — set on first call to read_artifact (idempotent)
  - ``acked_at``    — set when ack_artifact is called; .md file deleted then
  - ``size_bytes``  — byte size of the full file at creation time

No automatic TTL deletion.  Artifacts persist until explicitly acked.
Orphans older than 30 days without ack emit a WARNING in the logs.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("voxyflow.worker_artifacts")

# Hard cap — safety valve against truly runaway workers.  This is the
# canonical store so we keep the full output up to a generous limit.
MAX_ARTIFACT_BYTES = 10 * 1024 * 1024  # 10 MB

# Default slice length when read_artifact is called without an explicit length.
DEFAULT_READ_LENGTH = 50_000

# Orphan warning threshold: artifacts un-acked for longer than this emit a
# WARNING log.  We do NOT auto-delete.
ORPHAN_WARNING_DAYS = 30


def _data_dir() -> Path:
    voxyflow_data = os.environ.get("VOXYFLOW_DATA_DIR", os.path.expanduser("~/.voxyflow"))
    d = Path(voxyflow_data) / "worker_artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def artifact_path(task_id: str) -> Path:
    """Return the on-disk path for a task's artifact (may not exist)."""
    return _data_dir() / f"{task_id}.md"


def completion_path(task_id: str) -> Path:
    """Return the on-disk path for a task's structured completion sidecar."""
    return _data_dir() / f"{task_id}.completion.json"


def meta_path(task_id: str) -> Path:
    """Return the on-disk path for a task's lifecycle metadata sidecar."""
    return _data_dir() / f"{task_id}.meta.json"


def _yaml_escape(value: str) -> str:
    """Escape a string for safe inclusion as a YAML scalar value."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


# ---------------------------------------------------------------------------
# Lifecycle metadata helpers
# ---------------------------------------------------------------------------

def _read_meta(task_id: str) -> Optional[dict]:
    """Load the lifecycle metadata sidecar, or None if not present."""
    path = meta_path(task_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[WorkerArtifact] Failed to read meta {task_id}: {e}")
        return None


def _write_meta(task_id: str, data: dict) -> None:
    """Persist lifecycle metadata to the sidecar JSON file."""
    path = meta_path(task_id)
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.warning(f"[WorkerArtifact] Failed to write meta {task_id}: {e}")


def _create_meta(task_id: str, size_bytes: int) -> dict:
    """Create fresh lifecycle metadata for a newly written artifact."""
    now_iso = datetime.now(timezone.utc).isoformat()
    data = {
        "task_id": task_id,
        "created_at": now_iso,
        "read_at": None,
        "acked_at": None,
        "size_bytes": size_bytes,
    }
    _write_meta(task_id, data)
    return data


def mark_read(task_id: str) -> None:
    """Set read_at on first call (idempotent — no-op if already set)."""
    meta = _read_meta(task_id)
    if meta is None:
        # Artifact exists but has no meta sidecar (legacy artifact).
        # Synthesize a minimal meta so we can track it going forward.
        apath = artifact_path(task_id)
        size = apath.stat().st_size if apath.exists() else 0
        meta = {
            "task_id": task_id,
            "created_at": None,
            "read_at": None,
            "acked_at": None,
            "size_bytes": size,
        }
    if meta.get("read_at") is not None:
        return  # already marked
    meta["read_at"] = datetime.now(timezone.utc).isoformat()
    _write_meta(task_id, meta)


def _check_orphan_warning() -> None:
    """Scan for un-acked artifacts older than ORPHAN_WARNING_DAYS and log warnings."""
    try:
        from datetime import timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=ORPHAN_WARNING_DAYS)
        for path in _data_dir().glob("*.meta.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("acked_at") is not None:
                    continue
                created_str = data.get("created_at")
                if not created_str:
                    continue
                created = datetime.fromisoformat(created_str)
                if created < cutoff:
                    logger.warning(
                        f"[WorkerArtifact] Orphan artifact >30d un-acked: "
                        f"task_id={data.get('task_id')}, created_at={created_str}, "
                        f"size_bytes={data.get('size_bytes')}"
                    )
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"[WorkerArtifact] Orphan check failed: {e}")


# ---------------------------------------------------------------------------
# Core artifact I/O
# ---------------------------------------------------------------------------

def write_artifact(
    task_id: str,
    content: str,
    *,
    intent: Optional[str] = None,
    model: Optional[str] = None,
    workspace_id: Optional[str] = None,
    card_id: Optional[str] = None,
    session_id: Optional[str] = None,
    status: str = "success",
) -> Optional[str]:
    """Write a worker's full raw output to disk.

    Returns the absolute path as a string, or ``None`` on failure.
    Empty content returns ``None`` (no file is created).
    Also creates a lifecycle metadata sidecar (``.meta.json``).
    """
    if not content:
        return None

    body = content
    truncated = False
    body_bytes = body.encode("utf-8", errors="replace")
    if len(body_bytes) > MAX_ARTIFACT_BYTES:
        # Safety cap for truly runaway output.  Keep the head — at 10MB this
        # should rarely trigger, and if it does the interesting part (command
        # start, file contents) is at the beginning.
        body_bytes = body_bytes[:MAX_ARTIFACT_BYTES]
        body = body_bytes.decode("utf-8", errors="replace")
        body += f"\n\n[... truncated at {MAX_ARTIFACT_BYTES // (1024*1024)} MB — original was {len(content):,} chars ...]\n"
        truncated = True

    now_iso = datetime.now(timezone.utc).isoformat()
    frontmatter_lines = [
        "---",
        f'task_id: "{_yaml_escape(task_id)}"',
        f'written_at: "{now_iso}"',
        f'status: "{_yaml_escape(status)}"',
    ]
    if intent:
        frontmatter_lines.append(f'intent: "{_yaml_escape(intent)}"')
    if model:
        frontmatter_lines.append(f'model: "{_yaml_escape(model)}"')
    if workspace_id:
        frontmatter_lines.append(f'workspace_id: "{_yaml_escape(workspace_id)}"')
    if card_id:
        frontmatter_lines.append(f'card_id: "{_yaml_escape(card_id)}"')
    if session_id:
        frontmatter_lines.append(f'session_id: "{_yaml_escape(session_id)}"')
    frontmatter_lines.append(f"chars: {len(content)}")
    frontmatter_lines.append("---")
    frontmatter = "\n".join(frontmatter_lines) + "\n\n"

    full_text = frontmatter + body
    path = artifact_path(task_id)
    try:
        path.write_text(full_text, encoding="utf-8")
        size_bytes = len(full_text.encode("utf-8", errors="replace"))
        logger.info(
            f"[WorkerArtifact] Wrote {path.name} ({len(body)} chars"
            f"{', truncated' if truncated else ''})"
        )
        # Create lifecycle metadata sidecar.
        _create_meta(task_id, size_bytes)
        # Opportunistically check for orphan warnings (cheap scan).
        _check_orphan_warning()
        return str(path)
    except Exception as e:
        logger.warning(f"[WorkerArtifact] Failed to write {task_id}: {e}")
        return None


def read_artifact(
    task_id: str,
    offset: int = 0,
    length: int = DEFAULT_READ_LENGTH,
) -> Optional[dict]:
    """Read a slice of an artifact file.

    Returns a dict with ``content``, ``offset``, ``length``, ``total_chars``,
    ``has_more``, and ``path``. Returns ``None`` if the artifact doesn't exist.

    The slice is taken over the **body** (everything after the frontmatter
    block), so offsets are stable and easy for the dispatcher to reason about.

    Side effect: marks ``read_at`` in the lifecycle metadata sidecar on first
    call (idempotent thereafter).

    Works even if the in-memory task record has been purged — looks up the
    artifact directly by disk path.
    """
    path = artifact_path(task_id)
    if not path.exists():
        return None

    try:
        full = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"[WorkerArtifact] Failed to read {task_id}: {e}")
        return None

    # Strip frontmatter so offset is over the body only.
    body = full
    if full.startswith("---\n"):
        end = full.find("\n---\n", 4)
        if end != -1:
            body = full[end + len("\n---\n"):].lstrip("\n")

    total = len(body)
    if offset < 0:
        offset = 0
    if length <= 0:
        length = DEFAULT_READ_LENGTH
    end_pos = min(offset + length, total)
    slice_text = body[offset:end_pos]
    has_more = end_pos < total

    # Mark read_at (idempotent — no-op if already set).
    mark_read(task_id)

    return {
        "content": slice_text,
        "offset": offset,
        "length": len(slice_text),
        "total_chars": total,
        "has_more": has_more,
        "path": str(path),
    }


def read_artifact_meta(task_id: str) -> Optional[dict]:
    """Parse just the YAML frontmatter of an artifact, no body.

    Used as a last-resort fallback in workers.get_result when the in-memory
    supervisor and the DB row have both been GC'd: the artifact on disk has
    no TTL, so we can still tell the dispatcher "yes, this worker did finish,
    here's its intent / status / size".
    """
    path = artifact_path(task_id)
    if not path.exists():
        return None
    try:
        # Frontmatter is small — read at most the first 4 KB to find the
        # closing `---` marker.
        with path.open("r", encoding="utf-8", errors="replace") as f:
            head = f.read(4096)
    except Exception as e:
        logger.warning(f"[WorkerArtifact] Failed to read meta {task_id}: {e}")
        return None

    if not head.startswith("---\n"):
        return {"path": str(path), "task_id": task_id}

    end = head.find("\n---\n", 4)
    if end == -1:
        return {"path": str(path), "task_id": task_id}

    block = head[4:end]
    meta: dict = {"path": str(path)}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # Strip surrounding double-quotes from YAML scalar
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        # Coerce `chars` to int when present
        if key == "chars":
            try:
                meta[key] = int(value)
                continue
            except ValueError:
                pass
        if key:
            meta[key] = value
    return meta


def ack_artifact(task_id: str) -> dict:
    """Acknowledge and delete a worker artifact.

    Deletes the ``.md`` artifact file from disk, sets ``acked_at`` in the
    metadata sidecar.  The sidecar and completion JSON are **kept** as a
    historical trace.

    Returns:
        {success: True, acked_at, size_bytes_freed}  on success
        {success: False, error: "Already acked at <ts>"}  if already acked
        {success: False, error: "Unknown task: <id>"}  if no artifact found
    """
    meta = _read_meta(task_id)
    apath = artifact_path(task_id)

    if meta is None:
        # No sidecar — check if the artifact file at least exists.
        if not apath.exists():
            return {"success": False, "error": f"Unknown task: {task_id}"}
        # Legacy artifact with no meta — synthesize.
        size = apath.stat().st_size
        meta = {
            "task_id": task_id,
            "created_at": None,
            "read_at": None,
            "acked_at": None,
            "size_bytes": size,
        }

    if meta.get("acked_at") is not None:
        return {
            "success": False,
            "error": f"Already acked at {meta['acked_at']}",
        }

    # Capture size before deletion.
    size_bytes_freed = 0
    if apath.exists():
        try:
            size_bytes_freed = apath.stat().st_size
            apath.unlink()
            logger.info(f"[WorkerArtifact] Acked + deleted {task_id} ({size_bytes_freed} bytes)")
        except Exception as e:
            logger.warning(f"[WorkerArtifact] Failed to delete artifact {task_id}: {e}")
            return {"success": False, "error": f"Failed to delete artifact: {e}"}

    # Persist acked_at in the meta sidecar.
    now_iso = datetime.now(timezone.utc).isoformat()
    meta["acked_at"] = now_iso
    _write_meta(task_id, meta)

    return {
        "success": True,
        "acked_at": now_iso,
        "size_bytes_freed": size_bytes_freed,
    }


def list_unread(limit: int = 100) -> list[dict]:
    """Return artifacts where acked_at is None, sorted by created_at desc.

    Each entry: {task_id, created_at, read_at, size_bytes, summary_preview}.
    summary_preview is the first 200 chars of the completion summary, if any.
    """
    _check_orphan_warning()

    results: list[dict] = []
    for meta_file in _data_dir().glob("*.meta.json"):
        try:
            data = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if data.get("acked_at") is not None:
            continue
        tid = data.get("task_id", meta_file.stem.replace(".meta", ""))
        entry: dict = {
            "task_id": tid,
            "created_at": data.get("created_at"),
            "read_at": data.get("read_at"),
            "size_bytes": data.get("size_bytes"),
            "summary_preview": None,
        }
        # Try to get a summary preview from the completion sidecar.
        cpath = completion_path(tid)
        if cpath.exists():
            try:
                comp = json.loads(cpath.read_text(encoding="utf-8"))
                summary = comp.get("summary") or ""
                entry["summary_preview"] = summary[:200] if summary else None
            except Exception:
                pass
        results.append(entry)

    def _sort_key(e: dict):
        val = e.get("created_at")
        return val if val else ""

    results.sort(key=_sort_key, reverse=True)
    return results[:limit]


def delete_artifact(task_id: str) -> bool:
    """Delete an artifact file (and its completion sidecar, if any).

    NOTE: This intentionally does NOT delete the meta sidecar —
    use ack_artifact() for the consumer-driven lifecycle path instead.
    This function is for internal cleanup (e.g. workspace deletion).

    Returns True if the main .md file was removed.
    """
    path = artifact_path(task_id)
    removed = False
    try:
        if path.exists():
            path.unlink()
            removed = True
    except Exception as e:
        logger.debug(f"[WorkerArtifact] Failed to delete {task_id}: {e}")

    sidecar = completion_path(task_id)
    try:
        if sidecar.exists():
            sidecar.unlink()
    except Exception as e:
        logger.debug(f"[WorkerArtifact] Failed to delete completion {task_id}: {e}")
    return removed


# ---------------------------------------------------------------------------
# Structured completion sidecar
# ---------------------------------------------------------------------------
#
# The .md artifact holds the worker's full raw output (narration + any large
# tool outputs). The structured ``voxyflow.worker.complete`` payload — status,
# summary, findings, pointers, next_step — lives in a tiny sidecar JSON file
# so it survives backend restarts and supervisor GC, and can be consumed
# programmatically without reparsing markdown.
#
# Single source of truth for the dispatcher: ``workers.get_result`` reads the
# in-memory supervisor first, then falls back to this sidecar.

_COMPLETION_KEYS = ("status", "summary", "findings", "pointers", "next_step", "plan")


def write_completion(task_id: str, payload: dict[str, Any]) -> Optional[str]:
    """Persist the structured worker.complete payload alongside the artifact.

    Returns the absolute path on success, ``None`` if nothing was written
    (empty payload) or on I/O failure.
    """
    if not payload:
        return None

    clean: dict[str, Any] = {}
    for key in _COMPLETION_KEYS:
        if key in payload and payload[key] not in (None, ""):
            clean[key] = payload[key]
    if not clean:
        return None
    clean["written_at"] = datetime.now(timezone.utc).isoformat()

    path = completion_path(task_id)
    try:
        path.write_text(
            json.dumps(clean, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info(
            f"[WorkerArtifact] Wrote {path.name} "
            f"(findings={len(clean.get('findings') or [])}, "
            f"pointers={len(clean.get('pointers') or [])})"
        )
        return str(path)
    except Exception as e:
        logger.warning(f"[WorkerArtifact] Failed to write completion {task_id}: {e}")
        return None


def read_completion(task_id: str) -> Optional[dict[str, Any]]:
    """Load the structured worker.complete payload, or ``None`` if missing."""
    path = completion_path(task_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[WorkerArtifact] Failed to read completion {task_id}: {e}")
        return None
