"""Workspace autonomy — per-workspace heartbeat jobs.

Each project can opt into an autonomous heartbeat: a scheduled ``agent_task``
that fires on an interval, reads a project-scoped directive file, and runs the
instructions through the orchestrator with ``workspace_id`` set so memory / KG /
MCP scoping all land in the right place.

Layout
------
- Directive file: ``~/.voxyflow/workspace/projects/{workspace_id}/heartbeat.md``
- Job id:         ``proj-heartbeat-{workspace_id}``  (stored in ``jobs.json``)
- Job type:       ``agent_task`` (reuses existing executor in ``job_runner``)

The file uses the same ``---`` divider convention as the global heartbeat:
content below the divider is the "directive" — anything above is preamble /
instructions the user keeps static. The ``file_has_directive`` gate skips the
LLM call entirely when nothing actionable is below the line.

Chaining across cycles
----------------------
Intra-cycle chaining (worker completes → dispatcher re-entry) is already
handled by the debounced worker callback (``worker_pool._schedule_dispatcher_callback``).
Cross-cycle chaining is cooperative: Voxy is told to *rewrite the directive*
before exiting if she wants the next heartbeat to pick up where she left off,
and to *clear* the directive when she's done.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("voxyflow.workspace_autonomy")


VOXYFLOW_DIR = Path(os.environ.get("VOXYFLOW_DATA_DIR", os.path.expanduser("~/.voxyflow")))
SANDBOX_DIR = VOXYFLOW_DIR / "sandbox" / "workspaces"

DIVIDER = "---"
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

DEFAULT_SCHEDULE = "every_5min"


# ---------------------------------------------------------------------------
# Paths / ids
# ---------------------------------------------------------------------------


def heartbeat_file(workspace_id: str) -> Path:
    """Absolute path to the workspace's heartbeat directive file."""
    return SANDBOX_DIR / workspace_id / "heartbeat.md"


def job_id_for(workspace_id: str) -> str:
    """Stable job id for a workspace's autonomy heartbeat."""
    return f"proj-heartbeat-{workspace_id}"


# ---------------------------------------------------------------------------
# Directive file I/O
# ---------------------------------------------------------------------------


_DEFAULT_DIRECTIVE = (
    "Check worker status via workers.list.\n"
    "Check the todo column for a new task to start.\n"
    "If a todo card has no in-progress/running worker and no blocked dependencies,\n"
    "move it to in-progress and delegate an opus worker with a focused brief.\n"
    "Otherwise, log [AUTONOMY-NOOP] with the reason.\n"
)


_DEFAULT_PREAMBLE = (
    "# Workspace Heartbeat — {title}\n"
    "\n"
    "You are the autonomous agent for this project. You wake up on a schedule\n"
    "and read the directive below. If there is a directive, execute it — you\n"
    "have full project scoping (memory, KG, ledger) and may delegate to workers.\n"
    "\n"
    "**Chaining rules**\n"
    "- When you finish a step and want the next heartbeat to continue, rewrite\n"
    "  the directive below the divider with the next step.\n"
    "- When the work is fully done, clear the directive (leave only the HTML\n"
    "  comment) so the next cycle is a no-op.\n"
    "- To update this file, delegate a worker with a `file.write` action —\n"
    "  dispatcher tools cannot write files.\n"
    "\n"
    f"{DIVIDER}\n"
    "\n"
    "<!-- Drop the next directive below this line. Leave empty to pause. -->\n"
    "\n"
    f"{_DEFAULT_DIRECTIVE}"
)


def ensure_heartbeat_file(workspace_id: str, project_title: str = "") -> Path:
    """Create the workspace's heartbeat.md with a default preamble if missing.

    Idempotent: existing files are never overwritten.
    """
    path = heartbeat_file(workspace_id)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _DEFAULT_PREAMBLE.format(title=project_title or workspace_id),
        encoding="utf-8",
    )
    logger.info(f"[Autonomy] Seeded heartbeat file for project {workspace_id} at {path}")
    return path


def _split_at_divider(text: str) -> tuple[str, str]:
    """Return (preamble, directive_below_divider). Divider is kept in preamble."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == DIVIDER:
            preamble = "\n".join(lines[: i + 1]) + "\n"
            below = "\n".join(lines[i + 1 :])
            return preamble, below
    # No divider — whole file is preamble, directive is empty.
    return text, ""


def read_directive(workspace_id: str) -> str:
    """Return the directive text (below the divider), with HTML comments kept as-is."""
    path = heartbeat_file(workspace_id)
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"[Autonomy] Could not read {path}: {e}")
        return ""
    _, below = _split_at_divider(text)
    return below.lstrip("\n")


def write_directive(workspace_id: str, directive: str, project_title: str = "") -> None:
    """Replace the content below the divider with ``directive``.

    Creates the file with the default preamble if it doesn't exist yet.
    """
    ensure_heartbeat_file(workspace_id, project_title=project_title)
    path = heartbeat_file(workspace_id)
    text = path.read_text(encoding="utf-8")
    preamble, _ = _split_at_divider(text)
    if DIVIDER not in preamble:
        preamble = preamble.rstrip() + f"\n\n{DIVIDER}\n"
    new_text = preamble.rstrip() + "\n\n" + directive.rstrip() + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new_text, encoding="utf-8")
    os.replace(tmp, path)


def directive_is_actionable(workspace_id: str) -> bool:
    """True if the directive below the divider has non-comment, non-whitespace content."""
    body = _HTML_COMMENT_RE.sub("", read_directive(workspace_id))
    return bool(body.strip())


# ---------------------------------------------------------------------------
# Job dict shape
# ---------------------------------------------------------------------------


def build_job_dict(
    workspace_id: str,
    project_title: str,
    schedule: str = DEFAULT_SCHEDULE,
    enabled: bool = True,
) -> dict[str, Any]:
    """Return the canonical jobs.json entry for this workspace's heartbeat."""
    path = heartbeat_file(workspace_id)
    return {
        "id": job_id_for(workspace_id),
        "name": f"Heartbeat — {project_title or workspace_id}",
        "type": "agent_task",
        "schedule": schedule,
        "enabled": enabled,
        "payload": {
            "workspace_id": workspace_id,
            # The autonomy system prompt handles all operating rules; the
            # instruction here is just a tick marker appended after the
            # directive content in the user message.
            "instruction": "Execute the directive above, or log [AUTONOMY-NOOP] if nothing to do.",
            "gate": {
                "type": "file_has_directive",
                "path": str(path),
                "divider": DIVIDER,
            },
            # Flag in payload so _run_agent_task routes to the autonomy runner.
            # (The top-level flag below is kept for list views / filters.)
            "workspace_heartbeat": True,
        },
        # Marker so list views can group / filter these.
        "workspace_heartbeat": True,
    }


# ---------------------------------------------------------------------------
# High-level API (used by routes)
# ---------------------------------------------------------------------------


def _jobs_io():
    """Lazy import to avoid circulars at module load."""
    from app.services.job_runner import _find_job, _load_jobs, _save_jobs
    return _load_jobs, _save_jobs, _find_job


def _scheduler():
    from app.services.scheduler_service import get_scheduler_service
    return get_scheduler_service()


def get_status(workspace_id: str) -> dict[str, Any]:
    """Return ``{enabled, schedule, next_run, directive, file_path, actionable}``."""
    load, _save, find = _jobs_io()
    jobs = load()
    _idx, job = find(jobs, job_id_for(workspace_id))
    path = heartbeat_file(workspace_id)
    status = {
        "enabled": False,
        "schedule": DEFAULT_SCHEDULE,
        "next_run": None,
        "directive": read_directive(workspace_id),
        "file_path": str(path),
        "actionable": directive_is_actionable(workspace_id),
        "job_exists": job is not None,
    }
    if job is not None:
        status["enabled"] = bool(job.get("enabled", True))
        status["schedule"] = job.get("schedule") or DEFAULT_SCHEDULE
        try:
            status["next_run"] = _scheduler().get_next_run(job_id_for(workspace_id))
        except Exception:
            status["next_run"] = None
    return status


def upsert(
    workspace_id: str,
    project_title: str,
    *,
    enabled: bool = True,
    schedule: Optional[str] = None,
    directive: Optional[str] = None,
) -> dict[str, Any]:
    """Create or update the autonomy job for a workspace.

    ``directive`` — when provided, overwrites the content below the divider
    in ``heartbeat.md``. Pass an empty string to clear it (effectively pause
    without disabling the job).
    """
    load, save, find = _jobs_io()

    ensure_heartbeat_file(workspace_id, project_title=project_title)
    if directive is not None:
        write_directive(workspace_id, directive, project_title=project_title)

    jobs = load()
    idx, existing = find(jobs, job_id_for(workspace_id))
    new_job = build_job_dict(
        workspace_id,
        project_title,
        schedule=schedule or (existing and existing.get("schedule")) or DEFAULT_SCHEDULE,
        enabled=enabled,
    )
    if existing is None:
        jobs.append(new_job)
        logger.info(f"[Autonomy] Created heartbeat job for project {workspace_id}")
    else:
        # Preserve last_run / next_run from previous entry.
        new_job["last_run"] = existing.get("last_run")
        jobs[idx] = new_job
        logger.info(f"[Autonomy] Updated heartbeat job for project {workspace_id}")
    save(jobs)

    try:
        _scheduler().register_user_job(new_job)
    except Exception as e:
        logger.warning(f"[Autonomy] Could not (re)register APS job for {workspace_id}: {e}")

    return new_job


def disable(workspace_id: str) -> bool:
    """Remove the autonomy job entirely. Returns True if a job was removed."""
    load, save, find = _jobs_io()
    jobs = load()
    idx, existing = find(jobs, job_id_for(workspace_id))
    if existing is None:
        return False
    jobs.pop(idx)
    save(jobs)
    try:
        _scheduler().unregister_user_job(job_id_for(workspace_id))
    except Exception as e:
        logger.warning(f"[Autonomy] Could not unregister APS job for {workspace_id}: {e}")
    logger.info(f"[Autonomy] Disabled heartbeat job for project {workspace_id}")
    return True


async def run_now(workspace_id: str) -> dict[str, Any]:
    """Execute the workspace's heartbeat job immediately (bypassing the schedule)."""
    from app.services.job_runner import _execute_job

    load, _save, find = _jobs_io()
    jobs = load()
    _idx, job = find(jobs, job_id_for(workspace_id))
    if job is None:
        return {"status": "error", "message": "Autonomy not enabled for this project"}
    return await _execute_job(job)


__all__ = [
    "DEFAULT_SCHEDULE",
    "DIVIDER",
    "build_job_dict",
    "directive_is_actionable",
    "disable",
    "ensure_heartbeat_file",
    "get_status",
    "heartbeat_file",
    "job_id_for",
    "read_directive",
    "run_now",
    "upsert",
    "write_directive",
]
