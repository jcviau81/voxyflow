"""Board Executor — sequential execution of all cards on a Kanban board.

Builds an execution plan from todo/in-progress cards, then executes each card
sequentially through the chat orchestration pipeline, chaining context between
cards so each one knows what came before.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.database import Card, Project, async_session
from app.models.enums import CardStatus

logger = logging.getLogger("voxyflow.board_executor")

# Column priority for execution ordering
COLUMN_PRIORITY = {CardStatus.TODO: 1, CardStatus.IN_PROGRESS: 2}


@dataclass
class CardPlan:
    id: str
    title: str
    status: str
    position: int


@dataclass
class ExecutionPlan:
    execution_id: str
    project_id: str
    cards: list[CardPlan]
    total: int


@dataclass
class BoardExecution:
    execution_id: str
    project_id: str
    cards: list[CardPlan]
    current_index: int = 0
    cancelled: bool = False
    chain_context: list[str] = field(default_factory=list)


# In-memory registry of active executions
_active_executions: dict[str, BoardExecution] = {}


async def build_execution_plan(
    project_id: str,
    statuses: list[str] | None = None,
) -> ExecutionPlan:
    """Query cards for a project and build an ordered execution plan."""
    if statuses is None:
        statuses = [CardStatus.TODO, CardStatus.IN_PROGRESS]

    async with async_session() as db:
        stmt = (
            select(Card)
            .where(Card.project_id == project_id, Card.status.in_(statuses))
            .order_by(Card.position)
        )
        result = await db.execute(stmt)
        cards = result.scalars().all()

    # Sort: column priority first, then position within column
    sorted_cards = sorted(
        cards,
        key=lambda c: (COLUMN_PRIORITY.get(c.status, 99), c.position),
    )

    plan_cards = [
        CardPlan(id=c.id, title=c.title, status=c.status, position=c.position)
        for c in sorted_cards
    ]

    execution_id = str(uuid4())
    return ExecutionPlan(
        execution_id=execution_id,
        project_id=project_id,
        cards=plan_cards,
        total=len(plan_cards),
    )


async def _build_card_prompt(card_id: str) -> tuple[str, str | None]:
    """Build an execution prompt for a card (mirrors execute_card endpoint logic).

    Returns (prompt, project_name).
    """
    async with async_session() as db:
        stmt = (
            select(Card)
            .where(Card.id == card_id)
            .options(selectinload(Card.checklist_items))
        )
        result = await db.execute(stmt)
        card = result.scalar_one_or_none()
        if not card:
            return f"[Card {card_id} not found]", None

        # Build checklist section
        checklist_lines = []
        if card.checklist_items:
            for item in card.checklist_items:
                mark = "x" if item.completed else " "
                checklist_lines.append(f"- [{mark}] {item.text}")

        # Linked files
        files = json.loads(card.files) if card.files else []

        # Project name
        project_name = None
        if card.project_id:
            project = await db.get(Project, card.project_id)
            if project:
                project_name = project.title
            # Move to in-progress
            if card.status in (CardStatus.CARD, CardStatus.TODO):
                card.status = CardStatus.IN_PROGRESS
                await db.commit()

        # Build structured prompt
        parts = ["[CARD EXECUTION]"]
        parts.append(f"Title: {card.title}")
        if card.description:
            parts.append(f"Description: {card.description}")
        if checklist_lines:
            parts.append("\nChecklist:\n" + "\n".join(checklist_lines))
        if files:
            parts.append(f"\nLinked files: {', '.join(files)}")
        if project_name:
            parts.append(f"\nProject: {project_name}")
        parts.append("\nExecute this card. Read the description carefully and do what it asks.")
        parts.append("If anything is unclear, ask for clarification in the card chat.")
        parts.append("When you complete checklist items, check them off.")
        parts.append("When done, report what you did with the full raw output.")

        return "\n".join(parts), project_name


async def _move_card_to_done(card_id: str) -> None:
    """Move a card to done status."""
    async with async_session() as db:
        card = await db.get(Card, card_id)
        if card:
            card.status = CardStatus.DONE
            await db.commit()


async def _reset_recurring_cards(card_ids: list[str]) -> None:
    """Reset recurring cards back to todo status after a board run."""
    if not card_ids:
        return
    async with async_session() as db:
        for card_id in card_ids:
            card = await db.get(Card, card_id)
            if card and card.recurring:
                card.status = CardStatus.TODO
                logger.info(f"[BoardExecutor] Recurring card '{card.title}' ({card_id}) reset to todo")
        await db.commit()


async def execute_board(
    execution_id: str,
    project_id: str,
    cards: list[CardPlan],
    websocket: Any,
    orchestrator,
    session_id: str,
    chat_id: str | None = None,
) -> None:
    """Execute all cards sequentially through the chat pipeline.

    Sends WS events for progress and chains context between cards.
    """
    execution = BoardExecution(
        execution_id=execution_id,
        project_id=project_id,
        cards=cards,
    )
    _active_executions[execution_id] = execution
    chat_id = chat_id or f"project:{project_id}"
    done_card_ids: list[str] = []

    try:
        for i, card_plan in enumerate(cards):
            if execution.cancelled:
                logger.info(f"[BoardExecutor] Execution {execution_id} cancelled at card {i}")
                await websocket.send_json({
                    "type": "kanban:execute:cancelled",
                    "payload": {
                        "executionId": execution_id,
                        "cancelledAt": i,
                        "total": len(cards),
                    },
                    "timestamp": int(time.time() * 1000),
                })
                return

            execution.current_index = i

            # Emit card start
            await websocket.send_json({
                "type": "kanban:execute:card:start",
                "payload": {
                    "executionId": execution_id,
                    "cardId": card_plan.id,
                    "cardTitle": card_plan.title,
                    "index": i,
                    "total": len(cards),
                },
                "timestamp": int(time.time() * 1000),
            })

            # Build prompt with chain context
            prompt, _project_name = await _build_card_prompt(card_plan.id)

            if execution.chain_context:
                context_block = "[PREVIOUS CARDS CONTEXT]\n"
                context_block += "\n".join(execution.chain_context)
                context_block += "\n[/PREVIOUS CARDS CONTEXT]\n\n"
                prompt = context_block + prompt

            # Generate a unique message ID for this card execution
            message_id = f"exec-{execution_id}-{card_plan.id}"

            # Send through chat orchestration pipeline
            await orchestrator.handle_message(
                websocket=websocket,
                content=prompt,
                message_id=message_id,
                chat_id=chat_id,
                project_id=project_id,
                layers={"deep": False, "analyzer": False},
                chat_level="project",
                card_id=card_plan.id,
                session_id=session_id,
            )

            # Wait a moment for streaming to complete
            # The orchestrator streams asynchronously; we give it time to finish
            await asyncio.sleep(2)

            # Build chain context summary for next card
            summary = f"Card '{card_plan.title}': Executed successfully."
            execution.chain_context.append(summary)

            # Move card to done
            await _move_card_to_done(card_plan.id)
            done_card_ids.append(card_plan.id)

            # Emit card done
            await websocket.send_json({
                "type": "kanban:execute:card:done",
                "payload": {
                    "executionId": execution_id,
                    "cardId": card_plan.id,
                    "cardTitle": card_plan.title,
                    "index": i,
                    "total": len(cards),
                    "newStatus": "done",
                },
                "timestamp": int(time.time() * 1000),
            })

        # All cards done
        await websocket.send_json({
            "type": "kanban:execute:complete",
            "payload": {
                "executionId": execution_id,
                "total": len(cards),
                "completed": len(cards),
            },
            "timestamp": int(time.time() * 1000),
        })

    except Exception as e:
        logger.exception(f"[BoardExecutor] Execution {execution_id} failed: {e}")
        try:
            await websocket.send_json({
                "type": "kanban:execute:error",
                "payload": {
                    "executionId": execution_id,
                    "error": str(e),
                    "failedCardIndex": execution.current_index,
                },
                "timestamp": int(time.time() * 1000),
            })
        except Exception as e:
            logger.debug("Failed to send error notification via websocket: %s", e)
    finally:
        # Reset recurring cards back to todo (runs even on cancel/error)
        try:
            await _reset_recurring_cards(done_card_ids)
        except Exception as e:
            logger.error(f"[BoardExecutor] Failed to reset recurring cards: {e}")
        _active_executions.pop(execution_id, None)


def cancel_execution(execution_id: str) -> bool:
    """Cancel an active board execution. Returns True if found and cancelled."""
    execution = _active_executions.get(execution_id)
    if execution:
        execution.cancelled = True
        return True
    return False


def get_active_execution(execution_id: str) -> BoardExecution | None:
    return _active_executions.get(execution_id)
