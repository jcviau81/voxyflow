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
from app.routes import chats, projects, cards, voice, techdetect, github, settings, tools, sessions, documents, health, jobs, code, focus_sessions, mcp as mcp_routes
from app.services.claude_service import ClaudeService
from app.services.analyzer_service import AnalyzerService
from app.services.session_store import session_store
from app.services.rag_service import get_rag_service
from app.services.scheduler_service import get_scheduler_service
from app.tools import execute_tool, get_tool_definitions  # kept for legacy REST tool routes

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
        _voxyflow_dir = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/.openclaw/workspace/voxyflow")))
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
app.include_router(tools.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(health.router)
app.include_router(jobs.router)
app.include_router(code.router, prefix="/api")
app.include_router(focus_sessions.router, prefix="/api")
app.include_router(mcp_routes.router)  # MCP server (SSE + stdio, no /api prefix)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "voxyflow"}


_claude_service = ClaudeService()
_analyzer_service = AnalyzerService()


import re


async def _handle_chat_3layer(
    websocket: WebSocket,
    content: str,
    message_id: str,
    chat_id: str,
    project_id: str | None,
    layers: dict[str, bool] | None = None,
    chat_level: str = "general",
    card_id: str | None = None,
    session_id: str | None = None,
) -> None:
    """
    3-Layer Multi-Model Chat Orchestration.

    Layer 1 — Fast (<1s): Immediate conversational response.
    Layer 2 — Deep (2-5s): Enriches/corrects if needed, runs in parallel.
    Layer 3 — Analyzer (background): Detects actionable items → card suggestions.
    """
    # Resolve project context from project_id
    project_context = None
    card_context = None
    project_names: list[str] = []
    if project_id:
        try:
            from app.database import async_session, Project, Card, Sprint
            from sqlalchemy import select
            async with async_session() as db:
                result = await db.execute(select(Project).where(Project.id == project_id))
                proj = result.scalar_one_or_none()
                if proj:
                    # Fetch cards for this project (for dynamic state counts)
                    cards_result = await db.execute(
                        select(Card).where(Card.project_id == project_id)
                    )
                    proj_cards = cards_result.scalars().all()
                    cards_list = [
                        {
                            "title": c.title,
                            "status": c.status or "idea",
                            "updated_at": str(c.updated_at) if hasattr(c, "updated_at") and c.updated_at else "",
                        }
                        for c in proj_cards
                    ]

                    # Fetch active sprint
                    sprint_result = await db.execute(
                        select(Sprint).where(
                            Sprint.project_id == project_id,
                            Sprint.status == "active",
                        )
                    )
                    active_sprint = sprint_result.scalar_one_or_none()
                    sprint_name = active_sprint.name if active_sprint else None

                    project_context = {
                        "id": proj.id,
                        "title": proj.title,
                        "description": proj.description or "",
                        "tech_stack": getattr(proj, "tech_stack", "") or "",
                        "github_url": proj.github_url or "",
                        "cards": cards_list,
                        "active_sprint_name": sprint_name,
                    }
                if card_id:
                    result = await db.execute(select(Card).where(Card.id == card_id))
                    c = result.scalar_one_or_none()
                    if c:
                        # Fetch checklist items for this card
                        from app.database import ChecklistItem
                        cl_result = await db.execute(
                            select(ChecklistItem).where(ChecklistItem.card_id == card_id)
                        )
                        checklist_items = cl_result.scalars().all()
                        card_context = {
                            "id": c.id,
                            "title": c.title,
                            "description": c.description or "",
                            "status": c.status or "idea",
                            "priority": str(c.priority) if c.priority is not None else "medium",
                            "agent_type": getattr(c, "agent_type", None) or "ember",
                            "assignee": getattr(c, "assignee", None),
                            "checklist_items": [
                                {"done": getattr(item, "done", False) or getattr(item, "completed", False)}
                                for item in checklist_items
                            ],
                        }
        except Exception as e:
            logger.warning(f"Failed to resolve project/card context: {e}")

    # For general chat: fetch all project names for the Chat Init block
    if chat_level == "general" or not project_id:
        try:
            from app.database import async_session, Project
            from sqlalchemy import select
            async with async_session() as db:
                all_proj_result = await db.execute(
                    select(Project.title).where(Project.status != "archived")
                )
                project_names = [row[0] for row in all_proj_result.fetchall()]
        except Exception as e:
            logger.warning(f"Failed to fetch project names for general chat init: {e}")

    project_name = project_context.get("title") if project_context else None

    # Resolve layer toggles (default: all enabled)
    if layers is None:
        layers = {}
    deep_enabled = layers.get("deep", layers.get("opus", True))  # support legacy "opus" key too
    analyzer_enabled = layers.get("analyzer", True)

    # Helper to send model status updates
    async def _send_model_status(model: str, state: str) -> None:
        await websocket.send_json({
            "type": "model:status",
            "payload": {"model": model, "state": state, "sessionId": session_id},
            "timestamp": int(time.time() * 1000),
        })

    # Launch Deep + Analyzer in parallel (only if enabled)
    deep_task = None
    analyzer_task = None

    if deep_enabled:
        await _send_model_status("deep", "thinking")
        deep_task = asyncio.create_task(
            _claude_service.chat_deep_supervisor(
                chat_id=chat_id, user_message=content, project_name=project_name,
                chat_level=chat_level, project_context=project_context, card_context=card_context,
                project_id=project_id,
            )
        )

    if analyzer_enabled:
        await _send_model_status("analyzer", "thinking")
        analyzer_task = asyncio.create_task(
            _analyzer_service.analyze_for_cards(chat_id=chat_id, message=content, project_context="")
        )

    # --- Tool callback: emits tool:executed events over the WebSocket -------
    # This is called by the MCP bridge inside _call_api_stream whenever Claude
    # invokes a native tool_use block.  We schedule the send on the event loop
    # from the sync thread that executes the callback.
    _pending_tool_events: list[dict] = []

    def _on_tool_executed(tool_name: str, arguments: dict, result: dict) -> None:
        """Collect tool execution events; they are flushed after streaming ends."""
        _pending_tool_events.append({
            "tool": tool_name,
            "arguments": arguments,
            "result": result,
        })

    # --- Layer 1: Stream fast response token-by-token ---
    await _send_model_status("fast", "active")
    start = time.time()
    fast_full_response = ""
    try:
        first_token_sent = False
        async for token in _claude_service.chat_fast_stream(
            chat_id=chat_id, user_message=content, project_name=project_name,
            chat_level=chat_level, project_context=project_context, card_context=card_context,
            project_id=project_id,
            tool_callback=_on_tool_executed,
            project_names=project_names,
        ):
            fast_full_response += token
            if not first_token_sent:
                first_token_latency = int((time.time() - start) * 1000)
                logger.info(f"[Layer1-Fast] first token in {first_token_latency}ms")
                first_token_sent = True

            await websocket.send_json({
                "type": "chat:response",
                "payload": {
                    "messageId": message_id,
                    "content": token,
                    "model": "fast",
                    "streaming": True,
                    "done": False,
                    "sessionId": session_id,
                },
                "timestamp": int(time.time() * 1000),
            })

        # --- Execute tool calls BEFORE done signal ---
        # Fallback: parse <tool_call> blocks if proxy didn't support native tools
        import re as _re_pre
        _tool_pattern_pre = _re_pre.compile(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', _re_pre.DOTALL)
        _tool_matches_pre = _tool_pattern_pre.findall(fast_full_response)
        if _tool_matches_pre and not _pending_tool_events:
            import json as _json_pre
            for _match_pre in _tool_matches_pre:
                try:
                    _call_pre = _json_pre.loads(_match_pre)
                    _tool_name_pre = _call_pre.get("name", "")
                    _tool_args_pre = _call_pre.get("arguments", _call_pre.get("params", {}))
                    if _tool_name_pre:
                        logger.info(f"[ToolCall-Fallback] Executing: {_tool_name_pre}")
                        _mcp_name_pre = _tool_name_pre.replace("_", ".") if "_" in _tool_name_pre else _tool_name_pre
                        from app.mcp_server import _TOOL_DEFINITIONS as _TD, _call_api as _mcp_exec
                        _tool_def_pre = next((t for t in _TD if t["name"] == _mcp_name_pre), None)
                        if _tool_def_pre:
                            _result_pre = await _mcp_exec(_tool_def_pre, _tool_args_pre)
                        else:
                            _result_pre = {"error": f"Unknown tool: {_mcp_name_pre}"}
                        logger.info(f"[ToolCall-Fallback] Result: {str(_result_pre)[:200]}")
                        await websocket.send_json({
                            "type": "tool:executed",
                            "payload": {"tool": _mcp_name_pre, "arguments": _tool_args_pre, "result": _result_pre, "sessionId": session_id},
                            "timestamp": int(time.time() * 1000),
                        })
                except Exception as _e_pre:
                    logger.warning(f"[ToolCall-Fallback] Failed: {_e_pre}")

        # Flush native tool events from streaming
        for evt in _pending_tool_events:
            await websocket.send_json({
                "type": "tool:executed",
                "payload": {"tool": evt["tool"], "arguments": evt["arguments"], "result": evt["result"], "sessionId": session_id},
                "timestamp": int(time.time() * 1000),
            })

        # Send stream-done signal (AFTER tool events)
        latency = int((time.time() - start) * 1000)
        logger.info(f"[Layer1-Fast] stream complete in {latency}ms")
        await websocket.send_json({
            "type": "chat:response",
            "payload": {
                "messageId": message_id,
                "content": "",
                "model": "fast",
                "streaming": True,
                "done": True,
                "latency_ms": latency,
                "sessionId": session_id,
            },
            "timestamp": int(time.time() * 1000),
        })
        await _send_model_status("fast", "idle")
    except Exception as e:
        logger.error(f"[Layer1-Fast] error: {e}")
        await _send_model_status("fast", "error")
        await websocket.send_json({
            "type": "chat:error",
            "payload": {"messageId": message_id, "error": str(e), "sessionId": session_id},
            "timestamp": int(time.time() * 1000),
        })
        # Cancel background tasks on fast layer failure
        if deep_task:
            deep_task.cancel()
        if analyzer_task:
            analyzer_task.cancel()
        return

    # --- Layer 2: Deep enrichment/correction ---
    if not deep_enabled or deep_task is None:
        logger.debug("[Layer2-Deep] skipped (disabled by user)")
    else:
        try:
            deep_result = await asyncio.wait_for(deep_task, timeout=15.0)
            if deep_result and deep_result.get("action") in ("enrich", "correct"):
                enrichment_id = str(uuid4())
                logger.info(f"[Layer2-Deep] action={deep_result['action']}, sending enrichment")

                # Persist enrichment to disk
                session_store.save_message(chat_id, {
                    "role": "assistant",
                    "content": deep_result["content"],
                    "model": "deep",
                    "type": "enrichment",
                    "session_id": session_id,
                })

                await websocket.send_json({
                    "type": "chat:enrichment",
                    "payload": {
                        "messageId": enrichment_id,
                        "content": deep_result["content"],
                        "model": "deep",
                        "action": deep_result["action"],
                        "done": True,
                        "sessionId": session_id,
                    },
                    "timestamp": int(time.time() * 1000),
                })
            else:
                logger.debug("[Layer2-Deep] no enrichment needed")
            await _send_model_status("deep", "idle")
        except asyncio.TimeoutError:
            logger.warning("[Layer2-Deep] timed out after 15s, skipping")
            await _send_model_status("deep", "idle")
        except asyncio.CancelledError:
            await _send_model_status("deep", "idle")
        except Exception as e:
            logger.error(f"[Layer2-Deep] error: {e}")
            await _send_model_status("deep", "error")

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
                            "sessionId": session_id,
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
                    await _handle_chat_3layer(
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

                    # Clear conversation history (in-memory + disk)
                    if chat_id in _claude_service._histories:
                        _claude_service._histories[chat_id] = []
                    session_store.clear_session(chat_id)
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
