"""Worker Artifact Store — Persists full raw worker output to disk as .md files.

When a worker completes, its full ``result_content`` is written to
``~/.voxyflow/worker_artifacts/{task_id}.md`` with a YAML frontmatter header.

The dispatcher receives the full raw output in the callback. The artifact
file serves as persistent storage and supports paged reads via the
``workers_read_artifact`` inline tool for very large outputs.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("voxyflow.worker_artifacts")

# Hard cap on artifact file size on disk. Prevents a runaway worker from
# filling the data dir with multi-megabyte logs.
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024  # 2 MB

# Default slice length when read_artifact is called without an explicit length.
DEFAULT_READ_LENGTH = 50_000


def _data_dir() -> Path:
    voxyflow_data = os.environ.get("VOXYFLOW_DATA", os.path.expanduser("~/.voxyflow"))
    d = Path(voxyflow_data) / "worker_artifacts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def artifact_path(task_id: str) -> Path:
    """Return the on-disk path for a task's artifact (may not exist)."""
    return _data_dir() / f"{task_id}.md"


def _yaml_escape(value: str) -> str:
    """Escape a string for safe inclusion as a YAML scalar value."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def write_artifact(
    task_id: str,
    content: str,
    *,
    intent: Optional[str] = None,
    model: Optional[str] = None,
    project_id: Optional[str] = None,
    card_id: Optional[str] = None,
    session_id: Optional[str] = None,
    status: str = "success",
) -> Optional[str]:
    """Write a worker's full raw output to disk.

    Returns the absolute path as a string, or ``None`` on failure.
    Empty content returns ``None`` (no file is created).
    """
    if not content:
        return None

    body = content
    truncated_note = ""
    body_bytes = body.encode("utf-8", errors="replace")
    if len(body_bytes) > MAX_ARTIFACT_BYTES:
        # Keep the head — that's the useful part for `cat`/`head` style output.
        body_bytes = body_bytes[:MAX_ARTIFACT_BYTES]
        body = body_bytes.decode("utf-8", errors="replace")
        truncated_note = (
            f"\n\n[... artifact truncated at {MAX_ARTIFACT_BYTES} bytes ...]\n"
        )

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
    if project_id:
        frontmatter_lines.append(f'project_id: "{_yaml_escape(project_id)}"')
    if card_id:
        frontmatter_lines.append(f'card_id: "{_yaml_escape(card_id)}"')
    if session_id:
        frontmatter_lines.append(f'session_id: "{_yaml_escape(session_id)}"')
    frontmatter_lines.append(f"chars: {len(content)}")
    frontmatter_lines.append("---")
    frontmatter = "\n".join(frontmatter_lines) + "\n\n"

    path = artifact_path(task_id)
    try:
        path.write_text(frontmatter + body + truncated_note, encoding="utf-8")
        logger.info(
            f"[WorkerArtifact] Wrote {path.name} ({len(body)} chars"
            f"{', truncated' if truncated_note else ''})"
        )
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

    return {
        "content": slice_text,
        "offset": offset,
        "length": len(slice_text),
        "total_chars": total,
        "has_more": has_more,
        "path": str(path),
    }


def delete_artifact(task_id: str) -> bool:
    """Delete an artifact file. Returns True if a file was removed."""
    path = artifact_path(task_id)
    try:
        if path.exists():
            path.unlink()
            return True
    except Exception as e:
        logger.debug(f"[WorkerArtifact] Failed to delete {task_id}: {e}")
    return False
