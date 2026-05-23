"""Canonical chat_id derivation — shared logic for WS and REST entry points.

CLAUDE.md §Workspace Isolation §4: chat_id is server-canonical, not client-trusted.
Frontend-supplied chatId is accepted only when it matches the canonical id derived
from server-side workspace_id/card_id, or starts with ``canonical + ":"`` (sub-sessions).

This helper exists so the rule lives in exactly one place.
"""

from __future__ import annotations

import logging
from typing import Tuple

from app.database import SYSTEM_MAIN_WORKSPACE_ID

logger = logging.getLogger("voxyflow.chat_id")


def canonical_chat_id(workspace_id: str | None, card_id: str | None) -> str:
    """Return the canonical chat_id for a (workspace_id, card_id) context.

    Card chats win over workspace chats. Missing context falls back to the
    system-main general chat.
    """
    if card_id:
        return f"card:{card_id}"
    if workspace_id:
        return f"workspace:{workspace_id}"
    return f"workspace:{SYSTEM_MAIN_WORKSPACE_ID}"


def resolve_chat_id(
    workspace_id: str | None,
    card_id: str | None,
    frontend_chat_id: str | None,
    *,
    log_context: str = "",
) -> Tuple[str, str, bool]:
    """Canonicalize a chat_id, validating any frontend-supplied value.

    Returns ``(chat_id, canonical, rejected)``:
      * ``chat_id`` — the value to use (frontend's if valid, canonical otherwise)
      * ``canonical`` — the server-derived canonical id
      * ``rejected`` — True if a frontend-supplied id was overridden
    """
    canonical = canonical_chat_id(workspace_id, card_id)
    if not frontend_chat_id:
        return canonical, canonical, False
    if frontend_chat_id == canonical or frontend_chat_id.startswith(canonical + ":"):
        return frontend_chat_id, canonical, False
    if log_context:
        logger.warning(
            f"[{log_context}] Rejected mismatched chatId={frontend_chat_id!r} for "
            f"workspace_id={workspace_id!r} card_id={card_id!r} — "
            f"using canonical {canonical!r} instead"
        )
    return canonical, canonical, True
