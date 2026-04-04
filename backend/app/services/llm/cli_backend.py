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
from pathlib import Path
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)

# Voxyflow paths — cli_backend.py lives at backend/app/services/llm/
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent  # backend/
_MCP_STDIO_PATH = _BACKEND_DIR / "mcp_stdio.py"                     # backend/mcp_stdio.py
_VOXYFLOW_ROOT = _BACKEND_DIR.parent                                 # repo root


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


class ClaudeCliBackend:
    """Manages Claude Code CLI subprocess calls."""

    def __init__(self, cli_path: str = "claude"):
        self.cli_path = _find_claude_cli(cli_path)
        self._last_usage: dict = {}

    @property
    def last_usage(self) -> dict:
        """Token usage from the most recent call (for logging)."""
        return self._last_usage

    def _build_mcp_config(self) -> str:
        """Build MCP config JSON string pointing to Voxyflow's stdio server."""
        # Find the Python interpreter — prefer the backend venv, then current interpreter
        venv_python = str(_BACKEND_DIR / "venv" / "bin" / "python3")
        if os.path.exists(venv_python):
            python_path = venv_python
        else:
            python_path = os.sys.executable

        config = {
            "mcpServers": {
                "voxyflow": {
                    "command": python_path,
                    "args": [str(_MCP_STDIO_PATH)],
                    "cwd": str(_VOXYFLOW_ROOT),
                    "env": {
                        "VOXYFLOW_API_BASE": os.environ.get(
                            "VOXYFLOW_API_BASE", "http://localhost:8000"
                        ),
                    },
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
    ) -> list[str]:
        """Build the CLI argument list."""
        args = [
            "-p",
            "--model", _model_flag(model),
            "--system-prompt", system_prompt,
            "--no-session-persistence",
            # bypassPermissions: Voxyflow MCP tools are our own REST API — safe to auto-approve.
            # "auto" does not cover MCP tool calls, which would stall the subprocess.
            "--permission-mode", "bypassPermissions",
        ]

        if streaming:
            args.extend([
                "--output-format", "stream-json",
                "--verbose",
                "--include-partial-messages",
            ])
        else:
            args.extend(["--output-format", "json"])

        # Always disable built-in CLI tools (Bash, Edit, Read, etc.)
        args.extend(["--tools", ""])

        if use_tools:
            # Worker tasks: load Voxyflow MCP tools only
            args.extend(["--mcp-config", self._build_mcp_config()])

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
        cancel_event: Optional[asyncio.Event] = None,
    ) -> tuple[str, dict]:
        """Non-streaming CLI call. Returns (response_text, usage_dict).

        Used by chat_fast() and execute_worker_task().
        """
        system_prompt = _flatten_system(system)
        prompt = _format_messages(messages)
        args = self._build_args(
            model, system_prompt,
            streaming=False, use_tools=use_tools,
        )

        logger.info(
            f"[CLI] Spawning: {self.cli_path} -p --model {_model_flag(model)} "
            f"tools={use_tools} prompt_len={len(prompt)}"
        )

        proc = await asyncio.create_subprocess_exec(
            self.cli_path, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

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
            if cancel_task:
                cancel_task.cancel()
                try:
                    await cancel_task
                except asyncio.CancelledError:
                    pass

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

    async def stream(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        *,
        use_tools: bool = False,
    ) -> AsyncIterator[str]:
        """Streaming CLI call via --output-format stream-json.

        Yields text tokens as they arrive. Usage stats available via
        self.last_usage after iteration completes.
        """
        system_prompt = _flatten_system(system)
        prompt = _format_messages(messages)
        args = self._build_args(
            model, system_prompt,
            streaming=True, use_tools=use_tools,
        )

        logger.info(
            f"[CLI-stream] Spawning: {self.cli_path} -p --model {_model_flag(model)} "
            f"tools={use_tools} prompt_len={len(prompt)}"
        )

        proc = await asyncio.create_subprocess_exec(
            self.cli_path, *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Write prompt to stdin and close it
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.stdin.wait_closed()

        # Track what we've already yielded to avoid duplicating from result event
        yielded_length = 0

        # Read stdout line by line — events are newline-delimited JSON
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

            elif event_type == "result":
                # Final result — extract usage for token logging
                self._last_usage = event.get("usage", {})
                # Yield any text not yet streamed (safety net)
                result_text = event.get("result", "")
                if result_text and len(result_text) > yielded_length:
                    yield result_text[yielded_length:]

        await proc.wait()

        if proc.returncode != 0:
            stderr_text = (await proc.stderr.read()).decode("utf-8", errors="replace")
            logger.error(
                f"[CLI-stream] Process exited with code {proc.returncode}: "
                f"{stderr_text[:500]}"
            )
