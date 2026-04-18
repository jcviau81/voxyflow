"""Steerable worker subprocess management for ClaudeCliBackend.

Workers spawned with ``--input-format stream-json`` keep stdin open so
steering messages can be injected mid-execution without restarting the task.
A ``CliSession`` is registered keyed by ``task_id`` so ``steer_worker()``
can locate the subprocess.

Extracted from ``cli_backend.py`` to isolate the steerable CLI flow from the
one-shot ``call()`` and persistent-chat code paths.

Requires mixin consumer to provide:
  self.cli_path, self._last_usage, self._build_mcp_config(...)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Optional

from app.services.cli_session_registry import (
    CliSession, get_cli_session_registry, new_cli_session_id,
)
from app.services.llm.cli_rate_gate import get_rate_gate
from app.services.llm.model_utils import _flatten_system

logger = logging.getLogger(__name__)


def _model_flag(model: str) -> str:
    from app.services.llm.cli_backend import _model_flag as _mf
    return _mf(model)


def _format_messages(messages: list[dict]) -> str:
    from app.services.llm.cli_backend import _format_messages as _fm
    return _fm(messages)


def _is_voxyflow_app_cwd(cwd: str) -> bool:
    from app.services.llm.cli_backend import _is_voxyflow_app_cwd as _iv
    return _iv(cwd)


class SteerableMixin:
    """Steerable worker CLI calls (stream-json input + output).

    Mixed into ``ClaudeCliBackend``. Uses ``self._build_mcp_config()`` from
    the base class to construct the MCP config JSON.
    """

    def _build_args_steerable(
        self,
        model: str,
        system_prompt: str,
        *,
        use_tools: bool = True,
        mcp_role: str = "worker",
        voxyflow_dev_task: bool = False,
        project_id: str = "",
        card_id: str = "",
    ) -> list[str]:
        """Build CLI args for a steerable worker using --input-format stream-json.

        Uses stream-json for both input and output so steering messages can be
        injected into stdin while the process runs.  Session persistence is
        enabled (we omit --no-session-persistence) so the process keeps its
        conversation context across multi-turn steering.
        """
        args = [
            "-p",
            "--model", _model_flag(model),
            "--system-prompt", system_prompt,
            "--permission-mode", "bypassPermissions",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        # Always disable built-in CLI tools
        args.extend(["--tools", ""])

        if use_tools:
            args.extend([
                "--mcp-config",
                self._build_mcp_config(
                    role=mcp_role,
                    voxyflow_dev_task=voxyflow_dev_task,
                    project_id=project_id,
                    card_id=card_id,
                ),
            ])

        args.extend(["--strict-mcp-config"])
        if not use_tools:
            args.extend(["--mcp-config", '{"mcpServers":{}}'])

        return args

    async def call_steerable(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        *,
        use_tools: bool = True,
        mcp_role: str = "worker",
        cancel_event: Optional[asyncio.Event] = None,
        tool_callback: Optional[Callable] = None,
        session_id: str = "",
        chat_id: str = "",
        project_id: str = "",
        card_id: str = "",
        session_type: str = "worker",
        task_id: str = "",
        steer_queue: Optional[asyncio.Queue] = None,
        cwd: str = "",
    ) -> tuple[str, dict]:
        """Steerable CLI call — keeps stdin open so steering messages can be injected.

        Uses --input-format stream-json + --output-format stream-json.
        The initial prompt is sent as a JSON user message.  Any messages
        put into *steer_queue* while the subprocess runs are forwarded to
        stdin, allowing mid-execution steering without restarting the task.

        A CliSession with task_id is registered so steer_worker() can locate
        the subprocess by task_id.
        """
        system_prompt = _flatten_system(system)
        prompt = _format_messages(messages)
        args = self._build_args_steerable(
            model, system_prompt, use_tools=use_tools, mcp_role=mcp_role,
            voxyflow_dev_task=_is_voxyflow_app_cwd(cwd),
            project_id=project_id, card_id=card_id,
        )

        gate = get_rate_gate()
        _is_worker = session_type == "worker"
        logger.info(
            f"[CLI-steer] Spawning: {self.cli_path} -p --model {_model_flag(model)} "
            f"tools={use_tools} task_id={task_id!r} prompt_len={len(prompt)} "
            f"(gate: {gate.active}/{gate.max_concurrent} active, "
            f"workers: {gate.active_workers}/{gate.worker_concurrent})"
        )

        await gate.acquire(is_worker=_is_worker)
        # gate.release() in the finally block below
        proc = await asyncio.create_subprocess_exec(
            self.cli_path, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=16 * 1024 * 1024,  # 16MB line limit (default 64KB too small for large tool results)
            cwd=cwd or None,
        )

        _cancel = cancel_event or asyncio.Event()
        _steer_q: asyncio.Queue = steer_queue or asyncio.Queue()
        _reg_id = new_cli_session_id()
        get_cli_session_registry().register(CliSession(
            id=_reg_id, pid=proc.pid, session_id=session_id,
            chat_id=chat_id, project_id=project_id or None,
            model=_model_flag(model), session_type=session_type,
            started_at=time.time(), cancel_event=_cancel, _process=proc,
            task_id=task_id, steer_queue=_steer_q,
        ))

        # Send initial user message in stream-json format
        initial_msg = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": prompt},
        }) + "\n"
        proc.stdin.write(initial_msg.encode("utf-8"))
        await proc.stdin.drain()
        logger.debug(f"[CLI-steer] Sent initial message ({len(prompt)} chars)")

        # --- Concurrent tasks ---
        cancel_task = None
        steer_task = None

        if cancel_event:
            async def _watch_cancel():
                while not cancel_event.is_set():
                    await asyncio.sleep(0.5)
                logger.info("[CLI-steer] cancel_event set — terminating subprocess")
                try:
                    proc.terminate()
                    await asyncio.sleep(2)
                    if proc.returncode is None:
                        proc.kill()
                except ProcessLookupError:
                    pass
            cancel_task = asyncio.create_task(_watch_cancel())

        async def _watch_steer():
            """Forward steering messages from the queue to stdin."""
            try:
                while proc.returncode is None:
                    try:
                        msg = await asyncio.wait_for(_steer_q.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    if proc.returncode is not None or proc.stdin.is_closing():
                        logger.warning(f"[CLI-steer] Steer dropped (stdin closed): {str(msg)[:80]}")
                        break
                    steer_event = json.dumps({
                        "type": "user",
                        "message": {"role": "user", "content": f"[STEERING] {msg}"},
                    }) + "\n"
                    proc.stdin.write(steer_event.encode("utf-8"))
                    await proc.stdin.drain()
                    logger.info(f"[CLI-steer] Injected steering message: {str(msg)[:100]}")
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"[CLI-steer] Steer watcher error: {e}")

        steer_task = asyncio.create_task(_watch_steer())

        result_text = ""
        usage = {}
        pending_tools: dict[str, dict] = {}
        _last_touch = time.monotonic()
        _registry = get_cli_session_registry()

        try:
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                # Throttled liveness signal — prevents stall monitor false positives
                _now = time.monotonic()
                if _now - _last_touch > 10:
                    _registry.touch(_reg_id)
                    _last_touch = _now

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")

                if event_type == "assistant":
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        if block.get("type") == "tool_use":
                            tid = block.get("id", "")
                            pending_tools[tid] = {
                                "name": block.get("name", ""),
                                "arguments": block.get("input", {}),
                            }

                elif event_type == "user":
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        if block.get("type") == "tool_result":
                            tid = block.get("tool_use_id", "")
                            tool_info = pending_tools.pop(tid, None)
                            if tool_info and tool_callback:
                                raw_name = tool_info["name"]
                                name = (
                                    raw_name.replace("mcp__voxyflow__", "").replace("_", ".", 1)
                                    if raw_name.startswith("mcp__voxyflow__")
                                    else raw_name
                                )
                                tool_args = tool_info["arguments"]
                                result_content = block.get("content", "")
                                if isinstance(result_content, list):
                                    result_content = " ".join(
                                        b.get("text", "") for b in result_content
                                        if isinstance(b, dict)
                                    )
                                tool_result = {"content": result_content}
                                try:
                                    ret = tool_callback(name, tool_args, tool_result)
                                    if asyncio.iscoroutine(ret):
                                        await ret
                                except Exception as e:
                                    logger.warning(f"[CLI-steer] tool_callback error: {e}")

                elif event_type == "result":
                    result_text = event.get("result", "")
                    usage = event.get("usage", {})
                    self._last_usage = usage
                    # Natural end of task — close stdin gracefully
                    try:
                        if not proc.stdin.is_closing():
                            proc.stdin.close()
                            await proc.stdin.wait_closed()
                    except Exception:
                        pass

        finally:
            gate.release(is_worker=_is_worker)
            get_cli_session_registry().deregister(_reg_id)
            if steer_task:
                steer_task.cancel()
                try:
                    await steer_task
                except asyncio.CancelledError:
                    pass
            if cancel_task:
                cancel_task.cancel()
                try:
                    await cancel_task
                except asyncio.CancelledError:
                    pass

        await proc.wait()

        if cancel_event and cancel_event.is_set():
            return "[Task cancelled by supervisor]", {}

        if proc.returncode != 0:
            stderr_text = (await proc.stderr.read()).decode("utf-8", errors="replace")
            logger.error(f"[CLI-steer] Process exited with code {proc.returncode}: {stderr_text[:500]}")
            return f"[CLI error: process exited with code {proc.returncode}]", {}

        logger.info(
            f"[CLI-steer] Complete: {len(result_text)} chars, "
            f"in={usage.get('input_tokens', 0)} out={usage.get('output_tokens', 0)} "
            f"cache_read={usage.get('cache_read_input_tokens', 0)}"
        )

        return result_text, usage

    async def steer_worker(self, task_id: str, message: str) -> bool:
        """Inject a steering message into a running worker subprocess.

        Finds the active CliSession by task_id and puts the message into its
        steer_queue.  The _watch_steer coroutine inside call_steerable() will
        forward it to the subprocess stdin.

        Returns True if the session was found, False otherwise.
        """
        registry = get_cli_session_registry()
        session = registry.get_by_task_id(task_id)
        if not session:
            logger.warning(f"[CLI-steer] steer_worker: no active session for task_id={task_id!r}")
            return False
        if session.steer_queue is None:
            logger.warning(f"[CLI-steer] steer_worker: session has no steer_queue (task_id={task_id!r})")
            return False
        await session.steer_queue.put(message)
        logger.info(f"[CLI-steer] Queued steer for task {task_id}: {message[:100]!r}")
        return True
