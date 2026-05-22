"""Migrate ChromaDB memory collections from name-slug to workspace_id keying.

This script fixes the cross-workspace context leak introduced when memory
collections were keyed by a slugified workspace name. In particular,
``memory-workspace-main`` collided between the generic "general chat" scope
and the ``system-main`` workspace, mixing thousands of documents.

Migration rules
---------------
- ``memory-workspace-main`` → split into BOTH ``memory-global`` and
  ``memory-workspace-system-main``. We cannot distinguish which docs were
  "truly global" vs "system-main workspace", so we duplicate into both.
- ``memory-workspace-{slug}`` where ``slug`` is NOT a UUID → look up the
  workspace by slugified title in SQLite and copy to
  ``memory-workspace-{workspace_id}``. Ambiguous slugs (multiple workspaces
  sharing the same slug) are skipped and logged.
- ``memory-workspace-{uuid}`` → already in the new format, skip.
- ``memory-workspace-system-main`` → already a valid workspace_id, skip.
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
from chromadb.utils.embedding_functions import (  # noqa: E402
    SentenceTransformerEmbeddingFunction,
)

DB_PATH = os.path.expanduser("~/.voxyflow/voxyflow.db")
CHROMA_PATH = os.path.expanduser("~/.voxyflow/chroma")
# Must match memory_service.py — otherwise destination collections persist a
# different EF in their metadata and the runtime hits an "embedding function
# conflict" on first read/write. See fix_memory_ef_conflict.py for the rescue
# script if this ever drifts.
MEMORY_EF_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_EF = SentenceTransformerEmbeddingFunction(model_name=MEMORY_EF_MODEL)

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def _slugify(name: str) -> str:
    """Replicate the memory_service slugify so we can match legacy names."""
    slug = (name or "").lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "default"


def load_workspaces() -> list[tuple[str, str, str]]:
    """Return list of ``(id, title, slugified_title)`` from SQLite."""
    if not os.path.exists(DB_PATH):
        print(f"! SQLite DB not found at {DB_PATH} — no slug→id mapping available")
        return []
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, title FROM workspaces")
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
            dst_name,
            embedding_function=_EF,
            metadata={"hnsw:space": "cosine"},
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

    workspaces = load_workspaces()
    print(f"Found {len(workspaces)} workspaces in SQLite")

    # Build slug → [workspace_id] map (list to catch ambiguous slugs).
    slug_to_id: dict[str, list[str]] = {}
    for pid, _title, slug in workspaces:
        slug_to_id.setdefault(slug, []).append(pid)

    migrated = 0
    skipped = 0

    for col_name in list(cols.keys()):
        if not col_name.startswith("memory-workspace-"):
            continue
        if col_name == "memory-global":
            # Not a memory-workspace-* so never matches, but guard anyway.
            continue

        suffix = col_name[len("memory-workspace-"):]

        # Special: memory-workspace-main → split into global + system-main.
        if suffix == "main":
            print(
                f"\n=== {col_name} (special: split into global + system-main) ==="
            )
            n1 = copy_collection(client, col_name, "memory-global")
            print(f"  → memory-global: copied {n1} docs")
            n2 = copy_collection(client, col_name, "memory-workspace-system-main")
            print(f"  → memory-workspace-system-main: copied {n2} docs")
            migrated += 1
            continue

        # Already a UUID? Skip — already in new format.
        if UUID_RE.match(suffix):
            print(f"\n=== {col_name} (already UUID format, skip) ===")
            skipped += 1
            continue

        # system-main is a valid workspace_id reserved name, skip.
        if suffix == "system-main":
            print(f"\n=== {col_name} (already valid workspace_id, skip) ===")
            skipped += 1
            continue

        # Look up workspace by slug in SQLite.
        candidates = slug_to_id.get(suffix, [])
        if not candidates:
            print(
                f"\n=== {col_name} (slug {suffix!r} has no matching workspace, skip) ==="
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
        target_name = f"memory-workspace-{target_id}"
        print(f"\n=== {col_name} → {target_name} (workspace {suffix!r}) ===")
        n = copy_collection(client, col_name, target_name)
        print(f"  → copied {n} docs")
        migrated += 1

    print(f"\n{'=' * 60}")
    print(f"DONE: {migrated} migrated, {skipped} skipped")
    print("Old collections preserved. Drop manually after verification, e.g.:")
    print(
        '  python -c "import chromadb; '
        "c = chromadb.PersistentClient('~/.voxyflow/chroma'); "
        "c.delete_collection('memory-workspace-main')\""
    )


if __name__ == "__main__":
    main()
