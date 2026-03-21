"""Chat Orchestration Service — Multi-Model Chat Pipeline.

Extracted from main.py to separate WebSocket transport from orchestration logic.

Mode Fast (deep_enabled=False, default):
  Sonnet streams response directly to chat.
  <delegate> blocks → EventBus → DeepWorkerPool (silent execution, task WS events only).

Mode Deep (deep_enabled=True):
  Opus streams response directly to chat (Fast layer skipped).
  <delegate> blocks → EventBus → DeepWorkerPool (same delegate flow).

Key constraint: Fast and Deep are MUTUALLY EXCLUSIVE for chat output.
Only one model streams to chat per message — never two simultaneous responses.

Analyzer (background, both modes): Detects actionable items → card suggestions.

Event Bus Architecture:
  Chat response (Fast or Deep) emits ActionIntent events (parsed from <delegate> blocks).
  Deep workers listen on the per-session bus and execute actions in background.
  Frontend receives task:started → task:progress → task:completed via WebSocket.
"""

import asyncio
import json
import logging
import re
import time
from uuid import uuid4

from fastapi import WebSocket

from app.services.claude_service import ClaudeService
from app.services.analyzer_service import AnalyzerService
from app.services.session_store import session_store
from app.services.event_bus import ActionIntent, SessionEventBus, event_bus_registry
from app.services.pending_results import pending_store
from app.tools.response_parser import ToolResponseParser, TOOL_CALL_PATTERN
from app.tools.executor import get_executor

logger = logging.getLogger("voxyflow.orchestration")


# ---------------------------------------------------------------------------
# Deep Worker Pool — consumes ActionIntent events from the event bus
# ---------------------------------------------------------------------------

class DeepWorkerPool:
    """Pool of async workers that consume events from a SessionEventBus
    and execute them via the Deep layer (Opus) with full tool access.

    Each session gets its own pool. Max workers controls concurrency.
    """

    MAX_WORKERS = 3

    def __init__(
        self,
        claude_service: ClaudeService,
        bus: SessionEventBus,
        websocket: WebSocket,
    ):
        self._claude = claude_service
        self._bus = bus
        self._ws = websocket
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._listener_task: asyncio.Task | None = None
        self._semaphore = asyncio.Semaphore(self.MAX_WORKERS)
        self._stopped = False

    def start(self) -> None:
        """Start listening on the bus for events."""
        self._listener_task = asyncio.create_task(self._listen_loop())
        logger.info(f"[DeepWorkerPool] Started for session {self._bus.session_id}")

    async def stop(self) -> None:
        """Stop the pool and cancel all active tasks."""
        self._stopped = True
        self._bus.close()
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        for task_id, task in list(self._active_tasks.items()):
            task.cancel()
        self._active_tasks.clear()
        logger.info(f"[DeepWorkerPool] Stopped for session {self._bus.session_id}")

    async def _listen_loop(self) -> None:
        """Listen on the bus and spawn workers for each event."""
        try:
            async for event in self._bus.listen():
                # Enforce concurrency limit
                await self._semaphore.acquire()
                task = asyncio.create_task(self._execute_event(event))
                self._active_tasks[event.task_id] = task
                task.add_done_callback(
                    lambda t, tid=event.task_id: self._on_task_done(tid)
                )
        except asyncio.CancelledError:
            pass

    def _on_task_done(self, task_id: str) -> None:
        """Cleanup when a task completes."""
        if self._stopped:
            return
        self._active_tasks.pop(task_id, None)
        self._semaphore.release()

    async def _execute_event(self, event: ActionIntent) -> None:
        """Execute a single ActionIntent via model-routed worker (haiku/sonnet/opus)."""
        try:
            # Notify frontend: task started (include model for badge)
            await self._send_task_event("task:started", event.task_id, {
                "intent": event.intent,
                "summary": event.summary,
                "complexity": event.complexity,
                "model": event.model,
                "sessionId": event.session_id,
            })

            logger.info(f"[DeepWorker] Executing task {event.task_id}: {event.intent} (model={event.model})")

            # Build a focused prompt for the executor
            execution_prompt = (
                f"Execute this action:\n"
                f"Intent: {event.intent}\n"
                f"Summary: {event.summary}\n"
            )
            if event.data:
                # Pass relevant data but exclude internal context objects
                action_data = {k: v for k, v in event.data.items()
                               if k not in ("project_context", "card_context")}
                execution_prompt += f"Data: {json.dumps(action_data)}\n"

            # Use a dedicated chat_id for this task to avoid polluting main history
            task_chat_id = f"task-{event.task_id}"

            # Notify progress
            await self._send_task_event("task:progress", event.task_id, {
                "status": "executing",
                "sessionId": event.session_id,
            })

            # Route to model-specific worker
            result_content = await self._claude.execute_worker_task(
                chat_id=task_chat_id,
                prompt=execution_prompt,
                model=event.model,
                chat_level=event.data.get("chat_level", "general"),
                project_context=event.data.get("project_context"),
                card_context=event.data.get("card_context"),
                project_id=event.data.get("project_id"),
            )

            # Notify frontend: task completed
            await self._send_task_event("task:completed", event.task_id, {
                "intent": event.intent,
                "summary": event.summary,
                "result": result_content,
                "success": True,
                "sessionId": event.session_id,
            })

            logger.info(f"[DeepWorker] Task {event.task_id} completed: {event.intent}")

        except Exception as e:
            logger.error(f"[DeepWorker] Task {event.task_id} failed: {e}")
            try:
                await self._send_task_event("task:completed", event.task_id, {
                    "intent": event.intent,
                    "summary": event.summary,
                    "result": str(e),
                    "success": False,
                    "sessionId": event.session_id,
                })
            except Exception:
                pass

    async def _send_task_event(self, event_type: str, task_id: str, payload: dict) -> None:
        """Send a task event to the frontend via WebSocket.

        If the WebSocket is closed, store the result in pending_results
        for delivery on the next connection.
        """
        message = {
            "type": event_type,
            "payload": {"taskId": task_id, **payload},
            "timestamp": int(time.time() * 1000),
        }
        try:
            await self._ws.send_json(message)
        except Exception as e:
            logger.warning(f"[DeepWorkerPool] Failed to send {event_type} via WS: {e}")
            # Store completed results for later delivery (skip started/progress — only final matters)
            if event_type == "task:completed":
                session_id = payload.get("sessionId", self._bus.session_id)
                if session_id:
                    try:
                        await pending_store.store(session_id, message)
                        logger.info(f"[DeepWorkerPool] Stored pending result for task {task_id}")
                    except Exception as store_err:
                        logger.error(f"[DeepWorkerPool] Failed to store pending result: {store_err}")


class ChatOrchestrator:
    """Orchestrates the 3-layer AI chat pipeline over a WebSocket connection.

    This class owns the *flow* — which layers to call, how to combine results,
    and what WebSocket events to emit.  The actual AI calls are delegated to
    ClaudeService and AnalyzerService.

    Event Bus: After the Fast layer streams, any <delegate> blocks are parsed
    and emitted onto the session's event bus. Deep workers pick them up and
    execute them asynchronously.
    """

    def __init__(
        self,
        claude_service: ClaudeService,
        analyzer_service: AnalyzerService,
    ):
        self._claude = claude_service
        self._analyzer = analyzer_service
        self._worker_pools: dict[str, DeepWorkerPool] = {}

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def handle_message(
        self,
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
        """Full 3-layer orchestration for a single user message."""

        # Resolve project/card context from the database
        project_context, card_context, project_names = await self._resolve_context(
            project_id=project_id,
            card_id=card_id,
            chat_level=chat_level,
        )

        project_name = project_context.get("title") if project_context else None

        # Resolve layer toggles
        # deep_enabled=False (default): Fast streams to chat, Deep only for delegate workers
        # deep_enabled=True: Deep streams to chat directly, Fast is skipped
        if layers is None:
            layers = {}
        deep_enabled = layers.get("deep", layers.get("opus", False))
        analyzer_enabled = layers.get("analyzer", True)

        # Helper to send model status updates
        async def send_model_status(model: str, state: str) -> None:
            await websocket.send_json({
                "type": "model:status",
                "payload": {"model": model, "state": state, "sessionId": session_id},
                "timestamp": int(time.time() * 1000),
            })

        # Launch Analyzer in background (both modes)
        analyzer_task = None
        if analyzer_enabled:
            await send_model_status("analyzer", "thinking")
            analyzer_task = asyncio.create_task(
                self._analyzer.analyze_for_cards(
                    chat_id=chat_id, message=content, project_context=""
                )
            )

        # --- Chat response: Fast XOR Deep (mutually exclusive) ---
        if deep_enabled:
            # Mode Deep: Opus streams directly to chat
            chat_success = await self._run_deep_chat_layer(
                websocket=websocket,
                content=content,
                message_id=message_id,
                chat_id=chat_id,
                project_name=project_name,
                project_id=project_id,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_names=project_names,
                session_id=session_id,
                send_model_status=send_model_status,
            )
        else:
            # Mode Fast (default): Sonnet streams to chat
            chat_success = await self._run_fast_layer(
                websocket=websocket,
                content=content,
                message_id=message_id,
                chat_id=chat_id,
                project_name=project_name,
                project_id=project_id,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_names=project_names,
                session_id=session_id,
                send_model_status=send_model_status,
            )

        if not chat_success:
            if analyzer_task:
                analyzer_task.cancel()
            return

        # --- Parse <delegate> blocks and emit to event bus (BACKGROUND — non-blocking) ---
        if session_id:
            chat_response = ""
            history = self._claude.get_history(chat_id)
            for msg in reversed(history):
                if msg.get("role") == "assistant":
                    chat_response = msg.get("content", "")
                    break

            # Fire and forget — delegates execute in background via DeepWorkerPool
            if chat_response:
                asyncio.create_task(
                    self._parse_and_emit_delegates_safe(
                        fast_response=chat_response,
                        session_id=session_id,
                        websocket=websocket,
                        project_name=project_name,
                        chat_level=chat_level,
                        project_context=project_context,
                        card_context=card_context,
                        project_id=project_id,
                    )
                )

        # --- Layer 3: Analyzer card suggestions (BACKGROUND — non-blocking) ---
        if analyzer_enabled and analyzer_task is not None:
            asyncio.create_task(
                self._run_analyzer_layer_safe(
                    websocket=websocket,
                    analyzer_task=analyzer_task,
                    project_id=project_id,
                    session_id=session_id,
                    send_model_status=send_model_status,
                )
            )

        # --- Memory auto-extraction (BACKGROUND — non-blocking) ---
        asyncio.create_task(
            self._auto_extract_memories_safe(
                chat_id=chat_id,
                user_message=content,
                project_name=project_name,
            )
        )

        # handle_message returns HERE — WS handler is free for next message
        logger.debug("[Orchestrator] handle_message returning (delegates + analyzer in background)")

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def reset_session(self, chat_id: str) -> None:
        """Clear conversation history for a given chat_id."""
        if chat_id in self._claude._histories:
            self._claude._histories[chat_id] = []
        session_store.clear_session(chat_id)

    # ------------------------------------------------------------------
    # Event Bus: Worker pool lifecycle
    # ------------------------------------------------------------------

    def start_worker_pool(self, session_id: str, websocket: WebSocket) -> DeepWorkerPool:
        """Create and start a DeepWorkerPool for a session."""
        bus = event_bus_registry.get_or_create(session_id)
        pool = DeepWorkerPool(self._claude, bus, websocket)
        pool.start()
        self._worker_pools[session_id] = pool
        return pool

    async def stop_worker_pool(self, session_id: str) -> None:
        """Stop and cleanup a session's worker pool."""
        pool = self._worker_pools.pop(session_id, None)
        if pool:
            await pool.stop()
        event_bus_registry.remove(session_id)

    # ------------------------------------------------------------------
    # Background-safe wrappers (fire-and-forget with error handling)
    # ------------------------------------------------------------------

    async def _parse_and_emit_delegates_safe(self, **kwargs) -> None:
        """Wrapper that catches errors so background task doesn't crash silently."""
        try:
            await self._parse_and_emit_delegates(**kwargs)
        except Exception as e:
            logger.error(f"[Orchestrator] Background delegate parsing failed: {e}", exc_info=True)

    async def _auto_extract_memories_safe(
        self,
        chat_id: str,
        user_message: str,
        project_name: str | None = None,
    ) -> None:
        """Background-safe wrapper for memory auto-extraction."""
        try:
            from app.services.memory_service import get_memory_service
            memory = get_memory_service()
            if not memory.chromadb_enabled:
                return

            # Build a minimal messages list with the latest exchange
            history = self._claude.get_history(chat_id)
            # Take last 4 messages (2 user + 2 assistant turns) for extraction
            recent = history[-4:] if len(history) >= 4 else history

            project_slug = None
            if project_name:
                import re
                slug = project_name.lower().strip()
                slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
                project_slug = slug or None

            stored = await memory.auto_extract_memories(
                chat_id=chat_id,
                messages=recent,
                project_slug=project_slug,
            )
            if stored:
                logger.info(f"[Orchestrator] Auto-extracted {len(stored)} memories from chat {chat_id}")
        except Exception as e:
            logger.error(f"[Orchestrator] Memory auto-extraction failed: {e}", exc_info=True)

    async def _run_analyzer_layer_safe(
        self,
        websocket: WebSocket,
        analyzer_task: asyncio.Task,
        project_id: str | None,
        session_id: str | None,
        send_model_status,
    ) -> None:
        """Wrapper for analyzer that catches errors in background."""
        try:
            await self._run_analyzer_layer(
                websocket=websocket,
                analyzer_enabled=True,
                analyzer_task=analyzer_task,
                project_id=project_id,
                session_id=session_id,
                send_model_status=send_model_status,
            )
        except Exception as e:
            logger.error(f"[Orchestrator] Background analyzer failed: {e}", exc_info=True)

    # ------------------------------------------------------------------
    # Event Bus: Delegate parsing
    # ------------------------------------------------------------------

    _DELEGATE_PATTERN = re.compile(
        r'<delegate>\s*(\{.*?\})\s*</delegate>',
        re.DOTALL,
    )

    async def _parse_and_emit_delegates(
        self,
        fast_response: str,
        session_id: str,
        websocket: WebSocket,
        project_name: str | None = None,
        chat_level: str = "general",
        project_context: dict | None = None,
        card_context: dict | None = None,
        project_id: str | None = None,
    ) -> None:
        """Parse <delegate> blocks from the Fast response and emit ActionIntent events."""
        # Debug: log the tail of the response to verify delegate blocks are present
        response_preview = fast_response[-300:] if len(fast_response) > 300 else fast_response
        logger.info(f"[Orchestrator] Parsing delegates from response (len={len(fast_response)}), tail: {response_preview!r}")
        matches = self._DELEGATE_PATTERN.findall(fast_response)
        if not matches:
            return

        # Ensure worker pool is running for this session
        if session_id not in self._worker_pools:
            self.start_worker_pool(session_id, websocket)

        bus = event_bus_registry.get_or_create(session_id)

        for match in matches:
            try:
                data = json.loads(match)
                intent = data.get("intent", data.get("action", "unknown"))
                summary = data.get("summary", data.get("description", ""))
                complexity = data.get("complexity", "simple")

                # Extract model from delegate JSON (haiku/sonnet/opus)
                model = data.get("model", "sonnet")
                if model not in ("haiku", "sonnet", "opus"):
                    model = "sonnet"

                task_id = f"task-{uuid4().hex[:8]}"

                # Classify intent type
                if complexity == "complex" or model == "opus":
                    intent_type = "complex"
                elif intent in ("create_card", "add_note", "move_card", "update_card") or model == "haiku":
                    intent_type = "crud_simple"
                else:
                    intent_type = "complex"

                event = ActionIntent(
                    task_id=task_id,
                    intent_type=intent_type,
                    intent=intent,
                    summary=summary,
                    data={
                        "project_name": project_name,
                        "chat_level": chat_level,
                        "project_context": project_context,
                        "card_context": card_context,
                        "project_id": project_id,
                        **data,  # Include original delegate data
                    },
                    session_id=session_id,
                    complexity=complexity,
                    model=model,
                )

                await bus.emit(event)
                logger.info(f"[Orchestrator] Emitted delegate: {intent} → task {task_id}")

            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"[Orchestrator] Failed to parse delegate block: {e}")

    # ------------------------------------------------------------------
    # Internal: Context resolution
    # ------------------------------------------------------------------

    async def _resolve_context(
        self,
        project_id: str | None,
        card_id: str | None,
        chat_level: str,
    ) -> tuple[dict | None, dict | None, list[str]]:
        """Resolve project context, card context, and project name list from the database.

        Returns (project_context, card_context, project_names).
        """
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

        return project_context, card_context, project_names

    # ------------------------------------------------------------------
    # Internal: <tool_call> text fallback — parse, execute, follow-up
    # ------------------------------------------------------------------

    async def _handle_tool_call_fallback(
        self,
        full_response: str,
        websocket: WebSocket,
        message_id: str,
        chat_id: str,
        model_label: str,
        session_id: str | None,
        project_name: str | None,
        project_id: str | None,
        chat_level: str,
        project_context: dict | None,
        card_context: dict | None,
        project_names: list[str] | None,
    ) -> bool:
        """Check streamed response for <tool_call> blocks. If found:
        1. Strip <tool_call> blocks and update history with clean text
        2. Launch async background task for tool execution + follow-up
        3. Return immediately so the user sees the response right away

        Returns True if tool calls were detected (async task launched), False otherwise.
        """
        parser = ToolResponseParser()
        text_content, tool_calls = parser.parse(full_response)

        if not tool_calls:
            return False

        logger.info(f"[ToolCallFallback] Found {len(tool_calls)} <tool_call> blocks in {model_label} response — launching async execution")

        # Strip <tool_call> blocks from the original response for history
        clean_response = TOOL_CALL_PATTERN.sub("", full_response).strip()

        # Overwrite the last assistant message in history with the clean version
        history = self._claude.get_history(chat_id)
        if history and history[-1].get("role") == "assistant":
            history[-1]["content"] = clean_response

        # Fire-and-forget: launch tool execution + follow-up as background task
        asyncio.create_task(
            self._execute_tools_and_followup_safe(
                tool_calls=tool_calls,
                websocket=websocket,
                message_id=message_id,
                chat_id=chat_id,
                model_label=model_label,
                session_id=session_id,
                project_name=project_name,
                project_id=project_id,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_names=project_names,
            )
        )

        return True

    async def _execute_tools_and_followup_safe(self, **kwargs) -> None:
        """Background-safe wrapper for tool execution + follow-up."""
        try:
            await self._execute_tools_and_followup(**kwargs)
        except Exception as e:
            logger.error(f"[ToolCallFallback] Background tool execution failed: {e}", exc_info=True)
            # Try to notify the user of the failure
            ws = kwargs.get("websocket")
            session_id = kwargs.get("session_id")
            message_id = kwargs.get("message_id")
            if ws:
                try:
                    await ws.send_json({
                        "type": "chat:error",
                        "payload": {
                            "messageId": message_id,
                            "error": f"Tool execution failed: {e}",
                            "sessionId": session_id,
                        },
                        "timestamp": int(time.time() * 1000),
                    })
                except Exception:
                    pass

    async def _execute_tools_and_followup(
        self,
        tool_calls: list,
        websocket: WebSocket,
        message_id: str,
        chat_id: str,
        model_label: str,
        session_id: str | None,
        project_name: str | None,
        project_id: str | None,
        chat_level: str,
        project_context: dict | None,
        card_context: dict | None,
        project_names: list[str] | None,
    ) -> None:
        """Background async task: execute tools, then stream a follow-up LLM response.

        This runs AFTER the initial response has already been sent to the user,
        so the chat is non-blocking. Results arrive as a new streamed message.
        """
        # Send tool:status events for each tool
        for tc in tool_calls:
            try:
                await websocket.send_json({
                    "type": "tool:status",
                    "payload": {
                        "tool": tc.name,
                        "state": "executing",
                        "sessionId": session_id,
                    },
                    "timestamp": int(time.time() * 1000),
                })
            except Exception as e:
                logger.warning(f"[ToolCallFallback] Failed to send tool:status: {e}")

        # Execute tools
        executor = get_executor()
        executed_tools: list[dict] = []

        for tc in tool_calls:
            logger.info(f"[ToolCallFallback] Executing: {tc.name}({tc.arguments})")
            result = await executor.execute(tc, timeout=30)
            executed_tools.append({
                "tool": tc.name,
                "args": tc.arguments,
                "result": result,
            })

            # Send tool:executed event to frontend
            try:
                await websocket.send_json({
                    "type": "tool:executed",
                    "payload": {
                        "messageId": message_id,
                        "tool": tc.name,
                        "args": tc.arguments,
                        "result": result,
                        "sessionId": session_id,
                    },
                    "timestamp": int(time.time() * 1000),
                })
            except Exception as e:
                logger.warning(f"[ToolCallFallback] Failed to send tool:executed event: {e}")

        # Build tool results context for follow-up
        tool_context_parts = []
        for evt in executed_tools:
            tool_context_parts.append(
                f"Tool: {evt['tool']}\n"
                f"Args: {json.dumps(evt['args'], default=str)}\n"
                f"Result: {json.dumps(evt['result'], default=str)}"
            )
        tool_context = "\n\n".join(tool_context_parts)

        # Build follow-up messages: existing history + tool results as user context
        history = self._claude.get_history(chat_id)
        followup_messages = list(history) + [
            {
                "role": "user",
                "content": (
                    f"[SYSTEM: Tool execution results — incorporate these into your response]\n\n"
                    f"{tool_context}\n\n"
                    "Now provide your response to the user incorporating the tool results above. "
                    "Do NOT mention tool calls, <tool_call> blocks, or system internals. "
                    "Just answer naturally with the information."
                ),
            }
        ]

        # Determine which client/model to use
        if model_label == "deep":
            client = self._claude.deep_client
            client_type = self._claude.deep_client_type
            model = self._claude.deep_model
        else:
            client = self._claude.fast_client
            client_type = self._claude.fast_client_type
            model = self._claude.fast_model

        # Build a simple system prompt for the follow-up
        memory_context = self._claude.memory.build_memory_context(
            project_name=project_name,
            include_long_term=False,
            include_daily=True,
        )
        system_prompt = self._claude.personality.build_fast_prompt(
            memory_context=memory_context,
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            project_names=project_names,
        )

        # Generate a new message ID for the follow-up response
        followup_message_id = f"followup-{uuid4().hex[:8]}"

        # Stream follow-up response as a NEW message
        followup_full = ""
        try:
            async for token in self._claude._call_api_stream(
                model=model,
                system=system_prompt,
                messages=followup_messages,
                client=client,
                client_type=client_type,
                use_tools=False,
                chat_level=chat_level,
            ):
                followup_full += token
                await websocket.send_json({
                    "type": "chat:response",
                    "payload": {
                        "messageId": followup_message_id,
                        "content": token,
                        "model": model_label,
                        "streaming": True,
                        "done": False,
                        "sessionId": session_id,
                        "isToolFollowup": True,
                    },
                    "timestamp": int(time.time() * 1000),
                })

            # Send stream-done for the follow-up
            await websocket.send_json({
                "type": "chat:response",
                "payload": {
                    "messageId": followup_message_id,
                    "content": "",
                    "model": model_label,
                    "streaming": True,
                    "done": True,
                    "sessionId": session_id,
                    "isToolFollowup": True,
                },
                "timestamp": int(time.time() * 1000),
            })
        except Exception as e:
            logger.error(f"[ToolCallFallback] Follow-up streaming failed: {e}")

        # Persist the follow-up response in session history
        if followup_full:
            self._claude._append_and_persist(
                chat_id, "assistant", followup_full,
                model=model_label, session_id=session_id,
            )

        # Send final tool:status complete
        try:
            await websocket.send_json({
                "type": "tool:status",
                "payload": {
                    "state": "complete",
                    "sessionId": session_id,
                },
                "timestamp": int(time.time() * 1000),
            })
        except Exception:
            pass

        logger.info(f"[ToolCallFallback] Async follow-up complete ({len(followup_full)} chars)")

    # ------------------------------------------------------------------
    # Internal: Layer 1 — Fast (streaming)
    # ------------------------------------------------------------------

    async def _run_fast_layer(
        self,
        websocket: WebSocket,
        content: str,
        message_id: str,
        chat_id: str,
        project_name: str | None,
        project_id: str | None,
        chat_level: str,
        project_context: dict | None,
        card_context: dict | None,
        project_names: list[str],
        session_id: str | None,
        send_model_status,
    ) -> bool:
        """Run the fast layer, streaming tokens to the WebSocket.

        Returns True on success, False on failure.
        Chat layers have zero tools — clean streaming only.
        """
        await send_model_status("fast", "active")
        start = time.time()
        fast_full_response = ""

        try:
            first_token_sent = False
            async for token in self._claude.chat_fast_stream(
                chat_id=chat_id,
                user_message=content,
                project_name=project_name,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_id=project_id,
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

            # Check for <tool_call> text blocks and handle them
            if TOOL_CALL_PATTERN.search(fast_full_response):
                await self._handle_tool_call_fallback(
                    full_response=fast_full_response,
                    websocket=websocket,
                    message_id=message_id,
                    chat_id=chat_id,
                    model_label="fast",
                    session_id=session_id,
                    project_name=project_name,
                    project_id=project_id,
                    chat_level=chat_level,
                    project_context=project_context,
                    card_context=card_context,
                    project_names=project_names,
                )

            # Send stream-done signal
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
            await send_model_status("fast", "idle")
            return True

        except Exception as e:
            logger.error(f"[Layer1-Fast] error: {e}")
            try:
                await send_model_status("fast", "error")
            except Exception:
                pass
            try:
                await websocket.send_json({
                    "type": "chat:error",
                    "payload": {"messageId": message_id, "error": str(e), "sessionId": session_id},
                    "timestamp": int(time.time() * 1000),
                })
            except Exception:
                pass
            return False
        finally:
            # Safety net: always reset to idle even if WS is closed
            try:
                await send_model_status("fast", "idle")
            except Exception:
                logger.debug("[Layer1-Fast] Could not send final idle status (WS likely closed)")

    # ------------------------------------------------------------------
    # Internal: Layer 2 — Deep Chat (streaming, direct response)
    # ------------------------------------------------------------------

    async def _run_deep_chat_layer(
        self,
        websocket: WebSocket,
        content: str,
        message_id: str,
        chat_id: str,
        project_name: str | None,
        project_id: str | None,
        chat_level: str,
        project_context: dict | None,
        card_context: dict | None,
        project_names: list[str],
        session_id: str | None,
        send_model_status,
    ) -> bool:
        """Run the Deep layer as the primary chat responder (streaming).

        Used when deep_enabled=True. Opus streams directly to chat using the
        same delegate-first pattern as Fast layer: NO direct tool execution.
        The model responds conversationally and emits <delegate> blocks for actions,
        which are parsed by _parse_and_emit_delegates → DeepWorkerPool executes in background.
        Returns True on success, False on failure.
        """
        await send_model_status("deep", "active")
        start = time.time()
        deep_full_response = ""

        try:
            first_token_sent = False
            async for token in self._claude.chat_deep_stream(
                chat_id=chat_id,
                user_message=content,
                project_name=project_name,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_id=project_id,
                project_names=project_names,
            ):
                deep_full_response += token
                if not first_token_sent:
                    first_token_latency = int((time.time() - start) * 1000)
                    logger.info(f"[Layer-Deep-Chat] first token in {first_token_latency}ms")
                    first_token_sent = True

                await websocket.send_json({
                    "type": "chat:response",
                    "payload": {
                        "messageId": message_id,
                        "content": token,
                        "model": "deep",
                        "streaming": True,
                        "done": False,
                        "sessionId": session_id,
                    },
                    "timestamp": int(time.time() * 1000),
                })

            # Check for <tool_call> text blocks and handle them
            if TOOL_CALL_PATTERN.search(deep_full_response):
                await self._handle_tool_call_fallback(
                    full_response=deep_full_response,
                    websocket=websocket,
                    message_id=message_id,
                    chat_id=chat_id,
                    model_label="deep",
                    session_id=session_id,
                    project_name=project_name,
                    project_id=project_id,
                    chat_level=chat_level,
                    project_context=project_context,
                    card_context=card_context,
                    project_names=project_names,
                )

            # Send stream-done signal
            latency = int((time.time() - start) * 1000)
            logger.info(f"[Layer-Deep-Chat] stream complete in {latency}ms")
            await websocket.send_json({
                "type": "chat:response",
                "payload": {
                    "messageId": message_id,
                    "content": "",
                    "model": "deep",
                    "streaming": True,
                    "done": True,
                    "latency_ms": latency,
                    "sessionId": session_id,
                },
                "timestamp": int(time.time() * 1000),
            })
            await send_model_status("deep", "idle")
            return True

        except Exception as e:
            logger.error(f"[Layer-Deep-Chat] error: {e}")
            try:
                await send_model_status("deep", "error")
            except Exception:
                pass
            try:
                await websocket.send_json({
                    "type": "chat:error",
                    "payload": {"messageId": message_id, "error": str(e), "sessionId": session_id},
                    "timestamp": int(time.time() * 1000),
                })
            except Exception:
                pass
            return False
        finally:
            # Safety net: always reset to idle even if WS is closed
            try:
                await send_model_status("deep", "idle")
            except Exception:
                logger.debug("[Layer-Deep-Chat] Could not send final idle status (WS likely closed)")

    # ------------------------------------------------------------------
    # Internal: Layer 3 — Analyzer (card suggestions)
    # ------------------------------------------------------------------

    async def _run_analyzer_layer(
        self,
        websocket: WebSocket,
        analyzer_enabled: bool,
        analyzer_task: asyncio.Task | None,
        project_id: str | None,
        session_id: str | None,
        send_model_status,
    ) -> None:
        """Await the analyzer result and send card suggestions if any."""
        if not analyzer_enabled or analyzer_task is None:
            logger.debug("[Layer3-Analyzer] skipped (disabled by user)")
            return

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
            await send_model_status("analyzer", "idle")
        except asyncio.TimeoutError:
            logger.warning("[Layer3-Analyzer] timed out after 15s, skipping")
            await send_model_status("analyzer", "idle")
        except asyncio.CancelledError:
            await send_model_status("analyzer", "idle")
        except Exception as e:
            logger.error(f"[Layer3-Analyzer] error: {e}")
            await send_model_status("analyzer", "error")
