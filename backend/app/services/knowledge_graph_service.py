"""Knowledge Graph service — entity/relationship store with temporal bounds.

Temporal model
--------------
Triples (relationships) and attributes carry two time columns:

  valid_from  DATETIME NOT NULL  — when the fact became true (set to now() on INSERT)
  valid_to    DATETIME NULL      — when the fact stopped being true (NULL = still active)

The pair forms a half-open interval **[valid_from, valid_to)**:
  - A row with valid_to IS NULL is **current** — it represents the present state.
  - A row with valid_to set is **historical** — it was true during that window.
  - Calling ``invalidate(triple_id=...)`` sets valid_to = now(), closing the fact.

Entities themselves are NOT temporally scoped — they persist once created and are
mutated via upsert (updated_at tracks the last touch). Only their *relationships*
and *attributes* have temporal bounds. Deleting an entity cascades to its triples
and attributes.

Query behaviour:
  - ``query_relationships()`` returns only current facts (``valid_to IS NULL``).
  - ``query_relationships(as_of=dt)`` returns facts active at that instant:
    ``valid_from <= dt AND (valid_to IS NULL OR valid_to > dt)``.
    This includes facts that were later invalidated but were still true at ``dt``.
  - ``get_timeline()`` returns ALL facts (current + historical) ordered by
    valid_from DESC, giving a chronological audit trail.
  - ``get_stats()`` counts only current facts (``valid_to IS NULL``).

Pinned context (L0):
  An entity with an active attribute ``key='pinned', value='true', valid_to IS NULL``
  is surfaced by ``get_pinned_context()`` for injection into system prompts.
  Invalidating the 'pinned' attribute removes it from context on the next cache
  refresh (≤30 s TTL).
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.database import async_session, new_uuid, utcnow

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_kg_service: Optional["KnowledgeGraphService"] = None


def get_knowledge_graph_service() -> "KnowledgeGraphService":
    global _kg_service
    if _kg_service is None:
        _kg_service = KnowledgeGraphService()
    return _kg_service


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class KnowledgeGraphService:
    """Temporal knowledge graph backed by SQLite (kg_entities / kg_triples / kg_attributes).

    See module docstring for the full temporal model (valid_from / valid_to semantics).
    """

    CACHE_TTL = 30.0  # seconds
    MAX_NAME_LEN = 500
    MAX_VALUE_LEN = 5000

    def __init__(self):
        self._pinned_cache: dict[str, tuple[float, list[dict]]] = {}

    # ------------------------------------------------------------------
    # Entity CRUD
    # ------------------------------------------------------------------

    async def add_entity(
        self,
        name: str,
        entity_type: str,
        project_id: str,
        properties: Optional[dict] = None,
    ) -> str:
        """Upsert an entity by (name, entity_type, project_id). Returns entity id.

        Entities are not temporally scoped — they persist once created. Repeated
        calls with the same (name, type, project) update properties and
        updated_at but return the same id.
        """
        if len(name) > self.MAX_NAME_LEN:
            name = name[:self.MAX_NAME_LEN]
        if len(entity_type) > self.MAX_NAME_LEN:
            entity_type = entity_type[:self.MAX_NAME_LEN]
        now = utcnow()
        props_json = json.dumps(properties) if properties else None

        async with async_session() as db:
            # Try to find existing
            row = (await db.execute(text(
                "SELECT id FROM kg_entities "
                "WHERE name = :name AND entity_type = :etype AND project_id = :pid"
            ), {"name": name, "etype": entity_type, "pid": project_id})).fetchone()

            if row:
                entity_id = row[0]
                await db.execute(text(
                    "UPDATE kg_entities SET properties = :props, updated_at = :now "
                    "WHERE id = :id"
                ), {"props": props_json, "now": now, "id": entity_id})
                await db.commit()
                return entity_id

            entity_id = new_uuid()
            await db.execute(text(
                "INSERT INTO kg_entities (id, name, entity_type, project_id, properties, created_at, updated_at) "
                "VALUES (:id, :name, :etype, :pid, :props, :now, :now)"
            ), {
                "id": entity_id, "name": name, "etype": entity_type,
                "pid": project_id, "props": props_json, "now": now,
            })
            await db.commit()
            return entity_id

    async def add_triple(
        self,
        subject_id: str,
        predicate: str,
        object_id: str,
        confidence: float = 1.0,
        source: str = "auto",
    ) -> str:
        """Add a relationship triple. Returns triple id.

        The triple is created with valid_from = now() and valid_to = NULL,
        meaning it is immediately active. To end the relationship later, call
        ``invalidate(triple_id=...)``, which sets valid_to = now().

        Raises ValueError if subject_id or object_id don't exist.
        Confidence is clamped to [0.0, 1.0]; NaN/Inf default to 1.0.
        """
        # Validate confidence
        import math
        if not isinstance(confidence, (int, float)) or math.isnan(confidence) or math.isinf(confidence):
            confidence = 1.0
        confidence = max(0.0, min(1.0, float(confidence)))

        now = utcnow()
        triple_id = new_uuid()
        async with async_session() as db:
            # Verify both entities exist
            for label, eid in [("subject", subject_id), ("object", object_id)]:
                row = (await db.execute(text(
                    "SELECT 1 FROM kg_entities WHERE id = :id"
                ), {"id": eid})).fetchone()
                if not row:
                    raise ValueError(f"Triple {label} entity {eid!r} does not exist")

            await db.execute(text(
                "INSERT INTO kg_triples (id, subject_id, predicate, object_id, confidence, source, valid_from, created_at) "
                "VALUES (:id, :sid, :pred, :oid, :conf, :src, :now, :now)"
            ), {
                "id": triple_id, "sid": subject_id, "pred": predicate,
                "oid": object_id, "conf": confidence, "src": source, "now": now,
            })
            await db.commit()
        return triple_id

    async def add_attribute(
        self,
        entity_id: str,
        key: str,
        value: str,
    ) -> str:
        """Add a time-scoped attribute on an entity. Returns attribute id.

        Created with valid_from = now(), valid_to = NULL (active). Multiple
        attributes with the same key can coexist — each represents a distinct
        temporal assertion. To supersede an old value, invalidate the previous
        attribute and add a new one.
        """
        if len(key) > self.MAX_NAME_LEN:
            key = key[:self.MAX_NAME_LEN]
        if len(value) > self.MAX_VALUE_LEN:
            value = value[:self.MAX_VALUE_LEN]
        now = utcnow()
        attr_id = new_uuid()
        async with async_session() as db:
            await db.execute(text(
                "INSERT INTO kg_attributes (id, entity_id, key, value, valid_from, created_at) "
                "VALUES (:id, :eid, :key, :val, :now, :now)"
            ), {"id": attr_id, "eid": entity_id, "key": key, "val": value, "now": now})
            await db.commit()
        return attr_id

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def query_entities(
        self,
        project_id: str,
        name: Optional[str] = None,
        entity_type: Optional[str] = None,
        as_of: Optional[datetime] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search entities in a project. Filters are optional.

        Entities are not temporal — all entities are returned regardless of
        valid_from/valid_to (those live on triples/attributes, not entities).
        The ``as_of`` parameter is accepted for API symmetry but currently
        only affects ``query_relationships()``.
        """
        clauses = ["e.project_id = :pid"]
        params: dict = {"pid": project_id, "lim": limit}

        if name:
            clauses.append("LOWER(e.name) LIKE :name")
            params["name"] = f"%{name.lower()}%"
        if entity_type:
            clauses.append("e.entity_type = :etype")
            params["etype"] = entity_type

        where = " AND ".join(clauses)
        sql = f"SELECT id, name, entity_type, properties, created_at, updated_at FROM kg_entities e WHERE {where} ORDER BY updated_at DESC LIMIT :lim"

        async with async_session() as db:
            rows = (await db.execute(text(sql), params)).fetchall()

        return [
            {
                "id": r[0], "name": r[1], "entity_type": r[2],
                "properties": json.loads(r[3]) if r[3] else None,
                "created_at": str(r[4]), "updated_at": str(r[5]),
            }
            for r in rows
        ]

    async def query_relationships(
        self,
        project_id: str,
        entity_name: Optional[str] = None,
        predicate: Optional[str] = None,
        as_of: Optional[datetime] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Query active relationships (valid_to IS NULL) for a project.

        Optionally filtered by entity name, predicate, or point-in-time (as_of).
        Without ``as_of``, returns only current facts (valid_to IS NULL).
        With ``as_of``, returns facts that were active at that instant:
        valid_from <= as_of AND (valid_to IS NULL OR valid_to > as_of).
        """
        params: dict = {"pid": project_id, "lim": limit}

        if as_of:
            # Full temporal range: facts active at the given instant
            clauses = [
                "s.project_id = :pid",
                "t.valid_from <= :asof",
                "(t.valid_to IS NULL OR t.valid_to > :asof)",
            ]
            params["asof"] = as_of
        else:
            # Current state only
            clauses = ["s.project_id = :pid", "t.valid_to IS NULL"]

        if entity_name:
            clauses.append("(LOWER(s.name) LIKE :ename OR LOWER(o.name) LIKE :ename)")
            params["ename"] = f"%{entity_name.lower()}%"
        if predicate:
            clauses.append("t.predicate = :pred")
            params["pred"] = predicate

        where = " AND ".join(clauses)
        sql = (
            "SELECT t.id, s.name AS subject, t.predicate, o.name AS object, "
            "t.confidence, t.source, t.valid_from, t.created_at "
            "FROM kg_triples t "
            "JOIN kg_entities s ON t.subject_id = s.id "
            "JOIN kg_entities o ON t.object_id = o.id "
            f"WHERE {where} ORDER BY t.created_at DESC LIMIT :lim"
        )

        async with async_session() as db:
            rows = (await db.execute(text(sql), params)).fetchall()

        return [
            {
                "id": r[0], "subject": r[1], "predicate": r[2], "object": r[3],
                "confidence": r[4], "source": r[5],
                "valid_from": str(r[6]), "created_at": str(r[7]),
            }
            for r in rows
        ]

    async def get_timeline(
        self,
        project_id: str,
        entity_name: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Chronological audit trail of ALL triples and attributes (current + historical).

        Unlike query_relationships() which only returns active facts, timeline
        includes invalidated rows too — showing valid_from, valid_to, and whether
        each fact is still current (valid_to = None) or ended. Ordered by
        valid_from DESC (newest first).
        """
        params: dict = {"pid": project_id, "lim": limit}
        name_filter = ""
        if entity_name:
            name_filter = "AND (LOWER(s.name) LIKE :ename OR LOWER(o.name) LIKE :ename)"
            params["ename"] = f"%{entity_name.lower()}%"

        sql = (
            "SELECT 'triple' AS kind, t.id, s.name AS subject, t.predicate, o.name AS object, "
            "t.valid_from, t.valid_to, t.confidence "
            "FROM kg_triples t "
            "JOIN kg_entities s ON t.subject_id = s.id "
            "JOIN kg_entities o ON t.object_id = o.id "
            f"WHERE s.project_id = :pid {name_filter} "
            "UNION ALL "
            "SELECT 'attribute' AS kind, a.id, e.name AS subject, a.key AS predicate, a.value AS object, "
            "a.valid_from, a.valid_to, NULL AS confidence "
            "FROM kg_attributes a "
            "JOIN kg_entities e ON a.entity_id = e.id "
            f"WHERE e.project_id = :pid {name_filter.replace('s.name', 'e.name').replace('o.name', 'e.name')} "
            "ORDER BY valid_from DESC LIMIT :lim"
        )

        async with async_session() as db:
            rows = (await db.execute(text(sql), params)).fetchall()

        return [
            {
                "kind": r[0], "id": r[1], "subject": r[2],
                "predicate": r[3], "object": r[4],
                "valid_from": str(r[5]), "valid_to": str(r[6]) if r[6] else None,
                "confidence": r[7],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Invalidation
    # ------------------------------------------------------------------

    async def invalidate(
        self,
        triple_id: Optional[str] = None,
        attribute_id: Optional[str] = None,
    ) -> bool:
        """Close a triple or attribute by setting valid_to = now().

        This marks the fact as historical — it remains in the database for
        timeline queries but no longer appears in active queries or stats.
        Idempotent: invalidating an already-closed row returns False.
        """
        now = utcnow()
        async with async_session() as db:
            if triple_id:
                result = await db.execute(text(
                    "UPDATE kg_triples SET valid_to = :now WHERE id = :id AND valid_to IS NULL"
                ), {"now": now, "id": triple_id})
                await db.commit()
                return result.rowcount > 0
            if attribute_id:
                result = await db.execute(text(
                    "UPDATE kg_attributes SET valid_to = :now WHERE id = :id AND valid_to IS NULL"
                ), {"now": now, "id": attribute_id})
                await db.commit()
                return result.rowcount > 0
        return False

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_stats(self, project_id: str) -> dict:
        """Return counts of entities, active triples, active attributes for a project."""
        async with async_session() as db:
            entities = (await db.execute(text(
                "SELECT COUNT(*) FROM kg_entities WHERE project_id = :pid"
            ), {"pid": project_id})).scalar() or 0

            triples = (await db.execute(text(
                "SELECT COUNT(*) FROM kg_triples t "
                "JOIN kg_entities e ON t.subject_id = e.id "
                "WHERE e.project_id = :pid AND t.valid_to IS NULL"
            ), {"pid": project_id})).scalar() or 0

            attributes = (await db.execute(text(
                "SELECT COUNT(*) FROM kg_attributes a "
                "JOIN kg_entities e ON a.entity_id = e.id "
                "WHERE e.project_id = :pid AND a.valid_to IS NULL"
            ), {"pid": project_id})).scalar() or 0

        return {"entities": entities, "active_triples": triples, "active_attributes": attributes}

    # ------------------------------------------------------------------
    # Pinned context cache (sync-safe for L0)
    # ------------------------------------------------------------------

    def get_pinned_context(self, project_id: str) -> list[dict]:
        """Sync-safe: return cached pinned entities. Async refresh populates the cache."""
        entry = self._pinned_cache.get(project_id)
        if entry and (time.time() - entry[0]) < self.CACHE_TTL:
            return entry[1]
        return []

    async def refresh_pinned_cache(self, project_id: str):
        """Query DB for entities with pinned=true attribute and update in-memory cache."""
        async with async_session() as db:
            rows = (await db.execute(text(
                "SELECT e.id, e.name, e.entity_type, a.value "
                "FROM kg_entities e "
                "JOIN kg_attributes a ON a.entity_id = e.id "
                "WHERE e.project_id = :pid AND a.key = 'pinned' AND a.value = 'true' "
                "AND a.valid_to IS NULL"
            ), {"pid": project_id})).fetchall()

        pinned = [
            {"id": r[0], "name": r[1], "entity_type": r[2], "value": r[3]}
            for r in rows
        ]
        # Also include entities with a 'summary' attribute for richer L0
        async with async_session() as db:
            summary_rows = (await db.execute(text(
                "SELECT e.id, e.name, e.entity_type, a.value "
                "FROM kg_entities e "
                "JOIN kg_attributes a ON a.entity_id = e.id "
                "WHERE e.project_id = :pid AND a.key = 'summary' "
                "AND a.valid_to IS NULL "
                "AND EXISTS (SELECT 1 FROM kg_attributes p WHERE p.entity_id = e.id "
                "  AND p.key = 'pinned' AND p.value = 'true' AND p.valid_to IS NULL)"
            ), {"pid": project_id})).fetchall()

        for r in summary_rows:
            # Update value to summary text for pinned entities
            for p in pinned:
                if p["id"] == r[0]:
                    p["value"] = r[3]
                    break

        self._pinned_cache[project_id] = (time.time(), pinned)

    # ------------------------------------------------------------------
    # LLM extraction integration
    # ------------------------------------------------------------------

    async def extract_entities_from_llm_output(
        self,
        entities: list[dict],
        project_id: str,
    ) -> list[str]:
        """Process LLM-extracted entities into KG. Returns list of entity ids created/updated."""
        entity_ids = []
        for ent in entities:
            name = (ent.get("name") or "").strip()
            etype = (ent.get("type") or "concept").strip()
            if not name:
                continue

            try:
                eid = await self.add_entity(name, etype, project_id)
                entity_ids.append(eid)

                # Process relationships
                for rel in ent.get("relationships", []):
                    target_name = (rel.get("target") or "").strip()
                    target_type = (rel.get("target_type") or "concept").strip()
                    predicate = (rel.get("predicate") or "related_to").strip()
                    if not target_name:
                        continue

                    target_id = await self.add_entity(target_name, target_type, project_id)
                    await self.add_triple(eid, predicate, target_id, source="auto")

            except (ValueError, SQLAlchemyError) as e:
                logger.warning(f"[KG] Failed to extract entity {name!r}: {e}")
                continue

        # Refresh pinned cache if we touched this project
        if entity_ids:
            try:
                await self.refresh_pinned_cache(project_id)
            except SQLAlchemyError:
                logger.debug("refresh_pinned_cache failed after extraction", exc_info=True)

        logger.info(f"[KG] Extracted {len(entity_ids)} entities for project {project_id}")
        return entity_ids
