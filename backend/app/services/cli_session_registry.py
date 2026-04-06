"""CliSessionRegistry — tracks active `claude -p` subprocesses.

Singleton, asyncio-safe (single event loop). Every CLI subprocess is
registered on spawn and deregistered on completion or forced kill.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional
from uuid import uuid4

logger = logging.getLogger("voxyflow.cli_sessions")


@dataclass
class CliSession:
    id: str
    pid: int
    session_id: str
    chat_id: str
    project_id: Optional[str]
    model: str
    session_type: str  # "chat" | "worker"
    started_at: float
    cancel_event: asyncio.Event
    _process: asyncio.subprocess.Process = field(repr=False)
    task_id: str = ""           # Voxyflow task_id (for steering lookup)
    steer_queue: Optional[asyncio.Queue] = field(default=None, repr=False)  # Steering message queue
    last_activity: float = 0.0  # Updated on each message (for inactivity timeout)


class CliSessionRegistry:
    """In-memory registry of active CLI subprocesses."""

    _instance: Optional[CliSessionRegistry] = None

    def __new__(cls) -> CliSessionRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._sessions: dict[str, CliSession] = {}
        return cls._instance

    def register(self, session: CliSession) -> None:
        self._sessions[session.id] = session
        logger.info(
            f"[CliRegistry] Registered {session.session_type} session {session.id} "
            f"(pid={session.pid}, model={session.model}, chat={session.chat_id})"
        )
        # Broadcast to all WS clients
        from app.services.ws_broadcast import ws_broadcast
        ws_broadcast.emit_sync("cli:session:started", {
            "id": session.id,
            "pid": session.pid,
            "chatId": session.chat_id,
            "projectId": session.project_id,
            "model": session.model,
            "type": session.session_type,
            "startedAt": session.started_at,
            "taskId": session.task_id,
        })

    def deregister(self, session_id: str) -> None:
        removed = self._sessions.pop(session_id, None)
        if removed:
            logger.info(f"[CliRegistry] Deregistered session {session_id} (pid={removed.pid})")
            # Broadcast to all WS clients
            from app.services.ws_broadcast import ws_broadcast
            ws_broadcast.emit_sync("cli:session:ended", {
                "id": removed.id,
                "pid": removed.pid,
                "chatId": removed.chat_id,
                "projectId": removed.project_id,
                "taskId": removed.task_id,
            })

    def list_active(self) -> list[CliSession]:
        return list(self._sessions.values())

    def get(self, session_id: str) -> Optional[CliSession]:
        return self._sessions.get(session_id)

    def get_by_task_id(self, task_id: str) -> Optional[CliSession]:
        """Find an active CLI session by Voxyflow task_id."""
        for session in self._sessions.values():
            if session.task_id == task_id:
                return session
        return None

    def count(self) -> int:
        return len(self._sessions)

    async def kill(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if not session:
            return False

        logger.info(f"[CliRegistry] Killing session {session_id} (pid={session.pid})")

        # Signal via cancel_event (existing _watch_cancel pattern will SIGTERM)
        session.cancel_event.set()

        # Also terminate directly in case cancel_event watcher isn't running
        try:
            session._process.terminate()
            await asyncio.sleep(2)
            if session._process.returncode is None:
                session._process.kill()
        except ProcessLookupError:
            pass

        self.deregister(session_id)
        return True

    async def kill_all(self) -> int:
        count = 0
        for sid in list(self._sessions.keys()):
            if await self.kill(sid):
                count += 1
        return count

    async def steer(self, session_id: str, message: str) -> bool:
        """Inject a steering message into an active CLI subprocess via its steer_queue.

        Returns True if the session exists and the message was queued.
        The steer_queue is consumed by the subprocess watcher in ClaudeCliBackend.
        """
        session = self._sessions.get(session_id)
        if not session:
            return False
        if session.steer_queue is None:
            logger.warning(f"[CliRegistry] steer: session {session_id} has no steer_queue (not a steerable worker)")
            return False
        await session.steer_queue.put(message)
        logger.info(f"[CliRegistry] Steering message queued for session {session_id} (pid={session.pid}): {message[:80]}")
        return True

    def get_by_chat_id(self, chat_id: str) -> Optional[CliSession]:
        """Find an active CLI session by chat_id (e.g. 'project:xyz')."""
        for session in self._sessions.values():
            if session.chat_id == chat_id:
                return session
        return None

    async def kill_by_chat_id(self, chat_id: str) -> bool:
        """Kill an active CLI session by chat_id."""
        session = self.get_by_chat_id(chat_id)
        if session:
            return await self.kill(session.id)
        return False

    async def cleanup_inactive(self, max_idle_seconds: float = 1800) -> int:
        """Kill sessions idle for more than max_idle_seconds. Returns count killed."""
        now = time.time()
        to_kill = [
            s.id for s in self._sessions.values()
            if s.last_activity > 0 and (now - s.last_activity) > max_idle_seconds
        ]
        count = 0
        for sid in to_kill:
            if await self.kill(sid):
                logger.info(f"[CliRegistry] Killed inactive session {sid} (idle > {max_idle_seconds}s)")
                count += 1
        return count

    def touch(self, session_id: str) -> None:
        """Update last_activity timestamp for a session."""
        session = self._sessions.get(session_id)
        if session:
            session.last_activity = time.time()

    def find_by_task_session(self, task_chat_id: str) -> Optional[CliSession]:
        """Find an active session by its chat_id (e.g. 'task-<task_id>')."""
        for s in self._sessions.values():
            if s.chat_id == task_chat_id:
                return s
        return None


def new_cli_session_id() -> str:
    return f"cli-{uuid4().hex[:8]}"


def get_cli_session_registry() -> CliSessionRegistry:
    return CliSessionRegistry()
