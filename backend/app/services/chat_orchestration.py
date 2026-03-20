"""Chat Orchestration Service — 3-Layer Multi-Model Chat Pipeline.

Extracted from main.py to separate WebSocket transport from orchestration logic.

Layer 1 — Fast (<1s): Immediate conversational response (streaming).
Layer 2 — Deep (2-5s): Enriches/corrects if needed, runs in parallel.
Layer 3 — Analyzer (background): Detects actionable items -> card suggestions.
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

logger = logging.getLogger("voxyflow.orchestration")


class ChatOrchestrator:
    """Orchestrates the 3-layer AI chat pipeline over a WebSocket connection.

    This class owns the *flow* — which layers to call, how to combine results,
    and what WebSocket events to emit.  The actual AI calls are delegated to
    ClaudeService and AnalyzerService.
    """

    def __init__(
        self,
        claude_service: ClaudeService,
        analyzer_service: AnalyzerService,
    ):
        self._claude = claude_service
        self._analyzer = analyzer_service

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

        # Resolve layer toggles (default: all enabled)
        if layers is None:
            layers = {}
        deep_enabled = layers.get("deep", layers.get("opus", True))
        analyzer_enabled = layers.get("analyzer", True)

        # Helper to send model status updates
        async def send_model_status(model: str, state: str) -> None:
            await websocket.send_json({
                "type": "model:status",
                "payload": {"model": model, "state": state, "sessionId": session_id},
                "timestamp": int(time.time() * 1000),
            })

        # Launch Deep + Analyzer in parallel (only if enabled)
        deep_task = None
        analyzer_task = None

        # Deep task will be launched AFTER Fast completes (needs fast_response)
        # We store the parameters and launch in _run_deep_layer instead

        if analyzer_enabled:
            await send_model_status("analyzer", "thinking")
            analyzer_task = asyncio.create_task(
                self._analyzer.analyze_for_cards(
                    chat_id=chat_id, message=content, project_context=""
                )
            )

        # --- Layer 1: Stream fast response ---
        fast_success = await self._run_fast_layer(
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

        if not fast_success:
            # Cancel background tasks on fast layer failure
            if analyzer_task:
                analyzer_task.cancel()
            return

        # --- Layer 2: Deep enrichment/correction (launched after Fast, receives fast_response) ---
        await self._run_deep_layer(
            websocket=websocket,
            content=content,
            chat_id=chat_id,
            deep_enabled=deep_enabled,
            project_name=project_name,
            chat_level=chat_level,
            project_context=project_context,
            card_context=card_context,
            project_id=project_id,
            session_id=session_id,
            send_model_status=send_model_status,
        )

        # --- Layer 3: Analyzer card suggestions ---
        await self._run_analyzer_layer(
            websocket=websocket,
            analyzer_enabled=analyzer_enabled,
            analyzer_task=analyzer_task,
            project_id=project_id,
            session_id=session_id,
            send_model_status=send_model_status,
        )

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def reset_session(self, chat_id: str) -> None:
        """Clear conversation history for a given chat_id."""
        if chat_id in self._claude._histories:
            self._claude._histories[chat_id] = []
        session_store.clear_session(chat_id)

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
        """
        # Tool callback: collects tool execution events for flushing after stream
        pending_tool_events: list[dict] = []

        def on_tool_executed(tool_name: str, arguments: dict, result: dict) -> None:
            pending_tool_events.append({
                "tool": tool_name,
                "arguments": arguments,
                "result": result,
            })

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
                tool_callback=on_tool_executed,
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

            # Fallback: parse <tool_call> blocks if proxy didn't support native tools
            self._handle_fallback_tool_calls(
                fast_full_response, pending_tool_events
            )

            # Execute fallback tool calls and flush events
            await self._flush_tool_events(
                websocket, pending_tool_events, fast_full_response, session_id
            )

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
            await send_model_status("fast", "idle")
            return True

        except Exception as e:
            logger.error(f"[Layer1-Fast] error: {e}")
            await send_model_status("fast", "error")
            await websocket.send_json({
                "type": "chat:error",
                "payload": {"messageId": message_id, "error": str(e), "sessionId": session_id},
                "timestamp": int(time.time() * 1000),
            })
            return False

    def _handle_fallback_tool_calls(
        self,
        response_text: str,
        pending_events: list[dict],
    ) -> list[dict]:
        """Parse <tool_call> blocks from response text as a fallback
        when the proxy doesn't support native tool_use.

        Returns a list of parsed tool call dicts (name, arguments).
        Only populates if no native tool events were already collected.
        """
        if pending_events:
            return []

        tool_pattern = re.compile(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', re.DOTALL)
        matches = tool_pattern.findall(response_text)
        parsed = []
        for match in matches:
            try:
                call = json.loads(match)
                tool_name = call.get("name", "")
                tool_args = call.get("arguments", call.get("params", {}))
                if tool_name:
                    parsed.append({"name": tool_name, "arguments": tool_args})
            except (json.JSONDecodeError, Exception):
                pass
        return parsed

    async def _flush_tool_events(
        self,
        websocket: WebSocket,
        pending_events: list[dict],
        fast_full_response: str,
        session_id: str | None,
    ) -> None:
        """Execute fallback tool calls and flush all tool events to the WebSocket."""

        # Handle fallback <tool_call> blocks (only if no native events exist)
        if not pending_events:
            tool_pattern = re.compile(r'<tool_call>\s*(\{.*?\})\s*</tool_call>', re.DOTALL)
            matches = tool_pattern.findall(fast_full_response)
            for match in matches:
                try:
                    call = json.loads(match)
                    tool_name = call.get("name", "")
                    tool_args = call.get("arguments", call.get("params", {}))
                    if tool_name:
                        logger.info(f"[ToolCall-Fallback] Executing: {tool_name}")
                        mcp_name = tool_name.replace("_", ".") if "_" in tool_name else tool_name
                        from app.mcp_server import _TOOL_DEFINITIONS, _call_api as _mcp_exec
                        tool_def = next((t for t in _TOOL_DEFINITIONS if t["name"] == mcp_name), None)
                        if tool_def:
                            result = await _mcp_exec(tool_def, tool_args)
                        else:
                            result = {"error": f"Unknown tool: {mcp_name}"}
                        logger.info(f"[ToolCall-Fallback] Result: {str(result)[:200]}")
                        await websocket.send_json({
                            "type": "tool:executed",
                            "payload": {
                                "tool": mcp_name,
                                "arguments": tool_args,
                                "result": result,
                                "sessionId": session_id,
                            },
                            "timestamp": int(time.time() * 1000),
                        })
                except Exception as e:
                    logger.warning(f"[ToolCall-Fallback] Failed: {e}")

        # Flush native tool events from streaming
        for evt in pending_events:
            await websocket.send_json({
                "type": "tool:executed",
                "payload": {
                    "tool": evt["tool"],
                    "arguments": evt["arguments"],
                    "result": evt["result"],
                    "sessionId": session_id,
                },
                "timestamp": int(time.time() * 1000),
            })

    # ------------------------------------------------------------------
    # Internal: Layer 2 — Deep (enrichment/correction)
    # ------------------------------------------------------------------

    async def _run_deep_layer(
        self,
        websocket: WebSocket,
        content: str,
        chat_id: str,
        deep_enabled: bool,
        project_name: str | None,
        chat_level: str,
        project_context: dict | None,
        card_context: dict | None,
        project_id: str | None,
        session_id: str | None,
        send_model_status,
    ) -> None:
        """Launch and await the deep layer, passing the fast_response for supervision."""
        if not deep_enabled:
            logger.debug("[Layer2-Deep] skipped (disabled by user)")
            return

        # Retrieve fast_response from history (last assistant message)
        history = self._claude.get_history(chat_id)
        fast_response = ""
        for msg in reversed(history):
            if msg.get("role") == "assistant":
                fast_response = msg.get("content", "")
                break

        await send_model_status("deep", "thinking")
        deep_task = asyncio.create_task(
            self._claude.chat_deep_supervisor(
                chat_id=chat_id,
                user_message=content,
                fast_response=fast_response,
                project_name=project_name,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_id=project_id,
            )
        )

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
            await send_model_status("deep", "idle")
        except asyncio.TimeoutError:
            logger.warning("[Layer2-Deep] timed out after 15s, skipping")
            await send_model_status("deep", "idle")
        except asyncio.CancelledError:
            await send_model_status("deep", "idle")
        except Exception as e:
            logger.error(f"[Layer2-Deep] error: {e}")
            await send_model_status("deep", "error")

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
