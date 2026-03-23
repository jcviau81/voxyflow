"""WebSocket broadcast — notify all connected clients when data changes."""

import asyncio
import json
import logging
import time
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSBroadcast:
    """Simple broadcast registry. Routes can emit events to all connected WS clients."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()

    def register(self, ws: WebSocket) -> None:
        self._connections.add(ws)

    def unregister(self, ws: WebSocket) -> None:
        self._connections.discard(ws)

    async def emit(self, event_type: str, payload: dict) -> None:
        """Send an event to all connected WebSocket clients."""
        message = {
            "type": event_type,
            "payload": payload,
            "timestamp": int(time.time() * 1000),
        }
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    def emit_sync(self, event_type: str, payload: dict) -> None:
        """Fire-and-forget emit from sync context (FastAPI route handlers)."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self.emit(event_type, payload))
            else:
                asyncio.run(self.emit(event_type, payload))
        except RuntimeError:
            pass  # No event loop available


ws_broadcast = WSBroadcast()
