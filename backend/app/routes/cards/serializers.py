"""Shared serializers / helpers for card routes."""

import json
import logging
from pathlib import Path

from app.database import Card
from app.models.card import CardResponse, ChecklistProgress
from app.services.ws_broadcast import ws_broadcast

logger = logging.getLogger(__name__)

MAX_ATTACHMENT_SIZE = 50 * 1024 * 1024  # 50 MB

ATTACHMENTS_BASE = Path.home() / ".voxyflow" / "attachments"


def _broadcast_card_change(card):
    """Notify all WS clients that a card changed."""
    workspace_id = getattr(card, 'workspace_id', None) or 'system-main'
    ws_broadcast.emit_sync("cards:changed", {"workspaceId": workspace_id, "cardId": card.id})


def _card_to_response(card: Card) -> CardResponse:
    """Convert ORM Card to response, extracting dependency IDs, summing time, and computing checklist progress."""
    total_minutes = sum(e.duration_minutes for e in card.time_entries) if card.time_entries else 0
    checklist_total = len(card.checklist_items) if card.checklist_items else 0
    checklist_completed = sum(1 for i in card.checklist_items if i.completed) if card.checklist_items else 0
    checklist_progress = ChecklistProgress(total=checklist_total, completed=checklist_completed) if checklist_total > 0 else None
    return CardResponse(
        id=card.id,
        workspace_id=card.workspace_id,
        title=card.title,
        description=card.description,
        status=card.status,
        priority=card.priority,
        position=card.position,
        source_message_id=card.source_message_id,
        auto_generated=card.auto_generated,
        agent_assigned=card.agent_assigned,
        agent_type=card.agent_type,
        agent_context=card.agent_context,
        color=card.color,
        created_at=card.created_at,
        updated_at=card.updated_at,
        dependency_ids=[d.id for d in card.dependencies] if card.dependencies else [],
        total_minutes=total_minutes,
        checklist_progress=checklist_progress,
        assignee=card.assignee,
        watchers=card.watchers or "",
        votes=card.votes or 0,
        preferred_model=card.preferred_model,
        recurring=card.recurring or False,
        recurrence=card.recurrence,
        recurrence_next=card.recurrence_next,
        files=json.loads(card.files) if card.files else [],
        archived_at=card.archived_at,
    )
