"""Memory Service — ChromaDB-backed hierarchical memory with file-based fallback.

Collections:
  memory-global                    ← user preferences, cross-project decisions, lessons learned
  memory-project-{project_id}      ← project-specific decisions, bugs, tech choices, context
                                    (keyed by project UUID, not slug — isolation-safe)

ChromaDB persists to ~/.voxyflow/chroma/ (shared PersistentClient with RAG service).
Embeddings use sentence-transformers/all-MiniLM-L6-v2 (local, no API key needed).

IMPORTANT: All ChromaDB operations are wrapped in try/except.
Memory failure NEVER breaks chat. If chromadb is not installed, memory falls
back to the original file-based approach (graceful degradation).
"""

import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful degradation: if chromadb is not installed, fall back to file-based
# ---------------------------------------------------------------------------

try:
    import chromadb
    from app.services.embedding_function import get_embedding_function, _CHROMADB_AVAILABLE

    _CHROMADB_AVAILABLE = _CHROMADB_AVAILABLE
    if _CHROMADB_AVAILABLE:
        logger.info("chromadb available — ChromaDB memory enabled")
except ImportError:
    _CHROMADB_AVAILABLE = False
    logger.warning(
        "chromadb not installed — falling back to file-based memory "
        "(install chromadb + sentence-transformers to enable semantic memory)"
    )

# ---------------------------------------------------------------------------
# Shared constants / helpers (extracted to memory_service_constants)
# ---------------------------------------------------------------------------

from app.services.memory_service_constants import (
    WORKSPACE_DIR,
    MEMORY_FILE,
    MEMORY_DIR,
    GLOBAL_COLLECTION,
    VALID_TYPES,
    VALID_SOURCES,
    VALID_IMPORTANCE,
    _classify_text,
    _format_messages_for_extraction,
    _slugify,
    _project_collection,
    _MEMORY_EXTRACTION_SYSTEM,
    _MEMORY_EXTRACTION_USER_TEMPLATE,
)

CHROMA_PERSIST_DIR = os.path.expanduser("~/.voxyflow/chroma")
MIGRATION_FLAG_FILE = Path(CHROMA_PERSIST_DIR) / ".memory_migrated"




from app.services.memory_extraction import MemoryExtractionMixin
from app.services.memory_context import MemoryContextMixin


class MemoryService(MemoryExtractionMixin, MemoryContextMixin):
    """ChromaDB-backed hierarchical memory with file-based fallback.

    Memory hierarchy:
    - memory-global: user preferences, cross-project decisions, lessons learned
    - memory-project-{slug}: project-specific decisions, bugs, tech choices

    Falls back to file-based memory (MEMORY.md, daily .md files) if ChromaDB
    is unavailable or not installed.

    Extraction + context-building live in mixin classes (extracted April 2026
    for readability) — ``self.auto_extract_memories`` and
    ``self.build_memory_context`` resolve via MRO.
    """

    # B4: extraction throttle — only run every N messages per chat
    EXTRACTION_INTERVAL = 3

    def __init__(
        self,
        daily_lookback_days: int = 3,
        persist_dir: str = CHROMA_PERSIST_DIR,
    ):
        self.daily_lookback_days = daily_lookback_days
        self._chromadb_enabled = False
        self._client = None
        self._ef = None
        # B4: per-chat message counter for throttling extraction
        self._extraction_counters: dict[str, int] = {}

        if _CHROMADB_AVAILABLE:
            try:
                persist_path = os.path.expanduser(persist_dir)
                os.makedirs(persist_path, exist_ok=True)
                self._client = chromadb.PersistentClient(path=persist_path)
                self._ef = get_embedding_function()
                self._chromadb_enabled = True
                logger.info(f"MemoryService ChromaDB initialized, persist_dir={persist_path!r}")
            except Exception as e:
                self._chromadb_enabled = False
                logger.error(f"MemoryService ChromaDB init failed — file-based fallback: {e}")

    # ------------------------------------------------------------------
    # ChromaDB self-healing: detect & repair corrupted HNSW indexes
    # ------------------------------------------------------------------

    def repair_collections(self) -> dict[str, str]:
        """Check all memory-* collections and rebuild any with corrupt HNSW indexes.

        Returns a dict of {collection_name: status} where status is
        "ok", "repaired (N/M docs recovered)", or "empty".
        """
        if not self._chromadb_enabled:
            return {}

        results: dict[str, str] = {}
        try:
            collections = self._client.list_collections()
        except Exception as e:
            logger.error(f"repair_collections: cannot list collections: {e}")
            return {}

        memory_cols = [c for c in collections if c.name.startswith("memory-")]

        for col in memory_cols:
            name = col.name
            count = 0
            try:
                count = col.count()
                if count == 0:
                    results[name] = "empty"
                    continue
                col.query(query_texts=["health check"], n_results=1)
                results[name] = "ok"
            except Exception:
                logger.warning(f"[repair] Collection {name} ({count} docs) has corrupt index — rebuilding")
                repaired = self._rebuild_collection(col, name, count)
                results[name] = repaired

        return results

    def _rebuild_collection(self, col, name: str, count: int) -> str:
        """Export recoverable docs from a corrupt collection, drop it, and re-insert."""
        # Phase 1: get all IDs (this usually works even when queries fail)
        try:
            all_id_result = col.get(include=[])
            all_ids = all_id_result["ids"]
        except Exception as e:
            logger.error(f"[repair] {name}: cannot even list IDs — skipping: {e}")
            return f"failed (cannot list IDs: {e})"

        # Phase 2: fetch each doc individually, skip corrupt ones
        recovered_ids = []
        recovered_docs = []
        recovered_metas = []
        recovered_embeds = []

        for doc_id in all_ids:
            try:
                b = col.get(ids=[doc_id], include=["documents", "metadatas", "embeddings"])
                if b["ids"]:
                    recovered_ids.append(b["ids"][0])
                    recovered_docs.append(b["documents"][0])
                    recovered_metas.append(b["metadatas"][0])
                    recovered_embeds.append(b["embeddings"][0])
            except Exception:
                logger.debug(f"[repair] {name}: doc {doc_id} unreadable — skipping")

        # Phase 3: drop and recreate
        try:
            self._client.delete_collection(name)
            new_col = self._client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            logger.error(f"[repair] {name}: failed to recreate collection: {e}")
            return f"failed (recreate error: {e})"

        # Phase 4: re-insert in batches
        batch_size = 200
        for i in range(0, len(recovered_ids), batch_size):
            end = min(i + batch_size, len(recovered_ids))
            try:
                new_col.add(
                    ids=recovered_ids[i:end],
                    documents=recovered_docs[i:end],
                    metadatas=recovered_metas[i:end],
                    embeddings=recovered_embeds[i:end],
                )
            except Exception as e:
                logger.error(f"[repair] {name}: insert batch {i}-{end} failed: {e}")

        final_count = new_col.count()
        lost = count - final_count
        status = f"repaired ({final_count}/{count} docs recovered"
        if lost > 0:
            status += f", {lost} lost"
        status += ")"
        logger.info(f"[repair] {name}: {status}")
        return status

    # ------------------------------------------------------------------
    # ChromaDB collection helpers
    # ------------------------------------------------------------------

    def _get_or_create_collection(self, name: str):
        """Get or create a ChromaDB collection with the default embedding function.

        If the collection exists but was created with a different embedding
        function (e.g. ChromaDB's built-in default), automatically migrate it
        to the current sentence-transformer EF so callers never see the
        conflict error.
        """
        try:
            return self._client.get_or_create_collection(
                name=name,
                embedding_function=self._ef,
                metadata={"hnsw:space": "cosine"},
            )
        except Exception as e:
            if "Embedding function conflict" not in str(e):
                raise
            logger.warning(f"[migrate] {name}: embedding function conflict — migrating collection")
            return self._migrate_collection_ef(name)

    def _migrate_collection_ef(self, name: str):
        """Re-create a collection under the current embedding function.

        Reads all documents (without embeddings — they'll be re-generated),
        drops the collection, recreates with the correct EF, and re-inserts.
        """
        # Open with no EF override so ChromaDB uses the persisted default
        old_col = self._client.get_collection(name=name)
        count = old_col.count()
        logger.info(f"[migrate] {name}: reading {count} docs from old collection")

        all_ids: list[str] = []
        all_docs: list[str] = []
        all_metas: list[dict] = []
        batch_size = 500
        for offset in range(0, count, batch_size):
            batch = old_col.get(
                include=["documents", "metadatas"],
                limit=batch_size,
                offset=offset,
            )
            all_ids.extend(batch["ids"])
            all_docs.extend(batch["documents"])
            all_metas.extend(batch["metadatas"])

        # Drop and recreate with the correct EF + metadata
        self._client.delete_collection(name)
        new_col = self._client.get_or_create_collection(
            name=name,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

        # Re-insert in batches (ChromaDB re-embeds with sentence_transformer)
        inserted = 0
        for i in range(0, len(all_ids), batch_size):
            end = min(i + batch_size, len(all_ids))
            try:
                new_col.add(
                    ids=all_ids[i:end],
                    documents=all_docs[i:end],
                    metadatas=all_metas[i:end],
                )
                inserted += end - i
            except Exception as batch_err:
                logger.error(f"[migrate] {name}: batch {i}-{end} failed: {batch_err}")

        logger.info(f"[migrate] {name}: done — {inserted}/{count} docs migrated")
        return new_col

    # ------------------------------------------------------------------
    # Store / Delete / Search / List (new ChromaDB methods)
    # ------------------------------------------------------------------

    def store_memory(
        self,
        text: str,
        collection: str = GLOBAL_COLLECTION,
        metadata: Optional[dict] = None,
    ) -> Optional[str]:
        """Store a memory entry in a ChromaDB collection.

        Returns the document ID on success, None on failure.
        """
        if not self._chromadb_enabled:
            # File-based fallback: append to MEMORY.md so memories persist without ChromaDB
            try:
                import uuid as _uuid
                from datetime import datetime as _dt, timezone as _tz
                doc_id = f"mem-{_uuid.uuid4().hex[:12]}"
                meta = metadata or {}
                mem_type = meta.get('type', 'fact')
                importance = meta.get('importance', 'medium')
                date_str = _dt.now(_tz.utc).strftime('%Y-%m-%d %H:%M UTC')
                MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
                entry = (
                    f"\n## [{mem_type.upper()}] ({importance}) — {date_str}\n"
                    f"{text}\n"
                )
                with open(MEMORY_FILE, 'a', encoding='utf-8') as _f:
                    _f.write(entry)
                logger.info(f"store_memory: wrote to MEMORY.md (file-based) — {doc_id}")
                return doc_id
            except OSError as fe:
                logger.error(f"store_memory file fallback failed: {fe}")
                return None

        try:
            col = self._get_or_create_collection(collection)
            doc_id = f"mem-{uuid.uuid4().hex[:12]}"

            meta = metadata or {}
            now = datetime.now(timezone.utc)
            # Ensure required fields with defaults
            meta.setdefault("type", "context")
            meta.setdefault("date", now.strftime("%Y-%m-%d"))
            meta.setdefault("created_at", now.isoformat(timespec="seconds"))
            meta.setdefault("source", "manual")
            meta.setdefault("importance", "medium")
            # Attribution defaults (caller can override).
            meta.setdefault("speaker", "unknown")
            # chat_id / project_id: prefer caller metadata, fall back to env.
            env_chat = os.environ.get("VOXYFLOW_CHAT_ID", "") or ""
            env_project = os.environ.get("VOXYFLOW_PROJECT_ID", "") or ""
            if env_chat and "chat_id" not in meta:
                meta["chat_id"] = env_chat
            if env_project and "project_id" not in meta:
                meta["project_id"] = env_project
            # ChromaDB metadata values must be str, int, float, or bool
            # Remove None values
            meta = {k: v for k, v in meta.items() if v is not None}

            col.upsert(ids=[doc_id], documents=[text], metadatas=[meta])
            logger.info(f"store_memory: stored doc {doc_id} in {collection}")
            return doc_id
        except Exception as e:
            logger.error(f"store_memory failed: {e}")
            return None

    def delete_memory(self, doc_id: str, collection: str = GLOBAL_COLLECTION) -> bool:
        """Delete a specific memory by ID from a collection."""
        if not self._chromadb_enabled:
            return False

        try:
            col = self._get_or_create_collection(collection)
            col.delete(ids=[doc_id])
            logger.info(f"delete_memory: deleted {doc_id} from {collection}")
            return True
        except Exception as e:
            logger.error(f"delete_memory failed: {e}")
            return False

    def delete_memory_cascade(self, doc_id: str, collections: list[str]) -> list[str]:
        """Delete a doc_id from each given collection if it exists.

        Returns the subset of `collections` where the doc was actually present
        and removed. Used by the MCP `memory.delete` handler when no explicit
        collection is provided — prevents the legacy "delete reports success
        but leaves an orphaned copy in another collection of the same scope"
        bug (Home: same id duped across `memory-global` and
        `memory-project-system-main` from the old migration).
        """
        if not self._chromadb_enabled:
            return []

        deleted_from: list[str] = []
        for name in collections:
            try:
                col = self._get_or_create_collection(name)
                existing = col.get(ids=[doc_id], include=[])
                if not existing.get("ids"):
                    continue
                col.delete(ids=[doc_id])
                deleted_from.append(name)
                logger.info(f"delete_memory_cascade: deleted {doc_id} from {name}")
            except Exception as e:
                logger.warning(f"delete_memory_cascade: error in {name}: {e}")
        return deleted_from

    def search_memory(
        self,
        query: str,
        collections: Optional[list[str]] = None,
        filters: Optional[dict] = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict]:
        """Semantic search across specified collections.

        The ``collections`` parameter is REQUIRED — there is no silent
        fallback to a global collection anymore. Callers must be explicit
        about which project scope(s) they want to search, otherwise a
        ``ValueError`` is raised. This prevents cross-project context
        leaks that happened when callers relied on a hidden default.

        Returns list of {id, text, score, metadata, collection}.
        """
        if collections is None:
            raise ValueError("collections= is required for search_memory")

        if not self._chromadb_enabled:
            # Fall back to keyword search
            return self._keyword_search(query, limit)

        if not query or not query.strip():
            return []

        all_results: list[dict] = []

        for col_name in collections:
            try:
                col = self._get_or_create_collection(col_name)
                count = col.count()
                if count == 0:
                    continue

                fetch_n = min(limit + offset, count)
                query_kwargs = {
                    "query_texts": [query],
                    "n_results": fetch_n,
                }
                if filters:
                    query_kwargs["where"] = filters

                results = col.query(**query_kwargs)

                docs = results.get("documents", [[]])[0]
                distances = results.get("distances", [[]])[0]
                metas = results.get("metadatas", [[]])[0]
                ids = results.get("ids", [[]])[0]

                for doc_id, doc, dist, meta in zip(ids, docs, distances, metas):
                    score = max(0.0, 1.0 - dist)
                    all_results.append({
                        "id": doc_id,
                        "text": doc,
                        "score": score,
                        "metadata": meta or {},
                        "collection": col_name,
                    })
            except Exception as e:
                logger.warning(f"search_memory: error querying {col_name}: {e}")
                continue

        all_results.sort(key=lambda r: r["score"], reverse=True)
        if offset:
            all_results = all_results[offset:]
        return all_results[:limit]

    def list_memories(
        self,
        collection: str = GLOBAL_COLLECTION,
        filters: Optional[dict] = None,
        limit: int = 20,
    ) -> list[dict]:
        """List recent memories from a collection.

        Returns list of {id, text, metadata}.
        """
        if not self._chromadb_enabled:
            return []

        try:
            col = self._get_or_create_collection(collection)
            count = col.count()
            if count == 0:
                return []

            get_kwargs = {"limit": min(limit, count)}
            if filters:
                get_kwargs["where"] = filters

            results = col.get(**get_kwargs)

            docs = results.get("documents", [])
            metas = results.get("metadatas", [])
            ids = results.get("ids", [])

            return [
                {"id": doc_id, "text": doc, "metadata": meta or {}}
                for doc_id, doc, meta in zip(ids, docs, metas)
            ]
        except Exception as e:
            logger.error(f"list_memories failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Daily log / project memory (kept for backward compat + auto-extract)
    # ------------------------------------------------------------------

    async def append_to_daily_log(self, content: str, date: Optional[datetime] = None) -> bool:
        """Append an entry to today's daily log."""
        date = date or datetime.now(timezone.utc)
        date_str = date.strftime("%Y-%m-%d")
        daily_file = MEMORY_DIR / f"{date_str}.md"

        try:
            MEMORY_DIR.mkdir(parents=True, exist_ok=True)
            time_str = date.strftime("%H:%M")

            if daily_file.exists():
                existing = daily_file.read_text(encoding="utf-8")
                new_content = f"{existing}\n\n**{time_str} [Voxyflow]** {content}"
            else:
                new_content = f"# {date_str}\n\n**{time_str} [Voxyflow]** {content}"

            daily_file.write_text(new_content, encoding="utf-8")
            logger.info(f"Appended to daily log: {daily_file}")
            return True
        except OSError as e:
            logger.error(f"Failed to write daily log: {e}")
            return False

    async def update_project_memory(self, project_name: str, content: str) -> bool:
        """Update or create a project-specific memory file."""
        slug = _slugify(project_name)
        project_dir = MEMORY_DIR / "projects"
        project_file = project_dir / f"{slug}.md"

        try:
            project_dir.mkdir(parents=True, exist_ok=True)
            project_file.write_text(content, encoding="utf-8")
            logger.info(f"Updated project memory: {project_file}")
            return True
        except OSError as e:
            logger.error(f"Failed to update project memory: {e}")
            return False

    # ------------------------------------------------------------------
    # Migration: file-based → ChromaDB (one-time)
    # ------------------------------------------------------------------

    async def migrate_from_files(self) -> int:
        """One-time migration from file-based memory to ChromaDB.

        Reads MEMORY.md and daily logs, chunks them, and inserts into the
        global collection. Idempotent — skips if already migrated.

        Returns number of documents inserted.
        """
        if not self._chromadb_enabled:
            logger.info("migrate_from_files: ChromaDB not available, skipping")
            return 0

        if MIGRATION_FLAG_FILE.exists():
            logger.info("migrate_from_files: already migrated, skipping")
            return 0

        inserted = 0
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Migrate MEMORY.md
        if MEMORY_FILE.exists():
            try:
                content = MEMORY_FILE.read_text(encoding="utf-8").strip()
                if content:
                    # Split by double newlines (paragraphs)
                    chunks = [c.strip() for c in content.split("\n\n") if c.strip() and len(c.strip()) > 20]
                    for chunk in chunks:
                        mem_type, importance = _classify_text(chunk)
                        doc_id = self.store_memory(
                            text=chunk,
                            collection=GLOBAL_COLLECTION,
                            metadata={
                                "type": mem_type,
                                "date": today,
                                "source": "manual",
                                "importance": importance,
                                "migrated_from": "MEMORY.md",
                            },
                        )
                        if doc_id:
                            inserted += 1
                    logger.info(f"migrate_from_files: migrated {inserted} chunks from MEMORY.md")
            except Exception as e:
                logger.error(f"migrate_from_files: failed to read MEMORY.md: {e}")

        # Migrate daily logs
        if MEMORY_DIR.exists():
            for md_file in sorted(MEMORY_DIR.glob("*.md")):
                try:
                    content = md_file.read_text(encoding="utf-8").strip()
                    if not content:
                        continue

                    # Extract date from filename
                    file_date = md_file.stem  # e.g., "2026-03-21"

                    chunks = [c.strip() for c in content.split("\n\n") if c.strip() and len(c.strip()) > 20]
                    for chunk in chunks:
                        # Skip markdown headers like "# 2026-03-21"
                        if chunk.startswith("# ") and len(chunk) < 20:
                            continue

                        mem_type, importance = _classify_text(chunk)
                        doc_id = self.store_memory(
                            text=chunk,
                            collection=GLOBAL_COLLECTION,
                            metadata={
                                "type": mem_type,
                                "date": file_date,
                                "source": "manual",
                                "importance": importance,
                                "migrated_from": f"memory/{md_file.name}",
                            },
                        )
                        if doc_id:
                            inserted += 1
                except (OSError, UnicodeDecodeError):
                    logger.exception("migrate_from_files: failed to process %s", md_file)

            # Migrate project-specific files
            projects_dir = MEMORY_DIR / "projects"
            if projects_dir.exists():
                for proj_file in projects_dir.glob("*.md"):
                    try:
                        content = proj_file.read_text(encoding="utf-8").strip()
                        if not content:
                            continue

                        project_slug = proj_file.stem
                        proj_col = _project_collection(project_slug)

                        chunks = [c.strip() for c in content.split("\n\n") if c.strip() and len(c.strip()) > 20]
                        for chunk in chunks:
                            mem_type, importance = _classify_text(chunk)
                            doc_id = self.store_memory(
                                text=chunk,
                                collection=proj_col,
                                metadata={
                                    "type": mem_type,
                                    "date": today,
                                    "source": "manual",
                                    "importance": importance,
                                    "project": project_slug,
                                    "migrated_from": f"memory/projects/{proj_file.name}",
                                },
                            )
                            if doc_id:
                                inserted += 1
                    except (OSError, UnicodeDecodeError):
                        logger.exception("migrate_from_files: failed to process %s", proj_file)

        # Write migration flag
        try:
            Path(CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)
            MIGRATION_FLAG_FILE.write_text(
                f"Migrated on {today}. {inserted} documents inserted.\n",
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning(f"migrate_from_files: could not write flag file: {e}")

        logger.info(f"migrate_from_files: completed — {inserted} documents inserted")
        return inserted

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def chromadb_enabled(self) -> bool:
        """Whether ChromaDB memory is available and initialized."""
        return self._chromadb_enabled


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_memory_service: Optional[MemoryService] = None


def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service
