"""Voxyflow — Voice-first project management assistant."""

import asyncio
import json
import logging
import time
from uuid import uuid4

from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db
from app.routes import chats, projects, cards, voice, techdetect, github, settings, tools
from app.services.claude_service import ClaudeService
from app.services.analyzer_service import AnalyzerService
from app.tools import execute_tool, get_tool_definitions

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
app.include_router(techdetect.router)
app.include_router(github.router, prefix="/api")
app.include_router(settings.router)
app.include_router(tools.router, prefix="/api")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "voxyflow"}


_claude_service = ClaudeService()
_analyzer_service = AnalyzerService()


import re

def _parse_tool_calls(text: str) -> list[dict]:
    """Extract <tool_call>...</tool_call> blocks from Claude's response."""
    pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
    matches = re.findall(pattern, text, re.DOTALL)
    calls = []
    for match in matches:
        try:
            parsed = json.loads(match)
            if "name" in parsed:
                calls.append(parsed)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse tool call JSON: {match[:100]}")
    return calls


def _strip_tool_calls(text: str) -> str:
    """Remove <tool_call> blocks from text, leaving the conversational part."""
    return re.sub(r'<tool_call>\s*\{.*?\}\s*</tool_call>', '', text, flags=re.DOTALL).strip()


async def _handle_chat_3layer(
    websocket: WebSocket,
    content: str,
    message_id: str,
    chat_id: str,
    project_id: str | None,
    layers: dict[str, bool] | None = None,
    chat_level: str = "general",
    card_id: str | None = None,
) -> None:
    """
    3-Layer Multi-Model Chat Orchestration.

    Layer 1 — Haiku (fast, <1s): Immediate conversational response.
    Layer 2 — Opus (deep, 2-5s): Enriches/corrects if needed, runs in parallel.
    Layer 3 — Analyzer (background): Detects actionable items → card suggestions.
    """
    # Resolve project context from project_id
    project_context = None
    card_context = None
    if project_id:
        try:
            from app.database import async_session, Project, Card
            from sqlalchemy import select
            async with async_session() as db:
                result = await db.execute(select(Project).where(Project.id == project_id))
                proj = result.scalar_one_or_none()
                if proj:
                    project_context = {
                        "title": proj.title,
                        "description": proj.description or "",
                        "tech_stack": getattr(proj, "tech_stack", "") or "",
                        "github_url": proj.github_url or "",
                    }
                if card_id:
                    result = await db.execute(select(Card).where(Card.id == card_id))
                    c = result.scalar_one_or_none()
                    if c:
                        card_context = {
                            "title": c.title,
                            "description": c.description or "",
                            "status": c.status or "idea",
                            "priority": str(c.priority) if c.priority is not None else "medium",
                            "dependencies": "",
                        }
        except Exception as e:
            logger.warning(f"Failed to resolve project/card context: {e}")

    project_name = project_context.get("title") if project_context else None

    # Resolve layer toggles (default: all enabled)
    if layers is None:
        layers = {}
    opus_enabled = layers.get("opus", True)
    analyzer_enabled = layers.get("analyzer", True)

    # Helper to send model status updates
    async def _send_model_status(model: str, state: str) -> None:
        await websocket.send_json({
            "type": "model:status",
            "payload": {"model": model, "state": state},
            "timestamp": int(time.time() * 1000),
        })

    # Launch Opus + Analyzer in parallel (only if enabled)
    opus_task = None
    analyzer_task = None

    if opus_enabled:
        await _send_model_status("opus", "thinking")
        opus_task = asyncio.create_task(
            _claude_service.chat_opus_supervisor(
                chat_id=chat_id, user_message=content, project_name=project_name,
                chat_level=chat_level, project_context=project_context, card_context=card_context,
            )
        )

    if analyzer_enabled:
        await _send_model_status("analyzer", "thinking")
        analyzer_task = asyncio.create_task(
            _analyzer_service.analyze_for_cards(chat_id=chat_id, message=content, project_context="")
        )

    # --- Layer 1: Stream Haiku response token-by-token ---
    await _send_model_status("haiku", "active")
    start = time.time()
    haiku_full_response = ""
    try:
        first_token_sent = False
        async for token in _claude_service.chat_haiku_stream(
            chat_id=chat_id, user_message=content, project_name=project_name,
            chat_level=chat_level, project_context=project_context, card_context=card_context,
        ):
            haiku_full_response += token
            if not first_token_sent:
                first_token_latency = int((time.time() - start) * 1000)
                logger.info(f"[Layer1-Haiku] first token in {first_token_latency}ms")
                first_token_sent = True

            await websocket.send_json({
                "type": "chat:response",
                "payload": {
                    "messageId": message_id,
                    "content": token,
                    "model": "haiku",
                    "streaming": True,
                    "done": False,
                },
                "timestamp": int(time.time() * 1000),
            })

        # Send stream-done signal
        latency = int((time.time() - start) * 1000)
        logger.info(f"[Layer1-Haiku] stream complete in {latency}ms")
        await websocket.send_json({
            "type": "chat:response",
            "payload": {
                "messageId": message_id,
                "content": "",
                "model": "haiku",
                "streaming": True,
                "done": True,
                "latency_ms": latency,
            },
            "timestamp": int(time.time() * 1000),
        })
        await _send_model_status("haiku", "idle")
    except Exception as e:
        logger.error(f"[Layer1-Haiku] error: {e}")
        await _send_model_status("haiku", "error")
        await websocket.send_json({
            "type": "chat:error",
            "payload": {"messageId": message_id, "error": str(e)},
            "timestamp": int(time.time() * 1000),
        })
        # Cancel background tasks on Haiku failure
        if opus_task:
            opus_task.cancel()
        if analyzer_task:
            analyzer_task.cancel()
        return

    # --- Tool execution: parse <tool_call> blocks from Haiku response ---
    tool_calls = _parse_tool_calls(haiku_full_response)
    if tool_calls:
        from app.database import async_session
        async with async_session() as db:
            for tc in tool_calls:
                tool_name = tc["name"]
                tool_params = tc.get("params", tc.get("parameters", {}))
                logger.info(f"[Tools] executing: {tool_name}({tool_params})")
                result = await execute_tool(tool_name, tool_params, db=db)
                await websocket.send_json({
                    "type": "tool:result",
                    "payload": {
                        "tool": tool_name,
                        "success": result.success,
                        "data": result.data,
                        "error": result.error,
                        "ui_action": result.ui_action,
                    },
                    "timestamp": int(time.time() * 1000),
                })

    # --- Layer 2: Opus enrichment/correction ---
    if not opus_enabled or opus_task is None:
        logger.debug("[Layer2-Opus] skipped (disabled by user)")
    else:
        try:
            opus_result = await asyncio.wait_for(opus_task, timeout=15.0)
            if opus_result and opus_result.get("action") in ("enrich", "correct"):
                enrichment_id = str(uuid4())
                logger.info(f"[Layer2-Opus] action={opus_result['action']}, sending enrichment")
                await websocket.send_json({
                    "type": "chat:enrichment",
                    "payload": {
                        "messageId": enrichment_id,
                        "content": opus_result["content"],
                        "model": "opus",
                        "action": opus_result["action"],
                        "done": True,
                    },
                    "timestamp": int(time.time() * 1000),
                })
            else:
                logger.debug("[Layer2-Opus] no enrichment needed")
            await _send_model_status("opus", "idle")
        except asyncio.TimeoutError:
            logger.warning("[Layer2-Opus] timed out after 15s, skipping")
            await _send_model_status("opus", "idle")
        except asyncio.CancelledError:
            await _send_model_status("opus", "idle")
        except Exception as e:
            logger.error(f"[Layer2-Opus] error: {e}")
            await _send_model_status("opus", "error")

    # --- Layer 3: Analyzer card suggestions ---
    if not analyzer_enabled or analyzer_task is None:
        logger.debug("[Layer3-Analyzer] skipped (disabled by user)")
    else:
        try:
            cards = await asyncio.wait_for(analyzer_task, timeout=15.0)
            if cards:
                for card in cards:
                    logger.info(f"[Layer3-Analyzer] card suggestion: {card['title']}")
                    await websocket.send_json({
                        "type": "card:suggestion",
                        "payload": {
                            "title": card["title"],
                            "description": card.get("description", ""),
                            "agentType": card.get("agent_type", "ember"),
                            "agentName": card.get("agent_name", "Ember"),
                            "projectId": project_id or "",
                        },
                        "timestamp": int(time.time() * 1000),
                    })
            await _send_model_status("analyzer", "idle")
        except asyncio.TimeoutError:
            logger.warning("[Layer3-Analyzer] timed out after 15s, skipping")
            await _send_model_status("analyzer", "idle")
        except asyncio.CancelledError:
            await _send_model_status("analyzer", "idle")
        except Exception as e:
            logger.error(f"[Layer3-Analyzer] error: {e}")
            await _send_model_status("analyzer", "error")


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
                    msg_layers = payload.get("layers")  # {opus: bool, analyzer: bool}

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

                    # 3-Layer orchestration (Haiku + Opus + Analyzer in parallel)
                    await _handle_chat_3layer(
                        websocket=websocket,
                        content=content,
                        message_id=message_id,
                        chat_id=chat_id,
                        project_id=project_id,
                        layers=msg_layers,
                        chat_level=chat_level,
                        card_id=card_id,
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

                    # Clear conversation history for this chat
                    if chat_id in _claude_service._histories:
                        _claude_service._histories[chat_id] = []
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
