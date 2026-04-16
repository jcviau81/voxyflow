"""Async Event Bus — Per-session event routing for Fast→Deep communication.

Each WebSocket session gets its own SessionEventBus with an asyncio.Queue.
The Fast layer emits ActionIntent events; Deep workers consume them.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

logger = logging.getLogger("voxyflow.event_bus")


@dataclass
class ActionIntent:
    """An action detected by the Fast layer, to be executed by a Deep worker."""
    task_id: str
    intent_type: str        # "crud_simple", "complex", "research"
    intent: str             # "create_card", "run_command", etc.
    summary: str
    data: dict = field(default_factory=dict)
    session_id: str = ""
    complexity: str = "simple"  # "simple" | "complex"
    model: str = "sonnet"  # "haiku" | "sonnet" | "opus" — overridden at emit site
    callback_depth: int = 0  # 0 = normal, 1+ = spawned from callback (max auto-callback depth = 1)


class SessionEventBus:
    """Per-session async event bus for Fast→Deep communication."""

    # Sentinel object to signal the listener to stop
    _POISON = object()

    # Hard cap per-session queue so a runaway emitter (or a dead consumer)
    # cannot grow memory without bound. Overflow drops the oldest event.
    _QUEUE_MAXSIZE = 1000

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=self._QUEUE_MAXSIZE)
        self._closed = False
        self.last_activity: float = time.monotonic()
        logger.debug(f"[EventBus] Created bus for session {session_id}")

    async def emit(self, event: ActionIntent) -> None:
        """Emit an event onto the bus. Drops the oldest event if full."""
        if self._closed:
            logger.warning(f"[EventBus] Attempted emit on closed bus {self.session_id}")
            return
        self.last_activity = time.monotonic()
        logger.info(f"[EventBus] Emit: task_id={event.task_id} intent={event.intent} complexity={event.complexity}")
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                dropped = self.queue.get_nowait()
                logger.warning(
                    f"[EventBus] Queue full for {self.session_id} — "
                    f"dropped oldest event task_id={getattr(dropped, 'task_id', '?')}"
                )
            except asyncio.QueueEmpty:
                pass
            await self.queue.put(event)

    async def listen(self) -> AsyncIterator[ActionIntent]:
        """Async generator that yields events as they arrive."""
        while True:
            try:
                event = await self.queue.get()
                if event is self._POISON:
                    break
                yield event
            except asyncio.CancelledError:
                break

    def close(self) -> None:
        """Mark bus as closed and unblock any waiting listener."""
        self._closed = True
        self.queue.put_nowait(self._POISON)
        logger.debug(f"[EventBus] Closed bus for session {self.session_id}")

    @property
    def pending_count(self) -> int:
        return self.queue.qsize()


class EventBusRegistry:
    """Global registry of per-session event buses."""

    def __init__(self):
        self._buses: dict[str, SessionEventBus] = {}

    def get_or_create(self, session_id: str) -> SessionEventBus:
        """Get existing bus or create a new one for this session."""
        if session_id not in self._buses:
            self._buses[session_id] = SessionEventBus(session_id)
        return self._buses[session_id]

    def get(self, session_id: str) -> SessionEventBus | None:
        """Get bus if it exists."""
        return self._buses.get(session_id)

    def remove(self, session_id: str) -> None:
        """Remove and close a session's bus."""
        bus = self._buses.pop(session_id, None)
        if bus:
            bus.close()

    def active_sessions(self) -> list[str]:
        """List all sessions with active buses."""
        return list(self._buses.keys())

    def cleanup_idle(self, max_idle_seconds: float = 3600) -> int:
        """Remove buses that have been idle (no emits) for longer than max_idle_seconds.

        Returns the number of buses cleaned up.
        """
        now = time.monotonic()
        stale = [
            sid for sid, bus in self._buses.items()
            if (now - bus.last_activity) > max_idle_seconds and bus.pending_count == 0
        ]
        for sid in stale:
            self.remove(sid)
        if stale:
            logger.info(f"[EventBus] Cleaned up {len(stale)} idle bus(es): {stale}")
        return len(stale)


# Global singleton
event_bus_registry = EventBusRegistry()
