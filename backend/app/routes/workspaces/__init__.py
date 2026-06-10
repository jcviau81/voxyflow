"""Workspace endpoints — package facade.

Split from the former monolithic ``app/routes/workspaces.py``. Each submodule
defines its routes on local ``APIRouter`` instances which are included here in
THE EXACT ORDER the original module registered them. Registration order is
load-bearing: Starlette matches routes in registration order, so static paths
(``/templates``, ``/from-template/...``, ``/suggest-path``, ``/path-info``)
must register before the dynamic ``/{workspace_id}`` routes or they would be
captured as a workspace_id and 404. ``/import`` keeps its historical (late)
position — it never conflicts because no dynamic POST ``/{workspace_id}``
route exists.

``main.py`` does ``app.include_router(workspaces.router)`` — this package
exposes ``router`` unchanged (prefix and tags included).
"""

from fastapi import APIRouter

# Back-compat shims: the jobs.json store helpers historically lived at module
# level in routes/workspaces.py. The canonical home is now
# ``app.services.jobs_store`` (lock-protected implementation).
from app.services.jobs_store import (  # noqa: F401
    JOBS_FILE,
    VOXYFLOW_DIR,
    _load_jobs,
    _save_jobs,
)

from app.routes.workspaces import (
    ai_features,
    autonomy,
    crud,
    paths,
    templates_export,
    wiki,
)

# Re-exports so any historical ``from app.routes.workspaces import X`` keeps
# resolving (schemas, templates, helpers).
from app.routes.workspaces.crud import _require_workspace  # noqa: F401
from app.routes.workspaces.insights import (  # noqa: F401
    _compute_health,
    _compute_priority_score,
)
from app.routes.workspaces.schemas import (  # noqa: F401
    AutonomyUpsertBody,
    BriefResponse,
    CardExport,
    ChecklistItemExport,
    CreateFromTemplateRequest,
    CreateFromTemplateResponse,
    ExportPayload,
    HealthIssue,
    HealthResponse,
    ImportResponse,
    MeetingCardPreview,
    MeetingConfirmRequest,
    MeetingConfirmResponse,
    MeetingNotesRequest,
    MeetingNotesResponse,
    PrioritizeResponse,
    PriorizedCard,
    RelationExport,
    StandupResponse,
    StandupScheduleRequest,
    StandupScheduleResponse,
    TemplateResponse,
    TimeEntryExport,
    WikiPageCreate,
    WikiPageDetail,
    WikiPageExport,
    WikiPageSummary,
    WikiPageUpdate,
    WorkspaceExport,
)
from app.routes.workspaces.templates_export import TEMPLATES  # noqa: F401

# Aggregator router. Each submodule router already carries
# prefix="/api/workspaces" and tags=["workspaces"], so the final paths, tags
# and OpenAPI output are identical to the original single-router module.
# (FastAPI forbids an empty include prefix combined with an empty route path,
# so the collection routes — POST/GET "" — must get the prefix at the
# submodule level rather than here.)
router = APIRouter()

# ---------------------------------------------------------------------------
# Registration order — identical to the original monolithic module:
#   1. /templates, /from-template/{template_id}
#   2. POST "" (create), GET "" (list)
#   3. /suggest-path, /path-info        (BEFORE /{workspace_id} — see above)
#   4. /{workspace_id} core CRUD (get/delete/archive/restore/patch/favorite)
#   5. /{workspace_id}/autonomy*
#   6. /{workspace_id}/export, /import
#   7. meeting-notes*, brief, health, standup*
#   8. /{workspace_id}/wiki*
#   9. /{workspace_id}/prioritize
# ---------------------------------------------------------------------------
router.include_router(templates_export.templates_router)
router.include_router(crud.collection_router)
router.include_router(paths.router)
router.include_router(crud.item_router)
router.include_router(autonomy.router)
router.include_router(templates_export.export_import_router)
router.include_router(ai_features.router)
router.include_router(wiki.router)
router.include_router(ai_features.prioritize_router)
