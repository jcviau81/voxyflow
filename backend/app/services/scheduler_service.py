"""
SchedulerService — Background task scheduler for Voxyflow.

Provides:
- Heartbeat job (every 2 min): checks backend, XTTS, Claude proxy, ChromaDB
- RAG index job (every 15 min): re-indexes active project workspaces in ChromaDB
- Health status dict with timestamps exposed via /api/health
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger("voxyflow.scheduler")

# ---------------------------------------------------------------------------
# Graceful APScheduler import
# ---------------------------------------------------------------------------

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED

    _APSCHEDULER_AVAILABLE = True
except ImportError:
    _APSCHEDULER_AVAILABLE = False
    logger.warning("apscheduler not installed — scheduler disabled (add apscheduler>=3.10.0 to requirements.txt)")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# SchedulerService
# ---------------------------------------------------------------------------


class SchedulerService:
    """Background task scheduler for Voxyflow.

    Runs as a singleton. Start on app startup, stop on shutdown.
    Jobs are resilient: exceptions are caught and logged, never propagated.
    """

    def __init__(self) -> None:
        self._scheduler: Optional["AsyncIOScheduler"] = None
        self._health: dict = {
            "backend": {"status": "ok", "checked_at": None},
            "claude_proxy": {"status": "unknown", "checked_at": None},
            "xtts": {"status": "unknown", "checked_at": None},
            "chromadb": {"status": "unknown", "checked_at": None},
        }
        self._enabled = _APSCHEDULER_AVAILABLE

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self, heartbeat_interval_minutes: int = 2, rag_index_interval_minutes: int = 15) -> None:
        """Start all scheduled jobs. Safe to call multiple times (no-op if already running)."""
        if not self._enabled:
            logger.warning("SchedulerService: APScheduler not available — skipping start")
            return

        if self._scheduler and self._scheduler.running:
            logger.debug("SchedulerService: already running")
            return

        self._scheduler = AsyncIOScheduler()

        # Attach job error listener for better observability
        self._scheduler.add_listener(self._on_job_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

        # Heartbeat job
        self._scheduler.add_job(
            self._heartbeat_job,
            trigger="interval",
            minutes=heartbeat_interval_minutes,
            id="heartbeat",
            name="Service Heartbeat",
            replace_existing=True,
            misfire_grace_time=60,
        )

        # RAG index job
        self._scheduler.add_job(
            self._rag_index_job,
            trigger="interval",
            minutes=rag_index_interval_minutes,
            id="rag_index",
            name="RAG Workspace Indexer",
            replace_existing=True,
            misfire_grace_time=300,
        )

        # Recurrence job — runs every hour
        self._scheduler.add_job(
            self._recurrence_job,
            trigger="interval",
            hours=1,
            id="recurrence",
            name="Recurring Card Generator",
            replace_existing=True,
            misfire_grace_time=300,
        )

        self._scheduler.start()
        logger.info(
            f"✅ SchedulerService started "
            f"(heartbeat every {heartbeat_interval_minutes}m, "
            f"RAG index every {rag_index_interval_minutes}m, "
            f"recurrence check every 1h)"
        )

    def stop(self) -> None:
        """Clean shutdown. Waits for running jobs to finish (wait=True)."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("SchedulerService stopped")

    # ------------------------------------------------------------------
    # Job error listener
    # ------------------------------------------------------------------

    def _on_job_event(self, event) -> None:
        if hasattr(event, "exception") and event.exception:
            logger.error(
                f"[Scheduler] job '{event.job_id}' failed: {event.exception}",
                exc_info=event.traceback,
            )
        else:
            logger.debug(f"[Scheduler] job '{event.job_id}' executed OK")

    # ------------------------------------------------------------------
    # Built-in Jobs
    # ------------------------------------------------------------------

    async def _heartbeat_job(self) -> None:
        """
        Check health of all backend services.

        Services checked:
        - backend (always ok — if this runs, the backend is alive)
        - claude_proxy (GET http://localhost:3457/v1/models)
        - xtts (GET http://192.168.1.59:5500/health)
        - chromadb (local import check + collection list)
        """
        try:
            # Backend is always alive (we're executing)
            self._health["backend"] = {"status": "ok", "checked_at": _now_iso()}

            from app.config import get_settings
            _settings = get_settings()

            async with httpx.AsyncClient(timeout=5.0) as client:
                # Claude proxy
                try:
                    r = await client.get(_settings.claude_proxy_url + "/models")
                    status = "ok" if r.status_code < 500 else "down"
                except Exception as e:
                    status = "down"
                    logger.warning(f"[Heartbeat] Claude proxy down: {e}")
                prev = self._health["claude_proxy"].get("status")
                self._health["claude_proxy"] = {"status": status, "checked_at": _now_iso()}
                if prev not in (None, "unknown") and prev != status:
                    logger.warning(f"[Heartbeat] Claude proxy status changed: {prev} → {status}")

                # XTTS server — removed (TTS is now client-side)
                self._health["xtts"] = {"status": "removed", "checked_at": _now_iso()}

            # ChromaDB — check via local import
            try:
                import chromadb as _chromadb  # noqa: F401
                from app.services.rag_service import get_rag_service

                rag = get_rag_service()
                if rag.enabled and rag._client is not None:
                    rag._client.list_collections()
                    status = "ok"
                elif rag.enabled:
                    status = "ok"  # enabled but no client yet
                else:
                    status = "down"
            except Exception as e:
                status = "down"
                logger.warning(f"[Heartbeat] ChromaDB check failed: {e}")
            prev = self._health["chromadb"].get("status")
            self._health["chromadb"] = {"status": status, "checked_at": _now_iso()}
            if prev not in (None, "unknown") and prev != status:
                logger.warning(f"[Heartbeat] ChromaDB status changed: {prev} → {status}")

            logger.debug(
                f"[Heartbeat] claude_proxy={self._health['claude_proxy']['status']} "
                f"xtts={self._health['xtts']['status']} "
                f"chromadb={self._health['chromadb']['status']}"
            )

        except Exception as e:
            logger.error(f"[Heartbeat] unexpected error: {e}", exc_info=True)

    async def _recurrence_job(self) -> None:
        """
        Recurring card generator — runs every hour.

        Finds all cards with a recurrence schedule whose recurrence_next is in the past,
        creates a fresh copy (status=idea, title/description/agent_type preserved),
        and advances recurrence_next to the next occurrence.
        """
        try:
            from datetime import timedelta

            from sqlalchemy import select

            from app.database import Card, async_session, new_uuid, utcnow

            now = datetime.now(timezone.utc)

            async with async_session() as db:
                stmt = select(Card).where(
                    Card.recurrence.isnot(None),
                    Card.recurrence_next.isnot(None),
                    Card.recurrence_next <= now,
                )
                result = await db.execute(stmt)
                due_cards = result.scalars().all()

                for card in due_cards:
                    try:
                        # Create a copy with status="idea"
                        new_card = Card(
                            id=new_uuid(),
                            project_id=card.project_id,
                            title=card.title,
                            description=card.description,
                            status="idea",
                            priority=card.priority,
                            auto_generated=True,
                            agent_type=card.agent_type,
                            agent_assigned=card.agent_assigned,
                            recurrence=card.recurrence,
                        )

                        # Compute next recurrence_next for the new card
                        base = card.recurrence_next or now
                        if card.recurrence == "daily":
                            new_next = base + timedelta(days=1)
                        elif card.recurrence == "weekly":
                            new_next = base + timedelta(weeks=1)
                        elif card.recurrence == "monthly":
                            # Add ~30 days (simple approach)
                            new_next = base + timedelta(days=30)
                        else:
                            new_next = None

                        new_card.recurrence_next = new_next

                        # Advance the original card's recurrence_next so it won't re-fire
                        card.recurrence_next = new_next
                        card.updated_at = utcnow()

                        db.add(new_card)
                        logger.info(
                            f"[Recurrence] Created card '{new_card.title}' "
                            f"(id={new_card.id}) from template card={card.id}, "
                            f"recurrence={card.recurrence}, next={new_next}"
                        )

                    except Exception as e:
                        logger.error(
                            f"[Recurrence] Failed to process card {card.id}: {e}",
                            exc_info=True,
                        )

                await db.commit()

        except Exception as e:
            logger.error(f"[Recurrence] unexpected error: {e}", exc_info=True)

    async def _rag_index_job(self) -> None:
        """
        Re-index workspace for projects with recent chat activity (last 30 min).

        For each recently-active project:
        - Re-indexes cards (title, description, status, priority)
        - Re-indexes project info (title, description, tech_stack)

        Keeps RAG context fresh without doing full re-index on every message.
        Uses RAGService.index_workspace() which upserts by card_id.
        """
        try:
            from datetime import timedelta

            from app.database import async_session, Project, Card
            from app.services.rag_service import get_rag_service
            from app.services.session_store import session_store
            from sqlalchemy import select

            rag = get_rag_service()
            if not rag.enabled:
                logger.debug("[RAGIndex] RAG disabled — skipping")
                return

            cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)

            async with async_session() as db:
                result = await db.execute(select(Project))
                projects = result.scalars().all()

                indexed_count = 0
                for project in projects:
                    try:
                        # Check if this project had recent chat activity
                        chat_id = f"project:{project.id}"
                        history = session_store.get_recent_messages(chat_id, limit=1)
                        if not history:
                            continue

                        last_msg = history[-1] if history else None
                        if last_msg:
                            msg_ts = last_msg.get("timestamp")
                            if msg_ts:
                                try:
                                    from datetime import datetime as _dt

                                    if isinstance(msg_ts, (int, float)):
                                        msg_time = _dt.fromtimestamp(msg_ts, tz=timezone.utc)
                                    else:
                                        msg_time = _dt.fromisoformat(str(msg_ts))
                                    if msg_time < cutoff:
                                        continue
                                except Exception:
                                    pass  # can't parse timestamp → index anyway

                        logger.info(f"[RAGIndex] Re-indexing project '{project.title}' (id={project.id})")

                        # Build project_info dict (matches RAGService.index_workspace signature)
                        project_info = {
                            "title": project.title or "",
                            "description": project.description or "",
                            "context": getattr(project, "tech_stack", "") or "",
                        }

                        # Fetch cards and build card dicts
                        cards_result = await db.execute(
                            select(Card).where(Card.project_id == project.id)
                        )
                        cards_orm = cards_result.scalars().all()
                        cards_dicts = [
                            {
                                "id": card.id,
                                "title": card.title or "",
                                "description": card.description or "",
                                "status": card.status or "idea",
                                "agent_type": getattr(card, "agent_type", "") or "",
                            }
                            for card in cards_orm
                        ]

                        await rag.index_workspace(project.id, cards_dicts, project_info)
                        indexed_count += 1
                        logger.info(
                            f"[RAGIndex] Indexed project '{project.title}': {len(cards_dicts)} cards"
                        )

                    except Exception as e:
                        logger.error(f"[RAGIndex] Failed to index project {project.id}: {e}", exc_info=True)
                        # Continue with other projects — never abort the whole job

                if indexed_count:
                    logger.info(f"[RAGIndex] Done — re-indexed {indexed_count} active project(s)")
                else:
                    logger.debug("[RAGIndex] No recently-active projects to re-index")

        except Exception as e:
            logger.error(f"[RAGIndex] unexpected error: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Health status
    # ------------------------------------------------------------------

    def get_health_status(self) -> dict:
        """Return current health of all monitored services."""
        statuses = [v.get("status", "unknown") for v in self._health.values()]

        if all(s == "ok" for s in statuses):
            overall = "ok"
        elif all(s == "down" for s in statuses):
            overall = "down"
        else:
            overall = "degraded"

        return {
            "status": overall,
            "scheduler_running": bool(self._scheduler and self._scheduler.running),
            "services": dict(self._health),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_scheduler_service: Optional[SchedulerService] = None


def get_scheduler_service() -> SchedulerService:
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = SchedulerService()
    return _scheduler_service
