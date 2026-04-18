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
        for ws in list(self._connections):
            try:
                await ws.send_json(message)
            except (RuntimeError, ConnectionError, OSError) as exc:
                logger.debug("[WSBroadcast] drop dead socket on emit(%s): %s", event_type, exc)
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    async def emit_to_others(self, exclude: WebSocket, event_type: str, payload: dict) -> None:
        """Send an event to all connected WebSocket clients EXCEPT the sender.

        Used for cross-device sync: the originating device already has the data,
        so we only forward to other connected clients (other devices/tabs).
        """
        message = {
            "type": event_type,
            "payload": payload,
            "timestamp": int(time.time() * 1000),
        }
        dead: list[WebSocket] = []
        sent_count = 0
        for ws in list(self._connections):
            if ws is exclude:
                continue
            try:
                await ws.send_json(message)
                sent_count += 1
            except (RuntimeError, ConnectionError, OSError) as exc:
                logger.debug("[WSBroadcast] drop dead socket on emit_to_others(%s): %s", event_type, exc)
                dead.append(ws)
        if sent_count > 0:
            logger.info(f"[WSBroadcast] emit_to_others: {event_type} → {sent_count} client(s)")
        elif len(self._connections) <= 1:
            logger.debug(f"[WSBroadcast] emit_to_others: {event_type} — no other clients connected")
        for ws in dead:
            self._connections.discard(ws)

    def emit_sync(self, event_type: str, payload: dict) -> None:
        """Fire-and-forget emit from the running event loop.

        Callers are sync helpers inside async code (job handlers, MCP
        handlers that use ``asyncio.to_thread``). Dropping silently when
        no loop is running is fine — the prior ``asyncio.run()`` fallback
        blocked the caller for the length of the broadcast and risked
        spawning a second loop alongside FastAPI's.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.debug(f"[WSBroadcast] emit_sync: no running loop, dropping event {event_type}")
            return
        loop.create_task(self.emit(event_type, payload))


ws_broadcast = WSBroadcast()
