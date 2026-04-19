"""Memory auto-extraction — extracted from memory_service.

Handles the LLM-driven extraction pipeline that turns conversation
exchanges into structured memory entries (decisions, preferences, facts,
lessons). Also contains the regex fast-path used both as a cost-saving
pre-filter and as a fallback when the LLM call fails.

Split from MemoryService (April 2026 code-review pass). The methods
here are mixed into MemoryService — they depend on ``self.store_memory``,
``self._chromadb_enabled``, ``self._extraction_counters``, and
``self.EXTRACTION_INTERVAL`` being defined on the base class.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from app.services.memory_service_constants import (
    GLOBAL_COLLECTION,
    VALID_IMPORTANCE,
    VALID_TYPES,
    _classify_text,
    _format_messages_for_extraction,
    _high_importance_justified,
    _MEMORY_EXTRACTION_SYSTEM,
    _MEMORY_EXTRACTION_USER_TEMPLATE,
    _project_collection,
)

logger = logging.getLogger(__name__)


_CONVERSATIONAL_PREFIX_RE = re.compile(
    # Open with first-person "I'll / I'm going to / I'll log / tu veux / je vais / je te / dis-moi / check / peux-tu"
    r"^\s*(?:je\s+(?:vais|te|peux|pense)|tu\s+(?:veux|peux|sais)|"
    r"peux[- ]tu|veux[- ]tu|"
    r"dis[- ]moi|check|regarde|vois|voici|voilà|"
    r"i['’]?ll|i['’]?m\s+going\s+to|let\s+me|should\s+i|"
    r"can\s+you|could\s+you|would\s+you|want\s+me\s+to)\b",
    re.IGNORECASE,
)

_QUESTION_TAIL_RE = re.compile(r"[?？]\s*$")

# Conversational closings / handoff fluff — "dis-moi", "je suis là", "tell me",
# "let me know", "on continue", etc. Applied to the last 60 chars of the text.
# Short closers with no substance die; long factual sentences that happen to
# end in a friendly sign-off survive (overall length gate is 150 chars).
_CLOSING_FLUFF_RE = re.compile(
    r"(?:^|[\s,;:—–])\s*(?:"
    r"dis[- ]moi(?:\s+\w+){0,3}|"
    r"je\s+suis(?:\s+(?:l[àa]|dispo|pr[êe]t|pr[êe]te|avec\s+toi))?|"
    r"on\s+(?:continue|y\s+va|avance|reprend)(?:\s+\w+){0,2}|"
    r"tu\s+me\s+(?:dis|diras|fais\s+signe)(?:\s+\w+){0,2}|"
    r"let\s+me\s+know(?:\s+\w+){0,3}|"
    r"tell\s+me(?:\s+\w+){0,3}|"
    r"i['’]?m\s+here|"
    r"ping\s+me(?:\s+\w+){0,3}"
    r")\s*[\.!…]*\s*$",
    re.IGNORECASE,
)


def _is_actionable_memory(text: str) -> bool:
    """Reject conversational utterances that leak into memory as "facts".

    Heuristic gate — runs before every store in the extraction pipeline.
    Rules (all must pass):
      - Not a question (doesn't end with `?`)
      - Not short conversational-prefix speech ("je vais…", "tu veux…",
        "can you…", "let me…") under 80 chars
      - Not a handoff closer ("dis-moi", "je suis là", "let me know", …)
        when the tail text that *follows* the em-dash/comma is mostly that
        closer with no substance.
      - Has ≥ 4 words (single-token exclamations die)
    """
    t = (text or "").strip()
    if not t:
        return False
    if _QUESTION_TAIL_RE.search(t):
        return False
    if len(t.split()) < 4:
        return False
    if len(t) < 80 and _CONVERSATIONAL_PREFIX_RE.match(t):
        return False
    # Closing fluff: if the text ends with a conversational handoff and is
    # short-to-medium length, it's a sign-off masquerading as a fact.
    if len(t) <= 150 and _CLOSING_FLUFF_RE.search(t):
        return False
    return True


class MemoryExtractionMixin:
    """Mixin: auto-extract memories from chat exchanges."""

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
                # Upstream conversational filter — drop rhetorical questions
                # and short conversational prompts before they poison memory.
                if not _is_actionable_memory(content):
                    logger.debug(f"auto_extract[LLM]: skipped non-actionable: {content[:80]}")
                    continue

                # Normalize type to valid set
                if mem_type not in VALID_TYPES:
                    mem_type = "fact"
                if importance not in VALID_IMPORTANCE:
                    importance = "medium"
                # Safety net: if LLM tagged this `high` but the text carries
                # no strong signal (decision verb, deadline, absolute pref,
                # security/compliance, root-cause), downgrade to medium.
                if importance == "high" and not _high_importance_justified(content):
                    logger.debug(
                        f"auto_extract[LLM]: downgrading high→medium (no strong signal): {content[:80]}"
                    )
                    importance = "medium"

                speaker = str(item.get("speaker", "")).strip().lower()
                if speaker not in {"user", "assistant"}:
                    speaker = "unknown"
                metadata = {
                    "type": mem_type,
                    "date": today,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "source": "worker_summary",
                    "speaker": speaker,
                    "importance": importance,
                    "confidence": round(confidence, 2),
                }
                metadata["project"] = target_project_id
                metadata["project_id"] = target_project_id

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

                if not _is_actionable_memory(sentence):
                    logger.debug(f"auto_extract[regex]: skipped non-actionable: {sentence[:80]}")
                    continue

                msg_role = (msg.get("role") or "").strip().lower()
                speaker = msg_role if msg_role in {"user", "assistant"} else "unknown"
                metadata = {
                    "type": mem_type,
                    "date": today,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "source": "worker_summary",
                    "speaker": speaker,
                    "importance": importance,
                }
                metadata["project"] = target_project_id
                metadata["project_id"] = target_project_id

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


