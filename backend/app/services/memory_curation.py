"""Memory curation — periodic distillation of chat history into long-term memory.

Honcho-equivalent loop on top of Voxyflow's memory + temporal KG stack.
The per-message extractor (``memory_extraction.auto_extract_memories``) catches
facts as they fly by; this module is the COMPLEMENT — a scheduled job
(``memory_curation`` in ``job_runner``) that periodically re-reads recent chat
sessions per scope, distills *durable* facts about the user and project state
(preferences, corrections, decisions, recurring procedures), and reconciles
them with what's already stored:

- new memories      → ChromaDB, deduped semantically against the scope's collection
- KG facts          → temporal KG, invalidate-then-add so the audit trail survives
- stale candidates  → active KG facts contradicted by the conversation get closed
                      (``valid_to = now``), never hard-deleted

ISOLATION INVARIANTS (CLAUDE.md §Workspace Isolation — sacred):
- Workspace scopes write ONLY to ``memory-workspace-{workspace_uuid}`` and only
  touch KG entities with that ``workspace_id``.
- The general/system-main scope writes to ``memory-global`` (the cross-workspace
  collection reserved for the general chat) and KG entities under
  ``workspace_id='system-main'``.
- A scope NEVER reads or writes another scope's collections. Dedupe lookups use
  the same single collection as the write.

Skills are deliberately NOT touched by curation — pruning/improving skill
descriptions safely needs the full SKILL.md context and user intent, which is
beyond a "trivial" automated edit. (See task brief: "otherwise skip skills
entirely".)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("voxyflow.curation")


# Scope id used for the general / main chat (no workspace).
SYSTEM_MAIN_SCOPE = "system-main"

# First run (no last_curated_at on the job record) looks back this far.
DEFAULT_LOOKBACK_HOURS = 24

# Cap messages fed to the LLM per scope — keeps the one-shot prompt bounded.
MAX_MESSAGES_PER_SCOPE = 80

# Semantic-similarity score above which a candidate memory is considered a
# duplicate of an existing one and skipped (same threshold family as
# memory_extraction's 0.93 — slightly looser since curated text is distilled).
DEDUPE_SCORE_THRESHOLD = 0.92


# ---------------------------------------------------------------------------
# Curation prompt (fast layer, one-shot, JSON-only)
# ---------------------------------------------------------------------------

_CURATION_SYSTEM = """\
You are a memory curator for a personal workspace assistant. You receive a block of
recent conversation messages from ONE scope (the general chat or one workspace) and
must distill the DURABLE facts worth keeping long-term.

Focus on:
- user preferences and corrections ("don't do X", "always Y", "actually it's Z not W")
- decisions and their rationale ("we're going with Postgres")
- project state changes (versions, deployments, renames, ownership)
- recurring procedures the user repeats or refines

Ignore greetings, banter, one-off questions, transient status, and anything already
obvious. The conversation may be French, English, or a mix — keep each memory in the
language it was expressed in, self-contained (no dangling pronouns).

Respond with ONE JSON object only — no markdown, no code fence, no commentary:

{
  "new_memories": [
    {"content": "...", "type": "decision|preference|fact|lesson|procedure", "importance": "high|medium|low"}
  ],
  "kg_facts": [
    {"entity": "Redis", "entity_type": "technology", "attribute": "version", "value": "7"},
    {"entity": "auth-service", "entity_type": "component", "relation": "depends_on", "target": "JWT", "target_type": "technology"}
  ],
  "stale_candidates": [
    {"entity": "Redis", "attribute": "version", "value": "6"},
    {"entity": "auth-service", "relation": "depends_on", "target": "Memcached"}
  ]
}

Rules:
- "kg_facts" carry the CURRENT truth: an attribute fact has entity+attribute+value;
  a relationship fact has entity+relation+target.
- "stale_candidates" list existing facts the conversation CONTRADICTS (the old value
  of a changed attribute, a relationship that ended). Only include facts that were
  plausibly stored before — not random guesses.
- Be conservative: an empty list is a fine answer. Quality over quantity.
- Every list may be empty; always include all three keys.
"""

_CURATION_USER_TEMPLATE = """\
Scope: {scope_label}

Recent conversation messages (oldest first):

{messages_block}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collection_for_scope(scope_id: str) -> str:
    """Return the ONE ChromaDB collection a curation scope may touch.

    - workspace UUID  → memory-workspace-{uuid}
    - system-main     → memory-global (general-chat cross-workspace memory)
    """
    from app.services.memory_service_constants import (
        GLOBAL_COLLECTION,
        _workspace_collection,
    )
    if not scope_id or scope_id == SYSTEM_MAIN_SCOPE:
        return GLOBAL_COLLECTION
    return _workspace_collection(scope_id)


def _parse_ts(value) -> Optional[datetime]:
    """Parse a message/job timestamp into an aware UTC datetime, or None."""
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(value, tz=timezone.utc)
        dt = datetime.fromisoformat(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def _messages_since(chat_id: str, since: datetime) -> list[dict]:
    """Load user/assistant messages newer than ``since`` for a chat session."""
    from app.services.session_store import session_store

    messages = session_store.load_session(chat_id)
    out: list[dict] = []
    for m in messages:
        if m.get("role") not in ("user", "assistant"):
            continue
        content = (m.get("content") or "").strip()
        if not content:
            continue
        if m.get("type") in ("enrichment", "worker_result", "nl_task_result"):
            continue
        ts = _parse_ts(m.get("timestamp"))
        if ts is not None and ts <= since:
            continue
        out.append({"role": m["role"], "content": content})
    return out[-MAX_MESSAGES_PER_SCOPE:]


async def _workspace_ids() -> list[str]:
    """All workspace UUIDs from the DB (curation checks each for activity)."""
    from sqlalchemy import select
    from app.database import Workspace, async_session

    async with async_session() as db:
        rows = (await db.execute(select(Workspace.id))).scalars().all()
    return [str(r) for r in rows]


# ---------------------------------------------------------------------------
# LLM call — fast layer one-shot (same pattern as oneshot_generators)
# ---------------------------------------------------------------------------


async def _llm_curate(messages_block: str, scope_label: str) -> Optional[dict]:
    """One-shot fast-layer call. Returns the parsed curation dict or None on failure."""
    try:
        from app.services.claude_service import ClaudeService

        claude = ClaudeService()
        user_prompt = _CURATION_USER_TEMPLATE.format(
            scope_label=scope_label, messages_block=messages_block
        )
        raw = await claude._call_api(
            model=claude.fast_model,
            system=_CURATION_SYSTEM,
            messages=[{"role": "user", "content": user_prompt}],
            client=claude.fast_client,
            client_type=claude.fast_client_type,
            use_tools=False,
        )
        if not raw or not raw.strip():
            logger.warning("[Curation] empty LLM response for scope %s", scope_label)
            return None
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0].strip()
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            logger.warning("[Curation] LLM returned %s, expected object", type(parsed).__name__)
            return None
        return {
            "new_memories": parsed.get("new_memories") or [],
            "kg_facts": parsed.get("kg_facts") or [],
            "stale_candidates": parsed.get("stale_candidates") or [],
        }
    except json.JSONDecodeError as e:
        logger.warning("[Curation] JSON parse error for scope %s: %s", scope_label, e)
        return None
    except Exception as e:
        logger.warning("[Curation] LLM call failed for scope %s: %s", scope_label, e)
        return None


# ---------------------------------------------------------------------------
# KG reconciliation (invalidate-then-add — preserves temporal audit trail)
# ---------------------------------------------------------------------------


async def _active_attributes(kg, scope_id: str, entity: str, key: str) -> list[dict]:
    """Active (valid_to IS NULL) attributes for an entity, matched by key."""
    rows = await kg.get_timeline(scope_id, entity_name=entity, limit=200)
    ent_l = entity.strip().lower()
    return [
        r for r in rows
        if r.get("kind") == "attribute"
        and (r.get("subject") or "").strip().lower() == ent_l
        and r.get("predicate") == key
        and r.get("valid_to") is None
    ]


async def _apply_kg_fact(kg, scope_id: str, fact: dict) -> str:
    """Apply one curated KG fact. Returns 'added' | 'updated' | 'unchanged' | 'skipped'.

    Attribute facts use invalidate-then-add: the old active value is closed
    (valid_to = now) and the new one inserted, so kg.timeline keeps the full
    history while kg.query shows only the present state.
    """
    entity = (fact.get("entity") or "").strip()
    if not entity:
        return "skipped"
    etype = (fact.get("entity_type") or "concept").strip() or "concept"

    attribute = (fact.get("attribute") or "").strip()
    if attribute:
        value = str(fact.get("value") if fact.get("value") is not None else "").strip()
        if not value:
            return "skipped"
        eid = await kg.add_entity(entity, etype, scope_id)
        current = await _active_attributes(kg, scope_id, entity, attribute)
        if any(str(a.get("object") or "").strip() == value for a in current):
            return "unchanged"
        for a in current:
            await kg.invalidate(attribute_id=a["id"], workspace_id=scope_id)
        await kg.add_attribute(eid, attribute, value)
        return "updated" if current else "added"

    relation = (fact.get("relation") or "").strip()
    target = (fact.get("target") or "").strip()
    if relation and target:
        subj_id = await kg.add_entity(entity, etype, scope_id)
        obj_id = await kg.add_entity(
            target, (fact.get("target_type") or "concept").strip() or "concept", scope_id
        )
        rels = await kg.query_relationships(
            scope_id, entity_name=entity, predicate=relation, limit=100
        )
        ent_l, tgt_l = entity.lower(), target.lower()
        if any(
            (r.get("subject") or "").lower() == ent_l
            and (r.get("object") or "").lower() == tgt_l
            for r in rels
        ):
            return "unchanged"
        await kg.add_triple(subj_id, relation, obj_id, source="curation")
        return "added"

    return "skipped"


async def _invalidate_stale(kg, scope_id: str, cand: dict) -> int:
    """Close active KG facts matching a stale candidate. Returns count invalidated."""
    entity = (cand.get("entity") or "").strip()
    if not entity:
        return 0
    invalidated = 0

    attribute = (cand.get("attribute") or "").strip()
    if attribute:
        value = cand.get("value")
        value_s = str(value).strip() if value is not None else None
        for a in await _active_attributes(kg, scope_id, entity, attribute):
            if value_s and str(a.get("object") or "").strip() != value_s:
                continue
            if await kg.invalidate(attribute_id=a["id"], workspace_id=scope_id):
                invalidated += 1
        return invalidated

    relation = (cand.get("relation") or "").strip()
    if relation:
        target = (cand.get("target") or "").strip().lower()
        ent_l = entity.lower()
        rels = await kg.query_relationships(
            scope_id, entity_name=entity, predicate=relation, limit=100
        )
        for r in rels:
            if (r.get("subject") or "").lower() != ent_l:
                continue
            if target and (r.get("object") or "").lower() != target:
                continue
            if await kg.invalidate(triple_id=r["id"], workspace_id=scope_id):
                invalidated += 1
    return invalidated


# ---------------------------------------------------------------------------
# Per-scope curation
# ---------------------------------------------------------------------------


async def curate_scope(scope_id: str, messages: list[dict]) -> dict:
    """Curate one scope: LLM distillation + memory writes + KG reconciliation.

    Only ever touches ``_collection_for_scope(scope_id)`` and KG facts under
    ``workspace_id == scope_id``. Returns a counts dict.
    """
    from app.services.memory_service import get_memory_service
    from app.services.memory_service_constants import (
        VALID_IMPORTANCE,
        VALID_TYPES,
        _format_messages_for_extraction,
    )

    counts = {
        "scope": scope_id,
        "messages": len(messages),
        "memories_added": 0,
        "memories_deduped": 0,
        "kg_added": 0,
        "kg_updated": 0,
        "kg_unchanged": 0,
        "kg_invalidated": 0,
    }

    block = _format_messages_for_extraction(messages)
    if not block.strip():
        return counts

    data = await _llm_curate(block, scope_label=scope_id)
    if data is None:
        counts["error"] = "llm_failed"
        return counts

    # --- Memories (deduped against the scope's OWN collection only) ---------
    ms = get_memory_service()
    collection = _collection_for_scope(scope_id)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for item in data["new_memories"]:
        if not isinstance(item, dict):
            continue
        content = (item.get("content") or "").strip()
        if not content or len(content) < 15:
            continue
        mem_type = item.get("type") if item.get("type") in VALID_TYPES else "fact"
        importance = (
            item.get("importance") if item.get("importance") in VALID_IMPORTANCE else "medium"
        )
        try:
            existing = ms.search_memory(query=content, collections=[collection], limit=1)
        except Exception as e:  # noqa: BLE001 — dedupe failure must not block the write
            logger.debug("[Curation] dedupe lookup failed (%s) — storing anyway", e)
            existing = []
        if existing and existing[0].get("score", 0) > DEDUPE_SCORE_THRESHOLD:
            counts["memories_deduped"] += 1
            continue
        doc_id = ms.store_memory(
            text=content,
            collection=collection,
            metadata={
                "type": mem_type,
                "importance": importance,
                "date": today,
                "source": "curation",
                "speaker": "user",
                "workspace_id": scope_id,
            },
        )
        if doc_id:
            counts["memories_added"] += 1

    # --- KG facts (invalidate-then-add) + stale closure ----------------------
    try:
        from app.services.knowledge_graph_service import get_knowledge_graph_service

        kg = get_knowledge_graph_service()
        for fact in data["kg_facts"]:
            if not isinstance(fact, dict):
                continue
            try:
                outcome = await _apply_kg_fact(kg, scope_id, fact)
            except Exception as e:  # noqa: BLE001 — one bad fact never aborts the scope
                logger.warning("[Curation] kg fact failed (%s): %s", fact, e)
                continue
            if outcome == "added":
                counts["kg_added"] += 1
            elif outcome == "updated":
                counts["kg_updated"] += 1
                counts["kg_invalidated"] += 1
            elif outcome == "unchanged":
                counts["kg_unchanged"] += 1

        for cand in data["stale_candidates"]:
            if not isinstance(cand, dict):
                continue
            try:
                counts["kg_invalidated"] += await _invalidate_stale(kg, scope_id, cand)
            except Exception as e:  # noqa: BLE001
                logger.warning("[Curation] stale candidate failed (%s): %s", cand, e)
    except Exception as e:  # noqa: BLE001 — KG layer down must not lose the memories
        logger.warning("[Curation] KG reconciliation unavailable for %s: %s", scope_id, e)

    return counts


# ---------------------------------------------------------------------------
# Job entry point
# ---------------------------------------------------------------------------


async def run_memory_curation(job: dict, payload: dict) -> dict:
    """Execute one curation pass over all scopes with chat activity since last run.

    Scopes: the general chat (``system-main``) first, then every workspace whose
    ``workspace:{uuid}`` session has messages newer than ``last_curated_at``
    (a top-level field on the job record, updated after each run).
    """
    now = datetime.now(timezone.utc)
    since = (
        _parse_ts(job.get("last_curated_at"))
        or _parse_ts(payload.get("last_curated_at"))
        or now - timedelta(hours=DEFAULT_LOOKBACK_HOURS)
    )

    scope_ids = [SYSTEM_MAIN_SCOPE]
    try:
        scope_ids.extend(await _workspace_ids())
    except Exception as e:  # noqa: BLE001 — DB down: still curate the general chat
        logger.warning("[Curation] could not list workspaces: %s", e)

    results: list[dict] = []
    for scope_id in scope_ids:
        chat_id = f"workspace:{scope_id}"
        try:
            messages = _messages_since(chat_id, since)
        except Exception as e:  # noqa: BLE001
            logger.warning("[Curation] could not read session %s: %s", chat_id, e)
            continue
        if not messages:
            continue
        logger.info(
            "[Curation] scope=%s — %d message(s) since %s", scope_id, len(messages), since
        )
        results.append(await curate_scope(scope_id, messages))

    # Persist the watermark on the job record (best-effort).
    job_id = job.get("id")
    if job_id:
        try:
            from app.services.job_runner import update_job_fields
            import asyncio

            await asyncio.to_thread(update_job_fields, job_id, last_curated_at=now.isoformat())
        except Exception as e:  # noqa: BLE001
            logger.warning("[Curation] could not persist last_curated_at: %s", e)

    totals = {
        "memories_added": sum(r["memories_added"] for r in results),
        "memories_deduped": sum(r["memories_deduped"] for r in results),
        "kg_added": sum(r["kg_added"] for r in results),
        "kg_updated": sum(r["kg_updated"] for r in results),
        "kg_invalidated": sum(r["kg_invalidated"] for r in results),
    }
    message = (
        f"Curated {len(results)} scope(s): "
        f"+{totals['memories_added']} memories ({totals['memories_deduped']} dupes skipped), "
        f"KG +{totals['kg_added']}/~{totals['kg_updated']} updated/"
        f"{totals['kg_invalidated']} invalidated"
    )
    logger.info("[Curation] %s", message)
    return {"status": "ok", "message": message, "scopes": results, **totals}
