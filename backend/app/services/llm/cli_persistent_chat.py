"""Persistent chat subprocess management for ClaudeCliBackend.

Keeps a single ``claude -p`` subprocess alive across multiple conversation
turns via ``--input-format stream-json``. The first call spawns with full
history; subsequent calls inject only the new user message via stdin.

Extracted from ``cli_backend.py`` to isolate subprocess lifecycle management
from the one-shot ``call()`` / ``stream()`` code paths.

Requires mixin consumer to provide:
  self.cli_path, self._last_usage, self._persistent_chats (dict)
  self._build_args(...), self.stream(...)  (for fallback)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncIterator

from app.services.cli_session_registry import (
    CliSession, get_cli_session_registry, new_cli_session_id,
)
from app.services.llm.cli_rate_gate import get_rate_gate
from app.services.llm.model_utils import _flatten_system

logger = logging.getLogger(__name__)


def _model_flag(model: str) -> str:
    """Normalize model id for the ``--model`` flag. Local import to avoid cycles."""
    from app.services.llm.cli_backend import _model_flag as _mf
    return _mf(model)


def _format_messages(messages: list[dict]) -> str:
    """Format message list for stdin. Local import to avoid cycles."""
    from app.services.llm.cli_backend import _format_messages as _fm
    return _fm(messages)


@dataclass
class PersistentChatProcess:
    """Wraps a persistent claude -p subprocess for multi-turn chat."""
    proc: asyncio.subprocess.Process
    response_queue: asyncio.Queue  # str tokens or None (turn done sentinel)
    usage_result: dict
    reader_task: asyncio.Task
    turn_lock: asyncio.Lock
    chat_id: str
    registry_id: str


class PersistentChatMixin:
    """Persistent chat subprocess management.

    Mixed into ``ClaudeCliBackend`` to keep multi-turn chat subprocesses alive
    across calls. Uses ``self._persistent_chats: dict[str, PersistentChatProcess]``
    (initialized in the base class __init__).
    """

    async def _persistent_stdout_reader(
        self,
        proc: asyncio.subprocess.Process,
        response_queue: asyncio.Queue,
        usage_holder: dict,
    ) -> None:
        """Background task: reads stdout events and routes tokens to response_queue.

        Runs for the lifetime of the persistent process. Each turn ends
        when a 'result' event is received (sends None sentinel).

        When MCP tools are active, the CLI emits full assistant/user messages
        (not stream_event deltas) for the tool loop. Text content from the
        final assistant message is forwarded to the queue so it reaches the
        WebSocket stream.
        """
        # Track text already queued so we don't duplicate from the result event
        queued_length = 0
        try:
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")

                if event_type == "stream_event":
                    inner = event.get("event", {})
                    if inner.get("type") == "content_block_delta":
                        delta = inner.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                queued_length += len(text)
                                await response_queue.put(text)

                elif event_type == "assistant":
                    # MCP tool-use path: CLI emits full assistant messages
                    # instead of stream_event deltas. Extract text blocks.
                    # Only forward if we haven't already streamed via deltas.
                    if queued_length == 0:
                        msg = event.get("message", {})
                        for block in msg.get("content", []):
                            if block.get("type") == "text":
                                text = block.get("text", "")
                                if text:
                                    queued_length += len(text)
                                    await response_queue.put(text)

                elif event_type == "result":
                    usage = event.get("usage", {})
                    usage_holder.clear()
                    usage_holder.update(usage)
                    self._last_usage = usage
                    # Yield any text not yet streamed (safety net)
                    result_text = event.get("result", "")
                    if result_text and len(result_text) > queued_length:
                        await response_queue.put(result_text[queued_length:])
                    # Reset for next turn
                    queued_length = 0
                    # Signal turn complete
                    await response_queue.put(None)

        except Exception as e:
            logger.warning(f"[CLI-persistent] stdout reader error: {e}")
        finally:
            # Process died — signal any waiting consumer
            await response_queue.put(None)

    async def _spawn_persistent_chat(
        self,
        chat_id: str,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        *,
        use_tools: bool = False,
        mcp_role: str = "dispatcher",
        session_id: str = "",
        project_id: str = "",
        card_id: str = "",
        cwd: str = "",
    ) -> PersistentChatProcess:
        """Spawn a persistent claude -p process for multi-turn chat."""
        system_prompt = _flatten_system(system)
        prompt = _format_messages(messages)
        args = self._build_args(
            model, system_prompt,
            streaming=True, use_tools=use_tools, mcp_role=mcp_role,
            interactive=True,
            project_id=project_id, card_id=card_id,
            chat_id=chat_id,
        )

        logger.info(
            f"[CLI-persistent] Spawning persistent chat: model={_model_flag(model)} "
            f"chat_id={chat_id} prompt_len={len(prompt)} tools={use_tools}"
        )

        proc = await asyncio.create_subprocess_exec(
            self.cli_path, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=16 * 1024 * 1024,
            cwd=cwd or None,
        )

        # Register in session registry
        _reg_id = new_cli_session_id()
        get_cli_session_registry().register(CliSession(
            id=_reg_id, pid=proc.pid, session_id=session_id,
            chat_id=chat_id, project_id=project_id or None,
            model=_model_flag(model), session_type="chat",
            started_at=time.time(), cancel_event=asyncio.Event(),
            _process=proc, last_activity=time.time(),
        ))

        # Send initial prompt via stream-json stdin
        initial_msg = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": prompt},
        }) + "\n"
        proc.stdin.write(initial_msg.encode("utf-8"))
        await proc.stdin.drain()

        # Start background reader
        response_queue: asyncio.Queue[str | None] = asyncio.Queue()
        usage_holder: dict = {}
        reader_task = asyncio.create_task(
            self._persistent_stdout_reader(proc, response_queue, usage_holder)
        )

        pcp = PersistentChatProcess(
            proc=proc,
            response_queue=response_queue,
            usage_result=usage_holder,
            reader_task=reader_task,
            turn_lock=asyncio.Lock(),
            chat_id=chat_id,
            registry_id=_reg_id,
        )
        self._persistent_chats[chat_id] = pcp
        return pcp

    async def stream_persistent(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        *,
        chat_id: str,
        use_tools: bool = False,
        mcp_role: str = "dispatcher",
        session_id: str = "",
        project_id: str = "",
        card_id: str = "",
        session_type: str = "chat",
        cwd: str = "",
    ) -> AsyncIterator[str]:
        """Persistent streaming — reuses subprocess across turns.

        First call spawns the process with full history. Subsequent calls
        inject only the new user message via stdin stream-json.
        """
        pcp = self._persistent_chats.get(chat_id)

        # Guard-rail: enforce project_id consistency on reused persistent
        # processes. The MCP subprocess env is fixed at spawn time, so a
        # chat_id reused with a different project_id would leak across project
        # scopes via memory/knowledge handlers. We kill the stale subprocess
        # and fall through to respawn with the correct env.
        if pcp and project_id:
            sess = get_cli_session_registry().get_by_chat_id(chat_id)
            if sess and sess.project_id and sess.project_id != project_id:
                logger.error(
                    f"[CLI-persistent] PROJECT_ID DRIFT: chat_id={chat_id} "
                    f"was spawned with project_id={sess.project_id!r} "
                    f"but called with project_id={project_id!r} — "
                    f"killing stale subprocess to prevent context bleed"
                )
                await self.kill_persistent_chat(chat_id)
                pcp = None

        # Check if process is alive
        if pcp and pcp.proc.returncode is not None:
            logger.info(f"[CLI-persistent] Dead process for {chat_id}, respawning")
            await self.kill_persistent_chat(chat_id)
            pcp = None

        gate = get_rate_gate()
        _is_worker = session_type == "worker"
        await gate.acquire(is_worker=_is_worker)
        try:
            if not pcp:
                # First message — spawn with full history + system prompt
                pcp = await self._spawn_persistent_chat(
                    chat_id=chat_id, model=model, system=system, messages=messages,
                    use_tools=use_tools, mcp_role=mcp_role,
                    session_id=session_id, project_id=project_id, card_id=card_id,
                    cwd=cwd,
                )
                # Yield tokens from the first turn
                async with pcp.turn_lock:
                    while True:
                        token = await pcp.response_queue.get()
                        if token is None:
                            break
                        yield token
                    self._last_usage = pcp.usage_result.copy()
            else:
                # Subsequent message — inject only the last user message.
                # Defense-in-depth: drain any stale items left in the queue
                # from a prior interrupted turn. If an earlier turn's consumer
                # bailed mid-stream (e.g. WS close) and the GeneratorExit
                # handler below didn't fire for some reason, the reader task
                # may have kept filling this queue with that turn's remaining
                # tokens + its None sentinel. Reading them as the "response"
                # to this turn causes the one-turn-delay bug. Killing the
                # subprocess is the primary defense; this drain catches edge
                # cases where the kill was skipped.
                drained = 0
                while not pcp.response_queue.empty():
                    try:
                        pcp.response_queue.get_nowait()
                        drained += 1
                    except asyncio.QueueEmpty:
                        break
                if drained:
                    logger.warning(
                        f"[CLI-persistent] Drained {drained} stale queue item(s) "
                        f"for {chat_id} before new turn"
                    )

                async with pcp.turn_lock:
                    user_content = messages[-1]["content"] if messages else ""
                    event = json.dumps({
                        "type": "user",
                        "message": {"role": "user", "content": user_content},
                    }) + "\n"
                    pcp.proc.stdin.write(event.encode("utf-8"))
                    await pcp.proc.stdin.drain()

                    while True:
                        token = await pcp.response_queue.get()
                        if token is None:
                            break
                        yield token
                    self._last_usage = pcp.usage_result.copy()

            # Update activity timestamp
            get_cli_session_registry().touch(pcp.registry_id)

        except (GeneratorExit, asyncio.CancelledError):
            # Consumer cancelled mid-stream (most commonly: WebSocket closed
            # before the turn finished streaming). Kill the subprocess —
            # otherwise the background reader task keeps draining this turn's
            # remaining stdout into response_queue, and the NEXT turn would
            # read those leftover tokens as its response, causing every
            # subsequent message to be delayed by one turn. Respawning on the
            # next turn is cheap (~2-3s) and rebuilds full history from the
            # session store.
            logger.warning(
                f"[CLI-persistent] Stream cancelled for {chat_id} "
                f"(consumer gone) — killing subprocess to prevent "
                f"stale queue from polluting next turn"
            )
            try:
                await self.kill_persistent_chat(chat_id)
            except Exception as kill_err:
                logger.warning(
                    f"[CLI-persistent] kill after cancel failed: {kill_err}"
                )
            raise

        except Exception as e:
            logger.warning(f"[CLI-persistent] Error for {chat_id}, falling back to one-shot: {e}")
            await self.kill_persistent_chat(chat_id)
            # Fallback to one-shot stream (stream() has its own gate.acquire)
            gate.release(is_worker=_is_worker)
            gate = None  # prevent double-release in finally
            async for token in self.stream(
                model=model, system=system, messages=messages,
                use_tools=use_tools, mcp_role=mcp_role,
                session_id=session_id, chat_id=chat_id,
                project_id=project_id, session_type=session_type,
            ):
                yield token
        finally:
            if gate is not None:
                gate.release(is_worker=_is_worker)

    async def kill_persistent_chat(self, chat_id: str) -> None:
        """Kill a persistent chat process and clean up."""
        pcp = self._persistent_chats.pop(chat_id, None)
        if not pcp:
            return
        logger.info(f"[CLI-persistent] Killing persistent chat for {chat_id}")
        pcp.reader_task.cancel()
        try:
            pcp.proc.terminate()
            await asyncio.sleep(1)
            if pcp.proc.returncode is None:
                pcp.proc.kill()
        except ProcessLookupError:
            pass
        get_cli_session_registry().deregister(pcp.registry_id)

    def has_persistent_chat(self, chat_id: str) -> bool:
        """Check if a persistent chat process exists and is alive."""
        pcp = self._persistent_chats.get(chat_id)
        return pcp is not None and pcp.proc.returncode is None
