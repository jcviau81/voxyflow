"""Backfill the ``speaker`` metadata field on legacy memories.

Why this exists
---------------
Pre-April-2026 memories were stored without a ``speaker`` field. The
retrieval formatter inferred the speaker from ``source`` at read time, which
worked most of the time but had one critical blind spot: ``source="auto-extract"``
memories were labelled "Voxy auto", implying the bot had said them, when in
reality they were summaries where the original speaker was never tracked.

This script walks every ``memory-*`` collection and canonicalises the
speaker field at write time, using the same source-based inference the
formatter used to do — **except** for the genuinely ambiguous cases, where
it honestly sets ``speaker="unknown"`` so the new formatter renders
``[auto-saved · speaker=unknown · ...]``.

Inference rules (only applied to docs missing a valid ``speaker``):
  source="chat"         → speaker="assistant"  (explicit memory.save from bot)
  source="manual"       → speaker="user"       (CLI / manual entry by user)
  source="worker"       → speaker="worker"
  source="auto-extract" → speaker="unknown"    (pre-migration ambiguous)
  source="worker_summary" without explicit speaker → speaker="unknown"
  anything else         → speaker="unknown"

Idempotent: safe to re-run. Only touches docs that need fixing.

Usage
-----
    python -m scripts.backfill_memory_speaker                # dry-run
    python -m scripts.backfill_memory_speaker --apply        # write updates
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
VALID_SPEAKERS = {"user", "assistant", "worker", "system", "unknown"}


def _all_docs(col) -> list[tuple[str, dict]]:
    """Return [(id, metadata_dict)] for every doc in the collection."""
    out: list[tuple[str, dict]] = []
    batch_size = 1000
    offset = 0
    total = col.count()
    while offset < total:
        batch = col.get(
            include=["metadatas"],
            limit=batch_size,
            offset=offset,
        )
        ids = batch.get("ids", []) or []
        metas = batch.get("metadatas", []) or []
        for i, m in zip(ids, metas):
            out.append((i, dict(m or {})))
        if not ids:
            break
        offset += len(ids)
    return out


def _needs_backfill(meta: dict) -> bool:
    """True when this doc is missing a valid ``speaker`` field."""
    val = str(meta.get("speaker") or "").strip().lower()
    return val not in VALID_SPEAKERS


def _infer_speaker(meta: dict) -> str:
    """Best-effort speaker inference for legacy docs missing an explicit field.

    Mirrors the source-based inference the retrieval formatter used to do,
    then canonicalises the result into a stored ``speaker`` value so the new
    formatter (which trusts the field and stops guessing from source) keeps
    producing correct tags. The only genuinely ambiguous case — auto-extract
    — becomes ``"unknown"``, which is the whole reason for this backfill.
    """
    source = str(meta.get("source") or "").strip().lower()
    if source == "chat":
        return "assistant"
    if source == "manual":
        return "user"
    if source == "worker":
        return "worker"
    # auto-extract, worker_summary-without-speaker, and everything else —
    # honestly unknown.
    return "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write updates to ChromaDB. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--collection",
        default=None,
        help="Only process a specific collection (e.g. 'memory-global'). "
        "Default: every collection whose name starts with 'memory-'.",
    )
    args = parser.parse_args()

    print(f"Opening ChromaDB at {CHROMA_PATH}")
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    all_collections = client.list_collections()
    targets = [
        c for c in all_collections
        if (args.collection is None and c.name.startswith("memory-"))
        or (args.collection is not None and c.name == args.collection)
    ]
    if not targets:
        print("No matching collections.")
        return

    print(f"Scanning {len(targets)} collection(s):")
    grand_total = 0
    grand_fix = 0
    per_collection_fixes: list[tuple[str, list[str], list[dict]]] = []

    inference_counts: dict[str, int] = {"user": 0, "assistant": 0, "worker": 0, "unknown": 0}
    for col in targets:
        docs = _all_docs(col)
        to_fix_ids: list[str] = []
        to_fix_metas: list[dict] = []
        for doc_id, meta in docs:
            if _needs_backfill(meta):
                inferred = _infer_speaker(meta)
                inference_counts[inferred] = inference_counts.get(inferred, 0) + 1
                new_meta = dict(meta)
                new_meta["speaker"] = inferred
                # Leave `source` intact — it still helps with auditability.
                to_fix_ids.append(doc_id)
                to_fix_metas.append(new_meta)
        print(
            f"  {col.name}: {len(docs)} docs, "
            f"{len(to_fix_ids)} need speaker backfill."
        )
        grand_total += len(docs)
        grand_fix += len(to_fix_ids)
        if to_fix_ids:
            per_collection_fixes.append((col.name, to_fix_ids, to_fix_metas))

    print(f"\nTotal: {grand_total} docs scanned, {grand_fix} need backfill.")
    if grand_fix == 0:
        print("Nothing to do.")
        return
    print("Inferred speaker distribution:")
    for k in ("user", "assistant", "worker", "unknown"):
        if inference_counts.get(k):
            print(f"  speaker={k:<10s} {inference_counts[k]}")

    if not args.apply:
        print("\n[DRY-RUN] re-run with --apply to write the updates.")
        # Show a few sample fixes so the operator can sanity-check.
        print("\nSample of docs that would be updated:")
        sampled = 0
        for name, ids, metas in per_collection_fixes:
            for doc_id, meta in zip(ids, metas):
                src = meta.get("source", "<no source>")
                dt = meta.get("created_at") or meta.get("date") or "<no date>"
                print(f"  {name}  {doc_id}  source={src!r}  created={dt!r}")
                sampled += 1
                if sampled >= 10:
                    break
            if sampled >= 10:
                break
        return

    print("\nApplying updates ...")
    total_updated = 0
    for name, ids, metas in per_collection_fixes:
        col = next((c for c in targets if c.name == name), None)
        if col is None:
            print(f"  ! collection {name} disappeared, skipping")
            continue
        batch_size = 500
        for i in range(0, len(ids), batch_size):
            id_chunk = ids[i:i + batch_size]
            meta_chunk = metas[i:i + batch_size]
            try:
                col.update(ids=id_chunk, metadatas=meta_chunk)
                total_updated += len(id_chunk)
                print(
                    f"  {name}: updated batch {i}-{i + len(id_chunk)} "
                    f"({total_updated}/{grand_fix})"
                )
            except Exception as e:  # noqa: BLE001
                print(f"  ! {name} batch {i} failed: {e}")

    print(f"\nDone. Updated {total_updated} docs across {len(per_collection_fixes)} collection(s).")


if __name__ == "__main__":
    main()
