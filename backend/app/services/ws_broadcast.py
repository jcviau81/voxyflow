"""WebSocket broadcast — notify all connected clients when data changes.

Two registries:

- ``_connections`` — every connected WS. Used for app-wide events (card
  changes, task:* worker events) broadcast to everyone.
- ``_chat_subs`` — chat_id → set[WebSocket]. Used to fan out streaming
  ``chat:response`` tokens to every device/tab viewing the same canonical
  chat. Devices opt-in by sending a ``chat:subscribe`` message (or auto-opt
  by sending a ``chat:message`` — the main WS handler subscribes on receipt).
"""

import asyncio
import json
import logging
import time
from typing import Optional, Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WSBroadcast:
    """Simple broadcast registry. Routes can emit events to all connected WS clients."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        # chat_id → set of WS currently viewing that chat
        self._chat_subs: dict[str, Set[WebSocket]] = {}
        # reverse index so unregister() can drop a WS from every chat in O(k)
        self._ws_chats: dict[WebSocket, Set[str]] = {}

    def register(self, ws: WebSocket) -> None:
        self._connections.add(ws)

    def unregister(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        # Drop this WS from every chat it was subscribed to.
        chats = self._ws_chats.pop(ws, set())
        for chat_id in chats:
            subs = self._chat_subs.get(chat_id)
            if subs is None:
                continue
            subs.discard(ws)
            if not subs:
                self._chat_subs.pop(chat_id, None)

    # ------------------------------------------------------------------
    # Chat-scoped fan-out — live cross-device streaming
    # ------------------------------------------------------------------

    def subscribe_chat(self, ws: WebSocket, chat_id: str) -> None:
        """Mark ``ws`` as viewing ``chat_id`` — it will receive broadcasts
        targeted at that chat. Idempotent.
        """
        if not chat_id:
            return
        self._chat_subs.setdefault(chat_id, set()).add(ws)
        self._ws_chats.setdefault(ws, set()).add(chat_id)

    def unsubscribe_chat(self, ws: WebSocket, chat_id: str) -> None:
        """Remove ``ws`` from a single chat subscription."""
        if not chat_id:
            return
        subs = self._chat_subs.get(chat_id)
        if subs is not None:
            subs.discard(ws)
            if not subs:
                self._chat_subs.pop(chat_id, None)
        chats = self._ws_chats.get(ws)
        if chats is not None:
            chats.discard(chat_id)
            if not chats:
                self._ws_chats.pop(ws, None)

    def get_ws_chats(self, ws: WebSocket) -> Set[str]:
        """Current chat subscriptions for a single WS (defensive copy)."""
        return set(self._ws_chats.get(ws, set()))

    async def emit_to_chat(
        self,
        chat_id: str,
        event_type: str,
        payload: dict,
        exclude: Optional[WebSocket] = None,
    ) -> int:
        """Send an event to every WS subscribed to ``chat_id`` (minus ``exclude``).

        Returns the number of clients that actually received the event.
        Silent when no other devices are watching — that's the common case
        for a single-device user and not worth logging.
        """
        if not chat_id:
            return 0
        subs = self._chat_subs.get(chat_id)
        if not subs:
            return 0
        message = {
            "type": event_type,
            "payload": payload,
            "timestamp": int(time.time() * 1000),
        }
        sent = 0
        dead: list[WebSocket] = []
        for ws in list(subs):
            if ws is exclude:
                continue
            try:
                await ws.send_json(message)
                sent += 1
            except (RuntimeError, ConnectionError, OSError) as exc:
                logger.debug(
                    "[WSBroadcast] drop dead socket on emit_to_chat(%s/%s): %s",
                    chat_id, event_type, exc,
                )
                dead.append(ws)
        for ws in dead:
            self.unregister(ws)
        return sent

    async def send_and_fanout_chat(
        self,
        ws: WebSocket,
        chat_id: str,
        event_type: str,
        payload: dict,
    ) -> None:
        """Send ``event_type`` to ``ws`` directly, then fan out to every other
        WS viewing ``chat_id``. The single call site used by streaming chat
        responses so the originator and every subscribed peer stay in sync.

        Swallows send failures on ``ws`` — caller typically does not want a
        dead client to break the whole streaming loop.
        """
        message = {
            "type": event_type,
            "payload": payload,
            "timestamp": int(time.time() * 1000),
        }
        try:
            await ws.send_json(message)
        except Exception as exc:
            logger.debug(
                "[WSBroadcast] send_and_fanout_chat direct-send failed (%s): %s",
                event_type, exc,
            )
        if chat_id:
            await self.emit_to_chat(chat_id, event_type, payload, exclude=ws)

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
            self.unregister(ws)

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
            self.unregister(ws)

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
