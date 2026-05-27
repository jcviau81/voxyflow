"""Codex CLI backend — spawn `codex exec` subprocesses.

This is intentionally shaped like ``ClaudeCliBackend`` at the public boundary
so Voxyflow can route worker/chat calls to Codex without disturbing the legacy
Claude CLI path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from app.services.cli_session_registry import (
    CliSession, get_cli_session_registry, new_cli_session_id,
)
from app.services.logging_config import bind_contextvars

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent.parent
_MCP_STDIO_PATH = _BACKEND_DIR / "mcp_stdio.py"
_VOXYFLOW_ROOT = _BACKEND_DIR.parent


def _find_codex_cli(explicit_path: str = "codex") -> str:
    """Resolve the Codex CLI binary path."""
    if explicit_path != "codex" and os.path.isfile(explicit_path):
        return explicit_path
    resolved = shutil.which("codex")
    if resolved:
        return resolved
    return explicit_path


def _format_prompt(system: str | list[dict], messages: list[dict]) -> str:
    """Flatten system + messages into one Codex exec prompt.

    Codex CLI does not expose a ``--system-prompt`` flag in the current CLI
    surface, so we preserve role boundaries in the prompt text.
    """
    parts: list[str] = []
    if isinstance(system, list):
        system_text = "\n\n".join(
            str(block.get("text", ""))
            for block in system
            if isinstance(block, dict) and block.get("type") == "text"
        )
    else:
        system_text = system or ""
    if system_text:
        parts.append(f"System instructions:\n{system_text}")

    turn_lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = "\n".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
        if content:
            turn_lines.append(f"{role.upper()}:\n{content}")
    if turn_lines:
        parts.append("Conversation:\n\n" + "\n\n".join(turn_lines))
    return "\n\n---\n\n".join(parts).strip() or "(empty)"


def _extract_codex_error_message(value) -> str:
    """Return the human-readable message from Codex JSON error payloads."""
    if isinstance(value, dict):
        nested = value.get("message") or value.get("error")
        if nested is not None:
            return _extract_codex_error_message(nested)
        return json.dumps(value, default=str)
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(parsed, dict):
        err = parsed.get("error")
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])
        if parsed.get("message"):
            return _extract_codex_error_message(parsed["message"])
    return raw


def _is_capacity_error(text: str) -> bool:
    lower = (text or "").lower()
    return "selected model is at capacity" in lower or "model is at capacity" in lower


def _capacity_fallback_models(model: str) -> list[str]:
    preferred = ["gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.4", "gpt-5.5", "gpt-5.2"]
    return [candidate for candidate in preferred if candidate != model]


def _dedupe_lines(parts: list[str]) -> str:
    seen: set[str] = set()
    deduped: list[str] = []
    for part in parts:
        item = (part or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return "\n".join(deduped)


def _codex_tool_name_to_mcp(raw_tool: str) -> str:
    """Map Codex JSONL MCP tool names back to Voxyflow MCP names.

    Codex can report tool names in several shapes depending on CLI version:
    ``mcp__voxyflow__file_read``, ``file_read``, ``voxyflow_worker_claim``,
    or already dotted names. The old first-underscore replacement converted
    only ``file_read``-style names correctly and produced names such as
    ``voxyflow.workers_list`` for deeper tools, so callbacks missed lifecycle
    and content-tool events.
    """
    candidate = (raw_tool or "").strip()
    if not candidate:
        return "mcp.tool"
    if candidate.startswith("mcp__voxyflow__"):
        candidate = candidate.removeprefix("mcp__voxyflow__")

    try:
        from app.mcp_server import _TOOL_DEFINITIONS

        known = [str(t.get("name", "")) for t in _TOOL_DEFINITIONS]
        known_set = set(known)
        if candidate in known_set:
            return candidate
        dotted_all = candidate.replace("_", ".")
        if dotted_all in known_set:
            return dotted_all
        for name in known:
            if name.replace(".", "_") == candidate:
                return name
    except Exception:
        pass

    # Fallback for non-Voxyflow or local tool names such as file_read/system_exec.
    return candidate.replace("_", ".", 1)


@dataclass(frozen=True)
class CodexCallResult:
    ok: bool
    cancelled: bool
    response: str
    usage: dict = field(default_factory=dict)

    @classmethod
    def success(cls, response: str, usage: dict) -> "CodexCallResult":
        return cls(ok=True, cancelled=False, response=response, usage=usage)

    @classmethod
    def error(cls, response: str) -> "CodexCallResult":
        return cls(ok=False, cancelled=False, response=response, usage={})

    @classmethod
    def cancel(cls) -> "CodexCallResult":
        return cls(ok=False, cancelled=True, response="[Task cancelled by supervisor]", usage={})


class CodexCliBackend:
    """Manages Codex CLI subprocess calls."""

    def __init__(self, cli_path: str = "codex"):
        self._configured_cli_path = cli_path
        self._last_usage: dict = {}
        self._last_thread_id: str = ""
        self._thread_ids_by_chat: dict[str, str] = {}

    @property
    def cli_path(self) -> str:
        return _find_codex_cli(self._configured_cli_path)

    @property
    def last_usage(self) -> dict:
        return self._last_usage

    @property
    def last_thread_id(self) -> str:
        return self._last_thread_id

    def get_thread_id(self, chat_id: str) -> str:
        return self._thread_ids_by_chat.get(chat_id, "")

    def _build_args(
        self,
        model: str,
        *,
        cwd: str = "",
        sandbox: str = "workspace-write",
        approval_policy: str = "never",
        json_output: bool = True,
        resume_thread_id: str = "",
        use_tools: bool = False,
        mcp_role: str = "worker",
        workspace_id: str = "",
        card_id: str = "",
        chat_id: str = "",
        worker_id: str = "",
    ) -> list[str]:
        """Build Codex CLI args.

        The prompt is read from stdin via ``-`` so large worker prompts do not
        hit shell/argv length limits.
        """
        args: list[str] = []
        if approval_policy:
            args.extend(["-a", approval_policy])
        if use_tools:
            args.extend(self._build_mcp_config_args(
                role=mcp_role,
                workspace_id=workspace_id,
                card_id=card_id,
                chat_id=chat_id,
                worker_id=worker_id,
            ))

        if resume_thread_id:
            args.extend(["exec", "resume", resume_thread_id])
        else:
            args.extend(["exec"])

        if json_output:
            args.append("--json")
        args.append("--skip-git-repo-check")
        if cwd:
            args.extend(["-C", cwd])
        if model:
            args.extend(["-m", model])
        if sandbox:
            args.extend(["-s", sandbox])
        args.append("-")
        return args


    def _toml_string(self, value: str) -> str:
        return json.dumps(value or "")

    def _toml_array(self, values: list[str]) -> str:
        return "[" + ",".join(self._toml_string(str(v)) for v in values) + "]"

    def _toml_inline_table(self, values: dict[str, str]) -> str:
        parts = [f"{key}={self._toml_string(str(val))}" for key, val in values.items()]
        return "{" + ",".join(parts) + "}"

    def _build_mcp_config_args(
        self,
        *,
        role: str = "worker",
        workspace_id: str = "",
        card_id: str = "",
        chat_id: str = "",
        worker_id: str = "",
    ) -> list[str]:
        """Build Codex ``-c mcp_servers.*`` overrides.

        Codex reads MCP servers from config.toml. For Voxyflow tasks the MCP
        scope is per invocation, so we inject a temporary server with CLI
        config overrides instead of mutating ~/.codex/config.toml.
        """
        venv_python = _BACKEND_DIR / "venv" / "bin" / "python3"
        python_path = str(venv_python if venv_python.exists() else Path(os.sys.executable))
        env = {
            "VOXYFLOW_API_BASE": os.environ.get("VOXYFLOW_API_BASE", "http://localhost:8000"),
            "VOXYFLOW_MCP_ROLE": role,
            "VOXYFLOW_WORKSPACE_ID": workspace_id or "system-main",
        }
        for var in ("VOXYFLOW_DIR", "VOXYFLOW_DATA_DIR", "VOXYFLOW_SANDBOX_DIR", "VOXYFLOW_MCP_LOG_LEVEL"):
            val = os.environ.get(var)
            if val:
                env[var] = val
        if card_id:
            env["VOXYFLOW_CARD_ID"] = card_id
        if chat_id:
            env["VOXYFLOW_CHAT_ID"] = chat_id
        if worker_id:
            env["VOXYFLOW_WORKER_ID"] = worker_id

        overrides = [
            ("mcp_servers.voxyflow.command", self._toml_string(python_path)),
            ("mcp_servers.voxyflow.args", self._toml_array([str(_MCP_STDIO_PATH)])),
            ("mcp_servers.voxyflow.cwd", self._toml_string(str(_VOXYFLOW_ROOT))),
            ("mcp_servers.voxyflow.env", self._toml_inline_table(env)),
            ("mcp_servers.voxyflow.startup_timeout_sec", "20"),
            ("mcp_servers.voxyflow.tool_timeout_sec", "120"),
            ("mcp_servers.voxyflow.required", "true"),
            ("mcp_servers.voxyflow.default_tools_approval_mode", self._toml_string("approve")),
        ]

        try:
            from app.services.settings_loader import load_mcp_servers_sync
            for srv in load_mcp_servers_sync():
                if not srv.get("enabled", True):
                    continue
                if role not in (srv.get("scopes") or []):
                    continue
                key = (srv.get("key") or "").strip()
                if not key or key == "voxyflow":
                    continue
                prefix = f"mcp_servers.{key}"
                transport = (srv.get("transport") or "http").strip().lower()
                if transport == "http":
                    url = (srv.get("url") or "").strip()
                    if not url:
                        continue
                    overrides.append((f"{prefix}.url", self._toml_string(url)))
                    api_key = (srv.get("api_key") or "").strip()
                    if api_key and api_key != "***":
                        overrides.append((f"{prefix}.http_headers", self._toml_inline_table({"Authorization": f"Bearer {api_key}"})))
                elif transport == "stdio":
                    cmd = (srv.get("command") or "").strip()
                    if not cmd:
                        continue
                    overrides.append((f"{prefix}.command", self._toml_string(cmd)))
                    if srv.get("args"):
                        overrides.append((f"{prefix}.args", self._toml_array([str(x) for x in srv["args"]])))
                    if srv.get("cwd"):
                        overrides.append((f"{prefix}.cwd", self._toml_string(str(srv["cwd"]))))
                    if srv.get("env"):
                        overrides.append((f"{prefix}.env", self._toml_inline_table({str(k): str(v) for k, v in srv["env"].items()})))
        except Exception as exc:
            logger.warning("[CodexCLI] Failed to load user MCP servers: %s", exc)

        args: list[str] = []
        for key, value in overrides:
            args.extend(["-c", f"{key}={value}"])
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
        workspace_id: str = "",
        card_id: str = "",
        session_type: str = "worker",
        task_id: str = "",
        cwd: str = "",
        sandbox: str = "workspace-write",
    ) -> tuple[str, dict]:
        """Run one Codex exec turn and return ``(response_text, usage)``."""
        prompt = _format_prompt(system, messages)
        fallback_models = [model] + _capacity_fallback_models(model)
        last_result: CodexCallResult | None = None
        for attempt, candidate_model in enumerate(fallback_models[:3], start=1):
            if attempt > 1:
                delay = min(2 * attempt, 6)
                logger.warning(
                    "[CodexCLI] Model %s at capacity; retrying with fallback %s after %ss",
                    model, candidate_model, delay,
                )
                await asyncio.sleep(delay)
            result = await self._call_once(
                model=candidate_model,
                prompt=prompt,
                cancel_event=cancel_event,
                tool_callback=tool_callback,
                resume_thread_id=(
                    self.get_thread_id(chat_id)
                    if chat_id and session_type == "chat"
                    else ""
                ),
                message_queue=message_queue,
                session_id=session_id,
                chat_id=chat_id,
                workspace_id=workspace_id,
                session_type=session_type,
                task_id=task_id,
                cwd=cwd,
                sandbox=sandbox,
                use_tools=use_tools,
                mcp_role=mcp_role,
                card_id=card_id,
            )
            last_result = result
            if result.ok or not _is_capacity_error(result.response):
                return result.response, result.usage
        assert last_result is not None
        return last_result.response, last_result.usage

    async def _call_once(
        self,
        *,
        model: str,
        prompt: str,
        cancel_event: Optional[asyncio.Event],
        tool_callback: Optional[Callable],
        resume_thread_id: str,
        message_queue: Optional[asyncio.Queue],
        session_id: str,
        chat_id: str,
        workspace_id: str,
        session_type: str,
        task_id: str,
        cwd: str,
        sandbox: str,
        use_tools: bool,
        mcp_role: str,
        card_id: str,
    ) -> CodexCallResult:
        args = self._build_args(
            model,
            cwd=cwd,
            sandbox=sandbox,
            resume_thread_id=resume_thread_id,
            use_tools=use_tools,
            mcp_role=mcp_role,
            workspace_id=workspace_id,
            card_id=card_id,
            chat_id=chat_id,
            worker_id=(task_id if session_type == "worker" else ""),
        )
        logger.info(
            "[CodexCLI] Spawning: %s %s model=%s prompt_len=%s",
            self.cli_path, " ".join(args[:4]), model, len(prompt),
        )

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
            id=_reg_id,
            pid=proc.pid,
            session_id=session_id,
            chat_id=chat_id,
            workspace_id=workspace_id or None,
            model=model,
            session_type=session_type,
            started_at=time.time(),
            cancel_event=_cancel,
            _process=proc,
            task_id=task_id,
        ))
        bind_contextvars(cli_session_id=_reg_id, cli_pid=proc.pid)

        cancel_task = None
        if cancel_event:
            async def _watch_cancel():
                while not cancel_event.is_set():
                    await asyncio.sleep(0.5)
                logger.info("[CodexCLI] cancel_event set — terminating subprocess")
                try:
                    proc.terminate()
                    await asyncio.sleep(2)
                    if proc.returncode is None:
                        proc.kill()
                except ProcessLookupError:
                    pass
            cancel_task = asyncio.create_task(_watch_cancel())

        response_parts: list[str] = []
        usage: dict = {}
        stderr_task = asyncio.create_task(proc.stderr.read())
        assert proc.stdin is not None
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        await proc.stdin.wait_closed()

        try:
            assert proc.stdout is not None
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("[CodexCLI] Ignoring non-JSON line: %s", line[:200])
                    continue
                await self._handle_event(
                    event,
                    response_parts,
                    usage,
                    tool_callback,
                    chat_id=chat_id,
                )
        finally:
            get_cli_session_registry().deregister(_reg_id)
            if cancel_task:
                cancel_task.cancel()
                try:
                    await cancel_task
                except asyncio.CancelledError:
                    pass
            if message_queue:
                while not message_queue.empty():
                    try:
                        message_queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

        await proc.wait()
        stderr_text = (await stderr_task).decode("utf-8", errors="replace").strip()

        if cancel_event and cancel_event.is_set():
            return CodexCallResult.cancel()
        if proc.returncode != 0:
            detail = stderr_text or _dedupe_lines(response_parts)
            if not detail:
                detail = f"process exited with code {proc.returncode}"
            logger.error("[CodexCLI] Process exited with code %s: %s", proc.returncode, detail[:500])
            return CodexCallResult.error(f"[Codex CLI error: {detail}]")

        self._last_usage = usage
        response = "\n\n".join(part for part in response_parts if part).strip()
        logger.info(
            "[CodexCLI] Complete: %s chars, in=%s out=%s",
            len(response),
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
        )
        return CodexCallResult.success(response, usage)

    async def _handle_event(
        self,
        event: dict,
        response_parts: list[str],
        usage: dict,
        tool_callback: Optional[Callable],
        *,
        chat_id: str = "",
    ) -> None:
        event_type = event.get("type")
        if event_type == "thread.started":
            self._last_thread_id = event.get("thread_id", "") or ""
            if chat_id and self._last_thread_id:
                self._thread_ids_by_chat[chat_id] = self._last_thread_id
            return
        if event_type == "turn.completed":
            raw_usage = event.get("usage")
            if isinstance(raw_usage, dict):
                usage.clear()
                usage.update(raw_usage)
            return
        if event_type == "error":
            message = _extract_codex_error_message(event.get("message") or event)
            if message:
                response_parts.append(message)
            return
        if event_type == "turn.failed":
            message = _extract_codex_error_message(event.get("error") or event)
            if message:
                response_parts.append(message)
            return
        if event_type != "item.completed":
            return

        item = event.get("item") or {}
        item_type = item.get("type")
        if item_type == "agent_message":
            text = item.get("text", "")
            if text:
                await self._emit_lifecycle_blocks(text, tool_callback)
                response_parts.append(text)
            return
        if item_type == "command_execution" and tool_callback:
            command = item.get("command", "")
            result = {
                "content": item.get("aggregated_output", ""),
                "exit_code": item.get("exit_code"),
                "status": item.get("status"),
            }
            try:
                ret = tool_callback("codex.command", {"command": command}, result)
                if asyncio.iscoroutine(ret):
                    await ret
            except Exception as exc:
                logger.warning("[CodexCLI] tool_callback error: %s", exc)
            return
        if item_type == "mcp_tool_call" and tool_callback:
            raw_tool = item.get("tool", "") or "mcp.tool"
            tool_name = _codex_tool_name_to_mcp(raw_tool)
            arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
            error = item.get("error")
            result_payload = item.get("result")
            result = {
                "content": json.dumps(result_payload, default=str) if result_payload is not None else "",
                "is_error": bool(error),
                "error": error,
                "status": item.get("status"),
            }
            try:
                ret = tool_callback(tool_name, arguments, result)
                if asyncio.iscoroutine(ret):
                    await ret
            except Exception as exc:
                logger.warning("[CodexCLI] mcp tool_callback error: %s", exc)


    async def _emit_lifecycle_blocks(
        self,
        text: str,
        tool_callback: Optional[Callable],
    ) -> None:
        """Detect Voxyflow lifecycle JSON blocks in Codex final text.

        Codex does not receive Voxyflow's MCP tools in this first integration,
        so workers can report lifecycle transitions with fenced JSON blocks:

            ```json
            {"voxyflow_worker_complete": {...}}
            ```

        This method maps those blocks back to the same callback shape used by
        Claude MCP tool events.
        """
        if not tool_callback or "voxyflow_worker_" not in text:
            return
        for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
            raw = match.group(1)
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            for key in ("voxyflow_worker_claim", "voxyflow_worker_complete"):
                args = payload.get(key)
                if not isinstance(args, dict):
                    continue
                suffix = key.removeprefix("voxyflow_worker_")
                tool_name = f"voxyflow.worker.{suffix}"
                result = {"content": json.dumps({"success": True})}
                try:
                    ret = tool_callback(tool_name, args, result)
                    if asyncio.iscoroutine(ret):
                        await ret
                except Exception as exc:
                    logger.warning("[CodexCLI] lifecycle callback error: %s", exc)

    async def stream(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        **kwargs,
    ) -> AsyncIterator[str]:
        """Stream-compatible wrapper.

        Codex exec JSONL currently provides structured item events rather than
        stable token deltas. We yield the final text once the turn completes.
        """
        text, _usage = await self.call(model, system, messages, **kwargs)
        if text:
            yield text
