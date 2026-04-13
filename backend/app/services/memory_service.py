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
# Constants
# ---------------------------------------------------------------------------

WORKSPACE_DIR = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/.voxyflow"))) / "personality"
MEMORY_FILE = WORKSPACE_DIR / "MEMORY.md"
MEMORY_DIR = WORKSPACE_DIR / "memory"

CHROMA_PERSIST_DIR = os.path.expanduser("~/.voxyflow/chroma")
MIGRATION_FLAG_FILE = Path(CHROMA_PERSIST_DIR) / ".memory_migrated"

GLOBAL_COLLECTION = "memory-global"

VALID_TYPES = {"decision", "preference", "lesson", "fact", "context"}
VALID_SOURCES = {"chat", "manual", "auto-extract"}
VALID_IMPORTANCE = {"high", "medium", "low"}

# ---------------------------------------------------------------------------
# Keyword patterns for auto-extraction (FALLBACK heuristic — used when LLM fails)
# ---------------------------------------------------------------------------

_DECISION_PATTERNS = [
    re.compile(r"(?:I|we|let'?s)\s+(?:decided?|chose?|go(?:ing)?\s+with|picked|settled\s+on)", re.I),
    re.compile(r"(?:the\s+)?decision\s+(?:is|was)\s+to", re.I),
    re.compile(r"(?:I|we)\s+(?:will|'ll)\s+(?:use|go\s+with|stick\s+with)", re.I),
]

_PREFERENCE_PATTERNS = [
    re.compile(r"(?:I|we)\s+prefer", re.I),
    re.compile(r"(?:I|we)\s+(?:like|want|need)\s+(?:to\s+)?(?:use|have|keep)", re.I),
    re.compile(r"(?:always|never|don'?t)\s+(?:use|do|want)", re.I),
]

_BUG_PATTERNS = [
    re.compile(r"(?:bug|issue|problem|error|crash|broken|fix(?:ed)?)\b", re.I),
    re.compile(r"(?:doesn'?t|does\s+not|isn'?t|is\s+not)\s+work", re.I),
]

_TECH_PATTERNS = [
    re.compile(r"(?:using|switched?\s+to|migrated?\s+to|installed?|upgraded?)\s+\w+", re.I),
    re.compile(r"(?:stack|framework|library|tool|dependency|version)\b", re.I),
]

_LESSON_PATTERNS = [
    re.compile(r"(?:lesson|learned|takeaway|insight|realized?|turns?\s+out)\b", re.I),
    re.compile(r"(?:important|remember|note\s+to\s+self)\b", re.I),
]


def _classify_text(text: str) -> tuple[str, str]:
    """Classify text into (type, importance) using keyword heuristics.

    Fallback used when LLM extraction fails.
    Returns one of the VALID_TYPES and VALID_IMPORTANCE values.
    """
    # Check patterns in priority order
    for pat in _DECISION_PATTERNS:
        if pat.search(text):
            return "decision", "high"

    for pat in _BUG_PATTERNS:
        if pat.search(text):
            return "fact", "high"

    for pat in _PREFERENCE_PATTERNS:
        if pat.search(text):
            return "preference", "medium"

    for pat in _TECH_PATTERNS:
        if pat.search(text):
            return "fact", "medium"

    for pat in _LESSON_PATTERNS:
        if pat.search(text):
            return "lesson", "high"

    return "context", "low"


# ---------------------------------------------------------------------------
# LLM extraction prompt (B1)
# ---------------------------------------------------------------------------

_MEMORY_EXTRACTION_SYSTEM = """\
You are a memory extraction assistant for a project management tool. Your job is to analyze a \
short block of conversation messages and extract information worth remembering long-term.

## What to extract
- **decision**: A concrete choice that was made ("we'll use Redis", "going with Tailwind CSS")
- **preference**: A stated user preference or style guideline ("I prefer dark mode", "always use async")
- **fact**: A relevant technical fact, tool version, architecture detail, or bug/fix encountered
- **lesson**: A learned insight, hard-won takeaway, or "note to self"
- **skip**: Everything else — greetings, filler, vague statements, chitchat, questions without answers

## Language
The conversation may be in French, English, or franglais (FR/EN mix). Handle all naturally. \
Extract the memory content in the same language it was expressed.

## Output format
Respond with a JSON array ONLY — no markdown, no explanation, no code fence.
Each item in the array must be a JSON object with exactly these fields:
  - "content": string — the memory text, self-contained (no pronouns without referent)
  - "type": one of "decision" | "preference" | "fact" | "lesson" | "skip"
  - "importance": one of "high" | "medium" | "low"
  - "confidence": float between 0.0 and 1.0

## Rules
- Only include items with confidence > 0.7 that have real long-term value
- Skip pleasantries, repetitive content, questions, and anything too vague to be useful
- One memory per distinct piece of information (don't bundle multiple facts)
- Keep "content" concise but complete — someone reading it later should understand it without context
- If nothing is worth remembering, return an empty array: []

## Entity Extraction (Knowledge Graph)
Also extract named entities and relationships mentioned in the conversation:
- entities: People, technologies, tools, components, concepts, or decisions discussed
- relationships: How they relate (e.g. "project uses Redis", "auth depends on JWT")

Return a JSON object (not an array) with two keys:
  - "memories": the array of memory objects described above
  - "entities": an array of entity objects, each with:
    - "name": entity name (e.g. "Redis", "auth-service")
    - "type": one of "person" | "technology" | "component" | "concept" | "decision"
    - "relationships": array of {"predicate": string, "target": string, "target_type": string}

If no entities are found, set "entities": [].
If no memories are found, set "memories": [].
"""

_MEMORY_EXTRACTION_USER_TEMPLATE = """\
Extract memories from the following conversation messages:

{messages_block}
"""


def _format_messages_for_extraction(messages: list[dict]) -> str:
    """Format a list of message dicts into a readable block for the LLM."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown").upper()
        content = msg.get("content", "").strip()
        if content and role != "SYSTEM":
            lines.append(f"[{role}]: {content}")
    return "\n\n".join(lines)


def _slugify(name: str) -> str:
    """Convert a project name to a collection-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "default"


def _project_collection(project_id: str) -> str:
    """Return the collection name for a project (keyed by project_id, not slug).

    Using the project UUID as the collection key prevents cross-project
    context leaks that happened when slugs collided (e.g. "main" matching
    both the generic chat and the "system-main" project).
    """
    return f"memory-project-{project_id}"


class MemoryService:
    """ChromaDB-backed hierarchical memory with file-based fallback.

    Memory hierarchy:
    - memory-global: user preferences, cross-project decisions, lessons learned
    - memory-project-{slug}: project-specific decisions, bugs, tech choices

    Falls back to file-based memory (MEMORY.md, daily .md files) if ChromaDB
    is unavailable or not installed.
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
            # Ensure required fields with defaults
            meta.setdefault("type", "context")
            meta.setdefault("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
            meta.setdefault("source", "manual")
            meta.setdefault("importance", "medium")
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
    # Auto-extraction from conversations (LLM-based with regex fallback)
    # ------------------------------------------------------------------

    def _has_extractable_signal(self, messages: list[dict]) -> bool:
        """B4 pre-filter: check if any message contains regex-detectable signals.

        Returns True if at least one sentence in the messages matches a
        non-trivial pattern (decision, preference, fact, lesson, bug).
        Returns False if everything classifies as context/low — meaning
        the LLM call can be skipped entirely.
        """
        for msg in messages:
            content = msg.get("content", "")
            if not content:
                continue
            sentences = re.split(r'(?<=[.!?])\s+', content)
            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) < 20:
                    continue
                mem_type, importance = _classify_text(sentence)
                if mem_type != "context" or importance != "low":
                    return True
        return False

    async def auto_extract_memories(
        self,
        chat_id: str,
        messages: list[dict],
        project_id: Optional[str] = None,
    ) -> list[str]:
        """Analyze conversation messages and auto-store important facts/decisions.

        ``project_id`` is the UUID of the project chat (or ``"system-main"``
        / ``None`` for the general chat). Auto-extracted memories NEVER land
        in the cross-project ``memory-global`` collection — that collection
        is reserved for manual ``memory.save`` calls without a project
        scope. General-chat auto extractions land in
        ``memory-project-system-main``.

        B4 cost optimization flow:
        1. Message counter throttle — only run every EXTRACTION_INTERVAL messages
        2. Regex pre-filter — skip LLM call if no interesting patterns detected
        3. LLM extraction (haiku) for fine classification
        4. Regex fallback if LLM call itself fails

        Returns list of stored document IDs.
        """
        if not self._chromadb_enabled:
            return []

        # --- B4: message counter throttle ---
        self._extraction_counters[chat_id] = self._extraction_counters.get(chat_id, 0) + 1
        count = self._extraction_counters[chat_id]
        if count % self.EXTRACTION_INTERVAL != 0:
            logger.debug(
                f"auto_extract: throttled for {chat_id} (msg {count}, "
                f"next extraction at {count + (self.EXTRACTION_INTERVAL - count % self.EXTRACTION_INTERVAL)})"
            )
            return []

        stored_ids: list[str] = []
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Determine target collection.
        # - No project_id OR project_id == "system-main" → system-main project
        # - Any other project_id → that project's collection
        # We NEVER auto-extract into GLOBAL_COLLECTION; global memory is
        # reserved for deliberate user saves without a project scope.
        if not project_id or project_id == "system-main":
            target_project_id = "system-main"
        else:
            target_project_id = project_id
        collection = _project_collection(target_project_id)

        # Take the last 4 non-system messages
        relevant_messages = [
            m for m in messages
            if m.get("role") != "system" and m.get("content", "").strip()
        ][-4:]

        if not relevant_messages:
            return []

        # --- B4: regex pre-filter before LLM call ---
        if not self._has_extractable_signal(relevant_messages):
            logger.info(
                f"auto_extract: regex pre-filter found no signal for {chat_id} — skipping LLM call"
            )
            return []

        logger.info(f"auto_extract: regex pre-filter detected signal for {chat_id} — calling LLM")

        # --- Primary path: LLM extraction ---
        extraction_result = await self._llm_extract_memories(relevant_messages)

        if extraction_result is not None:
            extracted_items = extraction_result.get("memories", [])
            extracted_entities = extraction_result.get("entities", [])

            # Pipe entities to Knowledge Graph (non-blocking, never fails extraction)
            if extracted_entities:
                try:
                    from app.services.knowledge_graph_service import get_knowledge_graph_service
                    from sqlalchemy.exc import SQLAlchemyError
                    kg = get_knowledge_graph_service()
                    await kg.extract_entities_from_llm_output(extracted_entities, target_project_id)
                except (ImportError, ValueError, SQLAlchemyError) as e:
                    logger.warning(f"auto_extract: KG entity extraction failed (non-fatal): {e}")

            # LLM succeeded — process its output
            for item in extracted_items:
                mem_type = item.get("type", "skip")
                importance = item.get("importance", "low")
                confidence = float(item.get("confidence", 0.0))
                content = (item.get("content") or "").strip()

                # Skip low-confidence, noise, or empty entries
                if mem_type == "skip" or confidence <= 0.7 or not content or len(content) < 15:
                    continue

                # Normalize type to valid set
                if mem_type not in VALID_TYPES:
                    mem_type = "fact"
                if importance not in VALID_IMPORTANCE:
                    importance = "medium"

                metadata = {
                    "type": mem_type,
                    "date": today,
                    "source": "auto-extract",
                    "importance": importance,
                    "confidence": round(confidence, 2),
                }
                metadata["project"] = target_project_id

                # Dedup: check if very similar memory already exists
                existing = self.search_memory(
                    query=content,
                    collections=[collection],
                    limit=1,
                )
                if existing and existing[0]["score"] > 0.93:
                    logger.debug(f"auto_extract[LLM]: skipping duplicate (score={existing[0]['score']:.2f})")
                    continue

                doc_id = self.store_memory(
                    text=content,
                    collection=collection,
                    metadata=metadata,
                )
                if doc_id:
                    stored_ids.append(doc_id)
                    logger.info(f"auto_extract[LLM]: stored {mem_type} ({importance}, conf={confidence:.2f}): {content[:80]}...")

            return stored_ids

        # --- Fallback path: regex heuristics (LLM failed) ---
        logger.info("auto_extract: LLM extraction failed, falling back to regex heuristics")

        for msg in relevant_messages:
            content = msg.get("content", "")
            if not content:
                continue

            sentences = re.split(r'(?<=[.!?])\s+', content)

            for sentence in sentences:
                sentence = sentence.strip()
                if len(sentence) < 20:
                    continue

                mem_type, importance = _classify_text(sentence)

                if mem_type == "context" and importance == "low":
                    continue

                metadata = {
                    "type": mem_type,
                    "date": today,
                    "source": "auto-extract",
                    "importance": importance,
                }
                metadata["project"] = target_project_id

                existing = self.search_memory(
                    query=sentence,
                    collections=[collection],
                    limit=1,
                )
                if existing and existing[0]["score"] > 0.93:
                    logger.debug(f"auto_extract[regex]: skipping duplicate (score={existing[0]['score']:.2f})")
                    continue

                doc_id = self.store_memory(
                    text=sentence,
                    collection=collection,
                    metadata=metadata,
                )
                if doc_id:
                    stored_ids.append(doc_id)
                    logger.info(f"auto_extract[regex]: stored {mem_type} ({importance}): {sentence[:80]}...")

        return stored_ids

    async def _llm_extract_memories(
        self,
        messages: list[dict],
    ) -> Optional[dict]:
        """Call haiku to extract memories + entities from a block of messages.

        Returns a dict with keys "memories" (list[dict]) and "entities" (list[dict])
        on success, or None on failure. Backward-compatible: if LLM returns a plain
        list (old format), wraps it as {"memories": [...], "entities": []}.
        """
        try:
            # Import here to avoid circular dependency at module load time
            from app.services.claude_service import ClaudeService

            claude = ClaudeService()

            messages_block = _format_messages_for_extraction(messages)
            if not messages_block.strip():
                return None

            user_prompt = _MEMORY_EXTRACTION_USER_TEMPLATE.format(
                messages_block=messages_block
            )

            raw = await claude._call_api(
                model=claude.haiku_model,
                system=_MEMORY_EXTRACTION_SYSTEM,
                messages=[{"role": "user", "content": user_prompt}],
                client=claude.haiku_client,
                client_type=claude.haiku_client_type,
                use_tools=False,
            )

            if not raw or not raw.strip():
                logger.warning("_llm_extract_memories: empty response from LLM")
                return None

            # Strip markdown code fences if present
            text = raw.strip()
            if text.startswith("```"):
                text = text.split("```", 2)[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.rsplit("```", 1)[0].strip()

            parsed = json.loads(text)

            # Backward compat: old format returns a list (memories only)
            if isinstance(parsed, list):
                logger.info(f"_llm_extract_memories: LLM returned {len(parsed)} candidate memories (old format)")
                return {"memories": parsed, "entities": []}

            # New format: dict with "memories" and "entities"
            if isinstance(parsed, dict) and "memories" in parsed:
                memories = parsed.get("memories", [])
                entities = parsed.get("entities", [])
                logger.info(f"_llm_extract_memories: LLM returned {len(memories)} memories + {len(entities)} entities")
                return {"memories": memories, "entities": entities}

            logger.warning(f"_llm_extract_memories: unexpected format {type(parsed).__name__}")
            return None

        except json.JSONDecodeError as e:
            logger.warning(f"_llm_extract_memories: JSON parse error: {e}")
            return None
        except Exception as e:
            logger.warning(f"_llm_extract_memories: LLM call failed: {e}")
            return None

    # ------------------------------------------------------------------
    # build_memory_context — backward-compatible, now with semantic search
    # ------------------------------------------------------------------

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Rough token estimate (~1 token per 4 chars).

        More reliable than word-splitting for code, URLs, and non-English text
        where whitespace-delimited words don't map well to BPE tokens.
        """
        return max(1, len(text) // 4)

    def build_memory_context(
        self,
        project_name: Optional[str] = None,
        project_id: Optional[str] = None,
        include_long_term: bool = True,
        include_daily: bool = True,
        query: Optional[str] = None,
        card_id: Optional[str] = None,
        budget: int = 1500,
        layers: tuple[int, ...] = (0, 1, 2),
    ) -> Optional[str]:
        """Build a combined memory context string for injection into system prompts.

        If ChromaDB is available and a query is provided, uses semantic search
        with tiered layers:
          L0 — pinned KG entities (identity)
          L1 — high-importance recent memories (essentials)
          L2 — full semantic search (on-demand)

        ``budget`` caps total estimated tokens across all layers.
        ``layers`` controls which tiers to load.

        ``project_id`` is the UUID (or "system-main") that keys the Chroma
        collection. ``project_name`` is only used for display/section titles.

        Returns None if no memory available.
        """
        # If ChromaDB is available and we have a query, use semantic search
        if self._chromadb_enabled and query:
            return self._build_chromadb_context(
                query=query,
                project_name=project_name,
                project_id=project_id,
                card_id=card_id,
                include_long_term=include_long_term,
                budget=budget,
                layers=layers,
            )

        # Fallback: file-based memory
        return self._build_file_context(
            project_name=project_name,
            include_long_term=include_long_term,
            include_daily=include_daily,
        )

    def _build_l0_identity(self, project_id: str) -> Optional[str]:
        """L0: Pinned KG entities — project identity. Sync-safe (reads from cache)."""
        try:
            from app.services.knowledge_graph_service import get_knowledge_graph_service
            kg = get_knowledge_graph_service()
            pinned = kg.get_pinned_context(project_id or "system-main")
            if not pinned:
                return None
            lines = [f"- {e['name']} ({e['entity_type']}): {e['value']}" for e in pinned]
            return "**Project identity:**\n" + "\n".join(lines)
        except Exception:
            logger.debug("_build_l0_identity failed", exc_info=True)
            return None

    def _build_l1_essentials(
        self,
        query: str,
        project_id: Optional[str],
        card_id: Optional[str],
        budget: int,
    ) -> Optional[str]:
        """L1: High-importance recent memories (essentials). Budget-capped."""
        try:
            if not project_id:
                return None  # L1 only applies to project/card contexts

            proj_col = _project_collection(project_id)
            results = self.search_memory(
                query=query,
                collections=[proj_col],
                filters={"importance": "high"},
                limit=5,
            )
            if not results:
                return None

            display = project_id
            lines = []
            token_count = 0
            for r in results:
                line = f"- {r['text']}"
                line_tokens = self._estimate_tokens(line)
                if token_count + line_tokens > budget:
                    break
                lines.append(line)
                token_count += line_tokens

            if not lines:
                return None
            return f"**Key facts ({display}):**\n" + "\n".join(lines)
        except Exception as e:
            logger.debug(f"_build_l1_essentials failed: {e}")
            return None

    def _build_l2_ondemand(
        self,
        query: str,
        project_name: Optional[str],
        project_id: Optional[str],
        card_id: Optional[str],
        include_long_term: bool,
        budget: int,
        l1_ids: set[str] | None = None,
    ) -> Optional[str]:
        """L2: Full semantic search (current behavior, budget-capped). Deduplicates against L1."""
        sections: list[str] = []
        display_label = project_name or project_id or ""
        l1_ids = l1_ids or set()
        remaining = budget

        def _cap_results(results: list[dict], cap: int) -> list[str]:
            nonlocal remaining
            texts = []
            for r in results:
                if r["id"] in l1_ids:
                    continue
                line = r["text"]
                t = self._estimate_tokens(line)
                if remaining - t < 0:
                    break
                texts.append(line)
                remaining -= t
            return texts

        if project_id and card_id:
            proj_col = _project_collection(project_id)
            card_results = self.search_memory(
                query=query, collections=[proj_col],
                filters={"card_id": card_id}, limit=5,
            )
            if card_results:
                texts = _cap_results(card_results, remaining)
                if texts:
                    sections.append(
                        f"**Card memory ({display_label}):**\n" + "\n".join(f"- {t}" for t in texts)
                    )

            proj_results = self.search_memory(
                query=query, collections=[proj_col], limit=5,
            )
            if proj_results:
                card_ids = {r["id"] for r in card_results} if card_results else set()
                proj_unique = [r for r in proj_results if r["id"] not in card_ids]
                texts = _cap_results(proj_unique, remaining)
                if texts:
                    sections.append(
                        f"**Project memory ({display_label}):**\n" + "\n".join(f"- {t}" for t in texts)
                    )

        elif project_id:
            proj_col = _project_collection(project_id)
            proj_results = self.search_memory(
                query=query, collections=[proj_col], limit=10,
            )
            if proj_results:
                texts = _cap_results(proj_results, remaining)
                if texts:
                    sections.append(
                        f"**Project memory ({display_label}):**\n" + "\n".join(f"- {t}" for t in texts)
                    )

        else:
            main_col = _project_collection("system-main")
            search_cols = (
                [main_col, GLOBAL_COLLECTION] if include_long_term else [main_col]
            )
            main_results = self.search_memory(
                query=query, collections=search_cols, limit=10,
            )
            if main_results:
                texts = _cap_results(main_results, remaining)
                if texts:
                    sections.append("**Relevant memory:**\n" + "\n".join(f"- {t}" for t in texts))

        return "\n\n---\n\n".join(sections) if sections else None

    def _build_chromadb_context(
        self,
        query: str,
        project_name: Optional[str] = None,
        project_id: Optional[str] = None,
        card_id: Optional[str] = None,
        include_long_term: bool = True,
        budget: int = 1500,
        layers: tuple[int, ...] = (0, 1, 2),
    ) -> Optional[str]:
        """Build memory context using tiered layers with budget tracking.

        L0 — Pinned KG entities (project identity, ~100 tokens)
        L1 — High-importance recent memories (essentials, ~400 tokens)
        L2 — Full semantic search (on-demand, remaining budget)

        Strict project isolation: project chats NEVER see global.
        """
        remaining = budget
        sections: list[str] = []
        l1_ids: set[str] = set()

        try:
            # L0: Project identity from KG pinned cache
            if 0 in layers:
                l0 = self._build_l0_identity(project_id)
                if l0:
                    sections.append(l0)
                    remaining -= self._estimate_tokens(l0)

            # L1: High-importance essentials
            if 1 in layers and remaining > 50:
                l1 = self._build_l1_essentials(
                    query, project_id, card_id, min(400, remaining),
                )
                if l1:
                    sections.append(l1)
                    remaining -= self._estimate_tokens(l1)

            # L2: Full semantic search (current behavior)
            if 2 in layers and remaining > 50:
                l2 = self._build_l2_ondemand(
                    query, project_name, project_id, card_id,
                    include_long_term, min(remaining, 800),
                    l1_ids=l1_ids,
                )
                if l2:
                    sections.append(l2)

        except Exception as e:
            logger.error(f"_build_chromadb_context failed: {e}")
            return self._build_file_context(
                project_name=project_name,
                include_long_term=include_long_term,
                include_daily=True,
            )

        if not sections:
            return self._build_file_context(
                project_name=project_name,
                include_long_term=include_long_term,
                include_daily=True,
            )

        return "\n\n---\n\n".join(sections)

    # ------------------------------------------------------------------
    # File-based fallback (original implementation)
    # ------------------------------------------------------------------

    def _build_file_context(
        self,
        project_name: Optional[str] = None,
        include_long_term: bool = True,
        include_daily: bool = True,
    ) -> Optional[str]:
        """Build memory context from files (original approach, now a fallback)."""
        sections = []

        if include_long_term:
            ltm = self._load_long_term_memory()
            if ltm:
                sections.append(f"**Long-term memory:**\n{ltm}")

        if include_daily:
            daily = self._load_daily_logs()
            if daily:
                sections.append(f"**Recent daily logs:**\n{daily}")

        if project_name:
            proj = self._load_project_memory(project_name)
            if proj:
                sections.append(f"**Project notes ({project_name}):**\n{proj}")

        if not sections:
            return None

        return "\n\n---\n\n".join(sections)

    def _load_long_term_memory(self) -> str:
        """Load MEMORY.md — curated long-term memories."""
        if not MEMORY_FILE.exists():
            return ""
        try:
            content = MEMORY_FILE.read_text(encoding="utf-8").strip()
            return content
        except OSError as e:
            logger.warning(f"Failed to read MEMORY.md: {e}")
            return ""

    def _load_daily_logs(self, days: Optional[int] = None) -> str:
        """Load recent daily logs for context."""
        days = days or self.daily_lookback_days
        if not MEMORY_DIR.exists():
            return ""

        now = datetime.now(timezone.utc)
        entries = []

        for i in range(days):
            date = now - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            daily_file = MEMORY_DIR / f"{date_str}.md"
            if daily_file.exists():
                try:
                    content = daily_file.read_text(encoding="utf-8").strip()
                    entries.append(f"### {date_str}\n{content}")
                except OSError as e:
                    logger.warning(f"Failed to read {daily_file}: {e}")

        return "\n\n".join(entries)

    def _load_project_memory(self, project_name: str) -> str:
        """Load project-specific memory notes if they exist."""
        project_file = MEMORY_DIR / "projects" / f"{project_name}.md"
        if not project_file.exists():
            slug = _slugify(project_name)
            project_file = MEMORY_DIR / "projects" / f"{slug}.md"

        if not project_file.exists():
            return ""

        try:
            content = project_file.read_text(encoding="utf-8").strip()
            return content
        except OSError as e:
            logger.warning(f"Failed to read project memory {project_file}: {e}")
            return ""

    # ------------------------------------------------------------------
    # Keyword-based search fallback (original)
    # ------------------------------------------------------------------

    def _keyword_search(self, query: str, max_results: int = 5) -> list[dict]:
        """Simple keyword-based memory search across all memory files."""
        results = []
        query_lower = query.lower()
        query_terms = query_lower.split()

        if not MEMORY_DIR.exists():
            return results

        for md_file in sorted(MEMORY_DIR.rglob("*.md"), reverse=True):
            try:
                content = md_file.read_text(encoding="utf-8")
                content_lower = content.lower()

                hits = sum(1 for term in query_terms if term in content_lower)
                if hits == 0:
                    continue

                score = hits / len(query_terms)

                snippet = ""
                for para in content.split("\n\n"):
                    if any(term in para.lower() for term in query_terms):
                        snippet = para.strip()[:300]
                        break

                results.append({
                    "id": str(md_file),
                    "text": snippet,
                    "score": score,
                    "metadata": {"file": str(md_file.relative_to(WORKSPACE_DIR))},
                    "collection": "file-based",
                })
            except OSError:
                continue

        if MEMORY_FILE.exists():
            try:
                content = MEMORY_FILE.read_text(encoding="utf-8")
                content_lower = content.lower()
                hits = sum(1 for term in query_terms if term in content_lower)
                if hits > 0:
                    score = hits / len(query_terms)
                    for para in content.split("\n\n"):
                        if any(term in para.lower() for term in query_terms):
                            snippet = para.strip()[:300]
                            results.append({
                                "id": "MEMORY.md",
                                "text": snippet,
                                "score": score,
                                "metadata": {"file": "MEMORY.md"},
                                "collection": "file-based",
                            })
                            break
            except OSError as e:
                logger.warning("Failed to search MEMORY.md: %s", e)

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:max_results]

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
                except Exception as e:
                    logger.warning(f"migrate_from_files: failed to process {md_file}: {e}")

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
                    except Exception as e:
                        logger.warning(f"migrate_from_files: failed to process {proj_file}: {e}")

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
