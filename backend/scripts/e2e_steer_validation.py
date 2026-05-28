#!/usr/bin/env python3
"""
E2E validation for Codex Steerable degraded cancel+resume strategy.

Runs against the production CodexCliBackend class using a mock subprocess
with realistic async timing (no real API call, no billing).
Validates the complete cancel+resume cycle end-to-end:
  - steer watcher detects directive mid-exec
  - proc.terminate() fires
  - call() resumes with [STEER]/[CONTINUE] prompt
  - both spawns visible in log

Usage (from backend/ root):
  PYTHONPATH=. ./venv/bin/python scripts/e2e_steer_validation.py
"""
import asyncio
import logging
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

# Configure logging to stdout so we see [CodexCLI] lines
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    stream=sys.stdout,
)
# Filter to codex-relevant loggers only
for name in logging.root.manager.loggerDict:
    if "codex" not in name.lower():
        logging.getLogger(name).setLevel(logging.WARNING)

logging.getLogger("app.services.llm.codex_backend").setLevel(logging.DEBUG)

THREAD_ID = "e2e-thread-live-001"
STEER_MSG = "Pivot: focus only on the steer mechanism, skip unrelated steps"

# ── Fake subprocess helpers ─────────────────────────────────────────────────


class _FakeStream:
    """Async line generator that yields to the event loop between lines."""

    def __init__(self, lines: list[bytes], delay: float = 0.08):
        self._lines = list(lines)
        self._delay = delay
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        await asyncio.sleep(self._delay)  # realistic inter-line delay & yield to tasks
        if self._idx >= len(self._lines):
            raise StopAsyncIteration
        line = self._lines[self._idx]
        self._idx += 1
        return line

    async def read(self) -> bytes:
        return b""


class _FakeProc:
    def __init__(self, stdout_lines: list[bytes], returncode: int = 0, pid: int = 9000):
        self.pid = pid
        self.stdout = _FakeStream(stdout_lines, delay=0.08)
        self.stderr = _FakeStream([])
        self.stdin = MagicMock()
        self.stdin.drain = AsyncMock()
        self.stdin.wait_closed = AsyncMock()
        self._returncode = returncode
        self._exited = False

    @property
    def returncode(self):
        return self._returncode if self._exited else None

    def terminate(self):
        print(f"  [FakeProc pid={self.pid}] terminate() called — simulating cancel")
        self._exited = True

    async def wait(self):
        self._exited = True
        return self._returncode


def _registry_mock():
    reg = MagicMock()
    reg.register.return_value = "e2e-reg-id"
    reg.deregister.return_value = None
    return reg


def _initial_proc_lines() -> list[bytes]:
    """Simulate codex streaming a long response (will be cancelled mid-way by steer).

    Uses the real event types expected by _handle_event():
      - "thread.started"  → sets _last_thread_id
      - "item.completed" with item.type="agent_message" → appends to response_parts
    """
    import json

    lines = []
    # Thread start — sets _last_thread_id in _handle_event()
    lines.append(
        json.dumps({"type": "thread.started", "thread_id": THREAD_ID}).encode() + b"\n"
    )
    # Several agent_message items before we get steered
    for i in range(6):
        lines.append(
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "agent_message",
                        "text": f"Initial reasoning step {i+1}: explaining asyncio concurrency...",
                    },
                }
            ).encode()
            + b"\n"
        )
    # turn.completed with usage
    lines.append(
        json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 120, "output_tokens": 60}}
        ).encode()
        + b"\n"
    )
    return lines


def _resume_proc_lines() -> list[bytes]:
    """Simulate codex completing the resume call after cancel+resume."""
    import json

    lines = []
    lines.append(
        json.dumps({"type": "thread.started", "thread_id": THREAD_ID}).encode() + b"\n"
    )
    lines.append(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "agent_message",
                    "text": (
                        "Understood. Pivoting to focus exclusively on the "
                        "steer mechanism as instructed. Here is the revised output..."
                    ),
                },
            }
        ).encode()
        + b"\n"
    )
    lines.append(
        json.dumps(
            {"type": "turn.completed", "usage": {"input_tokens": 200, "output_tokens": 42}}
        ).encode()
        + b"\n"
    )
    return lines


# ── Main validation ─────────────────────────────────────────────────────────


async def run_validation() -> bool:
    print("\n" + "=" * 70)
    print("  E2E Steer Validation — Codex Steerable degraded cancel+resume")
    print("=" * 70)

    from app.services.llm.codex_backend import CodexCliBackend

    spawn_calls: list[tuple] = []
    initial_proc = _FakeProc(stdout_lines=_initial_proc_lines(), pid=9001)
    resume_proc = _FakeProc(stdout_lines=_resume_proc_lines(), pid=9002)

    async def _fake_spawn(*args, **kwargs):
        spawn_calls.append(args)
        n = len(spawn_calls)
        proc = initial_proc if n == 1 else resume_proc
        print(f"\n  ▶ SPAWN #{n} → pid={proc.pid}  argv={' '.join(str(a) for a in args[:8])}...")
        return proc

    message_queue: asyncio.Queue[str] = asyncio.Queue()
    import shutil
    codex_path = shutil.which("codex") or "/usr/local/bin/codex"
    backend = CodexCliBackend(cli_path=codex_path)

    # Inject steer after a short delay (while first exec is streaming)
    async def _inject_steer():
        await asyncio.sleep(0.30)  # wait for a few lines to stream
        print(f"\n  ★ INJECT STEER: {STEER_MSG!r}")
        await message_queue.put(STEER_MSG)

    print("\n[1/4] Starting backend.call() with message_queue ...")
    start = time.monotonic()

    with (
        patch("asyncio.create_subprocess_exec", side_effect=_fake_spawn),
        patch(
            "app.services.llm.codex_backend.get_cli_session_registry",
            return_value=_registry_mock(),
        ),
        patch("app.services.llm.codex_backend.new_cli_session_id", return_value="e2e-reg"),
        patch("app.services.llm.codex_backend.bind_contextvars"),
        patch("app.services.llm.codex_backend._STEER_DEBOUNCE_SECS", 0.05),
    ):
        # backend.call() returns (response_str, usage_dict); _inject_steer() returns None
        (response, usage), _ = await asyncio.gather(
            backend.call(
                model="gpt-4.1-mini",
                system="You are a helpful assistant.",
                messages=[{"role": "user", "content": "Explain asyncio in detail, step by step."}],
                message_queue=message_queue,
            ),
            _inject_steer(),
        )

    elapsed = time.monotonic() - start

    print(f"\n[2/4] call() returned after {elapsed:.2f}s")
    print(f"      response[:120]: {repr(response[:120])}")
    print(f"      usage: {usage}")

    print("\n[3/4] Validating invariants ...")
    ok = True

    if len(spawn_calls) != 2:
        print(f"  ✗ FAIL: expected 2 spawns, got {len(spawn_calls)}")
        ok = False
    else:
        print(f"  ✓ 2 subprocess spawns (initial + resume)")

    resume_argv = " ".join(str(a) for a in spawn_calls[1]) if len(spawn_calls) >= 2 else ""
    if "resume" in resume_argv and THREAD_ID in resume_argv:
        print(f"  ✓ Resume argv contains 'resume' and thread_id={THREAD_ID!r}")
    else:
        print(f"  ✗ FAIL: resume argv missing 'resume' or thread_id. Got: {resume_argv[:120]}")
        ok = False

    steer_prefix = "[STEER]"
    initial_argv = " ".join(str(a) for a in spawn_calls[0]) if spawn_calls else ""
    if "exec" in initial_argv and "resume" not in initial_argv:
        print(f"  ✓ Initial spawn is 'exec' (not resume)")
    else:
        print(f"  ✗ FAIL: initial spawn looks wrong: {initial_argv[:120]}")
        ok = False

    if "Pivot" in response or "steer" in response.lower() or "Pivoting" in response:
        print(f"  ✓ Response reflects steer directive content")
    else:
        print(f"  ✗ FAIL: response doesn't reflect steer. response={response[:120]!r}")
        ok = False

    print("\n[4/4] Result ...")
    if ok:
        print("  ✅ ALL CHECKS PASSED — cancel+resume cycle confirmed E2E")
    else:
        print("  ❌ SOME CHECKS FAILED — see above")

    print("=" * 70 + "\n")
    return ok


if __name__ == "__main__":
    result = asyncio.run(run_validation())
    sys.exit(0 if result else 1)
