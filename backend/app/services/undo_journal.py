"""Per-chat undo journal for reversible MCP actions.

After a successful MCP call, the dispatch layer (:mod:`app.mcp_server`) may
record an *inverse* here — an unexecuted tool call that reverts the effect.
Entries are keyed by the current dispatcher chat id (``VOXYFLOW_CHAT_ID``),
capped in count, and expired after :data:`TTL_SECONDS`.

Deliberately scoped: only a handful of tools have safe inverses wired up
(card create/archive/duplicate, memory.save). The rest are no-ops — better
to skip than to record something we can't cleanly replay.
"""
from __future__ import annotations

import time
import uuid
from collections import deque
from dataclasses import dataclass
from typing import Optional


TTL_SECONDS = 30 * 60
MAX_PER_CHAT = 20


@dataclass
class UndoEntry:
    id: str
    chat_id: str
    created_at: float
    label: str
    forward_tool: str
    forward_args: dict
    inverse_tool: str
    inverse_args: dict


_journals: dict[str, deque[UndoEntry]] = {}


def _prune(q: deque[UndoEntry]) -> None:
    now = time.time()
    while q and now - q[0].created_at > TTL_SECONDS:
        q.popleft()


def record(
    chat_id: str,
    label: str,
    forward_tool: str,
    forward_args: dict,
    inverse_tool: str,
    inverse_args: dict,
) -> Optional[UndoEntry]:
    if not chat_id:
        return None
    q = _journals.setdefault(chat_id, deque(maxlen=MAX_PER_CHAT))
    _prune(q)
    entry = UndoEntry(
        id=uuid.uuid4().hex[:12],
        chat_id=chat_id,
        created_at=time.time(),
        label=label,
        forward_tool=forward_tool,
        forward_args=dict(forward_args or {}),
        inverse_tool=inverse_tool,
        inverse_args=dict(inverse_args or {}),
    )
    q.append(entry)
    return entry


def list_entries(chat_id: str, limit: int = 5) -> list[UndoEntry]:
    q = _journals.get(chat_id)
    if not q:
        return []
    _prune(q)
    return list(q)[-limit:][::-1]


def pop_by_id(chat_id: str, entry_id: Optional[str]) -> Optional[UndoEntry]:
    q = _journals.get(chat_id)
    if not q:
        return None
    _prune(q)
    if not q:
        return None
    if entry_id is None:
        return q.pop()
    for i, e in enumerate(q):
        if e.id == entry_id:
            del q[i]
            return e
    return None


# ---------------------------------------------------------------------------
# Inverse derivation — which successful calls are worth journaling.
# ---------------------------------------------------------------------------

def derive_inverse(
    tool_name: str,
    params: dict,
    result: dict,
) -> Optional[tuple[str, dict, str]]:
    """Return (inverse_tool, inverse_args, label) or None if not reversible.

    Keep this list small and obviously-safe. Better to skip a journal entry
    than to record an inverse that would mis-fire.
    """
    if tool_name in (
        "voxyflow.card.create",
        "voxyflow.card.create_unassigned",
        "voxyflow.card.duplicate",
    ):
        card_id = (result or {}).get("id")
        if not card_id:
            return None
        title = (params or {}).get("title") or (result or {}).get("title") or card_id
        return (
            "voxyflow.card.archive",
            {"card_id": card_id},
            f"archive newly-created card ({title[:40]})",
        )
    if tool_name == "voxyflow.card.archive":
        card_id = (params or {}).get("card_id")
        if not card_id:
            return None
        return (
            "voxyflow.card.restore",
            {"card_id": card_id},
            f"restore card {str(card_id)[:8]}",
        )
    if tool_name == "memory.save":
        doc_id = (result or {}).get("id")
        if not doc_id:
            return None
        inv_args: dict = {"id": doc_id}
        col = (result or {}).get("collection")
        if col:
            inv_args["collection"] = col
        return (
            "memory.delete",
            inv_args,
            f"delete memory {doc_id}",
        )
    return None
