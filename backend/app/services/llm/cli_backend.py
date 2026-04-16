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
import signal
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import AsyncIterator, Callable, Optional

from app.services.cli_session_registry import (
    CliSession, get_cli_session_registry, new_cli_session_id,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rate gate — prevents hitting Claude Max subscription rate limits (529)
# ---------------------------------------------------------------------------

_CLI_MAX_CONCURRENT = int(os.environ.get("CLI_MAX_CONCURRENT", "2"))
_CLI_MIN_SPACING_MS = int(os.environ.get("CLI_MIN_SPACING_MS", "500"))


class CliRateGate:
    """Global concurrency + spacing limiter for CLI API calls.

    - Semaphore caps concurrent in-flight API calls.
    - Minimum spacing prevents burst-spawning multiple calls at once.
    """

    def __init__(
        self,
        max_concurrent: int = _CLI_MAX_CONCURRENT,
        min_spacing_ms: int = _CLI_MIN_SPACING_MS,
    ):
        self._sem = asyncio.Semaphore(max_concurrent)
        self._min_spacing = min_spacing_ms / 1000.0
        self._last_call: float = 0.0
        self._spacing_lock = asyncio.Lock()
        self._active: int = 0
        self.max_concurrent = max_concurrent
        self.min_spacing_ms = min_spacing_ms
        logger.info(
            f"[RateGate] Initialized: max_concurrent={max_concurrent}, "
            f"min_spacing={min_spacing_ms}ms"
        )

    async def acquire(self) -> None:
        """Acquire a slot — blocks if at capacity or too soon after last call."""
        await self._sem.acquire()
        self._active += 1
        # Enforce minimum spacing
        async with self._spacing_lock:
            now = time.monotonic()
            wait = self._min_spacing - (now - self._last_call)
            if wait > 0:
                logger.debug(f"[RateGate] Spacing wait: {wait:.3f}s")
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    def release(self) -> None:
        """Release a slot after the API call completes."""
        self._active -= 1
        self._sem.release()

    @property
    def active(self) -> int:
        """Number of currently in-flight calls."""
        return self._active


# Module-level singleton — shared across all ClaudeCliBackend instances
_rate_gate: CliRateGate | None = None


def get_rate_gate() -> CliRateGate:
    global _rate_gate
    if _rate_gate is None:
        _rate_gate = CliRateGate()
    return _rate_gate


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


def _flatten_system(system: str | list[dict]) -> str:
    """Convert Anthropic cache-control system blocks to plain string."""
    if isinstance(system, str):
        return system
    return "\n\n".join(block["text"] for block in system if block.get("text"))


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


class ClaudeCliBackend:
    """Manages Claude Code CLI subprocess calls."""

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
        else:
            # Hard-block built-in WebSearch for workers — they must use voxyflow.web.search
            # (SearXNG) instead. This is a CLI-level block, not just a prompt instruction.
            args.extend(["--disallowedTools", "WebSearch"])

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

        Used by chat_fast() and execute_worker_task().

        When *tool_callback* is provided, uses stream-json mode internally
        to capture MCP tool_use events and invoke the callback for each,
        giving the dispatcher visibility into worker progress.

        When *message_queue* is provided, steering messages can be injected
        mid-execution via stdin (--input-format stream-json native continuation).
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

        system_prompt = _flatten_system(system)
        prompt = _format_messages(messages)
        args = self._build_args(
            model, system_prompt,
            streaming=False, use_tools=use_tools, mcp_role=mcp_role,
            native_tools=use_tools,  # Workers get native Claude tools
            voxyflow_dev_task=_is_voxyflow_app_cwd(cwd),  # Auto-allow writes to ~/voxyflow/ for dev tasks
            project_id=project_id, card_id=card_id,
        )

        gate = get_rate_gate()
        logger.info(
            f"[CLI] Spawning: {self.cli_path} -p --model {_model_flag(model)} "
            f"tools={use_tools} prompt_len={len(prompt)} "
            f"(gate: {gate.active}/{gate.max_concurrent} active)"
        )

        await gate.acquire()
        try:
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

            # Monitor cancel_event in parallel
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
            gate.release()

        if cancel_event and cancel_event.is_set():
            return "[Task cancelled by supervisor]", {}

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            logger.error(
                f"[CLI] Process exited with code {proc.returncode}: {stderr_text[:500]}"
            )
            return f"[CLI error: process exited with code {proc.returncode}]", {}

        # Parse JSON result
        try:
            result = json.loads(stdout_text)
        except json.JSONDecodeError:
            # Sometimes the output may have non-JSON preamble; try to find the JSON
            logger.warning(f"[CLI] Failed to parse JSON output, returning raw text")
            self._last_usage = {}
            return stdout_text, {}

        # Extract response text and usage
        response_text = result.get("result", "")
        usage = result.get("usage", {})
        self._last_usage = usage

        if result.get("is_error"):
            logger.error(f"[CLI] Error response: {response_text[:200]}")

        logger.info(
            f"[CLI] Complete: {len(response_text)} chars, "
            f"in={usage.get('input_tokens', 0)} out={usage.get('output_tokens', 0)} "
            f"cache_read={usage.get('cache_read_input_tokens', 0)}"
        )

        return response_text, usage

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
        )

        gate = get_rate_gate()
        logger.info(
            f"[CLI-events] Spawning: {self.cli_path} -p --model {_model_flag(model)} "
            f"tools={use_tools} prompt_len={len(prompt)} "
            f"(gate: {gate.active}/{gate.max_concurrent} active)"
        )

        await gate.acquire()
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
                                    logger.debug(f"[CLI-events] tool_callback error: {e}")

                elif event_type == "result":
                    result_text = event.get("result", "")
                    usage = event.get("usage", {})
                    self._last_usage = usage

        finally:
            gate.release()
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

    # ------------------------------------------------------------------
    # Persistent chat sessions — keep CLI process alive across turns
    # ------------------------------------------------------------------

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

        # Guard-rail: detect project_id drift on reused persistent processes.
        # The MCP subprocess env is fixed at spawn time, so if a chat_id is
        # reused with a different project_id the memory/knowledge handlers
        # will leak across project scopes. Canary for bug #6 (unchecked
        # chat_id on the frontend).
        if pcp and project_id:
            sess = get_cli_session_registry().get_by_chat_id(chat_id)
            if sess and sess.project_id and sess.project_id != project_id:
                logger.error(
                    f"[CLI-persistent] PROJECT_ID DRIFT: chat_id={chat_id} "
                    f"was spawned with project_id={sess.project_id!r} "
                    f"but called with project_id={project_id!r} — context bleed!"
                )

        # Check if process is alive
        if pcp and pcp.proc.returncode is not None:
            logger.info(f"[CLI-persistent] Dead process for {chat_id}, respawning")
            await self.kill_persistent_chat(chat_id)
            pcp = None

        gate = get_rate_gate()
        await gate.acquire()
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
                # Subsequent message — inject only the last user message
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

        except Exception as e:
            logger.warning(f"[CLI-persistent] Error for {chat_id}, falling back to one-shot: {e}")
            await self.kill_persistent_chat(chat_id)
            # Fallback to one-shot stream (stream() has its own gate.acquire)
            gate.release()
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
                gate.release()

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

    # ------------------------------------------------------------------
    # Steerable workers — stream-json input for mid-execution steering
    # ------------------------------------------------------------------

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
        logger.info(
            f"[CLI-steer] Spawning: {self.cli_path} -p --model {_model_flag(model)} "
            f"tools={use_tools} task_id={task_id!r} prompt_len={len(prompt)} "
            f"(gate: {gate.active}/{gate.max_concurrent} active)"
        )

        await gate.acquire()
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
                                    logger.debug(f"[CLI-steer] tool_callback error: {e}")

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
            gate.release()
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
        )

        gate = get_rate_gate()
        logger.info(
            f"[CLI-stream] Spawning: {self.cli_path} -p --model {_model_flag(model)} "
            f"tools={use_tools} prompt_len={len(prompt)} "
            f"(gate: {gate.active}/{gate.max_concurrent} active)"
        )

        await gate.acquire()
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
            gate.release()
            raise

        _reg_id = new_cli_session_id()
        get_cli_session_registry().register(CliSession(
            id=_reg_id, pid=proc.pid, session_id=session_id,
            chat_id=chat_id, project_id=project_id or None,
            model=_model_flag(model), session_type=session_type,
            started_at=time.time(), cancel_event=asyncio.Event(), _process=proc,
        ))

        # Write prompt to stdin and close it
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.stdin.wait_closed()

        # Track what we've already yielded to avoid duplicating from result event
        yielded_length = 0

        # Read stdout line by line — events are newline-delimited JSON
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
        finally:
            gate.release()

        await proc.wait()
        get_cli_session_registry().deregister(_reg_id)

        if proc.returncode != 0:
            stderr_text = (await proc.stderr.read()).decode("utf-8", errors="replace")
            logger.error(
                f"[CLI-stream] Process exited with code {proc.returncode}: "
                f"{stderr_text[:500]}"
            )
