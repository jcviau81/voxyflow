"""Tests for the Codex CLI steerable (cancel+resume) implementation.

Covers the degraded steer strategy introduced in feature/codex-steerable-degraded:
  - Steer received during active codex exec → cancel proc + spawn resume
  - thread_id is reused after steer (assertion on subprocess mock args)
  - Two rapid steers accumulate into a single resume prompt
  - Steer post-completion = no-op (proc.returncode already set)
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm.codex_backend import CodexCliBackend, CodexCallResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jsonl_lines(*events: dict) -> list[bytes]:
    """Encode event dicts to JSONL byte lines."""
    return [json.dumps(e).encode() + b"\n" for e in events]


class _FakeStream:
    """Async iterable that yields pre-canned byte lines.

    Each item yields via ``asyncio.sleep(0)`` so concurrent asyncio tasks (the
    steer watcher) get a scheduling slot between lines.  This uses the module-
    level asyncio.sleep directly so it is not affected by any patches on
    codex_backend's imports.

    When ``stay_alive_event`` is supplied, the stream does NOT raise
    StopAsyncIteration once the canned lines are exhausted — instead it stays
    pending (awaiting the event) until the event is set (by ``_FakeProc.terminate``
    / ``wait``).  This models a real long-running ``codex exec`` whose stdout only
    ends when the proc is terminated, so the steer watcher is not cancelled by a
    prematurely-exhausted stdout loop before it can fire the (re-queued) directive.
    """

    def __init__(self, lines: list[bytes], stay_alive_event: asyncio.Event | None = None):
        self._lines = list(lines)
        self._idx = 0
        self._stay_alive_event = stay_alive_event

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        # Yield cooperative control so concurrent tasks can run between lines.
        await asyncio.sleep(0)
        if self._idx >= len(self._lines):
            if self._stay_alive_event is not None:
                # Behave like a long-running exec: block until the proc is
                # terminated, then end the stream.
                await self._stay_alive_event.wait()
            raise StopAsyncIteration
        line = self._lines[self._idx]
        self._idx += 1
        return line

    async def read(self) -> bytes:
        return b""


class _FakeProc:
    """Minimal asyncio.subprocess.Process stand-in.

    returncode is None until either terminate() is called or wait() completes,
    matching real subprocess semantics.
    """

    def __init__(
        self,
        stdout_lines: list[bytes],
        returncode: int = 0,
        pid: int = 9999,
        stay_alive: bool = False,
    ):
        self.pid = pid
        # When stay_alive is set, the stdout stream blocks after the canned
        # lines are exhausted until terminate()/wait() releases it — modelling a
        # long-running exec that only ends when the steer watcher terminates it.
        self._stay_alive_event = asyncio.Event() if stay_alive else None
        self.stdout = _FakeStream(stdout_lines, self._stay_alive_event)
        self.stderr = _FakeStream([])
        self.stdin = MagicMock()
        self.stdin.write = MagicMock()
        self.stdin.drain = AsyncMock()
        self.stdin.close = MagicMock()
        self.stdin.wait_closed = AsyncMock()
        self.stdin.is_closing = MagicMock(return_value=False)
        self._returncode = returncode
        self._exited = False

    @property
    def returncode(self) -> int | None:
        return self._returncode if self._exited else None

    def terminate(self):
        """Signal proc termination; returncode becomes visible."""
        self._exited = True
        if self._stay_alive_event is not None:
            self._stay_alive_event.set()

    async def wait(self) -> int:
        """Wait for proc; marks as exited (simulates natural completion)."""
        self._exited = True
        if self._stay_alive_event is not None:
            self._stay_alive_event.set()
        return self._returncode


# ---------------------------------------------------------------------------
# Standard event sequences
# ---------------------------------------------------------------------------

THREAD_ID = "thread-abc-123"

THREAD_STARTED_EVENT = {"type": "thread.started", "thread_id": THREAD_ID}
AGENT_MSG_EVENT = {
    "type": "item.completed",
    "item": {"type": "agent_message", "text": "Working..."},
}
TURN_COMPLETED_EVENT = {
    "type": "turn.completed",
    "usage": {"input_tokens": 10, "output_tokens": 5},
}


def _normal_proc_lines() -> list[bytes]:
    return _make_jsonl_lines(THREAD_STARTED_EVENT, AGENT_MSG_EVENT, TURN_COMPLETED_EVENT)


def _steer_proc_lines() -> list[bytes]:
    """Proc that only emits thread.started then gets terminated by the steer watcher."""
    return _make_jsonl_lines(THREAD_STARTED_EVENT)


# ---------------------------------------------------------------------------
# Shared helper: registry mock + patches
# ---------------------------------------------------------------------------

def _registry_mock():
    m = MagicMock()
    m.register = MagicMock()
    m.deregister = MagicMock()
    return m


# ---------------------------------------------------------------------------
# Unit tests for _build_steer_prompt
# ---------------------------------------------------------------------------

class TestBuildSteerPrompt:
    def test_single_directive(self):
        backend = CodexCliBackend()
        prompt = backend._build_steer_prompt(["focus on TypeScript"])
        assert "[STEER]" in prompt
        assert "focus on TypeScript" in prompt
        assert "[CONTINUE]" in prompt

    def test_multiple_directives_bulleted(self):
        backend = CodexCliBackend()
        prompt = backend._build_steer_prompt(["directive A", "directive B"])
        assert "- directive A" in prompt
        assert "- directive B" in prompt
        assert "[STEER]" in prompt
        assert "[CONTINUE]" in prompt

    def test_empty_list_returns_prompt(self):
        backend = CodexCliBackend()
        prompt = backend._build_steer_prompt([])
        assert "[STEER]" in prompt


# ---------------------------------------------------------------------------
# Unit tests for CodexCallResult.steer()
# ---------------------------------------------------------------------------

class TestCodexCallResultSteer:
    def test_steer_classmethod(self):
        r = CodexCallResult.steer(THREAD_ID, ["focus on errors", "be concise"])
        assert r.steered is True
        assert r.ok is False
        assert r.cancelled is False
        assert r.response == ""
        assert r.thread_id == THREAD_ID
        assert r.steer_directives == ("focus on errors", "be concise")

    def test_success_not_steered(self):
        r = CodexCallResult.success("hello", {})
        assert r.steered is False
        assert r.ok is True

    def test_cancel_not_steered(self):
        r = CodexCallResult.cancel()
        assert r.steered is False
        assert r.cancelled is True

    def test_error_not_steered(self):
        r = CodexCallResult.error("err")
        assert r.steered is False
        assert r.ok is False


# ---------------------------------------------------------------------------
# Integration tests using mocked subprocess
# NOTE: We do NOT patch asyncio.sleep globally — that would prevent
#       _FakeStream.__anext__'s sleep(0) from yielding to the event loop.
#       Instead we patch only _STEER_DEBOUNCE_SECS to 0.0 so the debounce
#       wait is a no-op while preserving proper asyncio cooperative scheduling.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_steer_cancels_and_spawns_resume():
    """Steer received during active exec → proc.terminate() called + resume spawned."""
    message_queue: asyncio.Queue[str] = asyncio.Queue()
    await message_queue.put("focus on error handling")

    first_proc = _FakeProc(stdout_lines=_steer_proc_lines(), stay_alive=True)
    second_proc = _FakeProc(stdout_lines=_normal_proc_lines())

    spawn_calls: list[tuple] = []

    async def _fake_spawn(*args, **kwargs):
        spawn_calls.append(args)
        return first_proc if len(spawn_calls) == 1 else second_proc

    backend = CodexCliBackend(cli_path="/fake/codex")
    # Pre-seed thread_id so the steer watcher can confirm a resume is possible
    backend._last_thread_id = THREAD_ID

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fake_spawn),
        patch(
            "app.services.llm.codex_backend.get_cli_session_registry",
            return_value=_registry_mock(),
        ),
        patch("app.services.llm.codex_backend.new_cli_session_id", return_value="reg-1"),
        patch("app.services.llm.codex_backend.bind_contextvars"),
        # Zero-out debounce without patching asyncio.sleep globally
        patch("app.services.llm.codex_backend._STEER_DEBOUNCE_SECS", 0.0),
    ):
        response, _usage = await backend.call(
            model="gpt-5.4-mini",
            system="You are a test assistant.",
            messages=[{"role": "user", "content": "Do something long"}],
            message_queue=message_queue,
        )

    # Two subprocess spawns: initial exec + resume
    assert len(spawn_calls) == 2, (
        f"Expected 2 subprocess calls (initial + resume), got {len(spawn_calls)}"
    )
    # The resume call must include 'resume' and the thread_id in argv
    resume_argv = " ".join(str(a) for a in spawn_calls[1])
    assert "resume" in resume_argv, f"'resume' not in resume args: {resume_argv}"
    assert THREAD_ID in resume_argv, f"thread_id not in resume args: {resume_argv}"


@pytest.mark.asyncio
async def test_steer_reuses_thread_id():
    """thread_id captured from the initial exec's stdout is used verbatim in the resume args.

    The backend may have a stale _last_thread_id from a prior exec (STALE_THREAD_ID).
    The first exec emits THREAD_ID in its stdout — that value overwrites _last_thread_id
    and MUST be what gets passed to ``codex exec resume``.  The stale value must NOT appear.
    """
    STALE_THREAD_ID = "thread-xyz-789"  # pre-existing, should be overwritten by exec stdout
    message_queue: asyncio.Queue[str] = asyncio.Queue()
    await message_queue.put("change direction")

    first_proc = _FakeProc(stdout_lines=_steer_proc_lines(), stay_alive=True)
    second_proc = _FakeProc(stdout_lines=_normal_proc_lines())

    spawn_calls: list[tuple] = []

    async def _fake_spawn(*args, **kwargs):
        spawn_calls.append(args)
        return first_proc if len(spawn_calls) == 1 else second_proc

    backend = CodexCliBackend(cli_path="/fake/codex")
    backend._last_thread_id = STALE_THREAD_ID  # seed with stale value

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fake_spawn),
        patch(
            "app.services.llm.codex_backend.get_cli_session_registry",
            return_value=_registry_mock(),
        ),
        patch("app.services.llm.codex_backend.new_cli_session_id", return_value="reg-2"),
        patch("app.services.llm.codex_backend.bind_contextvars"),
        patch("app.services.llm.codex_backend._STEER_DEBOUNCE_SECS", 0.0),
    ):
        await backend.call(
            model="gpt-5.4-mini",
            system="sys",
            messages=[{"role": "user", "content": "task"}],
            message_queue=message_queue,
        )

    assert len(spawn_calls) == 2, (
        f"Expected 2 spawns (initial + resume), got {len(spawn_calls)}"
    )
    resume_argv = " ".join(str(a) for a in spawn_calls[1])
    # Resume must use THREAD_ID (captured from first exec stdout), NOT the stale pre-set value
    assert THREAD_ID in resume_argv, (
        f"Expected thread_id {THREAD_ID!r} (from exec stdout) in resume args: {resume_argv}"
    )
    assert STALE_THREAD_ID not in resume_argv, (
        f"Stale thread_id {STALE_THREAD_ID!r} must NOT appear in resume args: {resume_argv}"
    )


@pytest.mark.asyncio
async def test_two_rapid_steers_accumulate():
    """Two directives queued before debounce expires are merged into 1 resume prompt."""
    message_queue: asyncio.Queue[str] = asyncio.Queue()
    await message_queue.put("directive A")
    await message_queue.put("directive B")

    first_proc = _FakeProc(stdout_lines=_steer_proc_lines(), stay_alive=True)
    second_proc = _FakeProc(stdout_lines=_normal_proc_lines())
    stdin_inputs: list[bytes] = []

    spawn_calls: list[tuple] = []

    async def _fake_spawn(*args, **kwargs):
        spawn_calls.append(args)
        if len(spawn_calls) == 1:
            return first_proc
        second_proc.stdin.write = lambda b: stdin_inputs.append(b)
        return second_proc

    backend = CodexCliBackend(cli_path="/fake/codex")
    backend._last_thread_id = THREAD_ID

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fake_spawn),
        patch(
            "app.services.llm.codex_backend.get_cli_session_registry",
            return_value=_registry_mock(),
        ),
        patch("app.services.llm.codex_backend.new_cli_session_id", return_value="reg-3"),
        patch("app.services.llm.codex_backend.bind_contextvars"),
        patch("app.services.llm.codex_backend._STEER_DEBOUNCE_SECS", 0.0),
    ):
        await backend.call(
            model="gpt-5.4-mini",
            system="sys",
            messages=[{"role": "user", "content": "task"}],
            message_queue=message_queue,
        )

    # Exactly ONE resume spawn (not two separate resumes)
    assert len(spawn_calls) == 2, (
        f"Expected exactly 2 spawns (initial + 1 resume), got {len(spawn_calls)}"
    )
    # The prompt fed to the resume proc must contain at least one directive
    prompt_sent = b"".join(stdin_inputs).decode(errors="replace")
    has_a = "directive A" in prompt_sent
    has_b = "directive B" in prompt_sent
    assert has_a or has_b, (
        f"Neither directive A nor B found in stdin prompt: {prompt_sent[:300]}"
    )


@pytest.mark.asyncio
async def test_steer_post_completion_is_noop():
    """Steer arriving after proc exits naturally = no-op: no second spawn."""
    message_queue: asyncio.Queue[str] = asyncio.Queue()
    # Nothing in the queue — proc completes without any steer.

    normal_proc = _FakeProc(stdout_lines=_normal_proc_lines())

    spawn_calls: list[tuple] = []

    async def _fake_spawn(*args, **kwargs):
        spawn_calls.append(args)
        return normal_proc

    backend = CodexCliBackend(cli_path="/fake/codex")

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fake_spawn),
        patch(
            "app.services.llm.codex_backend.get_cli_session_registry",
            return_value=_registry_mock(),
        ),
        patch("app.services.llm.codex_backend.new_cli_session_id", return_value="reg-4"),
        patch("app.services.llm.codex_backend.bind_contextvars"),
    ):
        response, _usage = await backend.call(
            model="gpt-5.4-mini",
            system="sys",
            messages=[{"role": "user", "content": "quick task"}],
            message_queue=message_queue,
        )

    # Only one subprocess spawn — no resume triggered
    assert len(spawn_calls) == 1, (
        f"Expected 1 spawn (no resume), got {len(spawn_calls)}"
    )
    assert response == "Working..."
