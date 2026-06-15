"""Jobs.json store — canonical service-layer import point for jobs persistence.

Historically ``routes/workspaces.py`` carried its own (lockless) copy of the
jobs.json load/save helpers and ``routes/jobs.py`` imported persistence
helpers across route modules — a layering violation. The lock-protected
implementation lives in ``app.services.job_runner``; this module re-exports it
under public names (``load_jobs`` / ``save_jobs``) so route modules import the
store from the service layer without reaching into private helpers.
"""

from app.services.job_runner import (  # noqa: F401
    JOBS_FILE,
    JOBS_LOCK,
    VOXYFLOW_DIR,
    _load_jobs,
    _save_jobs,
)

# Public names — preferred import surface.
load_jobs = _load_jobs
save_jobs = _save_jobs

__all__ = [
    "JOBS_FILE",
    "JOBS_LOCK",
    "VOXYFLOW_DIR",
    "load_jobs",
    "save_jobs",
    # Back-compat aliases (historical underscore names).
    "_load_jobs",
    "_save_jobs",
]
