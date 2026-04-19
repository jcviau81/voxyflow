"""One-shot cleanup: dedupe IDs duplicated across `memory-global` and
`memory-project-system-main`.

Why this exists
---------------
Home (the general chat) has `VOXYFLOW_PROJECT_ID="system-main"`, so its
`memory.search` queries both `memory-global` and `memory-project-system-main`
(see `mcp_system_handlers.memory_search._current_collections`). An older
migration path copied the legacy `memory-project-main` collection into both
of those without re-prefixing IDs, so the same `mem-XXXX` document now exists
twice and surfaces twice in retrieval.

Resolution policy
-----------------
Keep `memory-project-system-main` (consistent with where the current
`memory.save` handler writes for Home — see `mcp_system_handlers.memory_save`)
and delete the duplicate from `memory-global`. `memory-global` is reserved for
explicit cross-project saves; auto-extracted Home content does not belong
there.

If a duplicated ID exists in `memory-global` with a *different* document body
than the one in `memory-project-system-main`, we leave both untouched and
print a warning — that's a content collision, not a migration artifact, and a
human needs to look at it.

Usage
-----
    python -m scripts.dedup_memory_collections                # dry-run
    python -m scripts.dedup_memory_collections --apply        # actually delete
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import chromadb  # noqa: E402

CHROMA_PATH = os.path.expanduser("~/.voxyflow/chroma")
GLOBAL_COLLECTION = "memory-global"
SYSTEM_MAIN_COLLECTION = "memory-project-system-main"


def _all_ids_with_docs(col) -> dict[str, str]:
    """Return {id: document_text} for every doc in the collection."""
    out: dict[str, str] = {}
    batch_size = 1000
    offset = 0
    total = col.count()
    while offset < total:
        batch = col.get(
            include=["documents"],
            limit=batch_size,
            offset=offset,
        )
        ids = batch.get("ids", []) or []
        docs = batch.get("documents", []) or []
        for i, d in zip(ids, docs):
            out[i] = d or ""
        if not ids:
            break
        offset += len(ids)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete duplicates. Without this flag, runs in dry-run mode.",
    )
    args = parser.parse_args()

    print(f"Opening ChromaDB at {CHROMA_PATH}")
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    cols = {c.name: c for c in client.list_collections()}

    if GLOBAL_COLLECTION not in cols:
        print(f"  {GLOBAL_COLLECTION} not present — nothing to dedupe.")
        return
    if SYSTEM_MAIN_COLLECTION not in cols:
        print(f"  {SYSTEM_MAIN_COLLECTION} not present — nothing to dedupe.")
        return

    glob = cols[GLOBAL_COLLECTION]
    sysm = cols[SYSTEM_MAIN_COLLECTION]
    glob_count = glob.count()
    sysm_count = sysm.count()
    print(f"  {GLOBAL_COLLECTION}: {glob_count} docs")
    print(f"  {SYSTEM_MAIN_COLLECTION}: {sysm_count} docs")

    print("Loading IDs and docs ...")
    glob_docs = _all_ids_with_docs(glob)
    sysm_docs = _all_ids_with_docs(sysm)

    overlap = set(glob_docs) & set(sysm_docs)
    print(f"\nFound {len(overlap)} IDs present in BOTH collections.")

    if not overlap:
        print("Nothing to do.")
        return

    matching: list[str] = []
    diverging: list[str] = []
    for doc_id in overlap:
        if glob_docs[doc_id] == sysm_docs[doc_id]:
            matching.append(doc_id)
        else:
            diverging.append(doc_id)

    print(f"  {len(matching)} have identical bodies (safe to dedupe)")
    print(f"  {len(diverging)} have DIFFERENT bodies (will be left alone)")

    if diverging:
        print("\nDiverging IDs (need human review):")
        for doc_id in diverging[:20]:
            g = (glob_docs[doc_id] or "").replace("\n", " ")[:80]
            s = (sysm_docs[doc_id] or "").replace("\n", " ")[:80]
            print(f"  {doc_id}")
            print(f"    global:      {g!r}")
            print(f"    system-main: {s!r}")
        if len(diverging) > 20:
            print(f"  ... and {len(diverging) - 20} more")

    if not matching:
        print("\nNo safe deletions to perform. Done.")
        return

    if not args.apply:
        print(f"\n[DRY-RUN] would delete {len(matching)} IDs from {GLOBAL_COLLECTION}.")
        print("Re-run with --apply to actually delete.")
        return

    print(f"\nDeleting {len(matching)} duplicates from {GLOBAL_COLLECTION} ...")
    batch_size = 500
    deleted = 0
    for i in range(0, len(matching), batch_size):
        chunk = matching[i:i + batch_size]
        try:
            glob.delete(ids=chunk)
            deleted += len(chunk)
            print(f"  deleted batch {i}-{i + len(chunk)} ({deleted}/{len(matching)})")
        except Exception as e:
            print(f"  ! batch {i} failed: {e}")

    final_glob = glob.count()
    final_sysm = sysm.count()
    print(
        f"\nDone. {GLOBAL_COLLECTION}: {glob_count} → {final_glob} "
        f"(removed {glob_count - final_glob})."
    )
    print(
        f"     {SYSTEM_MAIN_COLLECTION}: {sysm_count} → {final_sysm} "
        f"(unchanged)."
    )


if __name__ == "__main__":
    main()
