"""End-to-end Codex steer tests (cancel + resume cycle).

These tests cover the steerable-degraded strategy described in
``feature/codex-steerable-degraded`` (the branch with ``CodexCallResult.steer``,
``_build_steer_prompt`` and ``_watch_steer_queue``). They drive the public
``CodexCliBackend.call`` surface end-to-end via a fake subprocess so no real
``codex exec`` is spawned.

If the steer feature is not yet merged into the branch under test, the whole
module is skipped — keeps the suite green on ``dev`` while the feature lands.

Coverage (per brief tests 5/6/7):

5. **End-to-end steer honored**: a directive injected mid-stream causes the
   second ``codex exec resume`` to carry a ``[STEER] ... [CONTINUE] ...``
   prefix on the same ``thread_id``.

6. **Multiple rapid steers accumulated**: two directives queued within the
   debounce window collapse into a single resume whose prompt concatenates
   both directives.

7. **Race steer-vs-natural-completion**: a steer that arrives after the
   subprocess has finished its turn becomes a no-op (no extra resume).
"""

from __future__ import annotations

import asyncio
import importlib

import pytest

from app.services.llm import codex_backend as cb


# ---------------------------------------------------------------------------
# Feature detection — skip module when the steer surface isn't present.
# ---------------------------------------------------------------------------


_HAS_STEER = (
    hasattr(cb.CodexCliBackend, "_build_steer_prompt")
    and hasattr(cb.CodexCallResult, "steer")
)

# No longer gated: feature/codex-steerable-degraded merged into dev (PR #114).
# Skip guard kept as dead-code safety in case of accidental revert.
pytestmark = pytest.mark.skipif(
    not _HAS_STEER,
    reason=(
        "Codex steer cancel+resume surface not present on this branch "
        "(expected post PR #114 merge). Skipping until merged."
    ),
)


# ---------------------------------------------------------------------------
# Helpers — only imported / used when the feature is available.
# ---------------------------------------------------------------------------


def _make_backend(known_thread: dict | None = None) -> cb.CodexCliBackend:
    backend = cb.CodexCliBackend.__new__(cb.CodexCliBackend)
    backend._configured_cli_path = "codex"
    # Snapshots of the last completed call (external properties only).
    backend._last_usage = {}
    backend._last_thread_id = ""
    backend._thread_ids_by_chat = dict(known_thread or {})
    # Per-call steer state now lives in a local ``_CallContext`` inside
    # ``_call_once`` — there are no longer any per-steer instance fields.
    return backend


# ---------------------------------------------------------------------------
# Test 5 — single steer honored
# ---------------------------------------------------------------------------


class TestSteerHonoredEndToEnd:
    async def test_single_steer_resumes_with_prefixed_prompt(self, monkeypatch):
        """A directive injected mid-stream triggers exactly one resume call
        whose prompt is prefixed with ``[STEER] ... [CONTINUE] ...`` and uses
        the same ``thread_id`` discovered in the first attempt."""
        backend = _make_backend()
        queue: asyncio.Queue = asyncio.Queue()
        # Zero the debounce so call()'s post-steer wait is a no-op.
        monkeypatch.setattr(cb, "_STEER_DEBOUNCE_SECS", 0.0)

        spawn_log: list[dict] = []

        async def fake_once(**kwargs):
            spawn_log.append(kwargs)
            # First spawn: pretend the steer watcher saw a directive arrive
            # mid-execution (after thread.started gave us a thread_id) and
            # terminated the proc, so _call_once returns a steered result that
            # carries the per-call thread_id + directives — the new API.
            if len(spawn_log) == 1:
                backend._last_thread_id = "thread-XYZ"
                backend._thread_ids_by_chat[kwargs.get("chat_id", "")] = "thread-XYZ"
                await queue.put("Refactor handler to use async/await.")
                # Mirror real _call_once: the watcher pulls the directive off
                # the queue into the per-call context before signalling steer.
                directive = await queue.get()
                return cb.CodexCallResult.steer("thread-XYZ", [directive])
            # Second spawn: the resume call.
            return cb.CodexCallResult.success("done", {})

        monkeypatch.setattr(backend, "_call_once", fake_once)

        response, _usage = await backend.call(
            model="gpt-5.4-mini",
            system="sys",
            messages=[{"role": "user", "content": "make it better"}],
            chat_id="chat-S1",
            session_type="chat",
            message_queue=queue,
        )

        assert response == "done"
        assert len(spawn_log) == 2, "expected exactly one resume after steer"
        resumed = spawn_log[1]
        assert resumed["resume_thread_id"] == "thread-XYZ"
        prompt = resumed["prompt"]
        assert "[STEER]" in prompt
        assert "[CONTINUE]" in prompt
        assert "Refactor handler to use async/await." in prompt


# ---------------------------------------------------------------------------
# Test 6 — multiple rapid steers accumulated
# ---------------------------------------------------------------------------


class TestRapidSteerAccumulation:
    async def test_two_directives_within_debounce_collapse_to_one_resume(self, monkeypatch):
        backend = _make_backend()
        queue: asyncio.Queue = asyncio.Queue()
        # Zero the debounce so call()'s post-steer wait is a no-op; the second
        # directive is still drained from the queue immediately after.
        monkeypatch.setattr(cb, "_STEER_DEBOUNCE_SECS", 0.0)
        spawn_log: list[dict] = []

        async def fake_once(**kwargs):
            spawn_log.append(kwargs)
            if len(spawn_log) == 1:
                backend._last_thread_id = "thread-R1"
                backend._thread_ids_by_chat[kwargs.get("chat_id", "")] = "thread-R1"
                # Two directives back-to-back (well within debounce window).
                await queue.put("First directive: skip tests.")
                await queue.put("Second directive: use feature flag.")
                # Mirror real _call_once: only the FIRST directive is pulled into
                # the per-call context before the steer signal fires; the second
                # is left on the queue for call() to drain during the debounce.
                first = await queue.get()
                return cb.CodexCallResult.steer("thread-R1", [first])
            return cb.CodexCallResult.success("ack", {})

        monkeypatch.setattr(backend, "_call_once", fake_once)

        await backend.call(
            model="gpt-5.4-mini",
            system="sys",
            messages=[{"role": "user", "content": "go"}],
            chat_id="chat-R1",
            session_type="chat",
            message_queue=queue,
        )

        # Exactly two spawns (initial + ONE resume), not three.
        assert len(spawn_log) == 2
        resume_prompt = spawn_log[1]["prompt"]
        assert "First directive: skip tests." in resume_prompt
        assert "Second directive: use feature flag." in resume_prompt
        # Both directives sit inside a single [STEER] block.
        assert resume_prompt.count("[STEER]") == 1


# ---------------------------------------------------------------------------
# Test 6b — second steer during the resume triggers another resume
# ---------------------------------------------------------------------------


class TestSteerDuringResume:
    async def test_second_steer_during_resume_resumes_again(self, monkeypatch):
        """If a directive arrives while the steer-resume is executing, the
        resume itself returns steered — call() must resume again with the new
        directive instead of returning the empty steer result."""
        backend = _make_backend()
        queue: asyncio.Queue = asyncio.Queue()
        monkeypatch.setattr(cb, "_STEER_DEBOUNCE_SECS", 0.0)
        spawn_log: list[dict] = []

        async def fake_once(**kwargs):
            spawn_log.append(kwargs)
            if len(spawn_log) == 1:
                # First spawn: steer cancels the proc.
                return cb.CodexCallResult.steer("thread-D2", ["First directive."])
            if len(spawn_log) == 2:
                # The resume is itself steered by a late second directive.
                return cb.CodexCallResult.steer("thread-D2", ["Second directive."])
            return cb.CodexCallResult.success("final answer", {"output_tokens": 3})

        monkeypatch.setattr(backend, "_call_once", fake_once)

        response, usage = await backend.call(
            model="gpt-5.4-mini",
            system="sys",
            messages=[{"role": "user", "content": "go"}],
            chat_id="chat-D2",
            session_type="chat",
            message_queue=queue,
        )

        # Three spawns: initial + two resumes — the second directive is honored.
        assert len(spawn_log) == 3
        assert "Second directive." in spawn_log[2]["prompt"]
        assert spawn_log[2]["resume_thread_id"] == "thread-D2"
        # The final (non-steered) result is what call() returns — not "".
        assert response == "final answer"
        assert usage == {"output_tokens": 3}


# ---------------------------------------------------------------------------
# Test 7 — race: steer arrives after natural completion
# ---------------------------------------------------------------------------


class TestSteerVsNaturalCompletion:
    async def test_steer_after_completion_is_noop(self, monkeypatch):
        """If the subprocess finished its turn before the steer is detected,
        the watcher must not trigger a follow-up resume."""
        backend = _make_backend()
        queue: asyncio.Queue = asyncio.Queue()
        spawn_log: list[dict] = []

        async def fake_once(**kwargs):
            spawn_log.append(kwargs)
            # Natural completion BEFORE any steer.
            backend._last_thread_id = "thread-Z9"
            backend._thread_ids_by_chat[kwargs.get("chat_id", "")] = "thread-Z9"
            return cb.CodexCallResult.success("turn done", {"output_tokens": 1})

        monkeypatch.setattr(backend, "_call_once", fake_once)

        # Pre-queue a directive that should be detected as "too late".
        await queue.put("Too-late directive.")

        response, _ = await backend.call(
            model="gpt-5.4-mini",
            system="sys",
            messages=[{"role": "user", "content": "go"}],
            chat_id="chat-N1",
            session_type="chat",
            message_queue=queue,
        )

        assert response == "turn done"
        # No resume issued because the call succeeded naturally.
        assert len(spawn_log) == 1
