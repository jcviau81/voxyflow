"""Tests for Codex CLI cancel-mid-exec behaviour.

When the supervisor sets ``cancel_event`` while ``codex exec`` is still
streaming, ``_call_once`` must:

* let the background ``_watch_cancel`` task call ``proc.terminate()``;
* drain the subprocess cleanly (no leaked transport);
* return ``CodexCallResult.cancel()`` rather than treating the non-zero
  exit code as an error.

We do not spawn a real Codex CLI here: the whole point of the test is to
verify the cancel plumbing without binding any port or starting any
subprocess. ``asyncio.create_subprocess_exec`` is monkeypatched with a tiny
fake that mirrors just enough of ``asyncio.subprocess.Process``.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from app.services.llm import codex_backend as cb


# ---------------------------------------------------------------------------
# Fake subprocess wiring
# ---------------------------------------------------------------------------


class _FakeStdin:
    def __init__(self):
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes):
        self.buffer.extend(data)

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


class _FakeStdout:
    """Async-iterable stdout that yields lines until ``stop_event`` is set."""

    def __init__(self, stop_event: asyncio.Event):
        self._stop = stop_event
        self._initial_lines: list[bytes] = []

    def feed(self, *lines: bytes):
        self._initial_lines.extend(lines)

    def __aiter__(self):
        return self

    async def __anext__(self):
        # Drain pre-fed lines first (lets us simulate a "thread.started" event
        # before cancel fires).
        if self._initial_lines:
            return self._initial_lines.pop(0)
        # Then block until the process is "terminated".
        await self._stop.wait()
        raise StopAsyncIteration


class _FakeStderr:
    async def read(self):
        return b""


class _FakeProcess:
    """Minimal ``asyncio.subprocess.Process`` stand-in."""

    def __init__(self):
        self.pid = 12345
        self.returncode: int | None = None
        self.stdin = _FakeStdin()
        self._stop = asyncio.Event()
        self.stdout = _FakeStdout(self._stop)
        self.stderr = _FakeStderr()
        self.terminate_calls = 0
        self.kill_calls = 0

    def terminate(self):
        self.terminate_calls += 1
        # SIGTERM-equivalent exit code.
        self.returncode = -15
        self._stop.set()

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9
        self._stop.set()

    async def wait(self):
        await self._stop.wait()
        if self.returncode is None:
            self.returncode = 0
        return self.returncode


# ---------------------------------------------------------------------------
# Stub the CLI session registry (avoid touching real backend state)
# ---------------------------------------------------------------------------


class _StubRegistry:
    def __init__(self):
        self.registered: list = []
        self.deregistered: list = []

    def register(self, sess):
        self.registered.append(sess)

    def deregister(self, sess_id):
        self.deregistered.append(sess_id)


def _patch_registry_and_subprocess(monkeypatch, proc: _FakeProcess) -> _StubRegistry:
    """Wire all I/O dependencies of ``_call_once`` to in-memory fakes."""
    registry = _StubRegistry()
    monkeypatch.setattr(cb, "get_cli_session_registry", lambda: registry)
    monkeypatch.setattr(cb, "bind_contextvars", lambda **_kw: None)

    async def fake_create_subprocess_exec(*args, **kwargs):
        return proc

    monkeypatch.setattr(
        cb.asyncio,
        "create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    return registry


def _make_backend() -> cb.CodexCliBackend:
    backend = cb.CodexCliBackend.__new__(cb.CodexCliBackend)
    backend._configured_cli_path = "codex"
    backend._last_usage = {}
    backend._last_thread_id = ""
    backend._thread_ids_by_chat = {}
    return backend


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCodexCancelMidExec:
    async def test_cancel_event_set_terminates_subprocess(self, monkeypatch):
        backend = _make_backend()
        proc = _FakeProcess()
        # Feed one event so the stdout loop iterates at least once.
        proc.stdout.feed(b'{"type":"thread.started","thread_id":"t-1"}\n')

        registry = _patch_registry_and_subprocess(monkeypatch, proc)

        cancel_event = asyncio.Event()

        async def _cancel_after_delay():
            # Let the subprocess start + stdout loop enter blocking wait.
            await asyncio.sleep(0.05)
            cancel_event.set()

        # Tighten the watcher's poll cadence by patching asyncio.sleep used
        # inside _watch_cancel; but we still need the real sleep elsewhere,
        # so we don't monkeypatch globally — instead we just rely on the
        # default 0.5s poll. To keep the test snappy we wrap it:
        original_sleep = asyncio.sleep

        async def _fast_sleep(seconds):
            # Anything ≥ 0.5s in this test path is the _watch_cancel poll OR
            # the 2s post-terminate grace; collapse them so we don't actually
            # wait. Smaller values (our test scheduler) use the real sleep.
            if seconds >= 0.5:
                seconds = 0.01
            await original_sleep(seconds)

        monkeypatch.setattr(cb.asyncio, "sleep", _fast_sleep)

        canceller = asyncio.create_task(_cancel_after_delay())
        result = await backend._call_once(
            model="gpt-5.4-mini",
            prompt="hi",
            cancel_event=cancel_event,
            tool_callback=None,
            resume_thread_id="",
            message_queue=None,
            session_id="sess",
            chat_id="chat",
            workspace_id="ws",
            session_type="worker",
            task_id="task-1",
            cwd="",
            sandbox="workspace-write",
            use_tools=False,
            mcp_role="worker",
            card_id="",
        )
        await canceller

        assert isinstance(result, cb.CodexCallResult)
        assert result.cancelled is True
        assert result.ok is False
        assert "cancelled" in result.response.lower()
        # The watcher must have called terminate exactly once. kill() is only
        # used as a backup if the process doesn't exit within the grace.
        assert proc.terminate_calls == 1
        # The CLI registry must be cleaned up — no leak across cancels.
        assert len(registry.deregistered) == 1

    async def test_terminated_process_does_not_leak_proc_handle(self, monkeypatch):
        """After cancel, the fake process must reach a final returncode and
        ``_call_once`` must not raise — guarding against a hung await."""
        backend = _make_backend()
        proc = _FakeProcess()
        registry = _patch_registry_and_subprocess(monkeypatch, proc)

        cancel_event = asyncio.Event()
        cancel_event.set()  # cancel immediately, before any stdout arrives.

        original_sleep = asyncio.sleep

        async def _fast_sleep(seconds):
            if seconds >= 0.5:
                seconds = 0.01
            await original_sleep(seconds)

        monkeypatch.setattr(cb.asyncio, "sleep", _fast_sleep)

        result = await backend._call_once(
            model="gpt-5.4-mini",
            prompt="hi",
            cancel_event=cancel_event,
            tool_callback=None,
            resume_thread_id="",
            message_queue=None,
            session_id="sess",
            chat_id="chat",
            workspace_id="ws",
            session_type="worker",
            task_id="task-1",
            cwd="",
            sandbox="workspace-write",
            use_tools=False,
            mcp_role="worker",
            card_id="",
        )

        assert result.cancelled is True
        # Process returncode is final and not None — no orphan waiting.
        assert proc.returncode is not None
        # Single register + deregister: lifecycle is clean.
        assert len(registry.registered) == 1
        assert len(registry.deregistered) == 1

    async def test_no_cancel_event_means_normal_completion(self, monkeypatch):
        """Sanity check: when no cancel_event is supplied, the subprocess
        completes naturally and the watcher is never installed."""
        backend = _make_backend()
        proc = _FakeProcess()
        # Feed a thread.started + turn.completed then let stdout drain.
        proc.stdout.feed(
            b'{"type":"thread.started","thread_id":"t-2"}\n',
            b'{"type":"turn.completed","usage":{"input_tokens":5,"output_tokens":1}}\n',
        )

        _patch_registry_and_subprocess(monkeypatch, proc)

        # Trigger the natural completion: once initial lines drain, the
        # stdout iterator blocks until ``_stop`` is set. Schedule that here.
        async def _finish_soon():
            await asyncio.sleep(0.02)
            proc.returncode = 0
            proc._stop.set()

        asyncio.create_task(_finish_soon())

        result = await backend._call_once(
            model="gpt-5.4-mini",
            prompt="hi",
            cancel_event=None,
            tool_callback=None,
            resume_thread_id="",
            message_queue=None,
            session_id="sess",
            chat_id="",
            workspace_id="ws",
            session_type="worker",
            task_id="task-2",
            cwd="",
            sandbox="workspace-write",
            use_tools=False,
            mcp_role="worker",
            card_id="",
        )

        assert result.ok is True
        assert result.cancelled is False
        # Usage was captured from turn.completed.
        assert result.usage.get("input_tokens") == 5
        # No terminate / kill because the process exited cleanly.
        assert proc.terminate_calls == 0
        assert proc.kill_calls == 0
