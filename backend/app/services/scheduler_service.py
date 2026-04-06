"""
SchedulerService — Background task scheduler for Voxyflow.

Provides:
- Heartbeat job (every 2 min): checks backend, XTTS, Claude proxy, ChromaDB
- RAG index job (every 15 min): re-indexes active project workspaces in ChromaDB
- Health status dict with timestamps exposed via /api/health
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
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

        # Recurrence job — runs every 5 minutes (supports 15min card intervals)
        self._scheduler.add_job(
            self._recurrence_job,
            trigger="interval",
            minutes=5,
            id="recurrence",
            name="Recurring Card Generator",
            replace_existing=True,
            misfire_grace_time=300,
        )

        # Session cleanup job — runs once per day at 03:00 UTC
        self._scheduler.add_job(
            self._session_cleanup_job,
            trigger="cron",
            hour=3,
            minute=0,
            id="session_cleanup",
            name="Session File Cleanup (30-day TTL)",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        self._scheduler.start()
        # Run heartbeat immediately at startup (so ChromaDB status is known right away)
        asyncio.ensure_future(self._heartbeat_job())
        logger.info(
            f"✅ SchedulerService started "
            f"(heartbeat every {heartbeat_interval_minutes}m, "
            f"RAG index every {rag_index_interval_minutes}m, "
            f"recurrence check every 1h, "
            f"session cleanup daily at 03:00 UTC)"
        )

        # Load user-defined jobs from ~/.voxyflow/jobs.json
        import os as _os
        _jobs_file = Path(_os.environ.get("VOXYFLOW_DATA_DIR", _os.path.expanduser("~/.voxyflow"))) / "jobs.json"
        self.load_user_jobs(_jobs_file)

    def stop(self) -> None:
        """Clean shutdown. Waits for running jobs to finish (wait=True)."""
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            logger.info("SchedulerService stopped")

    # ------------------------------------------------------------------
    # User job management
    # ------------------------------------------------------------------

    def _parse_schedule(self, schedule: str):
        """Parse a schedule string into (trigger_type, kwargs).

        Supports:
          - Cron expressions: "0 9 * * 1-5"
          - Shorthand: "every_30min", "every_2h", "every_hour", "every_day"
        Returns ("cron", {"crontab": expr}) or ("interval", {minutes/hours/days: n}).
        """
        s = schedule.strip()

        # every_Xmin / every_Xm
        m = re.match(r"^every[_\s]?(\d+)\s*min", s, re.IGNORECASE)
        if m:
            return ("interval", {"minutes": int(m.group(1))})

        # every_Xhr / every_Xh
        m = re.match(r"^every[_\s]?(\d+)\s*h", s, re.IGNORECASE)
        if m:
            return ("interval", {"hours": int(m.group(1))})

        # every_hour (no number)
        if re.match(r"^every[_\s]?hour$", s, re.IGNORECASE):
            return ("interval", {"hours": 1})

        # every_day
        if re.match(r"^every[_\s]?day$", s, re.IGNORECASE):
            return ("interval", {"days": 1})

        # Default: treat as cron expression
        return ("cron", {"crontab": s})

    def register_user_job(self, job: dict) -> None:
        """Register (or re-register) a user job with APScheduler.

        No-op if the scheduler is not running. Silently skips jobs with
        no schedule string or disabled jobs (removes any existing APS job).
        """
        if not (self._scheduler and self._scheduler.running):
            return

        job_id = job.get("id", "")
        aps_id = f"user_{job_id}"
        name = job.get("name", aps_id)
        enabled = job.get("enabled", True)

        # Always remove any existing registration first
        try:
            if self._scheduler.get_job(aps_id):
                self._scheduler.remove_job(aps_id)
        except Exception:
            pass

        if not enabled:
            logger.debug(f"[Jobs] Job '{name}' is disabled — not registering with APScheduler")
            return

        schedule = (job.get("schedule") or "").strip()
        if not schedule:
            logger.warning(f"[Jobs] Job '{name}' has no schedule — skipping APScheduler registration")
            return

        try:
            trigger_type, trigger_kwargs = self._parse_schedule(schedule)

            if trigger_type == "cron":
                from apscheduler.triggers.cron import CronTrigger
                trigger = CronTrigger.from_crontab(trigger_kwargs["crontab"])
            else:
                from apscheduler.triggers.interval import IntervalTrigger
                trigger = IntervalTrigger(**trigger_kwargs)

            self._scheduler.add_job(
                self._run_user_job,
                trigger=trigger,
                id=aps_id,
                name=name,
                args=[job],
                replace_existing=True,
                misfire_grace_time=300,
            )
            logger.info(f"[Jobs] Registered job '{name}' with APScheduler (id={job_id}, schedule={schedule})")
        except Exception as e:
            logger.error(f"[Jobs] Failed to register job '{name}': {e}", exc_info=True)

    def unregister_user_job(self, job_id: str) -> None:
        """Remove a user job from APScheduler."""
        if not (self._scheduler and self._scheduler.running):
            return
        aps_id = f"user_{job_id}"
        try:
            if self._scheduler.get_job(aps_id):
                self._scheduler.remove_job(aps_id)
                logger.info(f"[Jobs] Unregistered job from APScheduler (id={job_id})")
        except Exception as e:
            logger.error(f"[Jobs] Failed to unregister job {job_id}: {e}")

    def get_next_run(self, job_id: str) -> Optional[str]:
        """Return the ISO-formatted next_run_time for a user job, or None."""
        if not (self._scheduler and self._scheduler.running):
            return None
        aps_id = f"user_{job_id}"
        try:
            aps_job = self._scheduler.get_job(aps_id)
            if aps_job and aps_job.next_run_time:
                return aps_job.next_run_time.isoformat()
        except Exception:
            pass
        return None

    def load_user_jobs(self, jobs_file: Path) -> None:
        """Load all user jobs from jobs.json and register enabled ones with APScheduler."""
        if not (self._scheduler and self._scheduler.running):
            return
        if not jobs_file.exists():
            logger.debug(f"[Jobs] No user jobs file at {jobs_file} — nothing to load")
            return
        try:
            import json as _json
            with open(jobs_file, "r", encoding="utf-8") as f:
                jobs = _json.load(f)
            if not isinstance(jobs, list):
                return
            count = 0
            for job in jobs:
                self.register_user_job(job)
                if job.get("enabled", True):
                    count += 1
            logger.info(f"[Jobs] Loaded {len(jobs)} user job(s) from disk ({count} enabled)")
        except Exception as e:
            logger.error(f"[Jobs] Failed to load user jobs from {jobs_file}: {e}", exc_info=True)

    async def _run_user_job(self, job: dict) -> None:
        """APScheduler callback: execute a user job and update last_run in jobs.json."""
        job_id = job.get("id", "")
        name = job.get("name", "")
        logger.info(f"[Jobs] Executing scheduled job '{name}' (id={job_id})")

        # Lazy import to avoid circular dependency at module load time
        from app.routes.jobs import _execute_job, _load_jobs, _save_jobs, _find_job

        try:
            result = await _execute_job(job)
            logger.info(f"[Jobs] Scheduled job '{name}' completed: {result.get('status', 'ok')}")
        except Exception as e:
            logger.error(f"[Jobs] Scheduled job '{name}' failed: {e}", exc_info=True)

        # Update last_run in jobs.json (best-effort)
        try:
            jobs = _load_jobs()
            idx, existing = _find_job(jobs, job_id)
            if existing is not None:
                existing["last_run"] = _now_iso()
                jobs[idx] = existing
                _save_jobs(jobs)
        except Exception as e:
            logger.warning(f"[Jobs] Could not update last_run for '{name}': {e}")

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
        - xtts (GET http://localhost:5500/health)
        - chromadb (local import check + collection list)
        """
        try:
            # Backend is always alive (we're executing)
            self._health["backend"] = {"status": "ok", "checked_at": _now_iso()}

            from app.config import get_settings
            _settings = get_settings()

            async with httpx.AsyncClient(timeout=5.0) as client:
                # Claude proxy — skip check when using CLI backend (no proxy needed)
                if _settings.claude_use_cli:
                    self._health["claude_proxy"] = {"status": "not_applicable", "checked_at": _now_iso()}
                else:
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

                # XTTS server — check configured TTS URL
                try:
                    from app.routes.settings import _load_settings_from_db
                    settings_data = await _load_settings_from_db()
                    tts_url = ""
                    if settings_data:
                        tts_url = settings_data.get("voice", {}).get("tts_url", "")
                    if tts_url:
                        r = await client.get(tts_url.rstrip("/") + "/health")
                        status = "ok" if r.status_code < 500 else "down"
                    else:
                        status = "not_configured"
                except Exception as e:
                    status = "down"
                    logger.warning(f"[Heartbeat] XTTS server down: {e}")
                prev = self._health.get("xtts", {}).get("status")
                self._health["xtts"] = {"status": status, "checked_at": _now_iso()}
                if prev not in (None, "unknown") and prev != status:
                    logger.warning(f"[Heartbeat] XTTS status changed: {prev} → {status}")

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
                        RECURRENCE_DELTAS = {
                            "15min": timedelta(minutes=15),
                            "30min": timedelta(minutes=30),
                            "hourly": timedelta(hours=1),
                            "6hours": timedelta(hours=6),
                            "daily": timedelta(days=1),
                            "weekdays": timedelta(days=1),
                            "weekly": timedelta(weeks=1),
                            "biweekly": timedelta(weeks=2),
                            "monthly": timedelta(days=30),
                        }
                        if card.recurrence and card.recurrence.startswith("cron:"):
                            # Custom cron — compute next from APScheduler CronTrigger
                            try:
                                from apscheduler.triggers.cron import CronTrigger
                                cron_expr = card.recurrence.replace("cron:", "").strip()
                                trigger = CronTrigger.from_crontab(cron_expr)
                                new_next = trigger.get_next_fire_time(None, base)
                            except Exception:
                                new_next = base + timedelta(days=1)
                        else:
                            new_next = base + RECURRENCE_DELTAS.get(card.recurrence, timedelta(days=1))

                        # Weekdays: skip weekends
                        if card.recurrence == "weekdays":
                            while new_next.weekday() >= 5:  # Sat=5, Sun=6
                                new_next += timedelta(days=1)

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
                                except Exception as e:
                                    logger.debug("Can't parse message timestamp, indexing anyway: %s", e)

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

    async def _session_cleanup_job(self, max_age_days: int = 30) -> None:
        """
        Periodic cleanup of session files older than *max_age_days* (default 30).

        Walks the session store directory recursively and removes any .json
        session files whose modification time is older than the threshold.
        Archived files (.archived-*.json) are also cleaned up.

        Safe: errors per-file are caught individually so one bad file never
        aborts the whole cleanup pass.
        """
        try:
            import os
            import time as _time
            from pathlib import Path

            from app.services.session_store import session_store

            cutoff_epoch = _time.time() - (max_age_days * 86400)
            sessions_dir: Path = session_store.sessions_dir

            if not sessions_dir.exists():
                logger.debug("[SessionCleanup] sessions dir does not exist — skipping")
                return

            deleted = 0
            errors = 0

            for path in sessions_dir.rglob("*.json"):
                try:
                    mtime = path.stat().st_mtime
                    if mtime < cutoff_epoch:
                        path.unlink(missing_ok=True)
                        deleted += 1
                        logger.debug(f"[SessionCleanup] Deleted stale session file: {path}")
                except Exception as file_err:
                    errors += 1
                    logger.warning(f"[SessionCleanup] Could not remove {path}: {file_err}")

            if deleted or errors:
                logger.info(
                    f"[SessionCleanup] Done — deleted {deleted} stale file(s) "
                    f"(>{max_age_days}d), {errors} error(s)"
                )
            else:
                logger.debug(f"[SessionCleanup] No stale session files found (threshold: {max_age_days}d)")

        except Exception as e:
            logger.error(f"[SessionCleanup] unexpected error: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Health status
    # ------------------------------------------------------------------

    def get_health_status(self) -> dict:
        """Return current health of all monitored services."""
        # Ignore services that are removed or not applicable for overall status
        active_statuses = [
            v.get("status", "unknown") for v in self._health.values()
            if v.get("status") not in ("removed", "not_applicable")
        ]

        if not active_statuses or all(s == "ok" for s in active_statuses):
            overall = "ok"
        elif all(s == "down" for s in active_statuses):
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
