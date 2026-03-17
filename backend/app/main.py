"""Voxyflow — Voice-first project management assistant."""

import json
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.routes import chats, projects, cards, voice

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
    yield
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


@app.get("/health")
async def health():
    return {"status": "ok", "service": "voxyflow"}


@app.websocket("/ws")
async def general_websocket(websocket: WebSocket):
    """
    General-purpose WebSocket endpoint for the frontend ApiClient.
    Handles ping/pong, broadcasts, and command dispatch.
    """
    await websocket.accept()
    logger.info("General WebSocket client connected")
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
                msg_type = data.get("type")
                if msg_type == "ping":
                    await websocket.send_json({"type": "pong", "payload": {}, "timestamp": data.get("timestamp")})
                else:
                    # Echo back with ack for now
                    await websocket.send_json({"type": "ack", "payload": {"received": msg_type}, "timestamp": data.get("timestamp")})
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
