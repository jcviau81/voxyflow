"""Migrate ChromaDB memory collections from name-slug to project_id keying.

This script fixes the cross-project context leak introduced when memory
collections were keyed by a slugified project name. In particular,
``memory-project-main`` collided between the generic "general chat" scope
and the ``system-main`` project, mixing thousands of documents.

Migration rules
---------------
- ``memory-project-main`` → split into BOTH ``memory-global`` and
  ``memory-project-system-main``. We cannot distinguish which docs were
  "truly global" vs "system-main project", so we duplicate into both.
- ``memory-project-{slug}`` where ``slug`` is NOT a UUID → look up the
  project by slugified title in SQLite and copy to
  ``memory-project-{project_id}``. Ambiguous slugs (multiple projects
  sharing the same slug) are skipped and logged.
- ``memory-project-{uuid}`` → already in the new format, skip.
- ``memory-project-system-main`` → already a valid project_id, skip.
- ``memory-global`` → target collection, never touched as a source.

Safety
------
The script is idempotent (safe to rerun) and NEVER deletes anything. Old
collections are preserved until you drop them manually after verifying the
new ones are populated. Drop hint is printed at the end.
"""
from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import chromadb  # noqa: E402

DB_PATH = os.path.expanduser("~/.voxyflow/voxyflow.db")
CHROMA_PATH = os.path.expanduser("~/.voxyflow/chroma")

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _slugify(name: str) -> str:
    """Replicate the memory_service slugify so we can match legacy names."""
    slug = (name or "").lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "default"


def load_projects() -> list[tuple[str, str, str]]:
    """Return list of ``(id, title, slugified_title)`` from SQLite."""
    if not os.path.exists(DB_PATH):
        print(f"! SQLite DB not found at {DB_PATH} — no slug→id mapping available")
        return []
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, title FROM projects")
        rows = cur.fetchall()
    finally:
        conn.close()
    return [(pid, title, _slugify(title)) for pid, title in rows]


def copy_collection(client, src_name: str, dst_name: str) -> int:
    """Copy all docs from ``src`` to ``dst``. Returns the number of docs copied.

    Re-prefixes IDs with ``mig-`` to avoid collisions when the destination
    collection already contains documents from a previous run or another
    source. ``upsert`` is used so reruns are idempotent.
    """
    try:
        src = client.get_collection(src_name)
    except Exception:
        return 0

    try:
        dst = client.get_or_create_collection(
            dst_name, metadata={"hnsw:space": "cosine"}
        )
    except Exception as e:
        print(f"  ! cannot create dst {dst_name}: {e}")
        return 0

    data = src.get()  # all docs
    ids = data.get("ids", []) or []
    if not ids:
        return 0

    docs = data.get("documents", []) or []
    metas = data.get("metadatas", []) or []
    embeddings = data.get("embeddings")

    # Re-prefix IDs to avoid collisions if dst already had stuff.
    new_ids = [f"mig-{i}" for i in ids]

    kwargs: dict = {"ids": new_ids, "documents": docs, "metadatas": metas}
    if embeddings is not None and len(embeddings) > 0:
        kwargs["embeddings"] = embeddings

    dst.upsert(**kwargs)
    return len(ids)


def main() -> None:
    print(f"Opening ChromaDB at {CHROMA_PATH}")
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    cols = {c.name: c for c in client.list_collections()}
    print(f"Found {len(cols)} collections")

    projects = load_projects()
    print(f"Found {len(projects)} projects in SQLite")

    # Build slug → [project_id] map (list to catch ambiguous slugs).
    slug_to_id: dict[str, list[str]] = {}
    for pid, _title, slug in projects:
        slug_to_id.setdefault(slug, []).append(pid)

    migrated = 0
    skipped = 0

    for col_name in list(cols.keys()):
        if not col_name.startswith("memory-project-"):
            continue
        if col_name == "memory-global":
            # Not a memory-project-* so never matches, but guard anyway.
            continue

        suffix = col_name[len("memory-project-"):]

        # Special: memory-project-main → split into global + system-main.
        if suffix == "main":
            print(
                f"\n=== {col_name} (special: split into global + system-main) ==="
            )
            n1 = copy_collection(client, col_name, "memory-global")
            print(f"  → memory-global: copied {n1} docs")
            n2 = copy_collection(client, col_name, "memory-project-system-main")
            print(f"  → memory-project-system-main: copied {n2} docs")
            migrated += 1
            continue

        # Already a UUID? Skip — already in new format.
        if UUID_RE.match(suffix):
            print(f"\n=== {col_name} (already UUID format, skip) ===")
            skipped += 1
            continue

        # system-main is a valid project_id reserved name, skip.
        if suffix == "system-main":
            print(f"\n=== {col_name} (already valid project_id, skip) ===")
            skipped += 1
            continue

        # Look up project by slug in SQLite.
        candidates = slug_to_id.get(suffix, [])
        if not candidates:
            print(
                f"\n=== {col_name} (slug {suffix!r} has no matching project, skip) ==="
            )
            skipped += 1
            continue
        if len(candidates) > 1:
            print(
                f"\n=== {col_name} (slug {suffix!r} is ambiguous: {candidates}, skip) ==="
            )
            skipped += 1
            continue

        target_id = candidates[0]
        target_name = f"memory-project-{target_id}"
        print(f"\n=== {col_name} → {target_name} (project {suffix!r}) ===")
        n = copy_collection(client, col_name, target_name)
        print(f"  → copied {n} docs")
        migrated += 1

    print(f"\n{'=' * 60}")
    print(f"DONE: {migrated} migrated, {skipped} skipped")
    print("Old collections preserved. Drop manually after verification, e.g.:")
    print(
        '  python -c "import chromadb; '
        "c = chromadb.PersistentClient('~/.voxyflow/chroma'); "
        "c.delete_collection('memory-project-main')\""
    )


if __name__ == "__main__":
    main()
