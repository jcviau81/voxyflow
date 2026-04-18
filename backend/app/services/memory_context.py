"""Memory context-building — extracted from memory_service.

Builds the combined memory context string that gets injected into system
prompts. Supports three tiers:
  L0 — pinned KG entities (identity)
  L1 — high-importance recent memories (essentials)
  L2 — full semantic search (on-demand)

Also handles the file-based fallback path for when ChromaDB is
unavailable. Split from MemoryService (April 2026 code-review pass).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.services.memory_service_constants import (
    GLOBAL_COLLECTION,
    MEMORY_DIR,
    MEMORY_FILE,
    _project_collection,
)

logger = logging.getLogger(__name__)


class MemoryContextMixin:
    """Mixin: build memory context strings for system-prompt injection."""

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

    @staticmethod
    def _normalize_for_dedup(text: str) -> str:
        return " ".join(text.lower().split())

    def _build_l1_essentials(
        self,
        query: str,
        project_id: Optional[str],
        card_id: Optional[str],
        budget: int,
    ) -> tuple[Optional[str], set[str], set[str]]:
        """L1: High-importance recent memories (essentials). Budget-capped.

        Returns (rendered_text_or_None, ids_included, normalized_texts_included).
        The two sets feed L2 dedup so the same fact isn't echoed twice.
        """
        try:
            if not project_id:
                return None, set(), set()

            proj_col = _project_collection(project_id)
            results = self.search_memory(
                query=query,
                collections=[proj_col],
                filters={"importance": "high"},
                limit=5,
            )
            if not results:
                return None, set(), set()

            lines: list[str] = []
            ids_used: set[str] = set()
            texts_used: set[str] = set()
            token_count = 0
            for r in results:
                norm = self._normalize_for_dedup(r["text"])
                if norm in texts_used:
                    continue
                line = f"- {r['text']}"
                line_tokens = self._estimate_tokens(line)
                if token_count + line_tokens > budget:
                    break
                lines.append(line)
                ids_used.add(r["id"])
                texts_used.add(norm)
                token_count += line_tokens

            if not lines:
                return None, set(), set()
            return f"**Key facts ({project_id}):**\n" + "\n".join(lines), ids_used, texts_used
        except Exception as e:
            logger.debug(f"_build_l1_essentials failed: {e}")
            return None, set(), set()

    def _build_l2_ondemand(
        self,
        query: str,
        project_name: Optional[str],
        project_id: Optional[str],
        card_id: Optional[str],
        include_long_term: bool,
        budget: int,
        l1_ids: set[str] | None = None,
        l1_texts: set[str] | None = None,
    ) -> Optional[str]:
        """L2: Full semantic search (current behavior, budget-capped). Deduplicates against L1."""
        sections: list[str] = []
        display_label = project_name or project_id or ""
        l1_ids = l1_ids or set()
        l1_texts = l1_texts or set()
        remaining = budget
        seen_texts: set[str] = set(l1_texts)

        def _cap_results(results: list[dict], cap: int) -> list[str]:
            nonlocal remaining
            texts = []
            for r in results:
                if r["id"] in l1_ids:
                    continue
                norm = self._normalize_for_dedup(r["text"])
                if norm in seen_texts:
                    continue
                line = r["text"]
                t = self._estimate_tokens(line)
                if remaining - t < 0:
                    break
                texts.append(line)
                seen_texts.add(norm)
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
        l1_texts: set[str] = set()

        try:
            # L0: Project identity from KG pinned cache
            if 0 in layers:
                l0 = self._build_l0_identity(project_id)
                if l0:
                    sections.append(l0)
                    remaining -= self._estimate_tokens(l0)

            # L1: High-importance essentials (also returns IDs+texts for L2 dedup)
            if 1 in layers and remaining > 50:
                l1, l1_ids, l1_texts = self._build_l1_essentials(
                    query, project_id, card_id, min(400, remaining),
                )
                if l1:
                    sections.append(l1)
                    remaining -= self._estimate_tokens(l1)

            # L2: Full semantic search — dedup by both ID (exact) and text (near-dup)
            if 2 in layers and remaining > 50:
                l2 = self._build_l2_ondemand(
                    query, project_name, project_id, card_id,
                    include_long_term, min(remaining, 800),
                    l1_ids=l1_ids,
                    l1_texts=l1_texts,
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


