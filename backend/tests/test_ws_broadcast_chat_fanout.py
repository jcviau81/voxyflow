"""Regression tests for chat-scoped WS broadcast fan-out.

Locks the invariant that streaming `chat:response` tokens (and any chat-
scoped event) reach every WebSocket viewing the same canonical chat_id,
but NOT sockets subscribed to other chats or unsubscribed sockets.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.services.ws_broadcast import WSBroadcast


class FakeWS:
    """Minimal async WS stub capturing send_json calls."""

    def __init__(self, name: str = ""):
        self.name = name
        self.sent: list[dict[str, Any]] = []
        self.fail = False

    async def send_json(self, msg: dict[str, Any]) -> None:
        if self.fail:
            raise ConnectionError("simulated dead socket")
        self.sent.append(msg)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_subscribe_chat_delivers_to_subscribed_sockets_only():
    bus = WSBroadcast()
    a = FakeWS("a")
    b = FakeWS("b")
    c = FakeWS("c")
    bus.register(a); bus.register(b); bus.register(c)

    bus.subscribe_chat(a, "project:42")
    bus.subscribe_chat(b, "project:42")
    bus.subscribe_chat(c, "project:99")

    sent = _run(bus.emit_to_chat("project:42", "chat:response", {"content": "hi"}))
    assert sent == 2
    assert len(a.sent) == 1 and len(b.sent) == 1
    assert c.sent == []  # different chat


def test_emit_to_chat_respects_exclude():
    bus = WSBroadcast()
    a = FakeWS("a"); b = FakeWS("b")
    bus.register(a); bus.register(b)
    bus.subscribe_chat(a, "project:1"); bus.subscribe_chat(b, "project:1")

    sent = _run(bus.emit_to_chat("project:1", "chat:response", {"x": 1}, exclude=a))
    assert sent == 1
    assert a.sent == []
    assert len(b.sent) == 1


def test_send_and_fanout_chat_sends_to_originator_and_peers():
    bus = WSBroadcast()
    a = FakeWS("a"); b = FakeWS("b"); c = FakeWS("c")
    bus.register(a); bus.register(b); bus.register(c)
    # b and c are subscribed; a is the originator (and also subscribed)
    for ws in (a, b, c):
        bus.subscribe_chat(ws, "card:X")

    _run(bus.send_and_fanout_chat(a, "card:X", "chat:response", {"t": "tok"}))
    assert len(a.sent) == 1, "originator must receive its own event"
    assert len(b.sent) == 1 and len(c.sent) == 1, "peers must receive the fan-out"


def test_unregister_drops_all_chat_subscriptions():
    bus = WSBroadcast()
    a = FakeWS("a"); b = FakeWS("b")
    bus.register(a); bus.register(b)
    bus.subscribe_chat(a, "project:1")
    bus.subscribe_chat(a, "project:2")
    bus.subscribe_chat(b, "project:1")

    bus.unregister(a)
    # a should be gone from both chats; b still in project:1
    sent1 = _run(bus.emit_to_chat("project:1", "x", {}))
    sent2 = _run(bus.emit_to_chat("project:2", "x", {}))
    assert sent1 == 1  # only b
    assert sent2 == 0  # nobody left
    assert bus.get_ws_chats(a) == set()


def test_dead_socket_is_pruned_on_emit():
    bus = WSBroadcast()
    good = FakeWS("good")
    dead = FakeWS("dead"); dead.fail = True
    bus.register(good); bus.register(dead)
    bus.subscribe_chat(good, "chat:1"); bus.subscribe_chat(dead, "chat:1")

    sent = _run(bus.emit_to_chat("chat:1", "evt", {}))
    # dead got pruned; good still received
    assert sent == 1
    assert bus.get_ws_chats(dead) == set()
    # second emit should see only `good`
    sent2 = _run(bus.emit_to_chat("chat:1", "evt", {}))
    assert sent2 == 1


def test_empty_chat_id_is_noop():
    bus = WSBroadcast()
    a = FakeWS("a"); bus.register(a)
    # subscribing with empty chat_id silently does nothing
    bus.subscribe_chat(a, "")
    assert bus.get_ws_chats(a) == set()
    sent = _run(bus.emit_to_chat("", "evt", {}))
    assert sent == 0


def test_subscribe_is_idempotent():
    bus = WSBroadcast()
    a = FakeWS("a"); bus.register(a)
    bus.subscribe_chat(a, "chat:dup")
    bus.subscribe_chat(a, "chat:dup")
    bus.subscribe_chat(a, "chat:dup")
    sent = _run(bus.emit_to_chat("chat:dup", "evt", {}))
    assert sent == 1  # a receives once, not thrice


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
