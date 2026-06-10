"""Chat Orchestration Service — Multi-Model Chat Pipeline.

Extracted from main.py to separate WebSocket transport from orchestration logic.

Mode Fast (deep_enabled=False, default):
  The Fast dispatcher layer streams the response directly to chat.
  voxyflow.delegate tool_use → EventBus → DeepWorkerPool (silent execution, task WS events only).

Mode Deep (deep_enabled=True):
  The Deep dispatcher layer streams the response directly to chat (Fast layer skipped).
  voxyflow.delegate tool_use → EventBus → DeepWorkerPool (same delegate flow).

The actual model behind each layer is resolved per-provider via claude_service /
provider_factory (Claude/Codex CLI, Anthropic SDK, or any OpenAI-compatible
backend); orchestration only selects the layer, not a hardcoded model.

Key constraint: Fast and Deep are MUTUALLY EXCLUSIVE for chat output.
Only one layer streams to chat per message — never two simultaneous responses.

Event Bus Architecture:
  Chat response (Fast or Deep) emits ActionIntent events via the voxyflow.delegate MCP tool.
  Deep workers listen on the per-session bus and execute actions in background.
  Frontend receives task:started → task:progress → task:completed via WebSocket.
"""

import asyncio
import json
import logging
import threading
import time
from collections import OrderedDict
from uuid import uuid4

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.services.claude_service import ClaudeService
from app.services.session_store import session_store
from app.services.event_bus import event_bus_registry
from app.services.pending_results import pending_store
from app.services.worker_session_store import get_worker_session_store
from app.services.worker_supervisor import get_worker_supervisor
from app.services.orchestration.worker_pool import DeepWorkerPool
from app.services.orchestration.layer_runners import LayerRunnersMixin
from app.services.orchestration.delegate_dispatch import DelegateDispatchMixin
from app.services.orchestration.tool_call_fallback import ToolCallFallbackMixin
from app.services.orchestration.session_timeline import get_timeline

logger = logging.getLogger("voxyflow.orchestration")

# DeepWorkerPool → app.services.orchestration.worker_pool
# _run_fast_layer, _run_deep_chat_layer → app.services.orchestration.layer_runners


class ChatOrchestrator(LayerRunnersMixin, DelegateDispatchMixin, ToolCallFallbackMixin):
    """Orchestrates the multi-layer AI chat pipeline over a WebSocket connection.

    This class owns the *flow* — which layers to call, how to combine results,
    and what WebSocket events to emit.  The actual AI calls are delegated to
    ClaudeService.

    Event Bus: After the Fast layer streams, native voxyflow.delegate tool_use
    blocks are emitted onto the session's event bus. Deep workers pick them up
    and execute them asynchronously.
    """

    def __init__(
        self,
        claude_service: ClaudeService,
    ):
        self._claude = claude_service
        self._worker_pools: dict[str, DeepWorkerPool] = {}
        # Pending confirmations for destructive direct actions (taskId → delegate data)
        self._pending_confirms: dict[str, dict] = {}
        self._pending_confirms_lock = threading.Lock()
        # Per-chat lock to serialize user messages and worker callbacks.
        # Bounded LRU — oldest idle chats get evicted once we're over the cap so
        # long-lived servers don't grow this dict without bound.
        self._chat_locks: "OrderedDict[str, asyncio.Lock]" = OrderedDict()

    MAX_CALLBACK_DEPTH = 5  # Prevent infinite dispatcher↔worker re-trigger loops
    _CHAT_LOCKS_CAP = 512  # evict oldest unlocked entries past this

    def _get_chat_lock(self, chat_id: str) -> asyncio.Lock:
        """Get or create a per-chat asyncio.Lock to serialize responses."""
        lock = self._chat_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._chat_locks[chat_id] = lock
            # Evict oldest *unlocked* entries if we're over cap. Never evict a
            # locked entry — that would create a second lock for the same chat.
            while len(self._chat_locks) > self._CHAT_LOCKS_CAP:
                oldest_id, oldest_lock = next(iter(self._chat_locks.items()))
                if oldest_lock.locked():
                    break
                self._chat_locks.pop(oldest_id, None)
        else:
            self._chat_locks.move_to_end(chat_id)
        return lock

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def handle_message(
        self,
        websocket: WebSocket | None,
        content: str,
        message_id: str,
        chat_id: str,
        workspace_id: str | None,
        layers: dict[str, bool] | None = None,
        chat_level: str = "general",
        is_callback: bool = False,
        callback_depth: int = 0,
        card_id: str | None = None,
        session_id: str | None = None,
        role: str = "dispatcher",
        autonomy_directive_path: str = "",
    ) -> list[asyncio.Task]:
        """Full 3-layer orchestration for a single user message.

        Returns a list of background asyncio.Task objects created during this
        invocation so the caller can cancel them on disconnect (Fix 3).

        Uses a per-chat lock to prevent race conditions between user messages
        and worker callbacks generating simultaneous responses.
        """
        async with self._get_chat_lock(chat_id):
            return await self._handle_message_inner(
                websocket=websocket, content=content, message_id=message_id,
                chat_id=chat_id, workspace_id=workspace_id, layers=layers,
                chat_level=chat_level, is_callback=is_callback,
                callback_depth=callback_depth, card_id=card_id, session_id=session_id,
                role=role, autonomy_directive_path=autonomy_directive_path,
            )

    async def _handle_message_inner(
        self,
        websocket: WebSocket | None,
        content: str,
        message_id: str,
        chat_id: str,
        workspace_id: str | None,
        layers: dict[str, bool] | None = None,
        chat_level: str = "general",
        is_callback: bool = False,
        callback_depth: int = 0,
        card_id: str | None = None,
        session_id: str | None = None,
        role: str = "dispatcher",
        autonomy_directive_path: str = "",
    ) -> list[asyncio.Task]:
        """Inner implementation of handle_message (called under per-chat lock)."""
        _bg_tasks: list[asyncio.Task] = []

        # Resolve workspace/card context from the database
        project_context, card_context, project_names = await self._resolve_context(
            workspace_id=workspace_id,
            card_id=card_id,
            chat_level=chat_level,
        )

        workspace_name = project_context.get("title") if project_context else None

        # Resolve layer toggles
        # deep_enabled=False (default): Fast streams to chat, Deep only for delegate workers
        # deep_enabled=True: Deep streams to chat directly, Fast is skipped
        if layers is None:
            layers = {}
        deep_enabled = layers.get("deep", layers.get("opus", False))

        # Helper to send model status updates
        async def send_model_status(model: str, state: str) -> None:
            await websocket.send_json({
                "type": "model:status",
                "payload": {"model": model, "state": state, "sessionId": session_id},
                "timestamp": int(time.time() * 1000),
            })

        # Build active workers context for dispatcher awareness
        active_workers_context = self.get_active_workers_context(session_id)

        # --- Chat response: Fast XOR Deep (mutually exclusive) ---
        if deep_enabled:
            # Mode Deep: Opus streams directly to chat
            chat_success = await self._run_deep_chat_layer(
                websocket=websocket,
                content=content,
                message_id=message_id,
                chat_id=chat_id,
                workspace_name=workspace_name,
                workspace_id=workspace_id,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_names=project_names,
                session_id=session_id,
                send_model_status=send_model_status,
                active_workers_context=active_workers_context,
                is_callback=is_callback,
            )
        else:
            # Mode Fast (default): Sonnet streams to chat
            chat_success = await self._run_fast_layer(
                websocket=websocket,
                content=content,
                message_id=message_id,
                chat_id=chat_id,
                workspace_name=workspace_name,
                workspace_id=workspace_id,
                chat_level=chat_level,
                project_context=project_context,
                card_context=card_context,
                project_names=project_names,
                session_id=session_id,
                send_model_status=send_model_status,
                active_workers_context=active_workers_context,
                is_callback=is_callback,
                role=role,
                autonomy_directive_path=autonomy_directive_path,
            )

        if not chat_success:
            return _bg_tasks

        # --- Parse delegates and emit to event bus (BACKGROUND — non-blocking) ---
        if session_id and callback_depth < self.MAX_CALLBACK_DEPTH:
            # Native tool_use delegates (collected by claude_service). Since the
            # HTTP delegate migration, the voxyflow.delegate MCP tool posts back
            # through the REST API into ClaudeService._pending_delegates, so this
            # single source covers both SSE and stdio modes.
            native_delegates = self._claude.pop_pending_delegates(chat_id)

            # Workers spawned from a callback response carry incremented depth
            child_callback_depth = callback_depth + 1 if is_callback else callback_depth

            if native_delegates:
                # Native path: structured voxyflow.delegate tool_use blocks
                logger.info(f"[Orchestrator] Native delegate path: {len(native_delegates)} delegate(s) from tool_use")
                _t = asyncio.create_task(
                    self._emit_native_delegates_safe(
                        delegates=native_delegates,
                        session_id=session_id,
                        websocket=websocket,
                        workspace_name=workspace_name,
                        chat_level=chat_level,
                        project_context=project_context,
                        card_context=card_context,
                        workspace_id=workspace_id,
                        chat_id=chat_id,
                        callback_depth=child_callback_depth,
                    )
                )
                _bg_tasks.append(_t)

        # --- Memory auto-extraction (BACKGROUND — non-blocking) ---
        # Skip for callbacks and autonomy ticks — neither is user conversation.
        if not is_callback and role != "autonomy":
            _t = asyncio.create_task(
                self._auto_extract_memories_safe(
                    chat_id=chat_id,
                    user_message=content,
                    workspace_name=workspace_name,
                    workspace_id=workspace_id,
                )
            )
            _bg_tasks.append(_t)

        # handle_message returns HERE — WS handler is free for next message
        logger.debug("[Orchestrator] handle_message returning (delegates in background)")
        return _bg_tasks

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def reset_session(self, chat_id: str, session_id: str | None = None) -> None:
        """Clear conversation history, kill persistent CLI process, and clean up EventBus."""
        if chat_id in self._claude._histories:
            self._claude._histories[chat_id] = []
        session_store.clear_session(chat_id)
        # Kill persistent chat subprocess if alive
        if self._claude._cli_backend:
            asyncio.create_task(self._claude._cli_backend.kill_persistent_chat(chat_id))
        # Clean up per-session EventBus to prevent accumulation
        cleanup_id = session_id or chat_id
        event_bus_registry.remove(cleanup_id)

    # ------------------------------------------------------------------
    # Active Workers Context (for dispatcher system prompt injection)
    # ------------------------------------------------------------------

    def get_active_workers_context(self, session_id: str | None) -> str:
        """Build a text block describing active/recently-completed workers
        plus the session timeline.

        Injected into the dispatcher's system prompt so it knows what's
        running in the background and what happened so far.
        """
        if not session_id:
            return ""

        parts: list[str] = []

        # Session timeline — chronological ledger of all actions
        timeline_text = get_timeline().format(session_id)
        if timeline_text:
            parts.append("[Session Timeline]\n" + timeline_text)

        # Live worker status
        pool = self._worker_pools.get(session_id)
        if pool:
            info = pool.get_active_tasks()
            active = info["active"]
            completed = info["completed"]

            if active:
                lines = ["[Active Workers]"]
                for t in active:
                    desc = f' — "{t["description"]}"' if t["description"] else ""
                    tool_info = ""
                    if t.get("last_tool"):
                        tool_info = f" — last tool: {t['last_tool']} ({t['tool_count']} calls)"
                    lines.append(
                        f"- {t['task_id']}: {t['action']} ({t['model']}) "
                        f"— running {t['running_seconds']}s{desc}{tool_info}"
                    )
                parts.append("\n".join(lines))

            if completed:
                lines = ["[Recently Completed]"]
                for t in completed:
                    status = "done" if t.get("success", True) else "FAILED"
                    lines.append(
                        f"- {t['task_id']}: {t['action']} ({t['model']}) "
                        f"— {status} {t['seconds_ago']}s ago — {t['result']}"
                    )
                parts.append("\n".join(lines))

        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Event Bus: Worker pool lifecycle
    # ------------------------------------------------------------------

    def start_worker_pool(self, session_id: str, websocket: WebSocket | None) -> DeepWorkerPool:
        """Create and start a DeepWorkerPool for a session.

        If a pool already exists for this session_id (e.g. browser reconnect),
        update its WebSocket reference instead of stopping it — workers must
        survive a page refresh.
        """
        # --- Orphan cleanup: stop pools whose WS is dead and belong to a different session ---
        orphan_ids: list[str] = []
        for sid, pool in self._worker_pools.items():
            if sid == session_id:
                continue  # current session — handled below
            if pool._stopped:
                orphan_ids.append(sid)
                continue
            ws = pool._ws
            # Background pools (ws=None) are not orphans — they're intentionally headless.
            # Only real WebSocket connections that have gone dead are orphans.
            if ws is not None and getattr(ws, "client_state", WebSocketState.CONNECTED) != WebSocketState.CONNECTED:
                orphan_ids.append(sid)

        for orphan_sid in orphan_ids:
            logger.info(f"[ChatOrchestrator] Cleaning up orphan worker pool: {orphan_sid}")
            orphan_pool = self._worker_pools.pop(orphan_sid, None)
            if orphan_pool and not orphan_pool._stopped:
                asyncio.create_task(orphan_pool.stop())
            event_bus_registry.remove(orphan_sid)

        existing = self._worker_pools.get(session_id)
        if existing and not existing._stopped:
            # Pool is alive: update the WebSocket so in-flight workers
            # can deliver results to the new connection.
            existing.update_websocket(websocket)

            # If the event bus was cleaned up (idle timeout), the listener
            # is dead. Reconnect the pool to a fresh bus and restart it.
            bus = event_bus_registry.get_or_create(session_id)
            listener_dead = (
                existing._listener_task is None
                or existing._listener_task.done()
            )
            if listener_dead or existing._bus is not bus:
                existing._bus = bus
                existing._listener_task = asyncio.create_task(existing._listen_loop())
                logger.info(f"[ChatOrchestrator] Revived listener for pool {session_id} (bus was recycled)")
            else:
                logger.info(f"[ChatOrchestrator] Reused existing pool for {session_id}, updated WS")
            return existing

        # No existing pool (or stopped): create a fresh one.
        if existing:
            self._worker_pools.pop(session_id, None)

        bus = event_bus_registry.get_or_create(session_id)
        pool = DeepWorkerPool(self._claude, bus, websocket, orchestrator=self)
        pool.start()
        self._worker_pools[session_id] = pool
        return pool

    async def stop_worker_pool(self, session_id: str) -> None:
        """Stop and cleanup a session's worker pool."""
        pool = self._worker_pools.pop(session_id, None)
        if pool:
            await pool.stop()
        event_bus_registry.remove(session_id)

    def update_pool_websocket(self, session_id: str, websocket: WebSocket) -> None:
        """Update the WebSocket reference on a surviving pool after reconnect.

        Called from session:sync so in-flight workers can deliver results
        to the newly connected client immediately.
        """
        pool = self._worker_pools.get(session_id)
        if pool and not pool._stopped:
            pool.update_websocket(websocket)
            logger.info(f"[ChatOrchestrator] WS updated for surviving pool {session_id}")

    async def cancel_worker_task(self, session_id: str, task_id: str) -> bool:
        """Cancel a specific worker task in a session's pool."""
        pool = self._worker_pools.get(session_id)
        if not pool:
            logger.warning(f"[ChatOrchestrator] cancel_worker_task: no pool for session {session_id}")
            return False
        return await pool.cancel_task(task_id)

    async def cancel_worker_task_global(self, task_id: str) -> bool:
        """Cancel a worker task searching across all active pools.

        Also checks the autonomy tick registry — autonomy heartbeats aren't
        real workers (no pool) but we register them in WorkerSessionStore and
        stream them through the same Worker Panel, so users expect the cancel
        button to stop them too.
        """
        # Autonomy ticks first — they share the cancel button path but live
        # outside worker pools.
        if task_id.startswith("autonomy-"):
            try:
                from app.services.job_runner import cancel_autonomy_task
                if await cancel_autonomy_task(task_id):
                    logger.info(
                        f"[ChatOrchestrator] cancel_worker_task_global: cancelled "
                        f"autonomy tick {task_id}"
                    )
                    return True
            except Exception as e:
                logger.warning(f"[ChatOrchestrator] autonomy cancel failed: {e}")

        for sid, pool in self._worker_pools.items():
            if task_id in pool._active_tasks:
                result = await pool.cancel_task(task_id)
                logger.info(
                    f"[ChatOrchestrator] cancel_worker_task_global: found task {task_id} "
                    f"in pool {sid}, cancelled={result}"
                )
                return result
        logger.warning(f"[ChatOrchestrator] cancel_worker_task_global: task {task_id} not found in any pool")
        return False

    def peek_worker_task(self, task_id: str) -> dict | None:
        """Return peek data for a worker task, searching across all active pools."""
        for pool in self._worker_pools.values():
            result = pool.peek(task_id)
            if result is not None:
                return result
        return None

    async def steer_worker_task(self, session_id: str, task_id: str, message: str) -> bool:
        """Inject a steering message into a running worker task.

        Finds the worker pool for the session and forwards the message to the
        target task's message queue.  If the task is using the steerable CLI
        path, the message is forwarded to the subprocess stdin in real time.

        Returns True if the message was queued, False if the session or task
        was not found.
        """
        pool = self._worker_pools.get(session_id)
        if not pool:
            # Try to find task across all pools (dispatcher may not know exact session)
            for sid, p in self._worker_pools.items():
                if task_id in p._active_tasks:
                    result = await p.steer_task(task_id, message)
                    logger.info(
                        f"[ChatOrchestrator] steer_worker_task: found task {task_id} "
                        f"in pool {sid}, queued={result}"
                    )
                    return result
            logger.warning(f"[ChatOrchestrator] steer_worker_task: no pool for session {session_id}")
            return False
        return await pool.steer_task(task_id, message)

    # ------------------------------------------------------------------
    # Internal: Context resolution
    # ------------------------------------------------------------------

    async def _resolve_context(
        self,
        workspace_id: str | None,
        card_id: str | None,
        chat_level: str,
    ) -> tuple[dict | None, dict | None, list[str]]:
        """Resolve workspace context and card context from the database.

        Returns (project_context, card_context, project_names).
        project_names is always an empty list — the dispatcher calls
        voxyflow.workspace.list on demand instead of receiving the full roll.
        """
        project_context = None
        card_context = None
        project_names: list[str] = []

        # #8 card_id inherit: if we have a card but no workspace_id, look up
        # the parent workspace so the card chat gets workspace-level context too
        # (board state, tech stack, github). Without this, Voxy in card chat
        # sees only the card and hallucinates the surrounding world.
        if card_id and not workspace_id:
            try:
                from app.database import async_session, Card
                from sqlalchemy import select
                async with async_session() as db:
                    r = await db.execute(select(Card.workspace_id).where(Card.id == card_id))
                    parent = r.scalar_one_or_none()
                    if parent:
                        workspace_id = parent
            except Exception as e:
                logger.warning(f"_resolve_context: card->workspace lookup failed: {e}")

        if workspace_id:
            try:
                from app.database import async_session, Workspace, Card
                from sqlalchemy import select
                async with async_session() as db:
                    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
                    proj = result.scalar_one_or_none()
                    if proj:
                        # Fetch non-archived cards for this workspace (for dynamic state counts)
                        cards_result = await db.execute(
                            select(Card).where(
                                Card.workspace_id == workspace_id,
                                Card.archived_at.is_(None),
                            )
                        )
                        proj_cards = cards_result.scalars().all()
                        cards_list = [
                            {
                                "title": c.title,
                                "status": c.status or "backlog",
                                "updated_at": str(c.updated_at) if hasattr(c, "updated_at") and c.updated_at else "",
                            }
                            for c in proj_cards
                        ]

                        project_context = {
                            "id": proj.id,
                            "title": proj.title,
                            "description": proj.description or "",
                            "tech_stack": getattr(proj, "tech_stack", "") or "",
                            "github_url": proj.github_url or "",
                            "cards": cards_list,
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
                                "status": c.status or "backlog",
                                "priority": str(c.priority) if c.priority is not None else "medium",
                                "agent_type": getattr(c, "agent_type", None) or "general",
                                "assignee": getattr(c, "assignee", None),
                                "preferred_model": getattr(c, "preferred_model", None),
                                "checklist_items": [
                                    {"done": getattr(item, "done", False) or getattr(item, "completed", False)}
                                    for item in checklist_items
                                ],
                            }
            except Exception as e:
                logger.warning(f"Failed to resolve workspace/card context: {e}")

        return project_context, card_context, project_names


# --- Regression guard (commit 69e6fe3 follow-up) ---------------------------
# ChatOrchestrator used to redefine 7 DelegateDispatchMixin methods inline,
# shadowing the canonical mixin versions via MRO. Those duplicates carried
# regressions (missing _pending_confirms_lock, raw websocket.send_json instead
# of ws_broadcast fanout, stale model resolution). They are now deleted so the
# mixin versions take effect. This assert fails fast if anyone reintroduces an
# in-body override of the direct-action path.
assert (
    ChatOrchestrator._execute_direct_action
    is DelegateDispatchMixin._execute_direct_action
), (
    "ChatOrchestrator._execute_direct_action must resolve to "
    "DelegateDispatchMixin._execute_direct_action — do not redefine delegate "
    "dispatch methods in ChatOrchestrator (see commit 69e6fe3)."
)

