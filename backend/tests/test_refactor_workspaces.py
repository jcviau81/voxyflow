"""Regression guards for the workspaces route-package refactor.

The former monolithic ``app/routes/workspaces.py`` was split into the
``app/routes/workspaces/`` package. These tests pin:

1. The exact route table — (method, path) pairs IN REGISTRATION ORDER.
   Starlette matches routes in registration order, so the static paths
   (/templates, /from-template, /suggest-path, /path-info, /import) must keep
   their exact positions relative to the dynamic /{workspace_id} routes.
   The expected table below was captured from the pre-refactor monolith.
2. The jobs.json store layering fix (app.services.jobs_store) and its
   back-compat aliases.
3. The package facade re-exports.
"""

from fastapi import APIRouter

from app.routes import workspaces

# Captured from the pre-refactor app/routes/workspaces.py at commit 1ebc093
# (order is load-bearing — do not sort).
EXPECTED_ROUTE_TABLE = [
    ("GET", "/api/workspaces/templates"),
    ("POST", "/api/workspaces/from-template/{template_id}"),
    ("POST", "/api/workspaces"),
    ("GET", "/api/workspaces"),
    ("GET", "/api/workspaces/suggest-path"),
    ("GET", "/api/workspaces/path-info"),
    ("GET", "/api/workspaces/{workspace_id}"),
    ("DELETE", "/api/workspaces/{workspace_id}"),
    ("POST", "/api/workspaces/{workspace_id}/archive"),
    ("POST", "/api/workspaces/{workspace_id}/restore"),
    ("PATCH", "/api/workspaces/{workspace_id}"),
    ("PATCH", "/api/workspaces/{workspace_id}/favorite"),
    ("GET", "/api/workspaces/{workspace_id}/autonomy"),
    ("PUT", "/api/workspaces/{workspace_id}/autonomy"),
    ("DELETE", "/api/workspaces/{workspace_id}/autonomy"),
    ("POST", "/api/workspaces/{workspace_id}/autonomy/run"),
    ("GET", "/api/workspaces/{workspace_id}/export"),
    ("POST", "/api/workspaces/import"),
    ("POST", "/api/workspaces/{workspace_id}/meeting-notes"),
    ("POST", "/api/workspaces/{workspace_id}/meeting-notes/confirm"),
    ("POST", "/api/workspaces/{workspace_id}/brief"),
    ("POST", "/api/workspaces/{workspace_id}/health"),
    ("POST", "/api/workspaces/{workspace_id}/standup"),
    ("GET", "/api/workspaces/{workspace_id}/standup/schedule"),
    ("POST", "/api/workspaces/{workspace_id}/standup/schedule"),
    ("GET", "/api/workspaces/{workspace_id}/wiki"),
    ("POST", "/api/workspaces/{workspace_id}/wiki"),
    ("GET", "/api/workspaces/{workspace_id}/wiki/{page_id}"),
    ("PUT", "/api/workspaces/{workspace_id}/wiki/{page_id}"),
    ("DELETE", "/api/workspaces/{workspace_id}/wiki/{page_id}"),
    ("POST", "/api/workspaces/{workspace_id}/prioritize"),
]


def _route_table(router: APIRouter) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for r in router.routes:
        methods = sorted(m for m in (getattr(r, "methods", None) or []) if m != "HEAD")
        for m in methods:
            rows.append((m, r.path))
    return rows


def test_route_table_snapshot_order_preserved():
    """(method, path) table — including registration ORDER — is unchanged."""
    assert _route_table(workspaces.router) == EXPECTED_ROUTE_TABLE


def test_static_paths_registered_before_dynamic_get():
    """/suggest-path and /path-info must match before GET /{workspace_id}."""
    table = _route_table(workspaces.router)
    get_rows = [path for method, path in table if method == "GET"]
    dyn = get_rows.index("/api/workspaces/{workspace_id}")
    assert get_rows.index("/api/workspaces/suggest-path") < dyn
    assert get_rows.index("/api/workspaces/path-info") < dyn
    assert get_rows.index("/api/workspaces/templates") < dyn


def test_all_routes_tagged_workspaces():
    tags = {tuple(r.tags) for r in workspaces.router.routes}
    assert tags == {("workspaces",)}


def test_main_app_route_table_matches():
    """The table as mounted on the real app is identical (no prefix drift)."""
    from app.main import app

    app_rows = []
    for r in app.routes:
        path = getattr(r, "path", "")
        if path in {p for _, p in EXPECTED_ROUTE_TABLE}:
            methods = sorted(m for m in (getattr(r, "methods", None) or []) if m != "HEAD")
            for m in methods:
                if (m, path) in EXPECTED_ROUTE_TABLE:
                    app_rows.append((m, path))
    # Every expected route is mounted exactly once, in the same order.
    assert app_rows == EXPECTED_ROUTE_TABLE


def test_jobs_store_layering_and_aliases():
    """jobs_store exposes public names backed by the canonical locked impl."""
    from app.services import job_runner, jobs_store

    assert jobs_store.load_jobs is job_runner._load_jobs
    assert jobs_store.save_jobs is job_runner._save_jobs
    assert jobs_store._load_jobs is job_runner._load_jobs
    assert jobs_store._save_jobs is job_runner._save_jobs
    assert jobs_store.JOBS_FILE == job_runner.JOBS_FILE
    assert jobs_store.VOXYFLOW_DIR == job_runner.VOXYFLOW_DIR


def test_routes_jobs_reexports_still_resolve():
    """routes/jobs.py keeps its historical re-export surface (used by workers.py)."""
    from app.routes import jobs as jobs_routes

    for name in ("JOBS_FILE", "VOXYFLOW_DIR", "_execute_job", "_find_job",
                 "_load_jobs", "_save_jobs", "router"):
        assert hasattr(jobs_routes, name), name


def test_workspaces_package_facade_reexports():
    """Historical module-level names still importable from the package."""
    for name in (
        "router",
        "TEMPLATES",
        "JOBS_FILE",
        "VOXYFLOW_DIR",
        "_load_jobs",
        "_save_jobs",
        "_require_workspace",
        "_compute_health",
        "_compute_priority_score",
        # schemas
        "TemplateResponse",
        "CreateFromTemplateRequest",
        "CreateFromTemplateResponse",
        "ChecklistItemExport",
        "TimeEntryExport",
        "RelationExport",
        "CardExport",
        "WorkspaceExport",
        "WikiPageExport",
        "ExportPayload",
        "ImportResponse",
        "AutonomyUpsertBody",
        "MeetingNotesRequest",
        "MeetingCardPreview",
        "MeetingNotesResponse",
        "MeetingConfirmRequest",
        "MeetingConfirmResponse",
        "BriefResponse",
        "HealthIssue",
        "HealthResponse",
        "StandupResponse",
        "StandupScheduleRequest",
        "StandupScheduleResponse",
        "WikiPageSummary",
        "WikiPageDetail",
        "WikiPageCreate",
        "WikiPageUpdate",
        "PriorizedCard",
        "PrioritizeResponse",
    ):
        assert hasattr(workspaces, name), name

    assert set(workspaces.TEMPLATES) == {"software", "research", "content", "bugfix", "launch"}
