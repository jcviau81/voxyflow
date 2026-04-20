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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.services.memory_service_constants import (
    GLOBAL_COLLECTION,
    MEMORY_DIR,
    MEMORY_FILE,
    _project_collection,
    _slugify,
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

    @staticmethod
    def _attribution_prefix(meta: dict) -> str:
        """Build `[speaker · timestamp · scope · importance=x]` prefix.

        Speaker resolution:
          1. explicit ``speaker`` field (new saves post-April 2026)
          2. fallback on ``source`` for legacy entries:
             - "chat"          → Voxy said (dispatcher memory_save)
             - "manual"        → JC said (user-authored CLI / manual entry)
             - "worker"        → worker:<id>
             - "auto-extract"  → Voxy auto (pre-migration auto extractions)
             - "worker_summary"→ worker summary
          3. otherwise → "unknown said"

        The fallback is inference-only (no data mutation), so a backfill
        can replace it later without breaking anything.
        """
        meta = meta or {}
        speaker = str(meta.get("speaker") or "").strip().lower()
        source = str(meta.get("source") or "").strip().lower()
        worker_id = str(meta.get("worker_id") or "").strip()
        if speaker == "user":
            speaker_label = "JC said"
        elif speaker == "assistant":
            speaker_label = "Voxy said"
        elif speaker == "worker" or source == "worker":
            speaker_label = f"worker:{worker_id}" if worker_id else "worker"
        elif speaker == "system":
            speaker_label = "system"
        elif source == "chat":
            speaker_label = "Voxy said"
        elif source == "manual":
            speaker_label = "JC said"
        elif source == "auto-extract":
            speaker_label = "Voxy auto"
        elif source == "worker_summary":
            speaker_label = "worker summary"
        else:
            speaker_label = "unknown said"

        ts = (
            meta.get("created_at")
            or meta.get("date")
            or "unknown"
        )
        ts = str(ts).strip() or "unknown"
        # Trim ISO timestamps to date portion for readability.
        if len(ts) >= 10 and ts[4] == "-" and ts[7] == "-":
            ts = ts[:10]

        scope = (
            meta.get("chat_id")
            or meta.get("card_id")
            or (f"card:{meta['card_id']}" if meta.get("card_id") else None)
            or meta.get("project_id")
            or meta.get("project")
            or "unknown"
        )
        scope = str(scope).strip() or "unknown"

        importance = str(meta.get("importance") or "unknown").strip() or "unknown"
        return f"[{speaker_label} · {ts} · {scope} · importance={importance}]"

    def _format_memory_line(self, result: dict) -> str:
        """Render one retrieved fragment as an attributed bullet."""
        meta = dict(result.get("metadata") or {})
        # Backfill scope from the collection name for legacy entries that
        # lack chat_id / project_id in metadata. Collection format is always
        # ``memory-project-<project_id>`` (incl. "system-main") or the
        # reserved ``memory-global`` sentinel.
        collection = str(result.get("collection") or "")
        has_scope = any(meta.get(k) for k in ("chat_id", "card_id", "project_id", "project"))
        if not has_scope and collection:
            if collection.startswith("memory-project-"):
                meta["project_id"] = collection[len("memory-project-"):]
            elif collection == "memory-global":
                meta["project_id"] = "global"
        prefix = self._attribution_prefix(meta)
        text = (result.get("text") or "").strip()
        combined = result.get("_combined_score")
        if combined is not None:
            prefix = prefix[:-1] + f" · score={combined}]"
        return f"- {prefix} {text}"

    L2_RECENCY_HALF_LIFE_DAYS = 14.0
    L2_RECENCY_MISSING_TS_WEIGHT = 0.5

    @classmethod
    def _recency_weight(cls, meta: dict) -> float:
        """Exponential decay weight from a fragment's created_at / date.

        weight = 0.5 ** (age_days / HALF_LIFE). Missing/unparseable timestamp
        → MISSING_TS_WEIGHT (treated as moderately stale, not pinned). Future
        timestamps clamp to now.
        """
        meta = meta or {}
        raw = meta.get("created_at") or meta.get("date") or ""
        raw = str(raw).strip()
        if not raw:
            return cls.L2_RECENCY_MISSING_TS_WEIGHT
        try:
            if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
                ts = datetime.fromisoformat(raw + "T00:00:00+00:00")
            else:
                ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
        except Exception:
            return cls.L2_RECENCY_MISSING_TS_WEIGHT
        now = datetime.now(timezone.utc)
        age_seconds = max(0.0, (now - ts).total_seconds())
        age_days = age_seconds / 86400.0
        return 0.5 ** (age_days / cls.L2_RECENCY_HALF_LIFE_DAYS)

    @classmethod
    def _rerank_by_recency(cls, results: list[dict]) -> list[dict]:
        """Re-order semantic results by ``score * recency_weight`` (desc).

        Keeps the same entries (no filtering) — just floats fresh facts up so
        the L2 hard cap lands on recent evidence when semantic scores are close.
        """
        if not results:
            return results
        def _combined(r: dict) -> float:
            base = float(r.get("score") or 0.0)
            return base * cls._recency_weight(r.get("metadata") or {})
        return sorted(results, key=_combined, reverse=True)

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

    def _build_procedures_block(
        self,
        query: str,
        project_id: Optional[str],
        budget: int,
    ) -> tuple[Optional[str], set[str]]:
        """Procedural memory: reusable "how to do X" patterns.

        Filters by ``type=procedure`` and renders matches in a dedicated
        block (not mixed with fact/decision bullets). Returns up to 3
        procedures ranked by semantic relevance to the query.

        Returns (rendered_block_or_None, ids_used) so L2 can dedup.
        """
        MAX_PROCEDURES = 3
        try:
            # General chat (no project / system-main) may have saved procedures
            # to GLOBAL_COLLECTION; project chats stay in their own collection.
            if project_id and project_id != "system-main":
                collections = [_project_collection(project_id)]
            else:
                collections = [GLOBAL_COLLECTION, _project_collection("system-main")]
            results = self.search_memory(
                query=query,
                collections=collections,
                filters={"type": "procedure"},
                limit=MAX_PROCEDURES,
            )
            if not results:
                return None, set()
            blocks: list[str] = []
            ids_used: set[str] = set()
            token_count = 0
            for r in results:
                text = (r.get("text") or "").strip()
                if not text:
                    continue
                meta = r.get("metadata") or {}
                date_str = str(meta.get("created_at") or meta.get("date") or "")[:10] or "unknown"
                header = f"_({date_str})_"
                block = f"{header}\n{text}"
                block_tokens = self._estimate_tokens(block)
                if token_count + block_tokens > budget:
                    break
                blocks.append(block)
                ids_used.add(r.get("id", ""))
                token_count += block_tokens
            if not blocks:
                return None, set()
            return "**Known procedures:**\n" + "\n\n".join(blocks), ids_used
        except Exception:
            logger.debug("_build_procedures_block failed", exc_info=True)
            return None, set()

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

            from app.services.memory_extraction import _is_actionable_memory
            from app.services.memory_service_constants import _high_importance_justified

            lines: list[str] = []
            ids_used: set[str] = set()
            texts_used: set[str] = set()
            token_count = 0
            for r in results:
                norm = self._normalize_for_dedup(r["text"])
                if norm in texts_used:
                    continue
                # Retro-filter conversational closers on L1 too — they were
                # often classified `importance=high` before the extraction
                # gate existed, so they sneak into essentials otherwise.
                text_val = str(r.get("text") or "")
                if not _is_actionable_memory(text_val):
                    continue
                # Legacy high-importance cleanup: drop entries tagged `high`
                # that carry none of the strong signals (no decision verb,
                # deadline, absolute preference, security hit, root-cause).
                # They're the jokes and mood reactions that slipped past the
                # old classifier. They remain searchable via memory.search.
                if not _high_importance_justified(text_val):
                    continue
                # #12 annotate combined score on L1 too — same format as L2
                # so Voxy can compare relative weights across tiers.
                score = float(r.get("score") or 0.0)
                recency = self._recency_weight(r.get("metadata") or {})
                r["_combined_score"] = round(score * recency, 3)
                line = self._format_memory_line(r)
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
        """L2: Full semantic search, tightened filters. Deduplicates against L1.

        Tightened (April 2026): cap at 3 entries, exclude low-importance and
        worker_summary auto-extracts. This is the ambient retrieval block —
        Voxy gets `memory.search` on demand for anything beyond that.
        """
        L2_HARD_CAP = 3
        sections: list[str] = []
        display_label = project_name or project_id or ""
        l1_ids = l1_ids or set()
        l1_texts = l1_texts or set()
        remaining = budget
        seen_texts: set[str] = set(l1_texts)
        total_kept = 0

        # Over-fetch from Chroma (no composite where clause — some versions
        # reject `$and` + `$nin` combos with "Error finding id"). Apply the
        # importance/source filter in Python. Cheap: we fetch ≤20 rows max.
        FETCH_N = 20
        ALLOWED_IMPORTANCE = {"high", "medium"}
        BLOCKED_SOURCES = {"worker_summary"}
        MAX_AGE_DAYS = 90  # #2: hard cutoff — anything older than 90 days drops
        PERTINENCE_FLOOR = 0.15  # #17: drop score×recency below this — noise

        def _age_days(meta: dict) -> float | None:
            raw = (meta or {}).get("created_at") or (meta or {}).get("date") or ""
            raw = str(raw).strip()
            if not raw:
                return None
            try:
                if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
                    ts = datetime.fromisoformat(raw + "T00:00:00+00:00")
                else:
                    ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except Exception:
                return None
            return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0)

        from app.services.memory_extraction import _is_actionable_memory

        def _python_filter(results: list[dict]) -> list[dict]:
            keep = []
            for r in results:
                meta = r.get("metadata") or {}
                if str(meta.get("importance") or "").lower() not in ALLOWED_IMPORTANCE:
                    continue
                if str(meta.get("source") or "").lower() in BLOCKED_SOURCES:
                    continue
                # Retro-filter conversational fluff that slipped in before the
                # extraction-time gate existed. Legacy entries get evaluated
                # against the same heuristic as new writes.
                if not _is_actionable_memory(str(r.get("text") or "")):
                    continue
                # #2 hard age cutoff — honest timestamps only; missing ts passes
                # through (we can't punish legacy data without a backfill).
                age = _age_days(meta)
                if age is not None and age > MAX_AGE_DAYS:
                    continue
                # #17 pertinence floor — score × recency must clear the bar.
                score = float(r.get("score") or 0.0)
                recency = self._recency_weight(meta)
                if score * recency < PERTINENCE_FLOOR:
                    continue
                r["_combined_score"] = round(score * recency, 3)
                keep.append(r)
            return keep

        def _cap_results(results: list[dict]) -> list[str]:
            nonlocal remaining, total_kept
            lines: list[str] = []
            filtered = _python_filter(results)
            ranked = self._rerank_by_recency(filtered)
            for r in ranked:
                if total_kept >= L2_HARD_CAP:
                    break
                if r["id"] in l1_ids:
                    continue
                norm = self._normalize_for_dedup(r["text"])
                if norm in seen_texts:
                    continue
                line = self._format_memory_line(r)
                t = self._estimate_tokens(line)
                if remaining - t < 0:
                    break
                lines.append(line)
                seen_texts.add(norm)
                remaining -= t
                total_kept += 1
            return lines

        if project_id and card_id:
            proj_col = _project_collection(project_id)
            card_results = self.search_memory(
                query=query, collections=[proj_col],
                filters={"card_id": card_id}, limit=FETCH_N,
            )
            if card_results:
                lines = _cap_results(card_results)
                if lines:
                    sections.append(
                        f"**Card memory ({display_label}):**\n" + "\n".join(lines)
                    )

            if total_kept < L2_HARD_CAP:
                proj_results = self.search_memory(
                    query=query, collections=[proj_col], limit=FETCH_N,
                )
                if proj_results:
                    card_ids = {r["id"] for r in card_results} if card_results else set()
                    proj_unique = [r for r in proj_results if r["id"] not in card_ids]
                    lines = _cap_results(proj_unique)
                    if lines:
                        sections.append(
                            f"**Project memory ({display_label}):**\n" + "\n".join(lines)
                        )

        elif project_id:
            proj_col = _project_collection(project_id)
            proj_results = self.search_memory(
                query=query, collections=[proj_col], limit=FETCH_N,
            )
            if proj_results:
                lines = _cap_results(proj_results)
                if lines:
                    sections.append(
                        f"**Project memory ({display_label}):**\n" + "\n".join(lines)
                    )

        else:
            main_col = _project_collection("system-main")
            search_cols = (
                [main_col, GLOBAL_COLLECTION] if include_long_term else [main_col]
            )
            main_results = self.search_memory(
                query=query, collections=search_cols, limit=FETCH_N,
            )
            if main_results:
                lines = _cap_results(main_results)
                if lines:
                    sections.append("**Relevant memory:**\n" + "\n".join(lines))

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
        proc_ids: set[str] = set()

        try:
            # L0: Project identity from KG pinned cache
            if 0 in layers:
                l0 = self._build_l0_identity(project_id)
                if l0:
                    sections.append(l0)
                    remaining -= self._estimate_tokens(l0)

            # Procedural: reusable "how to do X" blocks, surfaced above L1/L2.
            # Separate section so Voxy can spot them when about to execute.
            if 1 in layers and remaining > 50:
                proc, proc_ids = self._build_procedures_block(
                    query, project_id, min(300, remaining),
                )
                if proc:
                    sections.append(proc)
                    remaining -= self._estimate_tokens(proc)

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
                    l1_ids=l1_ids | proc_ids,
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


