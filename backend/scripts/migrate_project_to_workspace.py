"""One-shot migration: rename the "project" concept to "workspace".

Run this once when upgrading past the project→workspace rename. Idempotent:
re-running on an already-migrated install is a no-op. Backend must be stopped.

What it does
------------
1. **Filesystem**:
     ~/.voxyflow/workspace/             → ~/.voxyflow/sandbox/
     ~/.voxyflow/sandbox/projects/      → ~/.voxyflow/sandbox/workspaces/
2. **SQLite (voxyflow.db)**:
     - rename column `project_id` → `workspace_id` in cards, chats, documents,
       focus_sessions, kg_entities, sprints, wiki_pages, worker_tasks
     - rename table `projects` → `workspaces` (FK references auto-update on
       SQLite 3.25+, which is required)
     - rename unique index `uq_kg_entity_name_type_project` → `_workspace`
     - backfill `workspaces.local_path` from `…/workspace/projects/…` to
       `…/sandbox/workspaces/…`
3. **ChromaDB (~/.voxyflow/chroma)**:
     - `memory-project-{id}`             → `memory-workspace-{id}`
     - `voxyflow_project_{id}_{kind}`    → `voxyflow_workspace_{id}_{kind}`
       (with `_workspace` kanban suffix → `_board` to avoid the awkward
       `workspace_workspace` name)

Usage
-----
    # Dry-run (default) — prints what would change, writes nothing
    python -m scripts.migrate_project_to_workspace

    # Apply
    python -m scripts.migrate_project_to_workspace --apply

    # Take a tar+zstd backup first (recommended for first apply)
    python -m scripts.migrate_project_to_workspace --apply --backup
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(os.environ.get(
    "VOXYFLOW_DATA_DIR", os.path.expanduser("~/.voxyflow")
))
DB_PATH = DATA_DIR / "voxyflow.db"
CHROMA_PATH = DATA_DIR / "chroma"

OLD_FILE_WORKSPACE = DATA_DIR / "workspace"       # pre-rename: file sandbox
NEW_FILE_SANDBOX   = DATA_DIR / "sandbox"         # post-rename: file sandbox

OLD_PROJECTS_SUBDIR = NEW_FILE_SANDBOX / "projects"
NEW_WORKSPACES_SUBDIR = NEW_FILE_SANDBOX / "workspaces"

# Tables holding a `project_id` column to rename → workspace_id.
PROJECT_ID_TABLES = [
    "cards",
    "chats",
    "documents",
    "focus_sessions",
    "kg_entities",
    "sprints",
    "wiki_pages",
    "worker_tasks",
]

# Indexes that need to be dropped + recreated under the new name.
INDEX_RENAMES = [
    (
        "uq_kg_entity_name_type_project",
        "CREATE UNIQUE INDEX uq_kg_entity_name_type_workspace ON kg_entities (name, entity_type, workspace_id)",
    ),
]


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def make_backup() -> Path:
    """Copy DB + chroma + settings to a timestamped sibling dir."""
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = DATA_DIR.parent / f".voxyflow.bak.project-to-workspace.{ts}"
    backup.mkdir(parents=True, exist_ok=False)
    for name in ("voxyflow.db", "voxyflow.db-shm", "voxyflow.db-wal", "settings.json"):
        src = DATA_DIR / name
        if src.exists():
            shutil.copy2(src, backup / name)
    if CHROMA_PATH.exists():
        shutil.copytree(CHROMA_PATH, backup / "chroma")
    print(f"  ✓ backup written to {backup}")
    return backup


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


def _plan_filesystem() -> list[tuple[Path, Path]]:
    """Compute the sequence of renames using *post-previous-step* state.

    Returns a list of (old, new) pairs whose paths are correct in order — the
    second pair already accounts for the first one having moved the parent.
    """
    plan: list[tuple[Path, Path]] = []

    sandbox_after_step1 = NEW_FILE_SANDBOX
    if OLD_FILE_WORKSPACE.exists() and not NEW_FILE_SANDBOX.exists():
        plan.append((OLD_FILE_WORKSPACE, NEW_FILE_SANDBOX))
    elif NEW_FILE_SANDBOX.exists():
        pass  # already done
    else:
        sandbox_after_step1 = None  # nothing to rename inside either

    if sandbox_after_step1 is not None:
        # Check what's *currently* inside (may still be the old path).
        current_root = OLD_FILE_WORKSPACE if OLD_FILE_WORKSPACE.exists() else NEW_FILE_SANDBOX
        if current_root and (current_root / "projects").exists() and not (sandbox_after_step1 / "workspaces").exists():
            plan.append((sandbox_after_step1 / "projects", sandbox_after_step1 / "workspaces"))

    return plan


def migrate_filesystem(apply: bool) -> None:
    print("\n=== Filesystem ===")
    plan = _plan_filesystem()

    if not plan:
        print("  ✓ nothing to do (filesystem already migrated)")
        return

    for old, new in plan:
        print(f"  {old}  →  {new}")

    if not apply:
        print("  [dry-run] no changes written")
        return

    # Apply sequentially so each rename observes the result of the previous one.
    for _ in range(len(plan)):
        step = _plan_filesystem()
        if not step:
            break
        old, new = step[0]
        old.rename(new)
    print("  ✓ renamed")


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------


def migrate_sqlite(apply: bool) -> None:
    print(f"\n=== SQLite ({DB_PATH}) ===")
    if not DB_PATH.exists():
        print(f"  ! DB not found at {DB_PATH} — skipping")
        return

    if sqlite3.sqlite_version_info < (3, 25, 0):
        sys.exit(
            f"  ! SQLite {sqlite3.sqlite_version} is too old — need 3.25+ for "
            "ALTER TABLE RENAME COLUMN and FK auto-rewrite. Upgrade Python / system SQLite."
        )

    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys = OFF")
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    existing_tables = {r[0] for r in cur.fetchall()}

    already_migrated = "workspaces" in existing_tables and "projects" not in existing_tables

    actions: list[str] = []

    # 1) Per-table column rename — only if `project_id` still exists.
    for tbl in PROJECT_ID_TABLES:
        if tbl not in existing_tables:
            continue
        cur.execute(f"PRAGMA table_info({tbl})")
        cols = [r[1] for r in cur.fetchall()]
        if "project_id" in cols and "workspace_id" not in cols:
            actions.append(f"ALTER TABLE {tbl} RENAME COLUMN project_id TO workspace_id")

    # 2) Table rename.
    if "projects" in existing_tables and "workspaces" not in existing_tables:
        actions.append("ALTER TABLE projects RENAME TO workspaces")

    # 3) Unique index rename (only if the old name still exists).
    for old_idx, recreate_sql in INDEX_RENAMES:
        cur.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (old_idx,)
        )
        if cur.fetchone():
            actions.append(f"DROP INDEX {old_idx}")
            actions.append(recreate_sql)

    # 4) Backfill local_path on workspaces from old path layout to new one.
    #    Safe to run even if already migrated — the LIKE pattern just won't match.
    if "workspaces" in existing_tables or "projects" in existing_tables:
        backfill_table = "workspaces" if "workspaces" in existing_tables else "projects"
        cur.execute(
            f"SELECT COUNT(*) FROM {backfill_table} "
            "WHERE local_path LIKE '%/workspace/projects/%'"
        )
        n_paths = cur.fetchone()[0]
        if n_paths:
            # The UPDATE targets the post-rename name; sequence the SQL so it
            # runs *after* the table rename above.
            actions.append(
                "UPDATE workspaces "
                "SET local_path = REPLACE(local_path, '/workspace/projects/', '/sandbox/workspaces/') "
                "WHERE local_path LIKE '%/workspace/projects/%'"
            )

    if not actions:
        if already_migrated:
            print("  ✓ already migrated (workspaces table exists, projects gone)")
        else:
            print("  ✓ nothing to do")
        conn.close()
        return

    print(f"  Planned actions ({len(actions)}):")
    for a in actions:
        print(f"    {a}")

    if not apply:
        print("  [dry-run] no changes written")
        conn.close()
        return

    try:
        cur.execute("BEGIN")
        for stmt in actions:
            cur.execute(stmt)
        conn.commit()
        print("  ✓ committed")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()


# ---------------------------------------------------------------------------
# ChromaDB
# ---------------------------------------------------------------------------


def _rename_target(name: str) -> str | None:
    """Return the target name for a collection, or None if no rename needed."""
    if name.startswith("memory-project-"):
        return "memory-workspace-" + name[len("memory-project-"):]
    if name.startswith("voxyflow_project_"):
        rest = name[len("voxyflow_project_"):]
        # The kanban-content kind was `_workspace`; rename to `_board` so we
        # don't end up with the absurd `voxyflow_workspace_<id>_workspace`.
        if rest.endswith("_workspace"):
            rest = rest[: -len("_workspace")] + "_board"
        return "voxyflow_workspace_" + rest
    return None


def migrate_chroma(apply: bool) -> None:
    print(f"\n=== ChromaDB ({CHROMA_PATH}) ===")
    if not CHROMA_PATH.exists():
        print("  ! chroma dir missing — skipping")
        return
    try:
        import chromadb
    except ImportError:
        sys.exit("  ! chromadb not installed in this venv — install it before running.")

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    cols = client.list_collections()
    print(f"  Total collections: {len(cols)}")

    renames: list[tuple[str, str, int]] = []
    for col in cols:
        new = _rename_target(col.name)
        if new and new != col.name:
            renames.append((col.name, new, col.count()))

    if not renames:
        print("  ✓ nothing to do (no legacy `*project*` collections)")
        return

    print(f"  Collections to rename: {len(renames)}")
    for old, new, n in renames[:8]:
        print(f"    {old}  →  {new}  ({n} docs)")
    if len(renames) > 8:
        print(f"    ... +{len(renames) - 8} more")

    if not apply:
        print("  [dry-run] no changes written")
        return

    existing = {c.name for c in cols}
    for old, new, _ in renames:
        if new in existing:
            print(f"    ! skip {old} → {new} (target already exists)")
            continue
        src = client.get_collection(name=old)
        # Reuse source embedding fn so we don't accidentally re-vectorize with
        # a different model.
        dst = client.create_collection(
            name=new,
            metadata=src.metadata or {},
            embedding_function=src._embedding_function,
        )
        data = src.get(include=["embeddings", "documents", "metadatas"])
        ids = data.get("ids") or []
        if ids:
            dst.add(
                ids=ids,
                embeddings=data.get("embeddings"),
                documents=data.get("documents"),
                metadatas=data.get("metadatas"),
            )
        client.delete_collection(name=old)
        existing.add(new)
        print(f"    ✓ {old} → {new}  ({len(ids)} docs copied)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="Write changes (default is dry-run)")
    parser.add_argument("--backup", action="store_true",
                        help="Copy DB + chroma + settings to a sibling dir before applying")
    parser.add_argument("--skip-fs", action="store_true",
                        help="Skip filesystem renames (advanced)")
    parser.add_argument("--skip-sqlite", action="store_true",
                        help="Skip SQLite migration (advanced)")
    parser.add_argument("--skip-chroma", action="store_true",
                        help="Skip ChromaDB migration (advanced)")
    args = parser.parse_args()

    print("=== APPLY MODE — writing changes ===" if args.apply
          else "=== DRY-RUN — pass --apply to commit ===")

    if args.apply and args.backup:
        print("\n=== Backup ===")
        make_backup()

    if not args.skip_fs:
        migrate_filesystem(args.apply)
    if not args.skip_sqlite:
        migrate_sqlite(args.apply)
    if not args.skip_chroma:
        migrate_chroma(args.apply)

    print("\n=== Done ===")
    if not args.apply:
        print("Re-run with --apply (and --backup for the first run) to commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
