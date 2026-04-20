"""Tests for the CLI retry + rate-limit helpers and gate integration."""
from __future__ import annotations

import asyncio
import time

import pytest

from app.services.llm.cli_rate_gate import CliRateGate
from app.services.llm.cli_retry import (
    MAX_RETRIES,
    RateLimitInfo,
    compute_backoff,
    is_transient_error,
    parse_rate_limit_event,
)


# --- is_transient_error -------------------------------------------------------

class TestIsTransientError:
    def test_econnreset_is_transient(self):
        assert is_transient_error("Error: ECONNRESET at socket", 1)

    def test_529_overloaded_is_transient(self):
        assert is_transient_error("Anthropic API overloaded (529)", 1)

    def test_rate_limit_is_transient(self):
        assert is_transient_error("usage rate limit exceeded", 1)

    def test_spawn_eagain_is_transient(self):
        assert is_transient_error("Error: spawn EAGAIN while forking", 1)

    def test_empty_stderr_with_exit_1_is_transient(self):
        # CLI crashed before writing stderr — treated as transient.
        assert is_transient_error("", 1)
        assert is_transient_error("   \n", 1)

    def test_empty_stderr_with_other_exit_is_not_transient(self):
        assert not is_transient_error("", 2)
        assert not is_transient_error("", 127)

    def test_plain_auth_error_is_not_transient(self):
        assert not is_transient_error("Invalid API key", 1)
        assert not is_transient_error("File not found: prompt.txt", 2)

    def test_case_insensitive(self):
        assert is_transient_error("SOCKET HANG UP", 1)
        assert is_transient_error("Overloaded", 1)


# --- compute_backoff ---------------------------------------------------------

class TestComputeBackoff:
    def test_attempt_1_near_1s(self):
        # attempt 1 → base 1s ± 20%
        for _ in range(20):
            d = compute_backoff(1)
            assert 0.8 <= d <= 1.2

    def test_attempt_2_near_2s(self):
        for _ in range(20):
            d = compute_backoff(2)
            assert 1.6 <= d <= 2.4

    def test_attempt_3_near_4s(self):
        for _ in range(20):
            d = compute_backoff(3)
            assert 3.2 <= d <= 4.8

    def test_minimum_floor(self):
        # Even with maximum negative jitter the result never goes below 0.1.
        for attempt in (1, 2, 3, 4):
            for _ in range(50):
                assert compute_backoff(attempt) >= 0.1


# --- parse_rate_limit_event --------------------------------------------------

class TestParseRateLimitEvent:
    def test_rejected_with_resets_at(self):
        msg = {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "rejected", "resets_at": 1713916800},
        }
        info = parse_rate_limit_event(msg)
        assert info is not None
        assert info.status == "rejected"
        assert info.resets_at == 1713916800.0
        assert info.is_rejected

    def test_allowed_warning_not_rejected(self):
        msg = {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "allowed_warning", "resets_at": 123},
        }
        info = parse_rate_limit_event(msg)
        assert info is not None
        assert not info.is_rejected

    def test_missing_resets_at(self):
        msg = {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "rejected"},
        }
        info = parse_rate_limit_event(msg)
        assert info is not None
        assert info.resets_at is None
        assert info.cooldown_s == 0.0

    def test_non_numeric_resets_at(self):
        msg = {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "rejected", "resets_at": "soon"},
        }
        info = parse_rate_limit_event(msg)
        assert info is not None
        assert info.resets_at is None

    def test_wrong_type_returns_none(self):
        assert parse_rate_limit_event({"type": "result"}) is None
        assert parse_rate_limit_event({}) is None

    def test_missing_info_block(self):
        assert parse_rate_limit_event({"type": "rate_limit_event"}) is None

    def test_empty_status(self):
        msg = {
            "type": "rate_limit_event",
            "rate_limit_info": {"status": "", "resets_at": 123},
        }
        assert parse_rate_limit_event(msg) is None

    def test_non_dict_input(self):
        assert parse_rate_limit_event(None) is None  # type: ignore[arg-type]
        assert parse_rate_limit_event("nope") is None  # type: ignore[arg-type]


# --- RateLimitInfo.cooldown_s ------------------------------------------------

class TestCooldownS:
    def test_future_resets_at(self):
        info = RateLimitInfo(status="rejected", resets_at=time.time() + 120)
        assert 100 < info.cooldown_s <= 120

    def test_past_resets_at(self):
        info = RateLimitInfo(status="rejected", resets_at=time.time() - 60)
        assert info.cooldown_s == 0.0


# --- CliRateGate cooldown integration ---------------------------------------

class TestCliRateGateCooldown:
    async def test_acquire_without_cooldown_is_immediate(self):
        gate = CliRateGate(session_concurrent=2, worker_concurrent=2, min_spacing_ms=0)
        start = time.monotonic()
        await gate.acquire(is_worker=False)
        elapsed = time.monotonic() - start
        gate.release(is_worker=False)
        assert elapsed < 0.1

    async def test_note_rate_limit_sets_cooldown(self):
        gate = CliRateGate(session_concurrent=2, worker_concurrent=2, min_spacing_ms=0)
        # 2 seconds in the future.
        gate.note_rate_limit(time.time() + 2.0)
        start = time.monotonic()
        await gate.acquire(is_worker=False)
        elapsed = time.monotonic() - start
        gate.release(is_worker=False)
        # Cooldown + 10s buffer means we wait ~12s. Skip actually sleeping that
        # long in the test by clearing the cooldown after a short pause via
        # a background task: see the next test. Here we assert the cooldown
        # *was* set and that acquire blocked briefly before we cleared it.
        assert elapsed >= 1.9

    async def test_clear_cooldown_unblocks_acquire(self):
        gate = CliRateGate(session_concurrent=1, worker_concurrent=1, min_spacing_ms=0)
        # Hour-long cooldown — definitely blocks.
        gate.note_rate_limit(time.time() + 3600)

        async def _clear_soon():
            await asyncio.sleep(0.3)
            gate.clear_cooldown()

        clearer = asyncio.create_task(_clear_soon())
        start = time.monotonic()
        await gate.acquire(is_worker=True)
        elapsed = time.monotonic() - start
        gate.release(is_worker=True)
        await clearer
        # Must have waited at least until clear_cooldown fired.
        assert 0.25 <= elapsed < 2.0

    async def test_cooldown_only_extends_not_shortens(self):
        gate = CliRateGate(session_concurrent=1, worker_concurrent=1, min_spacing_ms=0)
        far = time.time() + 3600
        gate.note_rate_limit(far)
        deadline_before = gate._cooldown_until
        # A shorter cooldown should not shrink the existing window.
        gate.note_rate_limit(time.time() + 5)
        assert gate._cooldown_until == deadline_before

    async def test_missing_resets_at_falls_back_to_15min(self):
        gate = CliRateGate(session_concurrent=1, worker_concurrent=1, min_spacing_ms=0)
        gate.note_rate_limit(None)
        remaining = gate._cooldown_until - time.monotonic()
        # 15 minutes ± a few seconds of slop.
        assert 14 * 60 < remaining <= 15 * 60 + 5


# --- Retry wrapper in ClaudeCliBackend ---------------------------------------

class TestCallRetryLoop:
    """Exercise ``ClaudeCliBackend.call`` with a stubbed ``_call_once`` to
    verify the retry policy (transient/non-transient/cancel) without spawning
    real subprocesses."""

    async def test_success_on_first_attempt(self, monkeypatch):
        from app.services.llm import cli_backend as cb
        backend = cb.ClaudeCliBackend.__new__(cb.ClaudeCliBackend)
        backend.cli_path = "claude"
        backend._last_usage = {}
        backend._persistent_chats = {}

        calls = []

        async def fake_once(**kwargs):
            calls.append(kwargs)
            return cb._CallResult.success("hello", {"input_tokens": 1})

        monkeypatch.setattr(backend, "_call_once", fake_once)

        response, usage = await backend.call(
            model="sonnet", system="sys", messages=[{"role": "user", "content": "hi"}],
        )
        assert response == "hello"
        assert usage == {"input_tokens": 1}
        assert len(calls) == 1

    async def test_retries_transient_then_succeeds(self, monkeypatch):
        from app.services.llm import cli_backend as cb
        # Make backoff deterministic & fast.
        monkeypatch.setattr(cb, "compute_backoff", lambda attempt: 0.01)

        backend = cb.ClaudeCliBackend.__new__(cb.ClaudeCliBackend)
        backend.cli_path = "claude"
        backend._last_usage = {}
        backend._persistent_chats = {}

        attempts = {"n": 0}

        async def fake_once(**_):
            attempts["n"] += 1
            if attempts["n"] < 2:
                return cb._CallResult.error("[transient]", transient=True)
            return cb._CallResult.success("ok", {})

        monkeypatch.setattr(backend, "_call_once", fake_once)

        response, _ = await backend.call(
            model="sonnet", system="sys", messages=[{"role": "user", "content": "hi"}],
        )
        assert response == "ok"
        assert attempts["n"] == 2

    async def test_non_transient_does_not_retry(self, monkeypatch):
        from app.services.llm import cli_backend as cb
        monkeypatch.setattr(cb, "compute_backoff", lambda attempt: 0.01)

        backend = cb.ClaudeCliBackend.__new__(cb.ClaudeCliBackend)
        backend.cli_path = "claude"
        backend._last_usage = {}
        backend._persistent_chats = {}

        attempts = {"n": 0}

        async def fake_once(**_):
            attempts["n"] += 1
            return cb._CallResult.error("[fatal]", transient=False)

        monkeypatch.setattr(backend, "_call_once", fake_once)

        response, _ = await backend.call(
            model="sonnet", system="sys", messages=[{"role": "user", "content": "hi"}],
        )
        assert response == "[fatal]"
        assert attempts["n"] == 1

    async def test_cancel_stops_retry(self, monkeypatch):
        from app.services.llm import cli_backend as cb
        monkeypatch.setattr(cb, "compute_backoff", lambda attempt: 0.01)

        backend = cb.ClaudeCliBackend.__new__(cb.ClaudeCliBackend)
        backend.cli_path = "claude"
        backend._last_usage = {}
        backend._persistent_chats = {}

        attempts = {"n": 0}

        async def fake_once(**_):
            attempts["n"] += 1
            return cb._CallResult.cancel()

        monkeypatch.setattr(backend, "_call_once", fake_once)

        response, _ = await backend.call(
            model="sonnet", system="sys", messages=[{"role": "user", "content": "hi"}],
        )
        assert "cancelled" in response.lower()
        assert attempts["n"] == 1

    async def test_exhausts_retries_on_persistent_transient(self, monkeypatch):
        from app.services.llm import cli_backend as cb
        monkeypatch.setattr(cb, "compute_backoff", lambda attempt: 0.01)

        backend = cb.ClaudeCliBackend.__new__(cb.ClaudeCliBackend)
        backend.cli_path = "claude"
        backend._last_usage = {}
        backend._persistent_chats = {}

        attempts = {"n": 0}

        async def fake_once(**_):
            attempts["n"] += 1
            return cb._CallResult.error("[still broken]", transient=True)

        monkeypatch.setattr(backend, "_call_once", fake_once)

        response, _ = await backend.call(
            model="sonnet", system="sys", messages=[{"role": "user", "content": "hi"}],
        )
        assert response == "[still broken]"
        assert attempts["n"] == MAX_RETRIES + 1


# --- _extract_and_record_rate_limit ------------------------------------------

class TestExtractAndRecordRateLimit:
    def test_parses_whole_document_json(self, monkeypatch):
        """The non-streaming --output-format=json path yields a single object
        with an embedded rate_limit_info block."""
        from app.services.llm import cli_backend as cb

        recorded: list[float | None] = []

        class FakeGate:
            def note_rate_limit(self, resets_at):
                recorded.append(resets_at)

        monkeypatch.setattr(cb, "get_rate_gate", lambda: FakeGate())

        backend = cb.ClaudeCliBackend.__new__(cb.ClaudeCliBackend)
        payload = (
            '{"type":"result","result":"hi",'
            '"rate_limit_info":{"status":"rejected","resets_at":123456}}'
        )
        backend._extract_and_record_rate_limit(payload)
        assert recorded == [123456.0]

    def test_parses_stream_json_line_fallback(self, monkeypatch):
        from app.services.llm import cli_backend as cb

        recorded: list[float | None] = []

        class FakeGate:
            def note_rate_limit(self, resets_at):
                recorded.append(resets_at)

        monkeypatch.setattr(cb, "get_rate_gate", lambda: FakeGate())

        backend = cb.ClaudeCliBackend.__new__(cb.ClaudeCliBackend)
        payload = (
            '{"type":"assistant","message":{"content":[]}}\n'
            '{"type":"rate_limit_event","rate_limit_info":{"status":"rejected","resets_at":999}}\n'
            '{"type":"result","result":"ok"}\n'
        )
        backend._extract_and_record_rate_limit(payload)
        assert recorded == [999.0]

    def test_ignores_non_rejected(self, monkeypatch):
        from app.services.llm import cli_backend as cb

        recorded: list[float | None] = []

        class FakeGate:
            def note_rate_limit(self, resets_at):
                recorded.append(resets_at)

        monkeypatch.setattr(cb, "get_rate_gate", lambda: FakeGate())

        backend = cb.ClaudeCliBackend.__new__(cb.ClaudeCliBackend)
        backend._extract_and_record_rate_limit(
            '{"type":"result","rate_limit_info":{"status":"allowed_warning","resets_at":1}}'
        )
        assert recorded == []

    def test_empty_input_is_noop(self):
        from app.services.llm import cli_backend as cb
        backend = cb.ClaudeCliBackend.__new__(cb.ClaudeCliBackend)
        # Should not raise.
        backend._extract_and_record_rate_limit("")
        backend._extract_and_record_rate_limit("not json at all {")
