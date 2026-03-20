"""Voxyflow — Voice-first project management assistant."""

import json
import logging
import time

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.routes import chats, projects, cards, voice, techdetect, github, settings, sessions, documents, health, jobs, code, focus_sessions, mcp as mcp_routes
from app.services.claude_service import ClaudeService
from app.services.analyzer_service import AnalyzerService
from app.services.chat_orchestration import ChatOrchestrator
from app.services.rag_service import get_rag_service
from app.services.scheduler_service import get_scheduler_service


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.DEBUG if get_settings().debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("voxyflow")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events."""
    logger.info("🚀 Voxyflow starting up...")
    await init_db()
    logger.info("✅ Database initialized")

    # Initialize RAGService singleton (chromadb + sentence-transformers)
    rag = get_rag_service()
    if rag.enabled:
        logger.info("✅ RAGService initialized (ChromaDB + all-MiniLM-L6-v2)")
    else:
        logger.warning("⚠️  RAGService disabled (chromadb not installed — install chromadb + sentence-transformers to enable)")

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
app.include_router(voice.router, prefix="/api")
app.include_router(techdetect.router)
app.include_router(github.router, prefix="/api")
app.include_router(settings.router)
app.include_router(sessions.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(code.router, prefix="/api")
app.include_router(focus_sessions.router, prefix="/api")
app.include_router(mcp_routes.router)  # MCP server (SSE + stdio, no /api prefix)


_claude_service = ClaudeService()
_analyzer_service = AnalyzerService()
_orchestrator = ChatOrchestrator(_claude_service, _analyzer_service)


@app.websocket("/ws")
async def general_websocket(websocket: WebSocket):
    """
    General-purpose WebSocket endpoint for the frontend ApiClient.
    Handles ping/pong, chat messages (3-layer orchestration), and command dispatch.
    """
    await websocket.accept()
    logger.info("General WebSocket client connected")
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                msg_type = data.get("type")
                payload = data.get("payload", {})
                msg_id = data.get("id", "")

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

                    session_id = payload.get("sessionId")

                    # Derive chat_id from context for conversation isolation
                    if card_id:
                        chat_id = f"card:{card_id}"
                        chat_level = "card"
                    elif project_id:
                        chat_id = f"project:{project_id}"
                        if chat_level == "general":
                            chat_level = "project"
                    else:
                        chat_id = f"general:{session_id}" if session_id else "general"
                        chat_level = "general"

                    logger.info(f"[WS] chat:message → chat_id={chat_id}, level={chat_level}, layers={msg_layers}: {content[:80]!r}")

                    # 3-Layer orchestration (Fast + Deep + Analyzer in parallel)
                    await _orchestrator.handle_message(
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

                elif msg_type == "session:reset":
                    chat_level = payload.get("chatLevel", "general")
                    project_id = payload.get("projectId")
                    session_id = payload.get("sessionId")

                    # Derive chat_id matching the conversation isolation logic
                    if project_id:
                        chat_id = f"project:{project_id}"
                    else:
                        chat_id = f"general:{session_id}" if session_id else "general"

                    _orchestrator.reset_session(chat_id)
                    logger.info(f"[WS] session:reset → cleared history for {chat_id}")

                    await websocket.send_json({
                        "type": "session:reset_ack",
                        "payload": {"chatId": chat_id},
                        "timestamp": int(time.time() * 1000),
                    })

                else:
                    # Ack unknown message types
                    await websocket.send_json({
                        "type": "ack",
                        "payload": {"received": msg_type},
                        "timestamp": data.get("timestamp"),
                    })

            except Exception as e:
                logger.warning(f"WS message parse error: {e}")
    except WebSocketDisconnect:
        logger.info("General WebSocket client disconnected")
    except Exception as e:
        logger.exception(f"General WebSocket error: {e}")


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
