"""Worker Session Store — Tracks worker sessions for persistence across page refresh.

Maintains an in-memory registry of worker sessions with periodic disk persistence.
Sessions are stored as individual JSON files under ~/.voxyflow/worker_sessions/.

Frontend can query active/recent sessions via the REST endpoint to rehydrate
the WorkerPanel after a page refresh.
"""

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("voxyflow.worker_sessions")

# Timeout: mark workers as timed_out if running > 10 minutes
RUNNING_TIMEOUT_SECONDS = 1800  # 30 minutes
# Only return sessions from the last hour (running sessions always included)
RECENT_WINDOW_SECONDS = 3600
# Terminal sessions (done/failed/cancelled) expire faster
TERMINAL_WINDOW_SECONDS = 120  # 2 minutes


class WorkerSession:
    """Single worker session entry."""

    __slots__ = (
        "task_id", "session_id", "chat_id", "project_id", "card_id", "status", "model", "intent",
        "summary", "start_time", "end_time", "result_summary", "artifact_path",
    )

    def __init__(
        self,
        task_id: str,
        session_id: str,
        chat_id: Optional[str] = None,
        project_id: Optional[str] = None,
        card_id: Optional[str] = None,
        status: str = "running",
        model: str = "sonnet",
        intent: str = "unknown",
        summary: str = "",
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        result_summary: Optional[str] = None,
        artifact_path: Optional[str] = None,
    ):
        self.task_id = task_id
        self.session_id = session_id
        self.chat_id = chat_id
        self.project_id = project_id
        self.card_id = card_id
        self.status = status
        self.model = model
        self.intent = intent
        self.summary = summary
        self.start_time = start_time or time.time()
        self.end_time = end_time
        self.result_summary = result_summary
        self.artifact_path = artifact_path

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "session_id": self.session_id,
            "chat_id": self.chat_id,
            "project_id": self.project_id,
            "card_id": self.card_id,
            "status": self.status,
            "model": self.model,
            "intent": self.intent,
            "summary": self.summary,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "result_summary": self.result_summary,
            "artifact_path": self.artifact_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkerSession":
        return cls(
            task_id=data["task_id"],
            session_id=data["session_id"],
            chat_id=data.get("chat_id"),
            project_id=data.get("project_id"),
            card_id=data.get("card_id"),
            status=data.get("status", "running"),
            model=data.get("model", "sonnet"),
            intent=data.get("intent", "unknown"),
            summary=data.get("summary", ""),
            start_time=data.get("start_time"),
            end_time=data.get("end_time"),
            result_summary=data.get("result_summary"),
            artifact_path=data.get("artifact_path"),
        )


class WorkerSessionStore:
    """In-memory store with file-based persistence for worker sessions."""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir is None:
            voxyflow_data = os.environ.get("VOXYFLOW_DATA", os.path.expanduser("~/.voxyflow"))
            data_dir = os.path.join(voxyflow_data, "worker_sessions")
        self._data_dir = Path(data_dir)
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, WorkerSession] = {}
        self._load_from_disk()
        logger.info(f"[WorkerSessionStore] Initialized at {self._data_dir} ({len(self._sessions)} sessions loaded)")

    def _load_from_disk(self) -> None:
        """Load persisted sessions from disk on startup."""
        for filepath in self._data_dir.glob("*.json"):
            try:
                data = json.loads(filepath.read_text())
                session = WorkerSession.from_dict(data)
                # Mark stale running sessions as timed_out
                if session.status == "running":
                    elapsed = time.time() - session.start_time
                    if elapsed > RUNNING_TIMEOUT_SECONDS:
                        session.status = "timed_out"
                        session.end_time = session.start_time + RUNNING_TIMEOUT_SECONDS
                self._sessions[session.task_id] = session
            except Exception as e:
                logger.warning(f"[WorkerSessionStore] Failed to load {filepath.name}: {e}")
                try:
                    filepath.unlink()
                except Exception as e:
                    logger.debug("Failed to delete corrupt session file %s: %s", filepath.name, e)
        # Persist any timeout corrections
        for s in self._sessions.values():
            if s.status == "timed_out":
                self._persist(s)

    def _refresh_from_disk(self) -> None:
        """Re-scan disk for new or updated sessions written by other processes.

        - New files (not in self._sessions) are loaded
        - Known files with status "running" are re-read to pick up status changes
        - Known terminal sessions are skipped (already final)
        """
        _TERMINAL = {"done", "failed", "cancelled", "timed_out"}
        try:
            on_disk = list(self._data_dir.glob("*.json"))
        except Exception as e:
            logger.debug("[WorkerSessionStore] _refresh_from_disk scan failed: %s", e)
            return

        for filepath in on_disk:
            task_id = filepath.stem
            try:
                existing = self._sessions.get(task_id)
                # Skip terminal sessions we already know about
                if existing and existing.status in _TERMINAL:
                    continue
                data = json.loads(filepath.read_text())
                session = WorkerSession.from_dict(data)
                # Apply timeout check for running sessions
                if session.status == "running":
                    elapsed = time.time() - session.start_time
                    if elapsed > RUNNING_TIMEOUT_SECONDS:
                        session.status = "timed_out"
                        session.end_time = session.start_time + RUNNING_TIMEOUT_SECONDS
                self._sessions[task_id] = session
            except Exception as e:
                logger.debug("[WorkerSessionStore] _refresh_from_disk skip %s: %s", filepath.name, e)

    def _persist(self, session: WorkerSession) -> None:
        """Write a single session to disk."""
        filepath = self._data_dir / f"{session.task_id}.json"
        try:
            filepath.write_text(json.dumps(session.to_dict(), default=str))
        except Exception as e:
            logger.warning(f"[WorkerSessionStore] Failed to persist {session.task_id}: {e}")

    def _cleanup_file(self, task_id: str) -> None:
        """Remove a session file from disk."""
        filepath = self._data_dir / f"{task_id}.json"
        try:
            filepath.unlink(missing_ok=True)
        except Exception as e:
            logger.debug("Failed to delete session file %s: %s", filepath.name, e)

    def register(
        self,
        task_id: str,
        session_id: str,
        chat_id: Optional[str] = None,
        project_id: Optional[str] = None,
        card_id: Optional[str] = None,
        model: str = "sonnet",
        intent: str = "unknown",
        summary: str = "",
    ) -> WorkerSession:
        """Register a new worker session (called when a task starts)."""
        session = WorkerSession(
            task_id=task_id,
            session_id=session_id,
            chat_id=chat_id,
            project_id=project_id,
            card_id=card_id,
            status="running",
            model=model,
            intent=intent,
            summary=summary,
        )
        self._sessions[task_id] = session
        self._persist(session)
        logger.info(f"[WorkerSessionStore] Registered task {task_id[:8]} ({intent}, {model})")
        return session

    def update_status(
        self,
        task_id: str,
        status: str,
        result_summary: Optional[str] = None,
        artifact_path: Optional[str] = None,
    ) -> None:
        """Update a session's status (completed, failed, timed_out, cancelled).

        ``result_summary`` stores the full raw output (no truncation).
        The full output also lives in the ``.md`` artifact at ``artifact_path``.
        """
        session = self._sessions.get(task_id)
        if not session:
            return
        session.status = status
        session.end_time = time.time()
        if result_summary is not None:
            session.result_summary = result_summary
        if artifact_path is not None:
            session.artifact_path = artifact_path
        self._persist(session)
        logger.debug(f"[WorkerSessionStore] Updated task {task_id[:8]} → {status}")

    def check_timeouts(self) -> list[str]:
        """Check for running sessions that have exceeded the timeout. Returns task_ids that timed out."""
        timed_out = []
        now = time.time()
        for task_id, session in self._sessions.items():
            if session.status == "running" and (now - session.start_time) > RUNNING_TIMEOUT_SECONDS:
                session.status = "timed_out"
                session.end_time = now
                session.result_summary = f"Timed out after {RUNNING_TIMEOUT_SECONDS}s"
                self._persist(session)
                timed_out.append(task_id)
        return timed_out

    def _is_visible(self, session: "WorkerSession", now: float, include_old: bool) -> bool:
        """Check if a session should be visible in listings.

        Running sessions are always visible. Terminal sessions (completed,
        failed, cancelled, timed_out) expire after TERMINAL_WINDOW_SECONDS.
        """
        if include_old:
            return True
        if session.status == "running":
            return True
        # Terminal sessions use the shorter window
        effective_time = session.end_time or session.start_time
        terminal_cutoff = now - TERMINAL_WINDOW_SECONDS
        return effective_time >= terminal_cutoff

    def get_sessions_by_project(
        self,
        project_id: str,
        include_old: bool = False,
    ) -> list[dict]:
        """Get sessions filtered by project_id (stable across WS reconnects)."""
        self.check_timeouts()
        now = time.time()
        results = []
        for session in self._sessions.values():
            if session.project_id != project_id:
                continue
            if not self._is_visible(session, now, include_old):
                continue
            results.append(session.to_dict())
        results.sort(key=lambda s: (0 if s["status"] == "running" else 1, -s["start_time"]))
        return results

    def get_sessions(
        self,
        session_id: Optional[str] = None,
        include_old: bool = False,
    ) -> list[dict]:
        """Get active + recent sessions, optionally filtered by session_id.

        Running sessions are always included. Terminal sessions expire
        after TERMINAL_WINDOW_SECONDS (2 min).
        """
        self._refresh_from_disk()
        self.check_timeouts()
        now = time.time()
        results = []

        for session in self._sessions.values():
            if session_id and session.session_id != session_id:
                continue
            if not self._is_visible(session, now, include_old):
                continue
            results.append(session.to_dict())

        results.sort(key=lambda s: (0 if s["status"] == "running" else 1, -s["start_time"]))
        return results

    def get_session(self, task_id: str) -> Optional[dict]:
        """Get a single session by task_id."""
        self._refresh_from_disk()
        session = self._sessions.get(task_id)
        if session:
            # Check timeout before returning
            if session.status == "running":
                elapsed = time.time() - session.start_time
                if elapsed > RUNNING_TIMEOUT_SECONDS:
                    session.status = "timed_out"
                    session.end_time = time.time()
                    self._persist(session)
            return session.to_dict()
        return None

    def cleanup_stale(self, timeout_seconds: int = 120) -> list[str]:
        """Find running sessions with no heartbeat beyond timeout_seconds,
        mark them as failed, and persist the change. Returns task_ids affected."""
        stale = []
        now = time.time()
        for task_id, session in self._sessions.items():
            if session.status == "running" and (now - session.start_time) > timeout_seconds:
                session.status = "failed"
                session.end_time = now
                session.result_summary = f"timeout — no heartbeat after {timeout_seconds}s"
                self._persist(session)
                stale.append(task_id)
        if stale:
            logger.info(f"[WorkerSessionStore] cleanup_stale: marked {len(stale)} workers as failed (>{timeout_seconds}s)")
        return stale

    def cleanup_old(self, max_age_seconds: int = 86400) -> int:
        """Remove sessions older than max_age_seconds. Returns count removed.

        Also deletes the on-disk worker artifact (.md) for each removed session
        so they don't accumulate forever.
        """
        from app.services.worker_artifact_store import delete_artifact

        cutoff = time.time() - max_age_seconds
        to_remove = [
            tid for tid, s in self._sessions.items()
            if s.status != "running" and s.start_time < cutoff
        ]
        for tid in to_remove:
            del self._sessions[tid]
            self._cleanup_file(tid)
            delete_artifact(tid)
        if to_remove:
            logger.info(f"[WorkerSessionStore] Cleaned up {len(to_remove)} old sessions")
        return len(to_remove)

    def clear_terminal(self) -> int:
        """Remove all non-running sessions immediately. Returns count removed."""
        from app.services.worker_artifact_store import delete_artifact

        to_remove = [
            tid for tid, s in self._sessions.items()
            if s.status != "running"
        ]
        for tid in to_remove:
            del self._sessions[tid]
            self._cleanup_file(tid)
            delete_artifact(tid)
        if to_remove:
            logger.info(f"[WorkerSessionStore] Cleared {len(to_remove)} terminal sessions")
        return len(to_remove)


# Global singleton
_store: Optional[WorkerSessionStore] = None


def get_worker_session_store() -> WorkerSessionStore:
    global _store
    if _store is None:
        _store = WorkerSessionStore()
    return _store
