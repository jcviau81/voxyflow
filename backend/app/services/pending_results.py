"""Pending Results Store — Persists worker results for offline delivery.

When a worker completes but the WebSocket is closed, results are stored
as JSON files. On the next WS connection for the same session, pending
results are delivered and cleaned up.

Storage: ~/.voxyflow/pending/{session_id}/{task_id}.json
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("voxyflow.pending_results")


class PendingResultStore:
    """File-based store for worker results awaiting delivery."""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            data_dir = os.path.expanduser("~/.voxyflow/pending")
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[PendingResults] Store initialized at {self._data_dir}")

    async def store(self, session_id: str, result: dict) -> None:
        """Store a pending result for later delivery.

        Args:
            session_id: The session that should receive this result.
            result: The full WS message dict (type, payload, timestamp).
        """
        session_dir = self._data_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        task_id = result.get("payload", {}).get("taskId", f"unknown-{int(time.time() * 1000)}")
        event_type = result.get("type", "unknown")
        filename = f"{task_id}_{event_type}_{int(time.time() * 1000)}.json"
        filepath = session_dir / filename

        try:
            filepath.write_text(json.dumps(result, default=str))
            logger.info(f"[PendingResults] Stored {event_type} for session {session_id}: {filename}")
        except Exception as e:
            logger.error(f"[PendingResults] Failed to store result: {e}")

    async def get_pending(self, session_id: str) -> list[dict]:
        """Retrieve all pending results for a session, ordered by timestamp.

        Returns list of WS message dicts ready to send.
        """
        session_dir = self._data_dir / session_id
        if not session_dir.exists():
            return []

        results = []
        for filepath in sorted(session_dir.glob("*.json")):
            try:
                data = json.loads(filepath.read_text())
                data["_pending_file"] = str(filepath)  # Track for cleanup
                results.append(data)
            except Exception as e:
                logger.warning(f"[PendingResults] Failed to read {filepath}: {e}")
                # Remove corrupt files
                try:
                    filepath.unlink()
                except Exception as e:
                    logger.debug("Failed to delete corrupt pending result file %s: %s", filepath, e)

        if results:
            logger.info(f"[PendingResults] Found {len(results)} pending results for session {session_id}")
        return results

    async def mark_delivered(self, result: dict) -> None:
        """Remove a delivered result from the store."""
        filepath = result.get("_pending_file")
        if filepath:
            try:
                Path(filepath).unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"[PendingResults] Failed to delete {filepath}: {e}")

    async def cleanup_session(self, session_id: str) -> None:
        """Remove all pending results for a session."""
        session_dir = self._data_dir / session_id
        if session_dir.exists():
            for filepath in session_dir.glob("*.json"):
                try:
                    filepath.unlink()
                except Exception as e:
                    logger.debug("Failed to delete pending result file %s: %s", filepath, e)
            try:
                session_dir.rmdir()
            except Exception as e:
                logger.debug("Failed to remove session dir %s: %s", session_dir, e)

    async def cleanup_stale(self, max_age_seconds: float = 86400) -> int:
        """Remove pending result files older than max_age_seconds (default 24h).

        Also removes empty session directories. Returns the number of files removed.
        """
        removed = 0
        now = time.time()
        if not self._data_dir.exists():
            return 0

        for session_dir in self._data_dir.iterdir():
            if not session_dir.is_dir():
                continue
            for filepath in session_dir.glob("*.json"):
                try:
                    age = now - filepath.stat().st_mtime
                    if age > max_age_seconds:
                        filepath.unlink()
                        removed += 1
                except Exception as e:
                    logger.debug("Failed to check/delete stale pending result %s: %s", filepath, e)
            # Remove empty session directories
            try:
                if session_dir.exists() and not any(session_dir.iterdir()):
                    session_dir.rmdir()
            except Exception as e:
                logger.debug("Failed to remove empty session dir %s: %s", session_dir, e)

        if removed:
            logger.info(f"[PendingResults] Cleaned up {removed} stale pending result(s)")
        return removed


# Global singleton
pending_store = PendingResultStore()
