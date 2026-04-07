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
# Only return sessions from the last hour
RECENT_WINDOW_SECONDS = 3600


class WorkerSession:
    """Single worker session entry."""

    __slots__ = (
        "task_id", "session_id", "chat_id", "project_id", "card_id", "status", "model", "intent",
        "summary", "start_time", "end_time", "result_summary",
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
    ) -> None:
        """Update a session's status (completed, failed, timed_out, cancelled)."""
        session = self._sessions.get(task_id)
        if not session:
            return
        session.status = status
        session.end_time = time.time()
        if result_summary is not None:
            session.result_summary = result_summary[:500]
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

    def get_sessions_by_project(
        self,
        project_id: str,
        include_old: bool = False,
    ) -> list[dict]:
        """Get sessions filtered by project_id (stable across WS reconnects)."""
        self.check_timeouts()
        now = time.time()
        cutoff = now - RECENT_WINDOW_SECONDS
        results = []
        for session in self._sessions.values():
            if session.project_id != project_id:
                continue
            if not include_old and session.status != "running" and session.start_time < cutoff:
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

        Returns sessions from the last hour by default. Running sessions
        are always included regardless of age.
        """
        self.check_timeouts()
        now = time.time()
        cutoff = now - RECENT_WINDOW_SECONDS
        results = []

        for session in self._sessions.values():
            # Filter by session_id if provided
            if session_id and session.session_id != session_id:
                continue
            # Include running sessions always, others only if recent
            if not include_old and session.status != "running" and session.start_time < cutoff:
                continue
            results.append(session.to_dict())

        # Sort: running first, then by start_time descending
        results.sort(key=lambda s: (0 if s["status"] == "running" else 1, -s["start_time"]))
        return results

    def get_session(self, task_id: str) -> Optional[dict]:
        """Get a single session by task_id."""
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
        """Remove sessions older than max_age_seconds. Returns count removed."""
        cutoff = time.time() - max_age_seconds
        to_remove = [
            tid for tid, s in self._sessions.items()
            if s.status != "running" and s.start_time < cutoff
        ]
        for tid in to_remove:
            del self._sessions[tid]
            self._cleanup_file(tid)
        if to_remove:
            logger.info(f"[WorkerSessionStore] Cleaned up {len(to_remove)} old sessions")
        return len(to_remove)


# Global singleton
_store: Optional[WorkerSessionStore] = None


def get_worker_session_store() -> WorkerSessionStore:
    global _store
    if _store is None:
        _store = WorkerSessionStore()
    return _store
