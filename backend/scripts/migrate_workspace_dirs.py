#!/usr/bin/env python3
"""Move legacy id-keyed workspace folders onto their readable path.

Before the path unification, ``config.workspace_workdir`` keyed a workspace's
working directory by id — ``sandbox/workspaces/f0c3149b-853f-…`` — while the
creation route made, and the frontend advertised, a slug-named one
(``sandbox/workspaces/uo-outlands-guild-system``). Workspaces that ran workers
therefore own two folders, and the files the user is looking for are in the
one the UI never mentions.

This script merges the id-keyed folder into the workspace's ``local_path``:

* target missing            → the folder is renamed (cheap, same filesystem)
* target exists             → entries are moved in one by one
* name already taken there  → the entry is kept as ``<name>.legacy-<id8>``
                              rather than overwriting anything

Nothing is ever deleted or overwritten. Run ``--dry-run`` first.

    python backend/scripts/migrate_workspace_dirs.py --dry-run
    python backend/scripts/migrate_workspace_dirs.py
"""

import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.workspace_paths import (  # noqa: E402
    _db_path,
    sanitize_id,
    workspace_sandbox_area,
)


def _data_dir() -> Path:
    return Path(os.environ.get("VOXYFLOW_DATA_DIR", "~/.voxyflow")).expanduser()


def _workspaces() -> list[tuple[str, str]]:
    """(id, title) for every workspace row.

    Reads through the resolver's own ``_db_path`` so this script and the
    runtime can never disagree about which database defines the workspaces —
    ``database_url`` is overridable, and recomputing it here would let the
    script merge folders using ids from an entirely different install.
    """
    conn = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True, timeout=5.0)
    try:
        return [
            (r[0], r[1] or "")
            for r in conn.execute("SELECT id, title FROM workspaces")
        ]
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    args = ap.parse_args()

    sandbox = Path(
        os.environ.get("VOXYFLOW_SANDBOX_DIR", str(_data_dir() / "sandbox"))
    ).expanduser().resolve()
    ws_root = sandbox / "workspaces"

    moved = emptied = 0
    for ws_id, title in _workspaces():
        legacy = ws_root / sanitize_id(ws_id)
        if not legacy.is_dir():
            continue

        # Ask the runtime resolver rather than recomputing the target: this is
        # the whole point of the change, and any drift between the two would
        # silently re-create the split we are fixing. The *sandbox area*, not
        # the worker cwd — a workspace pointing at an external checkout must
        # not have old sandbox output moved into the user's own repo.
        target = workspace_sandbox_area(ws_id)
        if target == legacy:
            continue  # already the readable path (or an id-titled workspace)

        entries = sorted(legacy.iterdir())
        label = title or ws_id
        print(f"\n{label}\n  {legacy}\n  → {target}  ({len(entries)} entries)")

        if not entries:
            print("  empty — removing")
            if not args.dry_run:
                legacy.rmdir()
            emptied += 1
            continue

        if args.dry_run:
            for e in entries:
                clash = " [CLASH → .legacy suffix]" if (target / e.name).exists() else ""
                print(f"    {e.name}{clash}")
            moved += 1
            continue

        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            legacy.rename(target)
            print("  renamed")
        else:
            for e in entries:
                dest = target / e.name
                if dest.exists():
                    dest = target / f"{e.name}.legacy-{ws_id[:8]}"
                shutil.move(str(e), str(dest))
                print(f"    moved {e.name} → {dest.name}")
            legacy.rmdir()
            print("  merged")
        moved += 1

    verb = "would migrate" if args.dry_run else "migrated"
    print(f"\n{verb} {moved} workspace folder(s); {emptied} empty folder(s) removed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
