"""Claude Code CLI backend — spawn `claude -p` subprocesses instead of API calls.

Uses the user's Claude Max subscription via the CLI binary (covered by subscription).
Falls back gracefully: if the CLI is unavailable, ClaudeService should use another backend.

Subprocess communication:
  - Prompt piped via stdin (avoids shell argument length limits)
  - System prompt via --system-prompt flag
  - Output parsed from --output-format json (non-streaming) or stream-json (streaming)
  - MCP tools loaded via --mcp-config for worker tasks
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Optional

from app.services.cli_session_registry import (
    CliSession, get_cli_session_registry, new_cli_session_id,
)
from app.services.logging_config import bind_contextvars
from app.services.llm.cli_persistent_chat import (
    PersistentChatMixin, PersistentChatProcess,
)
from app.services.llm.cli_rate_gate import get_rate_gate
from app.services.llm.cli_retry import (
    MAX_RETRIES, compute_backoff, is_transient_error, parse_rate_limit_event,
)
from app.services.llm.cli_steerable import SteerableMixin
from app.services.llm.model_utils import _flatten_system

logger = logging.getLogger(__name__)

# Voxyflow paths — cli_backend.py lives at backend/app/services/llm/
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent  # backend/
_MCP_STDIO_PATH = _BACKEND_DIR / "mcp_stdio.py"                     # backend/mcp_stdio.py
_VOXYFLOW_ROOT = _BACKEND_DIR.parent                                 # repo root


def _is_voxyflow_app_cwd(cwd: str) -> bool:
    """Return True if cwd is inside ~/voxyflow/ (the Voxyflow app codebase).

    Used to auto-detect Voxyflow dev tasks and grant workers write access to
    the app codebase (VOXYFLOW_DEV_TASK override in MCP server env).
    Note: ~/.voxyflow/ (dot-voxyflow, the workspace) is NOT matched here.
    """
    if not cwd:
        return False
    try:
        resolved_cwd = Path(cwd).expanduser().resolve()
        resolved_cwd.relative_to(_VOXYFLOW_ROOT)
        return True
    except ValueError:
        return False


def _model_flag(model_name: str) -> str:
    """Map full Anthropic model names to CLI --model aliases.

    claude-sonnet-4-6 -> sonnet
    claude-haiku-4-5-20251001 -> haiku
    claude-opus-4-6 -> opus
    Already-short names pass through.
    """
    lower = model_name.lower()
    if "opus" in lower:
        return "opus"
    if "haiku" in lower:
        return "haiku"
    if "sonnet" in lower:
        return "sonnet"
    # Fallback: pass as-is (CLI accepts full names too)
    return model_name


def _format_messages(messages: list[dict]) -> str:
    """Convert a messages array into a single prompt string for `claude -p`.

    Multi-turn history is formatted as labeled turns so Claude understands
    the conversation context.  System messages are skipped (they go via
    --system-prompt).
    """
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        if role == "system":
            continue

        content = msg.get("content", "")
        # Handle Anthropic-style content blocks
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        text_parts.append(block["text"])
                    elif block.get("type") == "tool_result":
                        text_parts.append(f"[Tool result: {block.get('content', '')}]")
                elif isinstance(block, str):
                    text_parts.append(block)
            content = "\n".join(text_parts)

        if not content:
            continue

        label = "Human" if role == "user" else "Assistant"
        parts.append(f"{label}: {content}")

    return "\n\n".join(parts)


def _find_claude_cli(explicit_path: str = "claude") -> str:
    """Resolve the Claude CLI binary path.

    Priority: explicit path > ~/.local/bin/claude > $PATH lookup.
    """
    if explicit_path != "claude" and os.path.isfile(explicit_path):
        return explicit_path
    # Common install location (npm global, pipx, etc.)
    local_bin = os.path.expanduser("~/.local/bin/claude")
    if os.path.isfile(local_bin):
        return local_bin
    return explicit_path  # fallback to bare name (relies on PATH)


@dataclass(frozen=True)
class _CallResult:
    """Outcome of a single ``_call_once`` attempt."""
    ok: bool
    cancelled: bool
    transient: bool
    response: str
    usage: dict = field(default_factory=dict)

    @classmethod
    def success(cls, response: str, usage: dict) -> "_CallResult":
        return cls(ok=True, cancelled=False, transient=False,
                   response=response, usage=usage)

    @classmethod
    def error(cls, response: str, transient: bool) -> "_CallResult":
        return cls(ok=False, cancelled=False, transient=transient,
                   response=response, usage={})

    @classmethod
    def cancel(cls) -> "_CallResult":
        return cls(ok=False, cancelled=True, transient=False,
                   response="[Task cancelled by supervisor]", usage={})


class ClaudeCliBackend(PersistentChatMixin, SteerableMixin):
    """Manages Claude Code CLI subprocess calls.

    Persistent multi-turn chat subprocesses (``stream_persistent``, ...) are
    provided by :class:`PersistentChatMixin`. Steerable worker subprocesses
    (``call_steerable``, ``steer_worker``) come from :class:`SteerableMixin`.
    """

    def __init__(self, cli_path: str = "claude"):
        self.cli_path = _find_claude_cli(cli_path)
        self._last_usage: dict = {}
        self._persistent_chats: dict[str, PersistentChatProcess] = {}

    @property
    def last_usage(self) -> dict:
        """Token usage from the most recent call (for logging)."""
        return self._last_usage

    def _build_mcp_config(
        self,
        role: str = "worker",
        voxyflow_dev_task: bool = False,
        project_id: str = "",
        card_id: str = "",
        chat_id: str = "",
        worker_id: str = "",
    ) -> str:
        """Build MCP config JSON string pointing to Voxyflow's stdio server.

        Args:
            role: "dispatcher" limits tools to lightweight CRUD + knowledge;
                  "worker" (default) exposes all tools including system, file, git, tmux.
            voxyflow_dev_task: When True, sets VOXYFLOW_DEV_TASK=1 in the MCP server env,
                  which allows workers to write to ~/voxyflow/ (the app codebase).
                  Only set this for tasks that explicitly modify the Voxyflow codebase.
            project_id: Project scope for MCP tools. Exposed as VOXYFLOW_PROJECT_ID.
                  Auto-injected into tool path parameters. Defaults to "system-main".
            card_id: Card scope for MCP tools. Exposed as VOXYFLOW_CARD_ID.
                  Auto-injected into tool path parameters when in card chat context.
            chat_id: Canonical chat id (e.g. "project:<uuid>" / "card:<id>").
                  Exposed as VOXYFLOW_CHAT_ID for memory attribution tagging.
            worker_id: Task id when this MCP subprocess is spawned for a worker.
                  Exposed as VOXYFLOW_WORKER_ID — when set, memory_save tags
                  source="worker", speaker="worker".
        """
        # Find the Python interpreter — prefer the backend venv, then current interpreter
        venv_python = str(_BACKEND_DIR / "venv" / "bin" / "python3")
        if os.path.exists(venv_python):
            python_path = venv_python
        else:
            python_path = os.sys.executable

        mcp_env = {
            "VOXYFLOW_API_BASE": os.environ.get(
                "VOXYFLOW_API_BASE", "http://localhost:8000"
            ),
            "VOXYFLOW_MCP_ROLE": role,
            "VOXYFLOW_PROJECT_ID": project_id or "system-main",
        }
        if card_id:
            mcp_env["VOXYFLOW_CARD_ID"] = card_id
        if chat_id:
            mcp_env["VOXYFLOW_CHAT_ID"] = chat_id
        if worker_id:
            mcp_env["VOXYFLOW_WORKER_ID"] = worker_id
        if voxyflow_dev_task:
            mcp_env["VOXYFLOW_DEV_TASK"] = "1"

        config = {
            "mcpServers": {
                "voxyflow": {
                    "command": python_path,
                    "args": [str(_MCP_STDIO_PATH)],
                    "cwd": str(_VOXYFLOW_ROOT),
                    "env": mcp_env,
                }
            }
        }
        return json.dumps(config)

    def _build_args(
        self,
        model: str,
        system_prompt: str,
        *,
        streaming: bool = False,
        use_tools: bool = False,
        mcp_role: str = "worker",
        interactive: bool = False,
        native_tools: bool = False,
        voxyflow_dev_task: bool = False,
        project_id: str = "",
        card_id: str = "",
        chat_id: str = "",
        worker_id: str = "",
    ) -> list[str]:
        """Build the CLI argument list.

        Args:
            mcp_role: "dispatcher" for chat layers (limited tools),
                      "worker" for worker tasks (all tools).
            interactive: When True, uses --input-format stream-json to keep stdin
                         open for mid-execution steering message injection.
            native_tools: When True, keep Claude's built-in tools (Bash, Read, Edit,
                         Grep, Glob, etc.). Workers use these for filesystem/code tasks.
                         Chat layers disable them for clean streaming.
            voxyflow_dev_task: When True, allows writes to ~/voxyflow/ app codebase.
                         Auto-detected from CWD; set when working on Voxyflow itself.
        """
        args = [
            "-p",
            "--model", _model_flag(model),
            "--system-prompt", system_prompt,
            "--no-session-persistence",
            "--permission-mode", "bypassPermissions",
        ]

        if streaming:
            args.extend([
                "--output-format", "stream-json",
                "--verbose",
                "--include-partial-messages",
            ])
            if interactive:
                args.extend(["--input-format", "stream-json"])
        else:
            args.extend(["--output-format", "json"])

        # Chat layers: disable built-in tools for clean streaming
        # Workers: keep native tools (Bash, Read, Edit, etc.) + add MCP for Voxyflow ops
        if not native_tools:
            args.extend(["--tools", ""])

        if use_tools:
            args.extend([
                "--mcp-config",
                self._build_mcp_config(
                    role=mcp_role,
                    voxyflow_dev_task=voxyflow_dev_task,
                    project_id=project_id,
                    card_id=card_id,
                    chat_id=chat_id,
                    worker_id=worker_id,
                ),
            ])

        # Prevent Claude Code from loading its own MCP servers (openfeeder, Gmail, etc.)
        # which add ~1700 tokens of system prompt noise. For workers, --strict-mcp-config
        # ensures only our Voxyflow MCP server is loaded; for chat, no MCP at all.
        args.extend(["--strict-mcp-config"])
        if not use_tools:
            args.extend(["--mcp-config", '{"mcpServers":{}}'])

        return args

    async def call(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        *,
        use_tools: bool = False,
        mcp_role: str = "worker",
        cancel_event: Optional[asyncio.Event] = None,
        tool_callback: Optional[Callable] = None,
        message_queue: Optional[asyncio.Queue] = None,
        session_id: str = "",
        chat_id: str = "",
        project_id: str = "",
        card_id: str = "",
        session_type: str = "worker",
        cwd: str = "",
    ) -> tuple[str, dict]:
        """Non-streaming CLI call. Returns (response_text, usage_dict).

        Used by ``execute_worker_task()`` and other one-shot helpers.

        When *tool_callback* is provided, uses stream-json mode internally
        to capture MCP tool_use events and invoke the callback for each,
        giving the dispatcher visibility into worker progress.

        When *message_queue* is provided, steering messages can be injected
        mid-execution via stdin (--input-format stream-json native continuation).

        Retries up to ``MAX_RETRIES`` times on transient CLI failures
        (ECONNRESET, 529, overloaded, spawn EAGAIN, …). Non-transient errors
        and supervisor cancellation short-circuit the loop.
        """
        # If tool_callback is provided, use stream-json to capture tool events
        if tool_callback and use_tools:
            return await self._call_with_tool_events(
                model=model, system=system, messages=messages,
                use_tools=use_tools, mcp_role=mcp_role,
                cancel_event=cancel_event, tool_callback=tool_callback,
                message_queue=message_queue,
                session_id=session_id, chat_id=chat_id,
                project_id=project_id, card_id=card_id,
                session_type=session_type, cwd=cwd,
            )

        last_error: tuple[str, dict] | None = None
        for attempt in range(MAX_RETRIES + 1):
            if attempt > 0:
                delay = compute_backoff(attempt)
                logger.warning(
                    f"[CLI] transient failure — retry {attempt}/{MAX_RETRIES} "
                    f"after {delay:.1f}s"
                )
                await asyncio.sleep(delay)

            result = await self._call_once(
                model=model, system=system, messages=messages,
                use_tools=use_tools, mcp_role=mcp_role,
                cancel_event=cancel_event,
                session_id=session_id, chat_id=chat_id,
                project_id=project_id, card_id=card_id,
                session_type=session_type, cwd=cwd,
            )

            if result.ok:
                return result.response, result.usage

            last_error = (result.response, result.usage)

            # Cancelled / non-transient: don't retry.
            if result.cancelled or not result.transient:
                return result.response, result.usage
            if attempt >= MAX_RETRIES:
                return result.response, result.usage

        # Unreachable in practice, but mypy-friendly.
        assert last_error is not None
        return last_error

    async def _call_once(
        self,
        *,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        use_tools: bool,
        mcp_role: str,
        cancel_event: Optional[asyncio.Event],
        session_id: str,
        chat_id: str,
        project_id: str,
        card_id: str,
        session_type: str,
        cwd: str,
    ) -> "_CallResult":
        """Single subprocess attempt for ``call()``.

        Returns a ``_CallResult`` that tells the caller whether to retry.
        Rate-limit information discovered in the result payload is pushed
        into the shared ``CliRateGate`` cooldown so subsequent acquires wait.
        """
        system_prompt = _flatten_system(system)
        prompt = _format_messages(messages)
        args = self._build_args(
            model, system_prompt,
            streaming=False, use_tools=use_tools, mcp_role=mcp_role,
            native_tools=use_tools,  # Workers get native Claude tools
            voxyflow_dev_task=_is_voxyflow_app_cwd(cwd),
            project_id=project_id, card_id=card_id,
            chat_id=chat_id,
            worker_id=(session_id if session_type == "worker" else ""),
        )

        gate = get_rate_gate()
        _is_worker = session_type == "worker"
        logger.info(
            f"[CLI] Spawning: {self.cli_path} -p --model {_model_flag(model)} "
            f"tools={use_tools} prompt_len={len(prompt)} "
            f"(gate: {gate.active}/{gate.max_concurrent} active, "
            f"workers: {gate.active_workers}/{gate.worker_concurrent})"
        )

        await gate.acquire(is_worker=_is_worker)
        try:
            proc = await asyncio.create_subprocess_exec(
                self.cli_path, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=16 * 1024 * 1024,
                cwd=cwd or None,
            )

            _cancel = cancel_event or asyncio.Event()
            _reg_id = new_cli_session_id()
            get_cli_session_registry().register(CliSession(
                id=_reg_id, pid=proc.pid, session_id=session_id,
                chat_id=chat_id, project_id=project_id or None,
                model=_model_flag(model), session_type=session_type,
                started_at=time.time(), cancel_event=_cancel, _process=proc,
            ))
            bind_contextvars(cli_session_id=_reg_id, cli_pid=proc.pid)

            cancel_task = None
            if cancel_event:
                async def _watch_cancel():
                    while not cancel_event.is_set():
                        await asyncio.sleep(0.5)
                    logger.info("[CLI] cancel_event set — terminating subprocess")
                    try:
                        proc.terminate()
                        await asyncio.sleep(2)
                        if proc.returncode is None:
                            proc.kill()
                    except ProcessLookupError:
                        pass
                cancel_task = asyncio.create_task(_watch_cancel())

            try:
                stdout, stderr = await proc.communicate(input=prompt.encode("utf-8"))
            finally:
                get_cli_session_registry().deregister(_reg_id)
                if cancel_task:
                    cancel_task.cancel()
                    try:
                        await cancel_task
                    except asyncio.CancelledError:
                        pass
        finally:
            gate.release(is_worker=_is_worker)

        if cancel_event and cancel_event.is_set():
            return _CallResult.cancel()

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        # Non-zero exit: classify as transient or terminal.
        if proc.returncode != 0:
            # Try to parse any rate_limit_event from stdout so the gate can
            # cool down even on non-zero exits.
            self._extract_and_record_rate_limit(stdout_text)
            transient = is_transient_error(stderr_text, proc.returncode)
            logger.error(
                f"[CLI] Process exited with code {proc.returncode} "
                f"(transient={transient}): {stderr_text[:500]}"
            )
            return _CallResult.error(
                response=f"[CLI error: process exited with code {proc.returncode}]",
                transient=transient,
            )

        try:
            result = json.loads(stdout_text)
        except json.JSONDecodeError:
            logger.warning("[CLI] Failed to parse JSON output, returning raw text")
            self._last_usage = {}
            return _CallResult.success(response=stdout_text, usage={})

        response_text = result.get("result", "")
        usage = result.get("usage", {})
        self._last_usage = usage

        # Even on a 0 exit, the CLI sometimes reports a rate-limit rejection
        # inside the result payload. Record it so the next call pauses.
        self._extract_and_record_rate_limit(stdout_text)

        if result.get("is_error"):
            logger.error(f"[CLI] Error response: {response_text[:200]}")

        logger.info(
            f"[CLI] Complete: {len(response_text)} chars, "
            f"in={usage.get('input_tokens', 0)} out={usage.get('output_tokens', 0)} "
            f"cache_read={usage.get('cache_read_input_tokens', 0)}"
        )
        return _CallResult.success(response=response_text, usage=usage)

    def _extract_and_record_rate_limit(self, stdout_text: str) -> None:
        """Scan stdout (JSON or stream-json) for rate_limit_event and push any
        rejection into the shared gate's cooldown window."""
        if not stdout_text:
            return
        # Try whole-document parse first (non-streaming --output-format json).
        try:
            doc = json.loads(stdout_text)
        except json.JSONDecodeError:
            doc = None
        candidates: list[dict] = []
        if isinstance(doc, dict):
            candidates.append(doc)
            rl = doc.get("rate_limit_info")
            if isinstance(rl, dict):
                candidates.append({"type": "rate_limit_event", "rate_limit_info": rl})
        elif isinstance(doc, list):
            candidates.extend(x for x in doc if isinstance(x, dict))
        else:
            # Fall back to line-by-line (stream-json accidentally flushed).
            for line in stdout_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    candidates.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        for msg in candidates:
            info = parse_rate_limit_event(msg)
            if info and info.is_rejected:
                get_rate_gate().note_rate_limit(info.resets_at)
                return

    async def _call_with_tool_events(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        *,
        use_tools: bool = True,
        mcp_role: str = "worker",
        cancel_event: Optional[asyncio.Event] = None,
        tool_callback: Optional[Callable] = None,
        message_queue: Optional[asyncio.Queue] = None,
        session_id: str = "",
        chat_id: str = "",
        project_id: str = "",
        card_id: str = "",
        session_type: str = "worker",
        cwd: str = "",
    ) -> tuple[str, dict]:
        """CLI call using stream-json to capture MCP tool events.

        Internally streams, but accumulates the full response text and
        invokes tool_callback(tool_name, arguments, result) for each
        MCP tool call observed in the stream.

        For steerable workers (with task_id), use call_steerable() instead,
        which keeps stdin open for mid-execution message injection.
        """
        system_prompt = _flatten_system(system)
        prompt = _format_messages(messages)
        args = self._build_args(
            model, system_prompt,
            streaming=True, use_tools=use_tools, mcp_role=mcp_role,
            native_tools=use_tools,  # Workers get native Claude tools (Read, Edit, Bash)
            voxyflow_dev_task=_is_voxyflow_app_cwd(cwd),  # Auto-allow writes to ~/voxyflow/ for dev tasks
            project_id=project_id, card_id=card_id,
            chat_id=chat_id,
            worker_id=(session_id if session_type == "worker" else ""),
        )

        gate = get_rate_gate()
        _is_worker = session_type == "worker"
        logger.info(
            f"[CLI-events] Spawning: {self.cli_path} -p --model {_model_flag(model)} "
            f"tools={use_tools} prompt_len={len(prompt)} "
            f"(gate: {gate.active}/{gate.max_concurrent} active, "
            f"workers: {gate.active_workers}/{gate.worker_concurrent})"
        )

        await gate.acquire(is_worker=_is_worker)
        # NOTE: gate.release() is called in the finally block at the end of
        # _call_with_tool_events — the slot is held for the full API call duration.
        proc = await asyncio.create_subprocess_exec(
            self.cli_path, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=16 * 1024 * 1024,  # 16MB line limit (default 64KB too small for large tool results)
            cwd=cwd or None,
        )

        _cancel = cancel_event or asyncio.Event()
        _reg_id = new_cli_session_id()
        get_cli_session_registry().register(CliSession(
            id=_reg_id, pid=proc.pid, session_id=session_id,
            chat_id=chat_id, project_id=project_id or None,
            model=_model_flag(model), session_type=session_type,
            started_at=time.time(), cancel_event=_cancel, _process=proc,
        ))
        bind_contextvars(cli_session_id=_reg_id, cli_pid=proc.pid)

        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.stdin.wait_closed()

        # Monitor cancel_event
        cancel_task = None
        if cancel_event:
            async def _watch_cancel():
                while not cancel_event.is_set():
                    await asyncio.sleep(0.5)
                logger.info("[CLI-events] cancel_event set — terminating subprocess")
                try:
                    proc.terminate()
                    await asyncio.sleep(2)
                    if proc.returncode is None:
                        proc.kill()
                except ProcessLookupError:
                    pass
            cancel_task = asyncio.create_task(_watch_cancel())

        result_text = ""
        usage = {}
        # Track pending tool_use blocks: id → {name, arguments}
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
                    # Parse content blocks for tool_use entries
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        if block.get("type") == "tool_use":
                            tid = block.get("id", "")
                            pending_tools[tid] = {
                                "name": block.get("name", ""),
                                "arguments": block.get("input", {}),
                            }

                elif event_type == "user":
                    # Tool results come as type="user" with content[].type="tool_result"
                    msg = event.get("message", {})
                    for block in msg.get("content", []):
                        if block.get("type") == "tool_result":
                            tid = block.get("tool_use_id", "")
                            tool_info = pending_tools.pop(tid, None)
                            if tool_info and tool_callback:
                                # Strip MCP prefix (mcp__voxyflow__) for cleaner names
                                raw_name = tool_info["name"]
                                name = raw_name.replace("mcp__voxyflow__", "").replace("_", ".", 1) if raw_name.startswith("mcp__voxyflow__") else raw_name
                                tool_args = tool_info["arguments"]
                                # Extract text from content blocks
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
                                    logger.warning(f"[CLI-events] tool_callback error: {e}")

                elif event_type == "result":
                    result_text = event.get("result", "")
                    usage = event.get("usage", {})
                    self._last_usage = usage

                elif event_type == "rate_limit_event":
                    info = parse_rate_limit_event(event)
                    if info and info.is_rejected:
                        get_rate_gate().note_rate_limit(info.resets_at)

        finally:
            gate.release(is_worker=_is_worker)
            _registry.deregister(_reg_id)
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
            logger.error(f"[CLI-events] Process exited with code {proc.returncode}: {stderr_text[:500]}")
            return f"[CLI error: process exited with code {proc.returncode}]", {}

        logger.info(
            f"[CLI-events] Complete: {len(result_text)} chars, "
            f"in={usage.get('input_tokens', 0)} out={usage.get('output_tokens', 0)} "
            f"cache_read={usage.get('cache_read_input_tokens', 0)}"
        )

        return result_text, usage


    async def stream(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        *,
        use_tools: bool = False,
        mcp_role: str = "worker",
        session_id: str = "",
        chat_id: str = "",
        project_id: str = "",
        card_id: str = "",
        session_type: str = "chat",
        cwd: str = "",
    ) -> AsyncIterator[str]:
        """Streaming CLI call via --output-format stream-json.

        Yields text tokens as they arrive. Usage stats available via
        self.last_usage after iteration completes.
        """
        system_prompt = _flatten_system(system)
        prompt = _format_messages(messages)
        args = self._build_args(
            model, system_prompt,
            streaming=True, use_tools=use_tools, mcp_role=mcp_role,
            project_id=project_id, card_id=card_id,
            chat_id=chat_id,
            worker_id=(session_id if session_type == "worker" else ""),
        )

        gate = get_rate_gate()
        _is_worker = session_type == "worker"
        logger.info(
            f"[CLI-stream] Spawning: {self.cli_path} -p --model {_model_flag(model)} "
            f"tools={use_tools} prompt_len={len(prompt)} "
            f"(gate: {gate.active}/{gate.max_concurrent} active, "
            f"workers: {gate.active_workers}/{gate.worker_concurrent})"
        )

        await gate.acquire(is_worker=_is_worker)
        try:
            proc = await asyncio.create_subprocess_exec(
                self.cli_path, *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=16 * 1024 * 1024,  # 16MB line limit (default 64KB too small for large tool results)
                cwd=cwd or None,
            )
        except Exception:
            gate.release(is_worker=_is_worker)
            raise

        _reg_id = new_cli_session_id()
        get_cli_session_registry().register(CliSession(
            id=_reg_id, pid=proc.pid, session_id=session_id,
            chat_id=chat_id, project_id=project_id or None,
            model=_model_flag(model), session_type=session_type,
            started_at=time.time(), cancel_event=asyncio.Event(), _process=proc,
        ))
        bind_contextvars(cli_session_id=_reg_id, cli_pid=proc.pid)

        # Write prompt to stdin and close it
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.stdin.wait_closed()

        # Track what we've already yielded to avoid duplicating from result event
        yielded_length = 0

        # Decouple subprocess draining from consumer speed: a background task
        # pulls every stdout line into a queue and releases the gate as soon as
        # the subprocess closes stdout (i.e. the subprocess is done emitting).
        # A slow UI consumer no longer holds the worker semaphore for the full
        # generator lifetime — the slot is freed when the subprocess exits.
        line_queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=1000)
        gate_released = False

        def _release_gate_once() -> None:
            nonlocal gate_released
            if not gate_released:
                gate.release(is_worker=_is_worker)
                gate_released = True

        async def _drain_stdout() -> None:
            try:
                async for raw_line in proc.stdout:
                    await line_queue.put(raw_line)
            finally:
                await line_queue.put(None)  # EOF sentinel
                _release_gate_once()

        drain_task = asyncio.create_task(_drain_stdout())

        try:
            while True:
                raw_line = await line_queue.get()
                if raw_line is None:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = event.get("type")

                if event_type == "stream_event":
                    # Real-time streaming deltas from the API
                    inner = event.get("event", {})
                    if inner.get("type") == "content_block_delta":
                        delta = inner.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yielded_length += len(text)
                                yield text

                elif event_type == "assistant":
                    # MCP tool-use path: CLI emits full assistant messages
                    # instead of stream_event deltas. Extract text blocks.
                    # Only forward if we haven't already streamed via deltas.
                    if yielded_length == 0:
                        msg = event.get("message", {})
                        for block in msg.get("content", []):
                            if block.get("type") == "text":
                                text = block.get("text", "")
                                if text:
                                    yielded_length += len(text)
                                    yield text

                elif event_type == "result":
                    # Final result — extract usage for token logging
                    self._last_usage = event.get("usage", {})
                    # Yield any text not yet streamed (safety net)
                    result_text = event.get("result", "")
                    if result_text and len(result_text) > yielded_length:
                        yield result_text[yielded_length:]

                elif event_type == "rate_limit_event":
                    info = parse_rate_limit_event(event)
                    if info and info.is_rejected:
                        get_rate_gate().note_rate_limit(info.resets_at)
        finally:
            # Safety net: if the generator is closed early (consumer abort),
            # cancel the drain task and release the gate if it hasn't already.
            if not drain_task.done():
                drain_task.cancel()
                try:
                    await drain_task
                except (asyncio.CancelledError, Exception):
                    pass
            _release_gate_once()

        await proc.wait()
        get_cli_session_registry().deregister(_reg_id)

        if proc.returncode != 0:
            stderr_text = (await proc.stderr.read()).decode("utf-8", errors="replace")
            logger.error(
                f"[CLI-stream] Process exited with code {proc.returncode}: "
                f"{stderr_text[:500]}"
            )
