"""
ChromaDB-based RAG (Retrieval-Augmented Generation) service for Voxyflow.

Each project gets 3 isolated collections:
  - voxyflow_project_{project_id}_docs       ← uploaded documents
  - voxyflow_project_{project_id}_history    ← conversation history
  - voxyflow_project_{project_id}_workspace  ← cards, notes, board data

ChromaDB persists to ~/.voxyflow/chroma/ (NOT inside the repo).
Embeddings use sentence-transformers/all-MiniLM-L6-v2 (local, no API key needed).

IMPORTANT: All ChromaDB operations are wrapped in try/except.
RAG failure NEVER breaks chat. If chromadb is not installed, RAG silently
disables itself (graceful degradation via ImportError catch at module load).
"""

import asyncio
import hashlib
import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful degradation: if chromadb is not installed, disable RAG silently
# ---------------------------------------------------------------------------

try:
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    _CHROMADB_AVAILABLE = True
    logger.info("chromadb available — RAG enabled")
except ImportError:
    _CHROMADB_AVAILABLE = False
    logger.warning("chromadb not installed — RAG disabled (install chromadb + sentence-transformers to enable)")

# ---------------------------------------------------------------------------
# Lazy import for ParsedDocument (avoid circular imports)
# ---------------------------------------------------------------------------

from app.services.document_parser import ParsedDocument


# ---------------------------------------------------------------------------
# RAGService
# ---------------------------------------------------------------------------


class RAGService:
    """
    Per-project ChromaDB RAG service.

    Collections per project:
    - voxyflow_project_{project_id}_docs      ← uploaded documents
    - voxyflow_project_{project_id}_history   ← conversation history
    - voxyflow_project_{project_id}_workspace ← cards, notes, board data
    """

    def __init__(self, persist_dir: str = "~/.voxyflow/chroma"):
        self._enabled = _CHROMADB_AVAILABLE
        self._client = None
        self._ef = None

        if not self._enabled:
            return

        try:
            persist_path = os.path.expanduser(persist_dir)
            os.makedirs(persist_path, exist_ok=True)

            self._client = chromadb.PersistentClient(path=persist_path)
            self._ef = SentenceTransformerEmbeddingFunction(
                model_name="sentence-transformers/all-MiniLM-L6-v2"
            )
            logger.info(f"RAGService initialized, persist_dir={persist_path!r}")
        except Exception as e:
            self._enabled = False
            logger.error(f"RAGService init failed — RAG disabled: {e}")

    # -----------------------------------------------------------------------
    # Collection name helpers
    # -----------------------------------------------------------------------

    def _col_docs(self, project_id: str) -> str:
        return f"voxyflow_project_{project_id}_docs"

    def _col_history(self, project_id: str) -> str:
        return f"voxyflow_project_{project_id}_history"

    def _col_workspace(self, project_id: str) -> str:
        return f"voxyflow_project_{project_id}_workspace"

    def _get_or_create_collection(self, name: str):
        """Get or create a ChromaDB collection with the default embedding function."""
        return self._client.get_or_create_collection(
            name=name,
            embedding_function=self._ef,
            metadata={"hnsw:space": "cosine"},
        )

    # -----------------------------------------------------------------------
    # Document indexing
    # -----------------------------------------------------------------------

    async def index_document(
        self, project_id: str, doc_id: str, parsed: ParsedDocument
    ) -> int:
        """
        Index all chunks from a parsed document into the docs collection.

        Returns the number of chunks indexed (0 on failure).
        """
        if not self._enabled:
            return 0

        try:
            collection = self._get_or_create_collection(self._col_docs(project_id))

            if not parsed.chunks:
                logger.warning(f"index_document: no chunks for doc_id={doc_id!r}")
                return 0

            ids = [f"{doc_id}__chunk_{i}" for i in range(len(parsed.chunks))]
            metadatas = [
                {
                    **parsed.metadata,
                    "doc_id": doc_id,
                    "chunk_index": i,
                    "source": "document",
                    "project_id": project_id,
                }
                for i in range(len(parsed.chunks))
            ]

            collection.upsert(
                ids=ids,
                documents=parsed.chunks,
                metadatas=metadatas,
            )

            logger.info(
                f"index_document: indexed {len(parsed.chunks)} chunks for doc_id={doc_id!r}, "
                f"project_id={project_id!r}"
            )
            return len(parsed.chunks)

        except Exception as e:
            logger.error(f"index_document failed (doc_id={doc_id!r}): {e}")
            return 0

    async def delete_document(self, project_id: str, doc_id: str) -> None:
        """Delete all chunks for a document from the docs collection."""
        if not self._enabled:
            return

        try:
            collection = self._get_or_create_collection(self._col_docs(project_id))
            # Query all IDs that belong to this doc_id
            results = collection.get(where={"doc_id": doc_id})
            ids_to_delete = results.get("ids", [])
            if ids_to_delete:
                collection.delete(ids=ids_to_delete)
                logger.info(
                    f"delete_document: deleted {len(ids_to_delete)} chunks "
                    f"for doc_id={doc_id!r}, project_id={project_id!r}"
                )
        except Exception as e:
            logger.error(f"delete_document failed (doc_id={doc_id!r}): {e}")

    # -----------------------------------------------------------------------
    # Conversation history indexing
    # -----------------------------------------------------------------------

    async def index_conversation_turn(
        self,
        project_id: str,
        session_id: str,
        role: str,
        content: str,
        timestamp: float,
    ) -> None:
        """Index a single conversation turn into the history collection."""
        if not self._enabled:
            return

        if not content or not content.strip():
            return

        try:
            collection = self._get_or_create_collection(self._col_history(project_id))

            # Deterministic ID: hash of session_id + timestamp + role to avoid dupes
            turn_hash = hashlib.sha256(
                f"{session_id}:{timestamp}:{role}:{content[:50]}".encode()
            ).hexdigest()[:16]
            turn_id = f"history__{session_id}__{turn_hash}"

            collection.upsert(
                ids=[turn_id],
                documents=[content.strip()],
                metadatas=[
                    {
                        "source": "history",
                        "session_id": session_id,
                        "role": role,
                        "timestamp": timestamp,
                        "project_id": project_id,
                    }
                ],
            )
        except Exception as e:
            logger.error(f"index_conversation_turn failed (project_id={project_id!r}): {e}")

    # -----------------------------------------------------------------------
    # Workspace indexing (cards, project info)
    # -----------------------------------------------------------------------

    async def index_workspace(
        self, project_id: str, cards: list[dict], project_info: dict
    ) -> None:
        """
        Index card titles/descriptions and project info into the workspace collection.
        Re-indexes fully on each call (upsert by card_id).
        """
        if not self._enabled:
            return

        try:
            collection = self._get_or_create_collection(self._col_workspace(project_id))

            ids = []
            documents = []
            metadatas = []

            # Index project info
            project_text = f"Project: {project_info.get('title', '')}\n"
            if project_info.get('description'):
                project_text += f"Description: {project_info['description']}\n"
            if project_info.get('context'):
                project_text += f"Context: {project_info['context']}\n"

            if project_text.strip():
                ids.append(f"workspace__project__{project_id}")
                documents.append(project_text.strip())
                metadatas.append({
                    "source": "workspace",
                    "type": "project_info",
                    "project_id": project_id,
                })

            # Index cards
            for card in cards:
                card_id = card.get('id', '')
                if not card_id:
                    continue

                card_text = f"Card: {card.get('title', '')}\n"
                if card.get('description'):
                    card_text += f"Description: {card['description']}\n"
                if card.get('status'):
                    card_text += f"Status: {card['status']}\n"
                if card.get('agent_type'):
                    card_text += f"Assigned to: {card['agent_type']}\n"

                if card_text.strip():
                    ids.append(f"workspace__card__{card_id}")
                    documents.append(card_text.strip())
                    metadatas.append({
                        "source": "workspace",
                        "type": "card",
                        "card_id": card_id,
                        "project_id": project_id,
                        "card_status": card.get('status', ''),
                    })

            if ids:
                collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
                logger.debug(
                    f"index_workspace: upserted {len(ids)} items for project_id={project_id!r}"
                )

        except Exception as e:
            logger.error(f"index_workspace failed (project_id={project_id!r}): {e}")

    # -----------------------------------------------------------------------
    # Query
    # -----------------------------------------------------------------------

    async def query(
        self, project_id: str, query_text: str, n_results: int = 5
    ) -> list[dict]:
        """
        Query ALL 3 collections, merge results, deduplicate, rank by relevance.

        Returns list of {text, source, score, metadata}.
        """
        if not self._enabled:
            return []

        if not query_text or not query_text.strip():
            return []

        all_results: list[dict] = []

        collection_names = [
            (self._col_docs(project_id), "document"),
            (self._col_history(project_id), "history"),
            (self._col_workspace(project_id), "workspace"),
        ]

        for col_name, source_label in collection_names:
            try:
                collection = self._get_or_create_collection(col_name)
                count = collection.count()
                if count == 0:
                    continue

                results = collection.query(
                    query_texts=[query_text],
                    n_results=min(n_results, count),
                )

                docs = results.get("documents", [[]])[0]
                distances = results.get("distances", [[]])[0]
                metas = results.get("metadatas", [[]])[0]

                for doc, dist, meta in zip(docs, distances, metas):
                    # Convert cosine distance to similarity score (0-1, higher = better)
                    score = max(0.0, 1.0 - dist)
                    all_results.append({
                        "text": doc,
                        "source": source_label,
                        "score": score,
                        "metadata": meta or {},
                    })

            except Exception as e:
                logger.warning(f"query: error querying collection {col_name!r}: {e}")
                continue

        # Deduplicate by text (keep highest score)
        seen_texts: dict[str, dict] = {}
        for item in all_results:
            text_key = item["text"][:200]  # first 200 chars as dedup key
            if text_key not in seen_texts or item["score"] > seen_texts[text_key]["score"]:
                seen_texts[text_key] = item

        # Sort by score descending
        deduped = sorted(seen_texts.values(), key=lambda x: x["score"], reverse=True)

        return deduped[:n_results]

    # -----------------------------------------------------------------------
    # Context building
    # -----------------------------------------------------------------------

    async def _get_inherit_main_context(self, project_id: str) -> bool:
        """Look up the project's inherit_main_context setting from the database."""
        try:
            from app.database import async_session, Project, SYSTEM_MAIN_PROJECT_ID
            if project_id == SYSTEM_MAIN_PROJECT_ID:
                return False
            async with async_session() as session:
                project = await session.get(Project, project_id)
                if project is None:
                    return True  # default
                return bool(project.inherit_main_context)
        except Exception as e:
            logger.warning(f"_get_inherit_main_context failed: {e}")
            return True  # default to inheriting

    async def build_rag_context(
        self, project_id: str, query: str, max_chars: int = 2000
    ) -> Optional[str]:
        """
        Query the project knowledge base and format results into a context string
        suitable for injection into a system prompt.

        When the project's inherit_main_context is True and the project is not
        system-main, also queries the Main project's collections in parallel
        and merges results.

        Returns None if no relevant results found or RAG is disabled.
        """
        if not self._enabled:
            return None

        try:
            from app.database import SYSTEM_MAIN_PROJECT_ID

            inherit = await self._get_inherit_main_context(project_id)

            # Query current project (and optionally Main project in parallel)
            should_query_main = inherit and project_id != SYSTEM_MAIN_PROJECT_ID

            if should_query_main:
                project_results, main_results = await asyncio.gather(
                    self.query(project_id, query, n_results=8),
                    self.query(SYSTEM_MAIN_PROJECT_ID, query, n_results=4),
                )
                # Merge and deduplicate (project results take priority)
                seen_texts: dict[str, dict] = {}
                for item in project_results + main_results:
                    text_key = item["text"][:200]
                    if text_key not in seen_texts or item["score"] > seen_texts[text_key]["score"]:
                        seen_texts[text_key] = item
                results = sorted(seen_texts.values(), key=lambda x: x["score"], reverse=True)[:8]
            else:
                results = await self.query(project_id, query, n_results=8)

            # Filter to reasonably relevant results
            # Threshold calibrated for sentence-transformers/all-MiniLM-L6-v2 (cosine):
            #   unrelated ≈ 0.75-0.83, related ≈ 0.83-0.90, strong match > 0.90
            relevant = [r for r in results if r["score"] > 0.82]

            if not relevant:
                return None

            parts: list[str] = []
            total_chars = 0

            for item in relevant:
                source = item["source"]
                text = item["text"]

                # Format prefix based on source type
                if source == "document":
                    filename = item["metadata"].get("filename", "document")
                    prefix = f"[Doc: {filename}]"
                elif source == "history":
                    role = item["metadata"].get("role", "")
                    prefix = f"[History ({role})]"
                else:
                    item_type = item["metadata"].get("type", "workspace")
                    prefix = f"[{item_type.replace('_', ' ').title()}]"

                entry = f"{prefix} {text}"

                if total_chars + len(entry) > max_chars:
                    # Truncate this entry to fit
                    remaining = max_chars - total_chars
                    if remaining > 100:
                        entry = entry[:remaining] + "…"
                        parts.append(entry)
                    break

                parts.append(entry)
                total_chars += len(entry)

            if not parts:
                return None

            return "\n\n".join(parts)

        except Exception as e:
            logger.error(f"build_rag_context failed (project_id={project_id!r}): {e}")
            return None

    # -----------------------------------------------------------------------
    # Project cleanup
    # -----------------------------------------------------------------------

    def delete_project(self, project_id: str) -> None:
        """Delete all 3 collections for a project."""
        if not self._enabled:
            return

        for col_name in [
            self._col_docs(project_id),
            self._col_history(project_id),
            self._col_workspace(project_id),
        ]:
            try:
                self._client.delete_collection(col_name)
                logger.info(f"delete_project: deleted collection {col_name!r}")
            except Exception as e:
                # Collection may not exist yet — that's fine
                logger.debug(f"delete_project: could not delete {col_name!r}: {e}")

    @property
    def enabled(self) -> bool:
        """Whether RAG is available and initialized."""
        return self._enabled


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    """Return the global RAGService singleton."""
    global _rag_service
    if _rag_service is None:
        _rag_service = RAGService()
    return _rag_service
