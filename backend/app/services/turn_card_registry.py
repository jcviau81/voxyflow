"""Per-chat registry of cards created during the current dispatcher turn.

Solves the "ghost card" bug: when Voxy creates a card via an MCP tool and
then emits a ``<delegate>`` in the same turn, the orchestrator has no way
to link the delegate back to the card just created. Without that link,
:func:`DeepWorkerPool._auto_create_card` fires and fabricates a duplicate
card from the delegate text.

Flow:
  1. MCP handlers call the REST API with an ``X-Voxyflow-Chat-Id`` header.
  2. Card-create routes record the new ``card_id`` here keyed by chat_id.
  3. ``_parse_and_emit_delegates`` pops one entry per delegate that lacks
     a ``card_id`` (FIFO — match in creation order).

Entries are capped and expire quickly so a stale entry from a previous
turn can't accidentally steer a later, unrelated delegate.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Deque

TTL_SECONDS = 120
MAX_PER_CHAT = 20


_lock = threading.Lock()
_entries: dict[str, Deque[tuple[float, str]]] = {}


def _prune(q: Deque[tuple[float, str]]) -> None:
    now = time.time()
    while q and now - q[0][0] > TTL_SECONDS:
        q.popleft()


def record_created_card(chat_id: str, card_id: str) -> None:
    if not chat_id or not card_id:
        return
    with _lock:
        q = _entries.setdefault(chat_id, deque(maxlen=MAX_PER_CHAT))
        _prune(q)
        q.append((time.time(), card_id))


def pop_created_card(chat_id: str) -> str | None:
    if not chat_id:
        return None
    with _lock:
        q = _entries.get(chat_id)
        if not q:
            return None
        _prune(q)
        if not q:
            return None
        _, card_id = q.popleft()
        return card_id


def clear(chat_id: str) -> None:
    with _lock:
        _entries.pop(chat_id, None)
