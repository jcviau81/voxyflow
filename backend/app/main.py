"""Voxyflow — Voice-first project management assistant."""

import asyncio
import json
import logging
import time
from uuid import uuid4

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, SYSTEM_MAIN_PROJECT_ID
from app.routes import chats, projects, cards, techdetect, github, settings, sessions, documents, health, jobs, code, focus_sessions, mcp as mcp_routes, workspace, workers, models, worker_tasks
from app.services.claude_service import ClaudeService
from app.services.analyzer_service import AnalyzerService
from app.services.chat_orchestration import ChatOrchestrator
from app.services.rag_service import get_rag_service
from app.services.scheduler_service import get_scheduler_service
from app.services.pending_results import pending_store
from app.services.board_executor import execute_board, cancel_execution, build_execution_plan, CardPlan


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.DEBUG if get_settings().debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("voxyflow")

# --- File-based logging (RotatingFileHandler) ---
import os as _os
from logging.handlers import RotatingFileHandler as _RotatingFileHandler
_log_dir = _os.path.expanduser("~/.voxyflow/logs")
_os.makedirs(_log_dir, exist_ok=True)
_log_file = _os.path.join(_log_dir, "backend.log")
_file_handler = _RotatingFileHandler(
    _log_file,
    maxBytes=10 * 1024 * 1024,  # 10 MB
    backupCount=3,
    encoding="utf-8",
)
_file_handler.setLevel(logging.DEBUG if get_settings().debug else logging.INFO)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
)
logging.getLogger().addHandler(_file_handler)
logger.info("File logging enabled: %s (max 10MB, 3 backups)", _log_file)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

async def _cleanup_stale_worker_tasks():
    """Purge terminal worker tasks older than 24h from the database."""
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import delete, and_
    from app.database import async_session, WorkerTask

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
    except Exception as e:
        logger.warning(f"⚠️  Worker task cleanup failed (non-fatal): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events."""
    logger.info("🚀 Voxyflow starting up...")
    await init_db()
    logger.info("✅ Database initialized")

    # Cleanup stale worker tasks (done/failed/cancelled older than 24h)
    await _cleanup_stale_worker_tasks()

    # Ensure workspace directory exists
    from app.services.workspace_service import get_workspace_service
    ws_service = get_workspace_service()
    ws_path = await ws_service.ensure_workspace()
    logger.info("✅ Workspace ready: %s", ws_path)

    # Initialize RAGService singleton (chromadb + sentence-transformers)
    rag = get_rag_service()
    if rag.enabled:
        logger.info("✅ RAGService initialized (ChromaDB + intfloat/multilingual-e5-large)")
    else:
        logger.warning("⚠️  RAGService disabled (chromadb not installed — install chromadb + sentence-transformers to enable)")

    # Initialize MemoryService and run one-time migration if needed
    from app.services.memory_service import get_memory_service
    memory = get_memory_service()
    if memory.chromadb_enabled:
        logger.info("✅ MemoryService ChromaDB initialized")
        try:
            migrated = await memory.migrate_from_files()
            if migrated > 0:
                logger.info(f"✅ Migrated {migrated} memory entries from files to ChromaDB")
        except Exception as e:
            logger.warning(f"⚠️  Memory migration failed (non-fatal): {e}")
    else:
        logger.info("ℹ️  MemoryService using file-based fallback")

    # Start scheduler (heartbeat + RAG indexer)
    scheduler = get_scheduler_service()
    _app_settings = get_settings()
    # Load scheduler settings from settings.json if available
    _sched_enabled = True
    _heartbeat_interval = 2
    _rag_interval = 15
    try:
        import json, os
        from pathlib import Path
        _voxyflow_dir = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/voxyflow")))
        _settings_file = _voxyflow_dir / "settings.json"
        if _settings_file.exists():
            with open(_settings_file) as _f:
                _stored = json.load(_f)
            _sched_cfg = _stored.get("scheduler", {})
            _sched_enabled = _sched_cfg.get("enabled", True)
            _heartbeat_interval = _sched_cfg.get("heartbeat_interval_minutes", 2)
            _rag_interval = _sched_cfg.get("rag_index_interval_minutes", 15)
    except Exception as _e:
        logger.warning(f"Failed to load scheduler settings: {_e} — using defaults")

    if _sched_enabled:
        scheduler.start(
            heartbeat_interval_minutes=_heartbeat_interval,
            rag_index_interval_minutes=_rag_interval,
        )
    else:
        logger.info("⏸️  Scheduler disabled via settings")

    yield

    # Shutdown scheduler cleanly
    scheduler.stop()
    logger.info("👋 Voxyflow shutting down")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Voxyflow",
    description="Voice-first project management assistant with multi-model orchestration",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — permissive for MVP (single-user, localhost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(chats.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(cards.router, prefix="/api")
app.include_router(techdetect.router)
app.include_router(github.router, prefix="/api")
app.include_router(settings.router)
app.include_router(sessions.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(code.router, prefix="/api")
app.include_router(focus_sessions.router, prefix="/api")
app.include_router(workspace.router)
app.include_router(workers.router)
app.include_router(worker_tasks.router)
app.include_router(models.router)
app.include_router(mcp_routes.router)  # MCP server (SSE + stdio, no /api prefix)


_claude_service = ClaudeService()
_analyzer_service = AnalyzerService()
_orchestrator = ChatOrchestrator(_claude_service, _analyzer_service)



# Serve frontend (SPA)
_frontend_dist = Path(__file__).parent.parent.parent / "frontend-react" / "dist"
if _frontend_dist.exists():
    app.mount("/static-dist", StaticFiles(directory=str(_frontend_dist)), name="static-dist")

@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    if _frontend_dist.exists():
        fp = _frontend_dist / full_path
        if fp.exists() and fp.is_file():
            return FileResponse(str(fp))
        return FileResponse(str(_frontend_dist / "index.html"))
    from fastapi import HTTPException
    raise HTTPException(status_code=404)

@app.websocket("/ws")
async def general_websocket(websocket: WebSocket):
    """
    General-purpose WebSocket endpoint for the frontend ApiClient.
    Handles ping/pong, chat messages (3-layer orchestration), and command dispatch.
    """
    await websocket.accept()
    logger.info("General WebSocket client connected")
    # Register for broadcast events (card changes from REST routes)
    from app.services.ws_broadcast import ws_broadcast
    ws_broadcast.register(websocket)
    # Track session IDs that got worker pools for cleanup
    active_session_ids: set[str] = set()
    # Fix 3: track fire-and-forget background tasks for cancellation on disconnect
    bg_tasks: list[asyncio.Task] = []

    async def _deliver_pending(sid: str) -> None:
        """Deliver any pending worker results for this session.

        Always fetches from store — deduplication is handled by mark_delivered()
        which deletes the file, so get_pending() won't return already-delivered results.
        This allows correct re-delivery after client reconnects.
        """
        try:
            pending = await pending_store.get_pending(sid)
            for result in pending:
                try:
                    # Remove internal tracking key before sending
                    pending_file = result.pop("_pending_file", None)
                    await websocket.send_json(result)
                    logger.info(f"[WS] Delivered pending result: {result.get('type')} task={result.get('payload', {}).get('taskId')}")
                    # Re-add for cleanup
                    if pending_file:
                        result["_pending_file"] = pending_file
                    await pending_store.mark_delivered(result)
                except Exception as e:
                    logger.warning(f"[WS] Failed to deliver pending result: {e}")
                    break  # WS probably closed, stop trying
        except Exception as e:
            logger.warning(f"[WS] Error checking pending results: {e}")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                msg_type = data.get("type")
                payload = data.get("payload", {})
                msg_id = data.get("id", "")

                if msg_type != "ping":
                    logger.info(f"[WS] Received: {msg_type}")

                if msg_type == "ping":
                    await websocket.send_json({
                        "type": "pong",
                        "payload": {},
                        "timestamp": data.get("timestamp"),
                    })

                elif msg_type == "chat:message":
                    content = payload.get("content", "")
                    message_id = payload.get("messageId", msg_id)
                    project_id = payload.get("projectId")
                    card_id = payload.get("cardId")
                    chat_level = payload.get("chatLevel", "general")
                    msg_layers = payload.get("layers")  # {deep: bool, analyzer: bool}

                    session_id = payload.get("sessionId") or str(uuid4())

                    # Deliver any pending results from previous connection
                    await _deliver_pending(session_id)

                    # Derive chat_id from context for conversation isolation
                    # If the frontend sends a stable chatId, use it directly.
                    frontend_chat_id = payload.get("chatId")

                    if frontend_chat_id:
                        # Frontend-provided stable chat_id (cross-device sync)
                        chat_id = frontend_chat_id
                        if not project_id:
                            project_id = SYSTEM_MAIN_PROJECT_ID
                        if chat_id.startswith("card:"):
                            chat_level = "card"
                        elif chat_level == "general":
                            chat_level = "project" if project_id != SYSTEM_MAIN_PROJECT_ID else "general"
                    elif card_id:
                        chat_id = f"card:{card_id}"
                        chat_level = "card"
                    elif project_id:
                        chat_id = f"project:{project_id}"
                        if chat_level == "general":
                            chat_level = "project"
                    else:
                        # No project specified → default to system-main project
                        project_id = SYSTEM_MAIN_PROJECT_ID
                        chat_id = f"project:{SYSTEM_MAIN_PROJECT_ID}"
                        chat_level = "general"  # Keep "general" for backward compat in prompts

                    logger.info(f"[WS] chat:message → chat_id={chat_id}, level={chat_level}, layers={msg_layers}: {content[:80]!r}")

                    # Ensure worker pool is running for this session
                    if session_id:
                        active_session_ids.add(session_id)

                    # Broadcast user message to OTHER connected clients (cross-device sync)
                    await ws_broadcast.emit_to_others(websocket, "chat:message:new", {
                        "chatId": chat_id,
                        "sessionId": session_id,
                        "message": {
                            "role": "user",
                            "content": content,
                            "timestamp": time.time(),
                        },
                    })

                    # 3-Layer orchestration (Fast + Deep + Analyzer in parallel)
                    # Fix 3: collect returned background tasks for cleanup on disconnect
                    new_tasks = await _orchestrator.handle_message(
                        websocket=websocket,
                        content=content,
                        message_id=message_id,
                        chat_id=chat_id,
                        project_id=project_id,
                        layers=msg_layers,
                        chat_level=chat_level,
                        card_id=card_id,
                        session_id=session_id,
                    )
                    if new_tasks:
                        bg_tasks.extend(new_tasks)

                    # Broadcast completed assistant response to OTHER connected clients
                    # (after orchestrator returns — fast layer is complete at this point)
                    try:
                        history = _orchestrator._claude.get_history(chat_id)
                        last_assistant = None
                        for msg in reversed(history):
                            if msg.get("role") == "assistant" and msg.get("content"):
                                last_assistant = msg
                                break
                        if last_assistant:
                            await ws_broadcast.emit_to_others(websocket, "chat:message:new", {
                                "chatId": chat_id,
                                "sessionId": session_id,
                                "message": {
                                    "role": "assistant",
                                    "content": last_assistant.get("content", ""),
                                    "timestamp": time.time(),
                                    "model": last_assistant.get("model"),
                                },
                            })
                    except Exception as _broadcast_err:
                        logger.warning(f"[WS] Failed to broadcast assistant message: {_broadcast_err}")

                elif msg_type == "session:reset":
                    chat_level = payload.get("chatLevel", "general")
                    project_id = payload.get("projectId")
                    card_id = payload.get("cardId")
                    session_id = payload.get("sessionId") or str(uuid4())
                    frontend_chat_id = payload.get("chatId")

                    # Derive chat_id matching the conversation isolation logic
                    if frontend_chat_id:
                        chat_id = frontend_chat_id
                    elif card_id:
                        chat_id = f"card:{card_id}"
                    elif project_id:
                        chat_id = f"project:{project_id}"
                    else:
                        chat_id = f"project:{SYSTEM_MAIN_PROJECT_ID}"

                    # Fix 5: full session teardown — stop worker pool, clear event bus,
                    # remove from active_session_ids, then clear chat history.
                    if session_id in active_session_ids:
                        active_session_ids.discard(session_id)
                        try:
                            await _orchestrator.stop_worker_pool(session_id)
                            logger.info(f"[WS] session:reset → stopped worker pool for {session_id}")
                        except Exception as _e:
                            logger.warning(f"[WS] session:reset worker pool stop failed: {_e}")

                    _orchestrator.reset_session(chat_id)
                    logger.info(f"[WS] session:reset → cleared history for {chat_id}")

                    await websocket.send_json({
                        "type": "session:reset_ack",
                        "payload": {"chatId": chat_id, "sessionId": session_id},
                        "timestamp": int(time.time() * 1000),
                    })

                elif msg_type == "kanban:execute:start":
                    project_id = payload.get("projectId")
                    session_id = payload.get("sessionId") or str(uuid4())
                    statuses = payload.get("statuses", ["todo", "in-progress"])

                    if not project_id:
                        await websocket.send_json({
                            "type": "kanban:execute:error",
                            "payload": {"error": "projectId is required"},
                            "timestamp": int(time.time() * 1000),
                        })
                    else:
                        # Build execution plan
                        plan = await build_execution_plan(project_id, statuses)
                        if plan.total == 0:
                            await websocket.send_json({
                                "type": "kanban:execute:error",
                                "payload": {"error": "No cards to execute"},
                                "timestamp": int(time.time() * 1000),
                            })
                        else:
                            # Ensure worker pool is running
                            active_session_ids.add(session_id)

                            # Launch execution as background task
                            exec_task = asyncio.create_task(
                                execute_board(
                                    execution_id=plan.execution_id,
                                    project_id=project_id,
                                    cards=plan.cards,
                                    websocket=websocket,
                                    orchestrator=_orchestrator,
                                    session_id=session_id,
                                )
                            )
                            bg_tasks.append(exec_task)
                            logger.info(f"[WS] kanban:execute:start → execution_id={plan.execution_id}, {plan.total} cards")

                elif msg_type == "kanban:execute:cancel":
                    execution_id = payload.get("executionId")
                    if execution_id:
                        cancelled = cancel_execution(execution_id)
                        logger.info(f"[WS] kanban:execute:cancel → {execution_id}, found={cancelled}")

                elif msg_type == "task:cancel":
                    task_id = payload.get("taskId")
                    session_id = payload.get("sessionId")
                    if task_id and session_id:
                        cancelled = await _orchestrator.cancel_worker_task(session_id, task_id)
                        logger.info(f"[WS] task:cancel → task_id={task_id}, session={session_id}, cancelled={cancelled}")
                    else:
                        logger.warning(f"[WS] task:cancel missing taskId or sessionId")

                elif msg_type == "action:confirm":
                    task_id = payload.get("taskId")
                    confirmed = payload.get("confirmed", False)
                    if task_id:
                        await _orchestrator.handle_action_confirm(task_id, confirmed, websocket)
                        logger.info(f"[WS] action:confirm → task_id={task_id}, confirmed={confirmed}")
                    else:
                        logger.warning("[WS] action:confirm missing taskId")

                elif msg_type == "session:sync":
                    # Deliver any pending worker results for the reconnecting session.
                    # Frontend sends this immediately on WebSocket connect so results
                    # are delivered without waiting for the next chat:message.
                    sync_session_id = payload.get("sessionId") or ""
                    if sync_session_id:
                        logger.info(f"[WS] session:sync → delivering pending for {sync_session_id}")
                        await _deliver_pending(sync_session_id)
                        # Update WebSocket reference on any surviving worker pool
                        # so in-flight workers can stream to the reconnected client.
                        _orchestrator.update_pool_websocket(sync_session_id, websocket)
                        active_session_ids.add(sync_session_id)

                else:
                    # Ack unknown message types
                    await websocket.send_json({
                        "type": "ack",
                        "payload": {"received": msg_type, "sessionId": payload.get("sessionId")},
                        "timestamp": data.get("timestamp"),
                    })

            except Exception as e:
                logger.warning(f"WS message parse error: {e}")
    except WebSocketDisconnect:
        logger.info("General WebSocket client disconnected")
    except Exception as e:
        logger.exception(f"General WebSocket error: {e}")
    finally:
        # Unregister from broadcast
        ws_broadcast.unregister(websocket)
        # NOTE: Do NOT cancel bg_tasks or stop worker pools on disconnect.
        # Workers must survive a browser refresh — they continue running and
        # store their results via pending_store for delivery on reconnect.
        if bg_tasks:
            running = sum(1 for t in bg_tasks if not t.done())
            logger.info(f"[WS] Disconnected — {running} background task(s) still running (workers persist)")
        # NOTE: Worker pools for active_session_ids are kept alive intentionally.
        # They will be stopped only on explicit session:reset from the frontend.


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
