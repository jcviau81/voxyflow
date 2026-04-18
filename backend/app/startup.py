"""Lifespan / startup bootstrap for the FastAPI app.

Extracted from ``app/main.py`` to keep the HTTP entrypoint small and keep
startup logic importable/testable on its own.

Usage in main.py::

    from app.startup import build_lifespan
    app = FastAPI(..., lifespan=build_lifespan(_claude_service, _orchestrator))

All DB/chromadb/scheduler init lives here, plus the background cleanup task.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI

if TYPE_CHECKING:
    from app.services.chat_orchestration import ChatOrchestrator
    from app.services.claude_service import ClaudeService

logger = logging.getLogger("voxyflow")

# Seconds of continuous idleness before a DeepWorkerPool is stopped.
IDLE_POOL_TIMEOUT = 1800  # 30 minutes


async def _cleanup_stale_worker_tasks() -> None:
    """Purge terminal worker tasks older than 24h from the database."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import and_, delete
    from app.database import WorkerTask, async_session

    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        async with async_session() as db:
            result = await db.execute(
                delete(WorkerTask).where(
                    and_(
                        WorkerTask.status.in_(["done", "failed", "cancelled", "timed_out"]),
                        WorkerTask.created_at < cutoff,
                    )
                )
            )
            await db.commit()
            if result.rowcount > 0:
                logger.info(f"🧹 Cleaned up {result.rowcount} stale worker tasks (>24h)")
            else:
                logger.info("🧹 No stale worker tasks to clean up")
    except Exception:
        logger.exception("⚠️  Worker task cleanup failed (non-fatal)")


async def _sync_settings_from_db(claude_service: "ClaudeService") -> None:
    """Pull settings.json from DB, then trigger a ClaudeService model reload."""
    from app.routes.settings import _load_settings_from_db, AppSettings, SETTINGS_FILE

    try:
        db_settings = await _load_settings_from_db()
        if db_settings:
            merged = AppSettings(**db_settings).dict()
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w") as f:
                json.dump(merged, f, indent=2)
            logger.info("✅ Settings synced from DB → settings.json")
        claude_service.reload_models()
    except Exception:
        logger.exception("Failed to load settings from DB — using defaults")


async def _init_personality_files() -> None:
    from app.routes.settings import init_personality_files as _init

    try:
        await _init()
        logger.info("✅ Personality files initialized")
    except Exception:
        logger.exception("Failed to initialize personality files")


async def _init_memory_service() -> None:
    from app.services.memory_service import get_memory_service

    memory = get_memory_service()
    if not memory.chromadb_enabled:
        logger.info("ℹ️  MemoryService using file-based fallback")
        return

    logger.info("✅ MemoryService ChromaDB initialized")
    try:
        repair_results = memory.repair_collections()
        repaired = {k: v for k, v in repair_results.items() if v.startswith("repaired")}
        if repaired:
            for col_name, status in repaired.items():
                logger.warning(f"🔧 ChromaDB auto-repair: {col_name} → {status}")
        else:
            logger.info("✅ ChromaDB collections healthy")
    except Exception:
        logger.exception("⚠️  ChromaDB repair check failed (non-fatal)")
    try:
        migrated = await memory.migrate_from_files()
        if migrated > 0:
            logger.info(f"✅ Migrated {migrated} memory entries from files to ChromaDB")
    except Exception:
        logger.exception("⚠️  Memory migration failed (non-fatal)")


def _load_scheduler_config() -> tuple[bool, int, int, bool, int]:
    """Read scheduler config from settings.json. Returns (enabled, hb_min, rag_min, backup_enabled, backup_hour)."""
    enabled = True
    heartbeat_interval = 2
    rag_interval = 15
    backup_enabled = False
    backup_hour = 3
    try:
        voxyflow_data_dir = Path(os.environ.get("VOXYFLOW_DATA_DIR", str(Path.home() / ".voxyflow")))
        settings_file = voxyflow_data_dir / "settings.json"
        if settings_file.exists():
            with open(settings_file) as f:
                stored = json.load(f)
            sched_cfg = stored.get("scheduler", {})
            enabled = sched_cfg.get("enabled", True)
            heartbeat_interval = sched_cfg.get("heartbeat_interval_minutes", 2)
            rag_interval = sched_cfg.get("rag_index_interval_minutes", 15)
            backup_cfg = stored.get("backup", {})
            backup_enabled = backup_cfg.get("chromadb_enabled", False)
            backup_hour = backup_cfg.get("backup_hour", 3)
    except Exception:
        logger.exception("Failed to load scheduler settings — using defaults")
    return enabled, heartbeat_interval, rag_interval, backup_enabled, backup_hour


async def _periodic_cleanup(orchestrator: "ChatOrchestrator") -> None:
    """Background loop: clean idle CLI sessions, event buses, pending results, and worker pools."""
    from app.services.cli_session_registry import get_cli_session_registry
    from app.services.event_bus import event_bus_registry
    from app.services.pending_results import pending_store
    from starlette.websockets import WebSocketState

    pool_idle_since: dict[str, float] = {}

    while True:
        await asyncio.sleep(300)  # 5 minutes

        try:
            killed = await get_cli_session_registry().cleanup_inactive(1800)
            if killed:
                logger.info(f"[Cleanup] Killed {killed} idle persistent chat sessions")
        except Exception as e:
            logger.debug(f"[Cleanup] idle session cleanup error: {e}")

        try:
            cleaned = event_bus_registry.cleanup_idle(3600)
            if cleaned:
                logger.info(f"[Cleanup] Removed {cleaned} idle EventBus instance(s)")
        except Exception as e:
            logger.debug(f"[Cleanup] EventBus cleanup error: {e}")

        try:
            removed = await pending_store.cleanup_stale(86400)
            if removed:
                logger.info(f"[Cleanup] Removed {removed} stale pending result(s)")
        except Exception as e:
            logger.debug(f"[Cleanup] pending results cleanup error: {e}")

        # Idle DeepWorkerPool cleanup
        try:
            now = time.monotonic()
            to_stop: list[str] = []
            live_pool_ids: set[str] = set()
            for sid, pool in list(orchestrator._worker_pools.items()):
                live_pool_ids.add(sid)
                if pool._stopped:
                    to_stop.append(sid)
                    continue
                has_active = bool(pool._active_tasks)
                ws = pool._ws
                ws_alive = ws is not None and ws.client_state == WebSocketState.CONNECTED
                if has_active or ws_alive:
                    pool_idle_since.pop(sid, None)
                    continue
                first_idle = pool_idle_since.get(sid)
                if first_idle is None:
                    pool_idle_since[sid] = now
                elif now - first_idle >= IDLE_POOL_TIMEOUT:
                    to_stop.append(sid)
            for sid in list(pool_idle_since.keys()):
                if sid not in live_pool_ids:
                    pool_idle_since.pop(sid, None)
            for sid in to_stop:
                try:
                    await orchestrator.stop_worker_pool(sid)
                    pool_idle_since.pop(sid, None)
                    logger.info(f"[Cleanup] Stopped idle worker pool: {sid}")
                except Exception:
                    logger.exception("[Cleanup] Failed to stop idle pool %s", sid)
        except Exception as e:
            logger.debug(f"[Cleanup] idle worker pool cleanup error: {e}")


def build_lifespan(
    claude_service: "ClaudeService",
    orchestrator: "ChatOrchestrator",
):
    """Return a FastAPI lifespan context manager bound to the given services."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.config import get_settings
        from app.database import init_db
        from app.services.rag_service import get_rag_service
        from app.services.scheduler_service import get_scheduler_service
        from app.services.workspace_service import get_workspace_service

        logger.info("🚀 Voxyflow starting up...")
        await init_db()
        logger.info("✅ Database initialized")

        await _sync_settings_from_db(claude_service)
        await _init_personality_files()
        await _cleanup_stale_worker_tasks()

        ws_service = get_workspace_service()
        ws_path = await ws_service.ensure_workspace()
        logger.info("✅ Workspace ready: %s", ws_path)

        rag = get_rag_service()
        if rag.enabled:
            logger.info("✅ RAGService initialized (ChromaDB + intfloat/multilingual-e5-large)")
        else:
            logger.warning("⚠️  RAGService disabled (chromadb not installed — install chromadb + sentence-transformers to enable)")

        await _init_memory_service()

        scheduler = get_scheduler_service()
        get_settings()  # touch settings so env is loaded early
        sched_enabled, _hb, _rag, backup_enabled, backup_hour = _load_scheduler_config()
        scheduler._backup_hour = backup_hour
        scheduler._backup_enabled = backup_enabled

        if sched_enabled:
            scheduler.start()
        else:
            logger.info("⏸️  Scheduler disabled via settings")

        if not backup_enabled:
            logger.info("💡 ChromaDB daily backup is disabled. Enable it in Settings → Backup to protect your memory data.")

        idle_cleanup_task = asyncio.create_task(_periodic_cleanup(orchestrator))

        try:
            yield
        finally:
            idle_cleanup_task.cancel()

            from app.services.cli_session_registry import get_cli_session_registry

            killed = await get_cli_session_registry().kill_all()
            if killed:
                logger.info(f"Killed {killed} active CLI sessions on shutdown")

            scheduler.stop()
            logger.info("Voxyflow shutting down")

    return lifespan
