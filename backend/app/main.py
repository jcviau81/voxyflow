"""Voxyflow — Voice-first project management assistant."""

import asyncio
import json
import logging
import os
import time
from uuid import uuid4

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import init_db, SYSTEM_MAIN_PROJECT_ID
from app.routes import projects, cards, techdetect, github, settings, sessions, documents, health, jobs, code, focus_sessions, mcp as mcp_routes, workspace, workers, models, worker_tasks, cli_sessions, backup, auth
from app.routes.health import metrics_router
from app.services.claude_service import ClaudeService
from app.services.chat_orchestration import ChatOrchestrator
from app.services.rag_service import get_rag_service
from app.services.scheduler_service import get_scheduler_service
from app.services.pending_results import pending_store
from app.services.board_executor import execute_board, cancel_execution, build_execution_plan, CardPlan, _build_card_prompt
from app.services.chat_id_utils import resolve_chat_id
from app.routes.settings import get_default_worker_model


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

from app.services.logging_config import bind_contextvars, bound_contextvars, clear_contextvars, configure_logging

_log_level = logging.DEBUG if get_settings().debug else logging.INFO
_log_dir = os.path.expanduser("~/.voxyflow/logs")

# systemd already redirects stderr into the journal / backend.log, so we skip
# the stream handler here and write straight to a rotating file.
configure_logging(level=_log_level, log_dir=_log_dir, stream=False)

logger = logging.getLogger("voxyflow")
logger.info("Structured logging enabled (dir=%s, json=%s)", _log_dir, os.environ.get("VOXYFLOW_LOG_JSON", "0"))


# ---------------------------------------------------------------------------
# Lifespan — full implementation lives in app/startup.py
# ---------------------------------------------------------------------------

from app.startup import build_lifespan


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

_claude_service = ClaudeService()
_orchestrator = ChatOrchestrator(_claude_service)

app = FastAPI(
    title="Voxyflow",
    description="Voice-first project management assistant with multi-model orchestration",
    version="0.1.0",
    lifespan=build_lifespan(_claude_service, _orchestrator),
)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    """Log unhandled exceptions so 500s leave a traceback in backend.log."""
    from fastapi.exceptions import HTTPException as FastAPIHTTPException
    from starlette.exceptions import HTTPException as StarletteHTTPException
    # Let FastAPI handle its own HTTP exceptions (404, 409, etc.) normally
    if isinstance(exc, (FastAPIHTTPException, StarletteHTTPException)):
        raise exc
    logger.error("Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


# CORS — restricted to allowed origins (configure via VOXYFLOW_CORS_ORIGINS env var)
# Default: localhost only. For Tailscale: set VOXYFLOW_CORS_ORIGINS to your Tailscale IP/hostname.
# Example: VOXYFLOW_CORS_ORIGINS="http://100.x.x.x:5173,http://machine.ts.net:5173"
_ALLOWED_ORIGINS = os.environ.get(
    "VOXYFLOW_CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ---------------------------------------------------------------------------
# Request timing middleware
# ---------------------------------------------------------------------------

_SKIP_TIMING_PREFIXES = ("/ws", "/static", "/assets", "/sw.js", "/workbox")
_timing_logger = logging.getLogger("voxyflow.timing")


@app.middleware("http")
async def _timing_middleware(request: Request, call_next):
    # Skip WebSocket upgrades and static assets
    path = request.url.path
    if any(path.startswith(p) for p in _SKIP_TIMING_PREFIXES):
        return await call_next(request)

    request_id = request.headers.get("x-request-id") or uuid4().hex[:12]
    with bound_contextvars(request_id=request_id, http_path=path, http_method=request.method):
        t0 = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - t0) * 1000

        from app.services.metrics_store import get_metrics_store, SLOW_THRESHOLD_MS
        get_metrics_store().record_request(path, request.method, response.status_code, duration_ms)

        response.headers["x-request-id"] = request_id

        if duration_ms >= SLOW_THRESHOLD_MS:
            _timing_logger.warning(
                "[SLOW] %s %s → %d  %.0fms", request.method, path, response.status_code, duration_ms
            )
        else:
            _timing_logger.debug(
                "%s %s → %d  %.0fms", request.method, path, response.status_code, duration_ms
            )

        return response

# Routes — every router declares its own full prefix (/api/... or /mcp).
# Keep this file free of prefix= arguments on include_router to avoid split-prefix drift.
app.include_router(projects.router)
app.include_router(cards.router)
app.include_router(techdetect.router)
app.include_router(github.router)
app.include_router(settings.router)
app.include_router(sessions.router)
app.include_router(documents.router)
app.include_router(health.router)
app.include_router(metrics_router)
app.include_router(jobs.router)
app.include_router(code.router)
app.include_router(focus_sessions.router)
app.include_router(workspace.router)
app.include_router(workers.router)
app.include_router(worker_tasks.router)
app.include_router(models.router)
app.include_router(cli_sessions.router)
app.include_router(backup.router)
app.include_router(auth.router)
app.include_router(mcp_routes.router)  # MCP server (SSE + stdio, no /api prefix)


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

    # Hard cap on inbound WebSocket payload size. The chat path already caps
    # content server-side via Pydantic models; this is the outer envelope.
    # 2 MiB is comfortably above any legitimate frontend message.
    WS_MAX_PAYLOAD_BYTES = 2 * 1024 * 1024

    try:
        ws_id = uuid4().hex[:12]
        while True:
            # Per-message scope — drop any context left over from a prior
            # iteration so stale project_id / session_id don't leak into
            # whatever the next message dispatches.
            clear_contextvars()
            bind_contextvars(ws_id=ws_id)
            raw = await websocket.receive_text()
            if len(raw) > WS_MAX_PAYLOAD_BYTES:
                logger.warning(
                    f"[WS] Rejected oversized payload: {len(raw)} bytes "
                    f"(cap={WS_MAX_PAYLOAD_BYTES})"
                )
                try:
                    await websocket.send_json({
                        "type": "error",
                        "payload": {"error": "payload_too_large", "limit": WS_MAX_PAYLOAD_BYTES},
                        "timestamp": int(time.time() * 1000),
                    })
                except Exception:
                    pass
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                logger.warning(f"[WS] Malformed JSON payload: {e}")
                try:
                    await websocket.send_json({
                        "type": "error",
                        "payload": {"error": "invalid_json", "detail": str(e)[:200]},
                        "timestamp": int(time.time() * 1000),
                    })
                except Exception:
                    pass
                continue

            if not isinstance(data, dict):
                logger.warning(f"[WS] Rejected non-object payload: {type(data).__name__}")
                continue

            try:
                msg_type = data.get("type")
                payload = data.get("payload", {})
                if not isinstance(payload, dict):
                    payload = {}
                msg_id = data.get("id", "")

                # Bind per-message context so every log line emitted during
                # dispatch (orchestrator, workers, MCP handlers) carries the
                # originating session + chat identifiers.
                _ctx: dict[str, str] = {"ws_msg_type": msg_type or "unknown"}
                for _src_key, _ctx_key in (
                    ("sessionId", "session_id"),
                    ("projectId", "project_id"),
                    ("cardId", "card_id"),
                    ("chatId", "chat_id"),
                    ("messageId", "message_id"),
                ):
                    _v = payload.get(_src_key)
                    if _v:
                        _ctx[_ctx_key] = str(_v)
                bind_contextvars(**_ctx)

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

                    # Acknowledge receipt immediately — lets client know message arrived before processing
                    await websocket.send_json({
                        "type": "message:ack",
                        "payload": {"messageId": message_id},
                        "timestamp": int(time.time() * 1000),
                    })
                    project_id = payload.get("projectId")
                    card_id = payload.get("cardId")
                    chat_level = payload.get("chatLevel", "general")
                    msg_layers = payload.get("layers")  # {deep: bool}

                    session_id = payload.get("sessionId") or str(uuid4())

                    # Deliver any pending results from previous connection
                    await _deliver_pending(session_id)

                    # Derive the canonical chat_id from project_id/card_id (server-side authority).
                    # The frontend may pass a stable chatId for sub-sessions, but we validate
                    # it against what the project/card context says — a mismatch would bleed
                    # history and CLI subprocesses across projects.
                    if card_id:
                        chat_level = "card"
                    elif project_id:
                        if chat_level == "general":
                            chat_level = "project" if project_id != SYSTEM_MAIN_PROJECT_ID else "general"
                    else:
                        project_id = SYSTEM_MAIN_PROJECT_ID
                        chat_level = "general"  # Keep "general" for backward compat in prompts

                    chat_id, _, _ = resolve_chat_id(
                        project_id, card_id, payload.get("chatId"), log_context="WS chat:message"
                    )

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

                    # Multi-layer orchestration (Fast XOR Deep + delegates in background)
                    # Fix 3: collect returned background tasks for cleanup on disconnect
                    try:
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
                    except Exception:
                        logger.exception("Orchestration failed for message %s", message_id)
                        try:
                            await websocket.send_json({
                                "type": "error",
                                "message": "Internal error processing your message. Please retry.",
                            })
                        except Exception:
                            pass  # websocket may already be closed

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
                    # Derive canonical chat_id from context (same isolation logic as chat:message)
                    chat_id, _, _ = resolve_chat_id(
                        project_id, card_id, payload.get("chatId"), log_context="WS session:reset"
                    )

                    # Fix 5: full session teardown — stop worker pool, clear event bus,
                    # remove from active_session_ids, then clear chat history.
                    if session_id in active_session_ids:
                        active_session_ids.discard(session_id)
                        try:
                            await _orchestrator.stop_worker_pool(session_id)
                            logger.info(f"[WS] session:reset → stopped worker pool for {session_id}")
                        except Exception as _e:
                            logger.warning(f"[WS] session:reset worker pool stop failed: {_e}")

                    _orchestrator.reset_session(chat_id, session_id=session_id)
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

                elif msg_type == "card:execute":
                    card_id = payload.get("cardId")
                    project_id = payload.get("projectId")
                    session_id = payload.get("sessionId") or str(uuid4())

                    if not card_id:
                        await websocket.send_json({
                            "type": "card:execute:error",
                            "payload": {"error": "cardId is required"},
                            "timestamp": int(time.time() * 1000),
                        })
                    else:
                        try:
                            from app.services.event_bus import ActionIntent, event_bus_registry
                            prompt, project_name = await _build_card_prompt(card_id)
                            pool = _orchestrator.start_worker_pool(session_id, websocket)
                            bus = event_bus_registry.get_or_create(session_id)
                            task_id = f"task-{uuid4().hex[:8]}"
                            worker_model = get_default_worker_model()
                            event = ActionIntent(
                                task_id=task_id,
                                intent_type="complex",
                                intent="execute_card",
                                summary=f"Execute card",
                                data={
                                    "action": "execute_card",
                                    "description": prompt,
                                    "project_id": project_id,
                                    "card_id": card_id,
                                    "model": worker_model,
                                    "complexity": "complex",
                                },
                                session_id=session_id,
                                complexity="complex",
                                model=worker_model,
                                callback_depth=0,
                            )
                            await bus.emit(event)
                            logger.info(f"[WS] card:execute → task {task_id}, card {card_id}")
                        except Exception as e:
                            logger.error(f"[WS] card:execute failed: {e}")
                            await websocket.send_json({
                                "type": "card:execute:error",
                                "payload": {"error": str(e)},
                                "timestamp": int(time.time() * 1000),
                            })

                elif msg_type == "task:cancel":
                    task_id = payload.get("taskId")
                    session_id = payload.get("sessionId")
                    if task_id and session_id:
                        cancelled = await _orchestrator.cancel_worker_task(session_id, task_id)
                        logger.info(f"[WS] task:cancel → task_id={task_id}, session={session_id}, cancelled={cancelled}")
                    else:
                        logger.warning(f"[WS] task:cancel missing taskId or sessionId")

                elif msg_type == "task:steer":
                    task_id = payload.get("taskId")
                    session_id = payload.get("sessionId")
                    steer_message = payload.get("message", "")
                    if task_id and steer_message:
                        steered = await _orchestrator.steer_worker_task(
                            session_id or "", task_id, steer_message
                        )
                        logger.info(
                            f"[WS] task:steer → task_id={task_id}, session={session_id}, "
                            f"queued={steered}, msg={steer_message[:60]!r}"
                        )
                        await websocket.send_json({
                            "type": "task:steer:ack",
                            "payload": {
                                "taskId": task_id,
                                "queued": steered,
                                "message": steer_message,
                            },
                            "timestamp": int(time.time() * 1000),
                        })
                    else:
                        logger.warning("[WS] task:steer missing taskId or message")

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
                        # Update WebSocket reference on any surviving worker pool
                        # FIRST so in-flight workers can stream to the reconnected client.
                        _orchestrator.update_pool_websocket(sync_session_id, websocket)
                        await _deliver_pending(sync_session_id)
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
        # Cancel WS-bound background tasks (kanban exec, delegate streams, …).
        # Delegate emission tasks are shielded internally so in-flight worker
        # spawns complete even if the parent task is cancelled here.
        # Worker pools are INTENTIONALLY left alive: a page refresh or device
        # switch must not kill in-flight workers. The client re-attaches to
        # surviving pools via session:sync → update_pool_websocket().
        # Idle pools (no WS + no active tasks) are collected by
        # _cleanup_idle_sessions after a grace period.
        if bg_tasks:
            running = sum(1 for t in bg_tasks if not t.done())
            for t in bg_tasks:
                if not t.done():
                    t.cancel()
            logger.info(f"[WS] Disconnected — cancelled {running} WS-bound background task(s)")


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
