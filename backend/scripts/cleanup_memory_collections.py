"""Drop legacy & orphan memory-* collections.

Phases (each gated by --apply, dry-run by default):

A. Slug-legacy collections — created before the slug→UUID migration.
   For each `memory-project-{slug}` where slug is not a UUID and not
   `system-main`:
     - Look up project by slugified title in SQLite.
     - If found AND every slug-doc-id has a `mig-{id}` counterpart in the
       UUID collection → drop the slug collection (already fully migrated;
       see migrate_memory_collections.py which re-prefixed IDs with `mig-`).
     - If found but some IDs are not yet migrated → copy the missing ones
       into the UUID collection as `legacy-{id}`, then drop.
     - If slug not in SQLite → orphan (project deleted) → drop with --drop-orphans
       (default: print and skip).

B. Empty collections — any `memory-project-*` with 0 docs, EXCLUDING
   `memory-project-system-main` (always preserved). The runtime auto-creates
   collections on first save, so dropping empties is harmless.

C. Test residues — `memory-project-e2e-*`, `memory-project-test-*`,
   `memory-project-nonexistent-*`. Always droppable.

Usage:
    python -m scripts.cleanup_memory_collections                      # dry-run all phases
    python -m scripts.cleanup_memory_collections --apply              # do it
    python -m scripts.cleanup_memory_collections --apply --drop-orphans
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import chromadb  # noqa: E402

CHROMA_PATH = os.path.expanduser("~/.voxyflow/chroma")
DB_PATH = os.path.expanduser("~/.voxyflow/voxyflow.db")

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
TEST_RESIDUE_RE = re.compile(r"^memory-project-(e2e-|test-|nonexistent-)")
PRESERVE = {"memory-global", "memory-project-system-main"}


def _slugify(name: str) -> str:
    s = (name or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "default"


def load_slug_to_id() -> dict[str, list[str]]:
    if not os.path.exists(DB_PATH):
        print(f"! SQLite DB not found at {DB_PATH}")
        return {}
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute("SELECT id, title FROM projects").fetchall()
    finally:
        conn.close()
    out: dict[str, list[str]] = {}
    for pid, title in rows:
        out.setdefault(_slugify(title), []).append(pid)
    return out


def _all_ids(col) -> set[str]:
    out: set[str] = set()
    batch_size = 1000
    offset = 0
    total = col.count()
    while offset < total:
        batch = col.get(include=[], limit=batch_size, offset=offset)
        ids = batch.get("ids", []) or []
        if not ids:
            break
        out.update(ids)
        offset += len(ids)
    return out


def _copy_missing(src, dst, missing_ids: list[str]) -> int:
    """Copy `missing_ids` from src to dst, prefixing them with `legacy-`."""
    if not missing_ids:
        return 0
    inserted = 0
    batch_size = 200
    for i in range(0, len(missing_ids), batch_size):
        chunk = missing_ids[i:i + batch_size]
        data = src.get(ids=chunk, include=["documents", "metadatas", "embeddings"])
        ids = data.get("ids", []) or []
        if not ids:
            continue
        new_ids = [f"legacy-{x}" for x in ids]
        kwargs: dict = {
            "ids": new_ids,
            "documents": data.get("documents", []),
            "metadatas": data.get("metadatas", []),
        }
        embeddings = data.get("embeddings")
        if embeddings is not None and len(embeddings) > 0:
            kwargs["embeddings"] = embeddings
        dst.upsert(**kwargs)
        inserted += len(ids)
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Actually drop / copy.")
    parser.add_argument(
        "--drop-orphans", action="store_true",
        help="Also drop slug collections whose project no longer exists in SQLite.",
    )
    args = parser.parse_args()

    print(f"Opening ChromaDB at {CHROMA_PATH}")
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    cols = {c.name: c for c in client.list_collections()}
    slug_to_id = load_slug_to_id()
    print(f"  {len(cols)} collections, {len(slug_to_id)} project slugs in SQLite")

    to_drop: list[str] = []
    copied_total = 0

    # --- Phase A: slug-legacy --------------------------------------------------
    print("\n=== Phase A: slug-legacy collections ===")
    slug_legacy = []
    for name in cols:
        if not name.startswith("memory-project-"):
            continue
        if name in PRESERVE:
            continue
        if TEST_RESIDUE_RE.match(name):
            continue
        suffix = name[len("memory-project-"):]
        if UUID_RE.match(suffix):
            continue
        slug_legacy.append((name, suffix))

    for name, suffix in sorted(slug_legacy):
        col = cols[name]
        n = col.count()
        candidates = slug_to_id.get(suffix, [])

        if not candidates:
            tag = "DROP" if args.drop_orphans else "SKIP (use --drop-orphans)"
            print(f"  {name} ({n} docs) — orphan, no project in SQLite → {tag}")
            if args.drop_orphans:
                to_drop.append(name)
            continue
        if len(candidates) > 1:
            print(f"  {name} ({n} docs) — AMBIGUOUS slug, {len(candidates)} projects → SKIP")
            continue

        project_id = candidates[0]
        uuid_name = f"memory-project-{project_id}"
        uuid_col = cols.get(uuid_name)
        if uuid_col is None:
            uuid_col = client.get_or_create_collection(
                uuid_name, metadata={"hnsw:space": "cosine"}
            )
            cols[uuid_name] = uuid_col

        if n == 0:
            print(f"  {name} (0 docs) → DROP (already empty)")
            to_drop.append(name)
            continue

        slug_ids = _all_ids(col)
        uuid_ids = _all_ids(uuid_col)
        already_migrated = {sid for sid in slug_ids if f"mig-{sid}" in uuid_ids or sid in uuid_ids}
        missing = sorted(slug_ids - already_migrated)

        if not missing:
            print(f"  {name} ({n} docs) → all migrated to {uuid_name} → DROP")
            to_drop.append(name)
            continue

        print(
            f"  {name} ({n} docs) → {len(missing)} not yet in {uuid_name} "
            f"→ copy as legacy-* + DROP"
        )
        if args.apply:
            inserted = _copy_missing(col, uuid_col, missing)
            copied_total += inserted
            print(f"      copied {inserted} docs into {uuid_name}")
        to_drop.append(name)

    # --- Phase B: empty collections -------------------------------------------
    print("\n=== Phase B: empty memory-project-* collections ===")
    empty_count = 0
    for name, col in sorted(cols.items()):
        if not name.startswith("memory-project-"):
            continue
        if name in PRESERVE:
            continue
        if name in to_drop:
            continue
        if TEST_RESIDUE_RE.match(name):
            continue
        try:
            if col.count() == 0:
                to_drop.append(name)
                empty_count += 1
        except Exception as e:
            print(f"  ! cannot count {name}: {e}")
    print(f"  {empty_count} empty collections queued for drop")

    # --- Phase C: test residues -----------------------------------------------
    print("\n=== Phase C: test residue collections ===")
    test_count = 0
    for name in sorted(cols):
        if not TEST_RESIDUE_RE.match(name):
            continue
        if name in to_drop:
            continue
        to_drop.append(name)
        test_count += 1
    print(f"  {test_count} test residue collections queued for drop")

    # --- Execute ---------------------------------------------------------------
    print(f"\n=== Total: {len(to_drop)} collections to drop ===")
    if not to_drop:
        print("Nothing to do.")
        return

    if not args.apply:
        for name in to_drop:
            print(f"  [DRY-RUN] would drop {name}")
        print("\nRe-run with --apply to actually drop.")
        return

    dropped = 0
    for name in to_drop:
        try:
            client.delete_collection(name)
            dropped += 1
        except Exception as e:
            print(f"  ! failed to drop {name}: {e}")
    print(f"\nDropped {dropped}/{len(to_drop)} collections.")
    if copied_total:
        print(f"Copied {copied_total} docs into UUID collections.")

    remaining = client.list_collections()
    print(f"Remaining collections: {len(remaining)}")


if __name__ == "__main__":
    main()
