"""Card/Task endpoints — with agent assignment support.

Package facade for the former monolithic ``app/routes/cards.py``.
Sub-routers are included in an order that exactly reproduces the original
route registration sequence. Registration-order hazard: the static
``/cards/unassigned`` and ``/cards/bulk-reorder`` routes MUST stay
registered before ``/cards/{card_id}`` or the path param captures them
(guarded by ``tests/test_refactor_cards.py``).
"""

from fastapi import APIRouter

from . import (
    attachments,
    crud,
    execution,
    history_votes,
    movement,
    relations,
    time_checklist,
)
from .attachments import FileRefRequest
from .crud import UnassignedCardCreate
from .execution import EnrichResponse
from .history_votes import CardHistoryEntry
from .relations import (
    VALID_RELATION_TYPES,
    RelationCreate,
    RelationResponse,
    _invert_relation_type,
)
from .serializers import (
    ATTACHMENTS_BASE,
    MAX_ATTACHMENT_SIZE,
    _broadcast_card_change,
    _card_to_response,
)

router = APIRouter(prefix="/api", tags=["cards"])

# Include order reproduces the original single-file declaration order.
router.include_router(crud.router)             # agents, create/list, unassigned, bulk-reorder, (un)assign, get/update
router.include_router(execution.router)        # assign agent, routing, duplicate, execute, board execute
router.include_router(crud.archive_router)     # delete, archive, restore, archived list
router.include_router(movement.router)         # clone-to, move-to
router.include_router(history_votes.router)    # history, vote, unvote
router.include_router(time_checklist.router)   # time entries, checklist
router.include_router(attachments.router)      # attachments upload/list/download/delete
router.include_router(relations.router)        # relations add/list/delete
router.include_router(execution.enrich_router)  # AI enrichment
router.include_router(attachments.files_router)  # card file references
