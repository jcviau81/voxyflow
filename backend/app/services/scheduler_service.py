"""
SchedulerService — Background task scheduler for Voxyflow.

All jobs (built-in and user-defined) are stored in ~/.voxyflow/jobs.json and
loaded on startup via load_user_jobs(). Built-in defaults are seeded on first
run and can be enabled/disabled/rescheduled like any other job.

Built-in job types: heartbeat, rag_index, recurrence, session_cleanup,
chromadb_backup. User job types: agent_task, execute_board, execute_card,
reminder, custom.
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
        self._backup_hour: int = 3
        self._backup_enabled: bool = False
        # Track previous health statuses for heartbeat change detection
        self._prev_health_statuses: dict[str, str] = {}
        # Global mutex for _rag_index_job — multiple rag_index job entries
        # (builtin, user-scoped, hourly, etc.) otherwise overlap and starve
        # the event loop. Lazily created on first use so __init__ doesn't
        # require a running loop.
        self._rag_index_lock: Optional[asyncio.Lock] = None

    # ------------------------------------------------------------------
    # WS event helper
    # ------------------------------------------------------------------

    def _emit_job_event(
        self,
        job_id: str,
        job_name: str,
        status: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        """Emit a ``system:job:completed`` WS event for scheduler jobs."""
        from app.services.ws_broadcast import ws_broadcast

        ws_broadcast.emit_sync("system:job:completed", {
            "jobId": job_id,
            "jobName": job_name,
            "status": status,       # ok | warning | error | skipped
            "message": message,
            "details": details or {},
            "timestamp": _now_iso(),
        })

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Default jobs — seeded into jobs.json on first run
    # ------------------------------------------------------------------

    _DEFAULT_JOBS: list[dict] = [
        # Removed: `builtin-agent-heartbeat` (global ~/.voxyflow/sandbox/heartbeat.md
        # poller). Replaced by the per-workspace autonomy layer — each workspace owns
        # its own heartbeat at ~/.voxyflow/sandbox/workspaces/{workspace_id}/heartbeat.md,
        # scheduled via proj-heartbeat-* jobs. See scripts/smoke_test_autonomy.py.
        {
            "id": "builtin-rag-index",
            "name": "RAG Workspace Indexer",
            "type": "rag_index",
            "schedule": "every_15min",
            "enabled": True,
            "builtin": True,
            "payload": {},
        },
        {
            "id": "builtin-session-cleanup",
            "name": "Session Cleanup",
            "type": "session_cleanup",
            "schedule": "0 3 * * *",
            "enabled": True,
            "builtin": True,
            "payload": {},
        },
        {
            "id": "builtin-chromadb-backup",
            "name": "ChromaDB Backup",
            "type": "chromadb_backup",
            "schedule": "30 3 * * *",
            "enabled": True,
            "builtin": True,
            "payload": {},
        },
        {
            "id": "builtin-recurrence",
            "name": "Recurring Card Reset",
            "type": "recurrence",
            "schedule": "every_1h",
            "enabled": True,
            "builtin": True,
            "payload": {},
        },
    ]

    @staticmethod
    def _migrate_builtin_jobs(jobs: list[dict]) -> bool:
        """Apply idempotent migrations to built-in job entries. Returns True if changed.

        Runs every boot (not gated by the seed marker) so live installs pick up
        new payload fields without needing a re-seed.
        """
        changed = False
        # Retire the legacy global heartbeat — the per-workspace autonomy layer
        # owns heartbeats now. Drop the row from jobs.json on boot.
        before = len(jobs)
        jobs[:] = [j for j in jobs if j.get("id") != "builtin-agent-heartbeat"]
        if len(jobs) != before:
            changed = True
        # Collapse the legacy `board_run` alias onto `execute_board`.
        for j in jobs:
            if j.get("type") == "board_run":
                j["type"] = "execute_board"
                changed = True
        return changed

    def _seed_default_jobs(self, jobs_file: Path) -> None:
        """Seed default built-in jobs (once) and run migrations (every boot)."""
        import json as _json

        existing: list[dict] = []
        if jobs_file.exists():
            try:
                with open(jobs_file, "r", encoding="utf-8") as f:
                    existing = _json.load(f)
                if not isinstance(existing, list):
                    existing = []
            except Exception:
                existing = []

        # Idempotent migrations on existing built-in jobs — runs every boot
        migrated = self._migrate_builtin_jobs(existing)

        # First-time seeding guarded by marker so we don't re-add deleted jobs
        marker = jobs_file.parent / ".jobs_defaults_seeded"
        added = 0
        if not marker.exists():
            existing_ids = {j.get("id") for j in existing}
            for default in self._DEFAULT_JOBS:
                if default["id"] not in existing_ids:
                    existing.append(dict(default))
                    added += 1

        if migrated or added:
            jobs_file.parent.mkdir(parents=True, exist_ok=True)
            with open(jobs_file, "w", encoding="utf-8") as f:
                _json.dump(existing, f, indent=2)
            if added:
                logger.info(f"[Jobs] Seeded {added} default job(s) into {jobs_file}")
            if migrated:
                logger.info(f"[Jobs] Migrated built-in job entries in {jobs_file}")

        # Seed default heartbeat.md if missing
        heartbeat_file = jobs_file.parent / "workspace" / "heartbeat.md"
        if not heartbeat_file.exists():
            heartbeat_file.parent.mkdir(parents=True, exist_ok=True)
            heartbeat_file.write_text(
                "# Heartbeat\n\n"
                "You are an autonomous agent running on a 5-minute heartbeat cycle.\n"
                "Read the instructions below. If there are any, follow them.\n"
                "If there are none, exit immediately without taking any action.\n\n"
                "After completing instructions, clear them from this file so they\n"
                "are not repeated on the next cycle.\n\n"
                "---\n\n"
                "<!-- Drop instructions below this line -->\n",
                encoding="utf-8",
            )
            logger.info(f"[Jobs] Created default heartbeat file at {heartbeat_file}")

        if not marker.exists():
            marker.touch()

    def start(self) -> None:
        """Start the scheduler. All jobs (built-in + user) are loaded from jobs.json."""
        if not self._enabled:
            logger.warning("SchedulerService: APScheduler not available — skipping start")
            return

        if self._scheduler and self._scheduler.running:
            logger.debug("SchedulerService: already running")
            return

        self._scheduler = AsyncIOScheduler()

        # Attach job error listener for better observability
        self._scheduler.add_listener(self._on_job_event, EVENT_JOB_ERROR | EVENT_JOB_EXECUTED)

        self._scheduler.start()

        # Seed default jobs into jobs.json on first run, then load all jobs
        import os as _os
        _jobs_file = Path(_os.environ.get("VOXYFLOW_DATA_DIR", _os.path.expanduser("~/.voxyflow"))) / "jobs.json"
        self._seed_default_jobs(_jobs_file)
        self.load_user_jobs(_jobs_file)

        # Service-health heartbeat — registered directly (not via jobs.json) so
        # health status / resource metrics never go stale; it must always run.
        from apscheduler.triggers.interval import IntervalTrigger
        self._scheduler.add_job(
            self._heartbeat_job,
            trigger=IntervalTrigger(minutes=5),
            id="builtin-service-heartbeat",
            name="Service Heartbeat",
            replace_existing=True,
            misfire_grace_time=300,
            coalesce=True,
            max_instances=1,
        )

        # Run heartbeat immediately at startup (so health status is known right away)
        asyncio.ensure_future(self._heartbeat_job())

        logger.info("SchedulerService started — all jobs loaded from jobs.json")

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

        # Default: treat as cron expression. APScheduler's from_crontab only
        # accepts 5 fields — normalise legacy 6-field (seconds-first) crontabs
        # like the persisted standup schedules ("0 M H * * *") by dropping the
        # leading seconds field.
        fields = s.split()
        if len(fields) == 6:
            s = " ".join(fields[1:])
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
                # Collapse missed fires into a single run, and refuse to
                # queue a second instance of the same job on top of one
                # that's still executing. Protects against slow jobs
                # (rag_index, heartbeat) stacking up under load.
                coalesce=True,
                max_instances=1,
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

    # ------------------------------------------------------------------
    # Standup jobs (per-workspace daily standup)
    # ------------------------------------------------------------------

    def register_standup_job(self, workspace_id: str, schedule: dict) -> None:
        """Register (or re-register) a workspace's standup job with APScheduler.

        ``schedule`` is either the full job dict persisted in jobs.json or a
        partial mapping — in the latter case the persisted standup job for the
        workspace is loaded from disk. Idempotent: standup reschedules mint a
        fresh job id, so any previous registration for this workspace is
        removed first.
        """
        if not (self._scheduler and self._scheduler.running):
            return

        self.unregister_standup_job(workspace_id)

        job: Optional[dict] = None
        if isinstance(schedule, dict) and schedule.get("id") and schedule.get("type") == "standup":
            job = schedule
        else:
            from app.services.job_runner import _load_jobs
            for j in _load_jobs():
                if (
                    j.get("type") == "standup"
                    and j.get("payload", {}).get("workspace_id") == workspace_id
                ):
                    job = j
                    break
        if job is None:
            logger.warning(
                f"[Jobs] No persisted standup job for workspace {workspace_id} — nothing to register"
            )
            return
        self.register_user_job(job)

    def unregister_standup_job(self, workspace_id: str) -> None:
        """Remove a workspace's standup job(s) from APScheduler. Idempotent.

        Matches by the job payload rather than job id — standup job ids are
        regenerated on every reschedule, so the id alone can't find stale
        registrations.
        """
        if not (self._scheduler and self._scheduler.running):
            return
        try:
            aps_jobs = self._scheduler.get_jobs()
        except Exception:
            return
        for aps_job in aps_jobs:
            args = getattr(aps_job, "args", None) or []
            job = args[0] if args else None
            if not isinstance(job, dict):
                continue
            if (
                job.get("type") == "standup"
                and job.get("payload", {}).get("workspace_id") == workspace_id
            ):
                try:
                    self._scheduler.remove_job(aps_job.id)
                    logger.info(
                        f"[Jobs] Unregistered standup job for workspace {workspace_id} (id={job.get('id')})"
                    )
                except Exception as e:
                    logger.error(f"[Jobs] Failed to unregister standup job {aps_job.id}: {e}")

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

    def get_next_upcoming_job(self) -> Optional[dict]:
        """Return the soonest upcoming scheduled job as {"name", "eta_seconds"}.

        Used by the Live-state heartbeat block so Voxy knows what's next on the
        calendar without calling jobs.list. Returns None if no jobs are queued
        or the scheduler is not running.
        """
        if not (self._scheduler and self._scheduler.running):
            return None
        try:
            jobs = self._scheduler.get_jobs()
        except Exception:
            return None
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        soonest: Optional[tuple[float, str]] = None
        for aps_job in jobs:
            nxt = getattr(aps_job, "next_run_time", None)
            if not nxt:
                continue
            delta = (nxt - now).total_seconds()
            if delta < 0:
                continue
            name = getattr(aps_job, "name", None) or aps_job.id
            if soonest is None or delta < soonest[0]:
                soonest = (delta, name)
        if soonest is None:
            return None
        return {"name": soonest[1], "eta_seconds": soonest[0]}

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

        # Lazy import avoids pulling the jobs persistence store at scheduler
        # module-load time; by now the app is fully booted.
        from app.services.job_runner import _execute_job, _load_jobs, _find_job, update_job_fields

        # Re-check enabled flag from disk — APScheduler may fire after the
        # job was disabled but before remove_job() took effect.
        try:
            _, current = _find_job(_load_jobs(), job_id)
            if current is not None and not current.get("enabled", True):
                logger.info(f"[Jobs] Job '{name}' is disabled — skipping execution")
                return
        except Exception:
            pass  # If we can't read disk, proceed with the snapshot we have

        logger.info(f"[Jobs] Executing scheduled job '{name}' (id={job_id})")

        result = {"status": "error", "message": "unknown"}
        try:
            result = await _execute_job(job)
            logger.info(f"[Jobs] Scheduled job '{name}' completed: {result.get('status', 'ok')}")
        except Exception as e:
            result = {"status": "error", "message": str(e)}
            logger.error(f"[Jobs] Scheduled job '{name}' failed: {e}", exc_info=True)

        # Broadcast completion to notification panel.
        # Built-in handlers (heartbeat, rag_index, etc.) emit their own
        # detailed events, so skip the generic emit for those.
        _builtin_types = {"heartbeat", "recurrence", "session_cleanup", "chromadb_backup", "rag_index"}
        if job.get("type") not in _builtin_types:
            self._emit_job_event(
                job_id,
                name,
                result.get("status", "ok"),
                result.get("message", ""),
                result,
            )

        # Update last_run in jobs.json (best-effort). update_job_fields holds
        # JOBS_LOCK across the read-modify-write so a concurrent job CRUD save
        # can't be clobbered by our stale snapshot; run it off-loop since the
        # lock is a threading lock shared with to_thread route callers.
        try:
            await asyncio.to_thread(update_job_fields, job_id, last_run=_now_iso())
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
                    from app.services.settings_loader import _load_settings_from_db
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

            # System resources via psutil
            try:
                import psutil, os as _os
                from app.services.metrics_store import get_metrics_store, ResourceSnapshot

                cpu_pct = psutil.cpu_percent(interval=0.2)
                vm = psutil.virtual_memory()
                proc = psutil.Process(_os.getpid())
                proc_ram_mb = proc.memory_info().rss / 1024 / 1024

                snap = ResourceSnapshot(
                    cpu_pct=cpu_pct,
                    ram_used_mb=round(vm.used / 1024 / 1024, 1),
                    ram_total_mb=round(vm.total / 1024 / 1024, 1),
                    ram_pct=vm.percent,
                    process_ram_mb=round(proc_ram_mb, 1),
                )
                get_metrics_store().record_resources(snap)
                self._health["resources"] = {
                    "cpu_pct": cpu_pct,
                    "ram_pct": vm.percent,
                    "ram_used_mb": snap.ram_used_mb,
                    "ram_total_mb": snap.ram_total_mb,
                    "process_ram_mb": snap.process_ram_mb,
                    "checked_at": _now_iso(),
                }
                logger.info(
                    f"[Heartbeat] cpu={cpu_pct:.1f}%  ram={vm.percent:.1f}%"
                    f" ({snap.ram_used_mb:.0f}/{snap.ram_total_mb:.0f} MB)"
                    f"  process={proc_ram_mb:.0f} MB"
                )
            except Exception as e:
                logger.debug(f"[Heartbeat] psutil unavailable: {e}")

            logger.debug(
                f"[Heartbeat] claude_proxy={self._health['claude_proxy']['status']} "
                f"xtts={self._health['xtts']['status']} "
                f"chromadb={self._health['chromadb']['status']}"
            )

            # Emit WS notification only when a service status changes
            current_statuses = {
                k: v.get("status", "unknown")
                for k, v in self._health.items()
                if k != "resources"
            }
            changed = {
                k: (self._prev_health_statuses.get(k), v)
                for k, v in current_statuses.items()
                if self._prev_health_statuses.get(k) not in (None, v)
            }
            if changed:
                parts = [f"{k}: {old} -> {new}" for k, (old, new) in changed.items()]
                any_down = any(v == "down" for v in current_statuses.values())
                self._emit_job_event(
                    "heartbeat",
                    "Service Heartbeat",
                    "error" if any_down else "ok",
                    "Status changed: " + ", ".join(parts),
                    {"services": current_statuses, "changes": {k: {"from": old, "to": new} for k, (old, new) in changed.items()}},
                )
            self._prev_health_statuses = current_statuses

        except Exception as e:
            logger.error(f"[Heartbeat] unexpected error: {e}", exc_info=True)

    async def _recurrence_job(self) -> None:
        """
        Recurring card reset — runs every hour.

        Finds all recurring cards whose recurrence_next is in the past,
        resets them to todo, and advances recurrence_next.
        No copies — the same card is reused each cycle.
        """
        try:
            from datetime import timedelta

            from sqlalchemy import select

            from app.database import Card, CardHistory, async_session, new_uuid, utcnow

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
                        old_status = card.status

                        # Reset card to todo for next execution cycle
                        card.status = "todo"
                        card.updated_at = utcnow()

                        # Track status change in history
                        if old_status != "todo":
                            db.add(CardHistory(
                                id=new_uuid(),
                                card_id=card.id,
                                field_changed="status",
                                old_value=old_status,
                                new_value="todo",
                                changed_at=utcnow(),
                                changed_by="Recurrence",
                            ))

                        # Advance recurrence_next
                        base = card.recurrence_next or now
                        if base.tzinfo is None:
                            base = base.replace(tzinfo=timezone.utc)
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
                            try:
                                from apscheduler.triggers.cron import CronTrigger
                                cron_expr = card.recurrence.replace("cron:", "").strip()
                                trigger = CronTrigger.from_crontab(cron_expr, timezone=timezone.utc)
                                # Compute the next fire strictly after now — using
                                # the stale `base` would yield a past timestamp
                                # after downtime and re-fire every hourly sweep.
                                new_next = trigger.get_next_fire_time(None, max(base, now))
                                if new_next is None:
                                    new_next = now + timedelta(days=1)
                            except Exception:
                                new_next = now + timedelta(days=1)
                        else:
                            delta = RECURRENCE_DELTAS.get(card.recurrence, timedelta(days=1))
                            new_next = base + delta
                            # Catch up after downtime: never persist a past
                            # recurrence_next, or the card resets to todo again
                            # on every subsequent sweep until caught up.
                            while new_next <= now:
                                new_next += delta

                        # Weekdays: skip weekends
                        if card.recurrence == "weekdays":
                            while new_next.weekday() >= 5:  # Sat=5, Sun=6
                                new_next += timedelta(days=1)

                        card.recurrence_next = new_next

                        logger.info(
                            f"[Recurrence] Reset card '{card.title}' (id={card.id}) "
                            f"to todo, recurrence={card.recurrence}, next={new_next}"
                        )

                    except Exception as e:
                        logger.error(
                            f"[Recurrence] Failed to process card {card.id}: {e}",
                            exc_info=True,
                        )

                await db.commit()

            if due_cards:
                from app.services.ws_broadcast import ws_broadcast
                for card in due_cards:
                    ws_broadcast.emit_sync("cards:changed", {
                        "workspaceId": card.workspace_id,
                        "cardId": card.id,
                    })
                titles = [c.title for c in due_cards[:5]]
                self._emit_job_event(
                    "recurrence",
                    "Recurring Card Reset",
                    "ok",
                    f"Reset {len(due_cards)} recurring card(s): {', '.join(titles)}",
                )

        except Exception as e:
            logger.error(f"[Recurrence] unexpected error: {e}", exc_info=True)

    async def _rag_index_job(self, workspace_ids: Optional[list[str]] = None) -> None:
        """
        Re-index workspaces with recent chat activity (last 30 min).

        For each recently-active workspace:
        - Re-indexes cards (title, description, status, priority)
        - Re-indexes workspace info (title, description, tech_stack)

        Keeps RAG context fresh without doing full re-index on every message.
        Uses RAGService.index_workspace() which upserts by card_id.

        If ``workspace_ids`` is provided, only those workspaces are considered
        (still gated by the "recent activity" cutoff). Pass None to scan
        all workspaces (default — used by the every-15min builtin sweep).

        Overlapping invocations are dropped: only one _rag_index_job may
        run at a time across the whole process. Without this, multiple
        rag_index job entries (builtin + user-created) would pile up on
        aligned schedules (e.g. :00 and :30) and stall the event loop.
        """
        # Lazy-init the lock on the running loop.
        if self._rag_index_lock is None:
            self._rag_index_lock = asyncio.Lock()

        if self._rag_index_lock.locked():
            logger.info(
                "[RAGIndex] Another rag_index pass is already running — "
                "skipping this invocation (scope=%s)",
                "all" if workspace_ids is None else f"{len(workspace_ids)} workspace(s)",
            )
            return

        async with self._rag_index_lock:
            await self._rag_index_job_inner(workspace_ids)

    async def _rag_index_job_inner(self, workspace_ids: Optional[list[str]]) -> None:
        try:
            from datetime import timedelta

            from app.database import async_session, Workspace, Card
            from app.services.rag_service import get_rag_service
            from app.services.session_store import session_store
            from sqlalchemy import select

            rag = get_rag_service()
            if not rag.enabled:
                logger.debug("[RAGIndex] RAG disabled — skipping")
                return

            cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
            scope_filter = set(workspace_ids) if workspace_ids else None

            async with async_session() as db:
                stmt = select(Workspace)
                if scope_filter:
                    stmt = stmt.where(Workspace.id.in_(scope_filter))
                result = await db.execute(stmt)
                workspaces = result.scalars().all()

                indexed_count = 0
                for workspace in workspaces:
                    try:
                        # Check if this workspace had recent chat activity
                        chat_id = f"workspace:{workspace.id}"
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

                        logger.info(f"[RAGIndex] Re-indexing workspace '{workspace.title}' (id={workspace.id})")

                        # Build workspace_info dict (matches RAGService.index_workspace signature)
                        workspace_info = {
                            "title": workspace.title or "",
                            "description": workspace.description or "",
                            "context": getattr(workspace, "tech_stack", "") or "",
                        }

                        # Fetch cards and build card dicts
                        cards_result = await db.execute(
                            select(Card).where(Card.workspace_id == workspace.id)
                        )
                        cards_orm = cards_result.scalars().all()
                        cards_dicts = [
                            {
                                "id": card.id,
                                "title": card.title or "",
                                "description": card.description or "",
                                "status": card.status or "backlog",
                                "agent_type": getattr(card, "agent_type", "") or "",
                            }
                            for card in cards_orm
                        ]

                        await rag.index_workspace(workspace.id, cards_dicts, workspace_info)
                        indexed_count += 1
                        logger.info(
                            f"[RAGIndex] Indexed workspace '{workspace.title}': {len(cards_dicts)} cards"
                        )

                    except Exception as e:
                        logger.error(f"[RAGIndex] Failed to index workspace {workspace.id}: {e}", exc_info=True)
                        # Continue with other workspaces — never abort the whole job

                if indexed_count:
                    logger.info(f"[RAGIndex] Done — re-indexed {indexed_count} active workspace(s)")
                    self._emit_job_event(
                        "rag_index",
                        "RAG Workspace Indexer",
                        "ok",
                        f"Re-indexed {indexed_count} active workspace(s)",
                    )
                else:
                    logger.debug("[RAGIndex] No recently-active workspaces to re-index")

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
                self._emit_job_event(
                    "session_cleanup",
                    "Session Cleanup",
                    "ok" if not errors else "warning",
                    f"Deleted {deleted} stale file(s) (>{max_age_days}d), {errors} error(s)",
                )
            else:
                logger.debug(f"[SessionCleanup] No stale session files found (threshold: {max_age_days}d)")

        except Exception as e:
            logger.error(f"[SessionCleanup] unexpected error: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # ChromaDB backup
    # ------------------------------------------------------------------

    async def _chromadb_backup_job(self) -> None:
        """Daily backup of all ChromaDB collections to timestamped directories.

        Exports each collection's documents, metadatas, and embeddings to a
        pickle file under ~/.voxyflow/backups/chromadb/<date>/. Old backups
        beyond the retention window are pruned automatically.
        """
        try:
            import os
            import pickle
            import shutil
            import time as _time

            # Read settings for retention
            from app.services.settings_loader import _load_settings_from_db
            settings = await _load_settings_from_db() or {}
            backup_cfg = settings.get("backup", {})
            if not backup_cfg.get("chromadb_enabled", False):
                logger.debug("[ChromaBackup] Disabled in settings — skipping")
                return

            retention_days = backup_cfg.get("retention_days", 7)

            chroma_dir = os.path.expanduser("~/.voxyflow/chroma")
            backup_root = Path(os.path.expanduser("~/.voxyflow/backups/chromadb"))
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            backup_dir = backup_root / today

            if backup_dir.exists():
                logger.debug(f"[ChromaBackup] Backup for {today} already exists — skipping")
                return

            backup_dir.mkdir(parents=True, exist_ok=True)

            import chromadb
            client = chromadb.PersistentClient(path=chroma_dir)
            collections = client.list_collections()

            total_docs = 0
            col_count = 0

            for col in collections:
                name = col.name
                count = col.count()
                if count == 0:
                    continue

                # Export all docs (by ID to avoid query-index issues)
                try:
                    all_data = col.get(include=["documents", "metadatas", "embeddings"])
                    with open(backup_dir / f"{name}.pkl", "wb") as f:
                        pickle.dump({
                            "ids": all_data["ids"],
                            "documents": all_data["documents"],
                            "metadatas": all_data["metadatas"],
                            "embeddings": all_data["embeddings"],
                        }, f)
                    total_docs += len(all_data["ids"])
                    col_count += 1
                except Exception as col_err:
                    logger.warning(f"[ChromaBackup] Failed to backup {name}: {col_err}")

            logger.info(
                f"[ChromaBackup] Backed up {col_count} collection(s), "
                f"{total_docs} doc(s) → {backup_dir}"
            )

            # Prune old backups
            cutoff = _time.time() - (retention_days * 86400)
            pruned = 0
            for entry in backup_root.iterdir():
                if entry.is_dir() and entry != backup_dir:
                    try:
                        dir_mtime = entry.stat().st_mtime
                        if dir_mtime < cutoff:
                            shutil.rmtree(entry)
                            pruned += 1
                    except Exception as prune_err:
                        logger.warning(f"[ChromaBackup] Failed to prune {entry}: {prune_err}")

            if pruned:
                logger.info(f"[ChromaBackup] Pruned {pruned} backup(s) older than {retention_days}d")

            self._emit_job_event(
                "chromadb_backup",
                "ChromaDB Backup",
                "ok",
                f"Backed up {col_count} collection(s), {total_docs} doc(s). Pruned {pruned} old backup(s).",
            )

        except Exception as e:
            logger.error(f"[ChromaBackup] unexpected error: {e}", exc_info=True)

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
