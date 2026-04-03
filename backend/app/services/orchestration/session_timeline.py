"""Session Timeline — chronological event ledger for dispatcher context.

Maintains a bounded FIFO of key events per session so the dispatcher always
has a clear picture of what happened, independent of the chat message window.
"""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal

MAX_ENTRIES = 20  # Per session — oldest entries evicted when full


EventType = Literal[
    "delegated", "completed", "failed", "cancelled",
    "inline", "direct",
]


class _TimelineEntry:
    __slots__ = ("ts", "event_type", "action", "task_id", "model", "summary")

    def __init__(
        self,
        event_type: EventType,
        action: str,
        task_id: str | None = None,
        model: str | None = None,
        summary: str = "",
    ):
        self.ts = time.time()
        self.event_type = event_type
        self.action = action
        self.task_id = task_id
        self.model = model
        self.summary = summary[:120]  # Keep summaries compact

    def format(self) -> str:
        t = datetime.fromtimestamp(self.ts, tz=timezone.utc).strftime("%H:%M")
        tag = self.event_type.upper()
        tid = f" task-{self.task_id[:8]}" if self.task_id else ""
        mdl = f" ({self.model})" if self.model else ""
        detail = f" — {self.summary}" if self.summary else ""
        return f"[{t}] {tag} {self.action}{tid}{mdl}{detail}"


class SessionTimeline:
    """Per-session event ledger. Thread-safe for single-threaded asyncio."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[_TimelineEntry]] = defaultdict(list)

    def record(
        self,
        session_id: str,
        event_type: EventType,
        action: str,
        task_id: str | None = None,
        model: str | None = None,
        summary: str = "",
    ) -> None:
        """Append an event to the session timeline."""
        entries = self._sessions[session_id]
        entries.append(_TimelineEntry(
            event_type=event_type,
            action=action,
            task_id=task_id,
            model=model,
            summary=summary,
        ))
        # FIFO eviction
        if len(entries) > MAX_ENTRIES:
            self._sessions[session_id] = entries[-MAX_ENTRIES:]

    def format(self, session_id: str) -> str:
        """Return the timeline as a compact text block for system prompt injection."""
        entries = self._sessions.get(session_id)
        if not entries:
            return ""
        lines = [e.format() for e in entries]
        return "\n".join(lines)

    def clear(self, session_id: str) -> None:
        """Clear timeline for a session."""
        self._sessions.pop(session_id, None)


# Module-level singleton
_timeline = SessionTimeline()


def get_timeline() -> SessionTimeline:
    return _timeline
