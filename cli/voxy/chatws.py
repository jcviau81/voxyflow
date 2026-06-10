"""WebSocket chat: envelope construction + streaming runner.

Envelope format (server: ``backend/app/main.py`` general_websocket):
``{"type": ..., "payload": {...}, "timestamp": ms}``.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Callable, Optional

from .config import ws_url


def now_ms() -> int:
    return int(time.time() * 1000)


def build_session_sync(session_id: str) -> dict:
    return {
        "type": "session:sync",
        "payload": {"sessionId": session_id},
        "timestamp": now_ms(),
    }


def build_chat_envelope(
    content: str,
    session_id: str,
    message_id: str | None = None,
    workspace_id: str | None = None,
    card_id: str | None = None,
    deep: bool = False,
) -> dict:
    """Build a ``chat:message`` envelope as the web frontend sends it."""
    payload: dict[str, Any] = {
        "content": content,
        "messageId": message_id or str(uuid.uuid4()),
        "sessionId": session_id,
        "layers": {"deep": bool(deep)},
    }
    if workspace_id:
        payload["workspaceId"] = workspace_id
    if card_id:
        payload["cardId"] = card_id
    return {"type": "chat:message", "payload": payload, "timestamp": now_ms()}


class ChatTimeout(Exception):
    pass


class ChatError(Exception):
    pass


class ChatSession:
    """A persistent websocket chat session (used by one-shot and the REPL)."""

    def __init__(self, base_url: str, workspace_id: str | None = None,
                 timeout: float = 120.0):
        self.base_url = base_url
        self.workspace_id = workspace_id
        self.timeout = timeout
        self.session_id = str(uuid.uuid4())
        self._ws = None

    async def __aenter__(self) -> "ChatSession":
        await self.connect()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    async def connect(self) -> None:
        import websockets

        self._ws = await asyncio.wait_for(
            websockets.connect(ws_url(self.base_url), max_size=16 * 1024 * 1024),
            timeout=15.0,
        )
        # Sync the session before chatting; tolerate servers that don't ack.
        await self._ws.send(json.dumps(build_session_sync(self.session_id)))
        try:
            await self._wait_for({"session:sync:ack"}, timeout=10.0)
        except ChatTimeout:
            pass

    async def close(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _recv(self, timeout: float) -> dict:
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            raise ChatTimeout()
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return msg if isinstance(msg, dict) else {}

    async def _wait_for(self, types: set[str], timeout: float) -> dict:
        """Wait for one of the given message types, answering server pings."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChatTimeout()
            msg = await self._recv(remaining)
            mtype = msg.get("type")
            if mtype == "ping":
                await self._ws.send(json.dumps(
                    {"type": "pong", "payload": {}, "timestamp": now_ms()}))
                continue
            if mtype in types:
                return msg
            if mtype == "error":
                p = msg.get("payload", {}) or {}
                raise ChatError(p.get("message") or p.get("error") or "server error")

    async def send_and_stream(
        self,
        content: str,
        deep: bool = False,
        on_token: Optional[Callable[[str], None]] = None,
    ) -> str:
        """Send one message and stream the response. Returns the final content."""
        envelope = build_chat_envelope(
            content,
            session_id=self.session_id,
            workspace_id=self.workspace_id,
            deep=deep,
        )
        message_id = envelope["payload"]["messageId"]
        await self._ws.send(json.dumps(envelope))
        await self._wait_for({"message:ack"}, timeout=15.0)

        # The live backend streams `chat:response` events: token chunks in
        # payload["content"] with done=False, then a final done=True frame.
        # `chat:response:stream` / `chat:response:done` are accepted too for
        # forward compatibility.
        deadline = time.monotonic() + self.timeout
        streamed: list[str] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ChatTimeout()
            msg = await self._wait_for(
                {"chat:response", "chat:response:stream", "chat:response:done"},
                timeout=remaining,
            )
            payload = msg.get("payload", {}) or {}
            # Ignore frames for other in-flight messages (e.g. worker callbacks).
            other_id = payload.get("messageId")
            if other_id and other_id != message_id:
                continue
            mtype = msg["type"]
            if mtype == "chat:response":
                token = payload.get("content", "")
                if token and not payload.get("done"):
                    streamed.append(token)
                    if on_token:
                        on_token(token)
                if payload.get("done"):
                    return "".join(streamed)
            elif mtype == "chat:response:stream":
                token = payload.get("token", "")
                if token:
                    streamed.append(token)
                    if on_token:
                        on_token(token)
            else:  # chat:response:done
                return payload.get("content") or "".join(streamed)


async def chat_once(
    base_url: str,
    content: str,
    workspace_id: str | None = None,
    deep: bool = False,
    timeout: float = 120.0,
    on_token: Optional[Callable[[str], None]] = None,
) -> str:
    """One-shot: connect, sync, send, stream, return final content."""
    async with ChatSession(base_url, workspace_id=workspace_id, timeout=timeout) as session:
        return await session.send_and_stream(content, deep=deep, on_token=on_token)
