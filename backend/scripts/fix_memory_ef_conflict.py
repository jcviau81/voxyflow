"""Fix ChromaDB embedding function conflict on memory collections.

Background
----------
``migrate_memory_collections.py`` created the new ``memory-project-{uuid}``
and ``memory-global`` collections without passing an explicit
``embedding_function``. ChromaDB persisted ``default`` in the collection
metadata. The app code in ``memory_service.py`` opens collections with
``SentenceTransformerEmbeddingFunction`` and Chroma raises:

    An embedding function already exists in the collection configuration,
    and a new one is provided. Embedding function conflict: new:
    sentence_transformer vs persisted: default

Both reads and writes fail. Voxy can no longer use memory tools inside any
migrated project.

Fix
---
Detect every memory collection where the persisted EF conflicts with
``SentenceTransformerEmbeddingFunction``, then rebuild it:

  1. Read all rows (ids/documents/metadatas/embeddings) using the bad EF.
  2. Delete the broken collection.
  3. Recreate it with the correct ``embedding_function`` set.
  4. Re-add the rows, passing the existing ``embeddings`` so we don't pay
     for re-embedding (the underlying vectors are already
     all-MiniLM-L6-v2 dimensions — they were copied from collections that
     used the same model, just under a different EF marker).

Idempotent — re-running on a clean store is a no-op.

Run with the backend STOPPED to avoid concurrent ChromaDB access:

    systemctl --user stop voxyflow-backend
    cd backend && venv/bin/python scripts/fix_memory_ef_conflict.py
    systemctl --user start voxyflow-backend
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import chromadb  # noqa: E402
from chromadb.utils.embedding_functions import (  # noqa: E402
    SentenceTransformerEmbeddingFunction,
)

CHROMA_PATH = os.path.expanduser("~/.voxyflow/chroma")
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


def is_memory_collection(name: str) -> bool:
    return name == "memory-global" or name.startswith("memory-project-")


def probe(client, name: str, ef) -> str:
    """Return one of: ok, conflict, missing, error:<msg>."""
    try:
        col = client.get_collection(name=name, embedding_function=ef)
        col.count()
        return "ok"
    except Exception as e:
        msg = str(e).lower()
        if "embedding function" in msg and "conflict" in msg:
            return "conflict"
        if "does not exist" in msg or "not found" in msg:
            return "missing"
        return f"error:{e}"


def rebuild(client, name: str, ef) -> tuple[int, str]:
    """Rebuild ``name`` to use the correct EF. Returns (n_docs, status)."""
    # Step 1: read everything via the bad EF (no EF override → use persisted).
    try:
        bad = client.get_collection(name=name)
        data = bad.get(include=["documents", "metadatas", "embeddings"])
    except Exception as e:
        return 0, f"read-failed: {e}"

    ids = list(data.get("ids") or [])
    docs = list(data.get("documents") or [])
    metas = list(data.get("metadatas") or [])
    embeds_raw = data.get("embeddings")

    # ChromaDB returns embeddings as numpy arrays; convert to plain lists.
    embeds: list | None
    if embeds_raw is None:
        embeds = None
    else:
        try:
            embeds = [list(e) for e in embeds_raw]
        except Exception:
            embeds = None

    n = len(ids)

    # Step 2: delete the broken collection.
    try:
        client.delete_collection(name=name)
    except Exception as e:
        return n, f"delete-failed: {e}"

    # Step 3: recreate with the right EF.
    try:
        new_col = client.get_or_create_collection(
            name=name,
            embedding_function=ef,
            metadata={"hnsw:space": "cosine"},
        )
    except Exception as e:
        return n, f"recreate-failed: {e}"

    if n == 0:
        return 0, "recreated-empty"

    # Step 4: re-add rows. Use upsert so partial reruns are safe.
    kwargs: dict = {"ids": ids, "documents": docs, "metadatas": metas}
    if embeds is not None and len(embeds) == n:
        kwargs["embeddings"] = embeds

    try:
        new_col.upsert(**kwargs)
    except Exception as e:
        return n, f"upsert-failed: {e}"

    return n, "ok"


def main() -> None:
    print(f"Opening ChromaDB at {CHROMA_PATH}")
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    ef = SentenceTransformerEmbeddingFunction(model_name=MODEL_NAME)

    cols = [c.name for c in client.list_collections() if is_memory_collection(c.name)]
    print(f"Found {len(cols)} memory collections to check\n")

    ok = 0
    fixed = 0
    failed = 0
    skipped_other = 0

    for name in sorted(cols):
        status = probe(client, name, ef)
        if status == "ok":
            print(f"  [OK]       {name}")
            ok += 1
        elif status == "conflict":
            print(f"  [REBUILD]  {name} ...", end=" ", flush=True)
            n, result = rebuild(client, name, ef)
            if result == "ok" or result == "recreated-empty":
                print(f"done ({n} docs, {result})")
                fixed += 1
            else:
                print(f"FAILED: {result}")
                failed += 1
        elif status == "missing":
            print(f"  [MISSING]  {name} (skipped)")
            skipped_other += 1
        else:
            print(f"  [ERROR]    {name}: {status}")
            skipped_other += 1

    print()
    print("=" * 60)
    print(f"Results: {ok} ok, {fixed} rebuilt, {failed} failed, {skipped_other} other")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
