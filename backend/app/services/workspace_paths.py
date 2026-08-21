"""One source of truth for a workspace's on-disk working directory.

Historically two independent schemes wrote under ``~/.voxyflow/sandbox/workspaces/``:

* **creation** (``POST /api/workspaces``) slugified the title into
  ``workspaces/<slug>`` and stored it in ``workspaces.local_path`` — that is the
  path the frontend advertises (workspace form, ``/api/workspaces/suggest-path``,
  Settings → Storage);
* the **worker runtime** (``config.workspace_workdir``) keyed a *second*
  directory by workspace id, ``workspaces/<uuid>``, and used it as the default
  cwd for ``system.exec`` and lightweight tasks.

So a single workspace owned two folders and the one the UI promised was not the
one workers actually wrote into. This module resolves a workspace id to the
directory the UI already shows: ``local_path`` first, the slugified title next,
and only then the legacy id-keyed folder (machines whose rows predate the
backfill, and ids with no row at all).

Reads go through ``sqlite3`` directly rather than SQLAlchemy: the resolver is
synchronous and is called from sync constructors as well as async handlers, so
it must not touch the async engine's event loop. Same reasoning — and same
shape — as ``llm/tool_defs._read_settings_from_db_sync``. Lookups are cached
with a short TTL; the workspace mutation routes call :func:`invalidate`.
"""

import logging
import re
import sqlite3
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# Workspace rows change rarely and a stale read only costs one turn of a worker
# writing to the previous directory, so a short TTL plus explicit invalidation
# from the mutation routes is enough — no need to hit sqlite on every exec.
_CACHE_TTL_SECONDS = 30.0
_cache: dict[str, tuple[float, tuple[str, str] | None]] = {}
_cache_lock = threading.Lock()


def slugify(name: str) -> str:
    """Convert a workspace title into a safe, readable directory name.

    Must stay byte-identical to what created the existing directories on disk —
    ``SandboxService`` delegates here so there is a single implementation.
    """
    slug = name.strip().lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    return slug or "unnamed"


def sanitize_id(workspace_id: str) -> str:
    """Legacy id-keyed folder name (pre-``local_path`` fallback)."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", workspace_id) or "system-main"


def _db_path() -> str:
    """Filesystem path of the app DB, derived from the SQLAlchemy URL.

    ``sqlite+aiosqlite:///`` + an absolute path yields four slashes, so the part
    after the scheme still carries a leading ``//``. A plain ``sqlite3.connect``
    tolerates that; the ``file:`` URI form does not (it reads ``home`` as a
    hostname), so collapse it here.
    """
    from app.config import get_settings

    db_url = get_settings().database_url
    raw = db_url.split("://", 1)[1] if "://" in db_url else db_url
    return "/" + raw.lstrip("/") if raw.startswith("//") else raw


def _lookup(workspace_id: str) -> tuple[str, str] | None:
    """Return ``(local_path, title)`` for a workspace id, or None.

    Never raises: a missing DB/table (fresh install) or a locked file must
    degrade to the id-keyed fallback rather than break ``system.exec``.
    """
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(workspace_id)
        if hit and now - hit[0] < _CACHE_TTL_SECONDS:
            return hit[1]

    row: tuple[str, str] | None = None
    try:
        conn = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True, timeout=5.0)
        try:
            cur = conn.execute(
                "SELECT local_path, title FROM workspaces WHERE id = ?",
                (workspace_id,),
            )
            found = cur.fetchone()
            if found:
                row = (found[0] or "", found[1] or "")
        finally:
            conn.close()
    except sqlite3.Error as e:
        # Fresh install (no file / no table) or transient lock — fall back.
        logger.debug("workspace_paths lookup failed for %s: %s", workspace_id, e)
        return None

    with _cache_lock:
        _cache[workspace_id] = (now, row)
    return row


def invalidate(workspace_id: str | None = None) -> None:
    """Drop cached lookups — call after creating/updating/deleting a workspace."""
    with _cache_lock:
        if workspace_id is None:
            _cache.clear()
        else:
            _cache.pop(workspace_id, None)


def _workspaces_root() -> Path:
    from app.config import VOXYFLOW_SANDBOX_DIR

    return Path(VOXYFLOW_SANDBOX_DIR).expanduser().resolve() / "workspaces"


def workspace_sandbox_area(workspace_id: str | None) -> Path:
    """Voxyflow's own folder for a workspace, always under the sandbox.

    Unlike :func:`resolve_workspace_dir` this never returns a user-supplied
    external checkout — Voxyflow bookkeeping (the autonomy ``heartbeat.md``)
    belongs in our sandbox, not dropped into someone's git repo.

    Naming, in order: the ``local_path`` when it already points inside the
    sandbox, else ``slug(title)``, else the sanitized id. Pure path arithmetic,
    no filesystem access.
    """
    workspaces_root = _workspaces_root()
    ws_id = (workspace_id or "").strip() or "system-main"

    row = _lookup(ws_id)
    if row:
        local_path, title = row
        if local_path:
            candidate = Path(local_path).expanduser()
            if candidate.is_relative_to(workspaces_root):
                return candidate
        if title:
            return workspaces_root / slugify(title)

    return workspaces_root / sanitize_id(ws_id)


def resolve_workspace_dir(workspace_id: str | None) -> Path:
    """Resolve a workspace id to its working directory (does NOT create it).

    This is where workers run. Resolution order:

    1. ``workspaces.local_path`` — what the frontend shows, and what the user
       may have pointed at an external checkout. An external path is only used
       when it actually exists; we never materialise a stale one.
    2. :func:`workspace_sandbox_area` — the readable sandbox folder.

    Note it deliberately does *not* follow a title rename: ``local_path`` is
    written once at creation and stays put, so renaming a workspace can never
    orphan the files already on disk.
    """
    workspaces_root = _workspaces_root()
    ws_id = (workspace_id or "").strip() or "system-main"

    row = _lookup(ws_id)
    if row and row[0]:
        local_path = row[0]
        candidate = Path(local_path).expanduser()
        # is_relative_to is lexical (no I/O) and covers every path we own, so
        # the stat below only ever runs for user-supplied external checkouts.
        # It is guarded: a dead NFS/removable mount makes os.stat block and
        # then raise, and this sits on the system.exec path where neither is
        # acceptable.
        if candidate.is_relative_to(workspaces_root):
            return candidate
        try:
            if candidate.is_dir():
                return candidate
            reason = "is missing"
        except OSError as e:
            reason = f"is unreachable ({e.strerror})"
        logger.warning(
            "Workspace %s local_path %s %s — using the sandbox area instead",
            ws_id, local_path, reason,
        )

    return workspace_sandbox_area(ws_id)
