"""Card lifecycle + worker-ledger DB helpers (system-managed).

Free functions — they only touch the DB + ws_broadcast, no pool state beyond
logging. Extracted verbatim from worker_pool.py.
"""

from __future__ import annotations

import logging

from app.services.event_bus import ActionIntent
from app.services.orchestration.result_formatting import _make_short_title

logger = logging.getLogger("voxyflow.orchestration")

# Trivial delegate intents that should never produce a tracking card,
# even when no worker class matched. These are housekeeping verbs — the
# state change itself is the result, there is no "work in progress" to
# represent as a card.
_TRIVIAL_INTENTS = frozenset({
    "archive", "archive_card", "archive_cards",
    "unarchive", "restore", "restore_card",
    "delete", "delete_card", "remove",
    "move", "move_card", "reorder", "reorder_cards",
    "rename", "rename_card",
    "tag", "untag",
    "assign", "unassign", "reassign",
    "duplicate",
})


def _should_auto_create_card(event: ActionIntent, worker_class: dict | None) -> bool:
    """Decide whether a delegated task deserves its own tracking card.

    Signals, in order:
      1. ``worker_class.name == "Quick"`` → no card (lightweight one-shot).
      2. Intent verb in :data:`_TRIVIAL_INTENTS` → no card (housekeeping).
      3. No worker class matched + ``complexity == "simple"`` → no card.
      4. Otherwise → create a card (Coding / Research / Creative, or
         anything non-trivial).
    """
    wc_name = ((worker_class or {}).get("name") or "").strip().lower()
    if wc_name == "quick":
        return False

    intent = (event.intent or "").strip().lower()
    if intent in _TRIVIAL_INTENTS:
        return False

    complexity = (event.complexity or "").strip().lower()
    if not wc_name and complexity == "simple":
        return False

    return True


async def _auto_create_card(
    workspace_id: str | None,
    intent: str,
    summary: str,
) -> str | None:
    """Auto-create a card for a worker task when no card_id was provided.

    Returns the new card_id, or None if creation fails.
    """
    try:
        from app.database import async_session, Card, CardHistory, new_uuid, utcnow, SYSTEM_MAIN_WORKSPACE_ID
        from app.services.agent_router import get_agent_router
        from app.services.agent_personas import AgentType, get_persona
        from app.services.ws_broadcast import ws_broadcast

        effective_workspace_id = workspace_id or SYSTEM_MAIN_WORKSPACE_ID

        # Auto-route agent type from intent/summary
        router = get_agent_router()
        detected_type, _confidence = router.route(title=intent, description=summary)
        agent_type = detected_type.value
        persona = get_persona(AgentType(agent_type))
        agent_display = f"{persona.emoji} {persona.name}"

        # Build a short title and a full description.
        # intent = action name or full directive; summary = description/instruction
        full_text = summary or intent
        short_title = _make_short_title(intent, summary)

        card_id = new_uuid()
        async with async_session() as db:
            card = Card(
                id=card_id,
                workspace_id=effective_workspace_id,
                title=short_title,
                description=full_text[:2000] if full_text else "",
                status="todo",
                auto_generated=True,
                agent_type=agent_type,
                agent_assigned=agent_display,
            )
            db.add(card)
            db.add(CardHistory(
                id=new_uuid(),
                card_id=card_id,
                field_changed="status",
                old_value=None,
                new_value="todo",
                changed_at=utcnow(),
                changed_by="System",
            ))
            await db.commit()

        ws_broadcast.emit_sync("cards:changed", {
            "workspaceId": effective_workspace_id,
            "cardId": card_id,
        })
        logger.info(f"[CardLifecycle] Auto-created card {card_id} for \"{intent[:60]}\"")
        return card_id
    except Exception as e:
        logger.warning(f"[CardLifecycle] Failed to auto-create card: {e}")
        return None


async def _update_card_status(
    card_id: str,
    new_status: str,
    workspace_id: str | None = None,
) -> None:
    """Move a card to a new status with CardHistory tracking.

    Guards against backward transitions from 'done' or 'archived'.
    No-ops if the card is already at the target status.
    """
    try:
        from app.database import async_session, Card, CardHistory, new_uuid, utcnow
        from sqlalchemy import select
        from app.services.ws_broadcast import ws_broadcast

        async with async_session() as db:
            result = await db.execute(select(Card).where(Card.id == card_id))
            card = result.scalar_one_or_none()
            if not card:
                logger.warning(f"[CardLifecycle] Card {card_id} not found for status update")
                return

            old_status = card.status
            logger.info(f"[CardLifecycle] Card {card_id}: current={old_status}, target={new_status}")
            if old_status == new_status:
                logger.info(f"[CardLifecycle] Card {card_id}: already at {new_status}, skipping")
                return
            if old_status in ("done", "archived"):
                logger.info(
                    f"[CardLifecycle] Skipping {old_status} -> {new_status} "
                    f"for card {card_id} (no backward transitions)"
                )
                return

            card.status = new_status
            card.updated_at = utcnow()
            db.add(CardHistory(
                id=new_uuid(),
                card_id=card_id,
                field_changed="status",
                old_value=old_status,
                new_value=new_status,
                changed_at=utcnow(),
                changed_by="System",
            ))
            await db.commit()

        _effective_workspace_id = workspace_id or "system-main"
        ws_broadcast.emit_sync("cards:changed", {
            "workspaceId": _effective_workspace_id,
            "cardId": card_id,
        })
        logger.info(f"[CardLifecycle] Card {card_id}: {old_status} -> {new_status}")
    except Exception as e:
        logger.warning(f"[CardLifecycle] Failed to update card {card_id} status: {e}")


# ------------------------------------------------------------------
# Worker Ledger DB helpers
# ------------------------------------------------------------------


async def _ledger_insert(
    task_id: str,
    session_id: str,
    workspace_id: str | None,
    action: str,
    description: str,
    model: str,
    card_id: str | None = None,
) -> None:
    """Insert a new row into worker_tasks with status='running'."""
    try:
        from app.database import async_session, WorkerTask, utcnow
        async with async_session() as db:
            row = WorkerTask(
                id=task_id,
                session_id=session_id,
                workspace_id=workspace_id,
                card_id=card_id,
                action=action,
                description=description[:500],
                model=model,
                status="running",
                started_at=utcnow(),
                created_at=utcnow(),
            )
            db.add(row)
            await db.commit()
            logger.debug(f"[Ledger] Inserted task {task_id} status=running")
    except Exception as e:
        logger.warning(f"[Ledger] Failed to insert task {task_id}: {e}")


async def _ledger_update(
    task_id: str,
    status: str,
    result_summary: str | None = None,
    error: str | None = None,
) -> None:
    """Update a worker_tasks row with final status."""
    try:
        from app.database import async_session, WorkerTask, utcnow
        from sqlalchemy import select
        async with async_session() as db:
            result = await db.execute(
                select(WorkerTask).where(WorkerTask.id == task_id)
            )
            row = result.scalar_one_or_none()
            if row:
                row.status = status
                if result_summary is not None:
                    row.result_summary = result_summary
                if error is not None:
                    row.error = error
                if status in ("done", "failed", "cancelled", "timed_out"):
                    row.completed_at = utcnow()
                await db.commit()
                logger.debug(f"[Ledger] Updated task {task_id} → {status}")
    except Exception as e:
        logger.warning(f"[Ledger] Failed to update task {task_id}: {e}")
