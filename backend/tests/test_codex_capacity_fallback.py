"""Tests for Codex CLI capacity-based model fallback chain.

The Codex backend's ``call()`` wraps a single attempt in a small loop that
walks ``_capacity_fallback_models(model)`` when the primary model returns a
"capacity"/"overloaded" error. These tests exercise that path with a stubbed
``_call_once`` (no real subprocess) so the policy is verified deterministically.
"""

from __future__ import annotations

import pytest

from app.services.llm import codex_backend as cb


# ---------------------------------------------------------------------------
# _capacity_fallback_models — pure helper
# ---------------------------------------------------------------------------


class TestCapacityFallbackModelsHelper:
    def test_excludes_current_model(self):
        chain = cb._capacity_fallback_models("gpt-5.4-mini")
        assert "gpt-5.4-mini" not in chain

    def test_includes_known_fallbacks(self):
        chain = cb._capacity_fallback_models("gpt-5.5")
        # Order matters: mini is preferred first to maximise throughput.
        assert chain[0] == "gpt-5.4-mini"
        assert "gpt-5.3-codex" in chain
        assert "gpt-5.2" in chain

    def test_unknown_model_returns_full_preferred_list(self):
        chain = cb._capacity_fallback_models("totally-made-up")
        assert chain == ["gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.4", "gpt-5.5", "gpt-5.2"]


# ---------------------------------------------------------------------------
# _is_capacity_error — pattern detection
# ---------------------------------------------------------------------------


class TestIsCapacityError:
    def test_selected_model_at_capacity(self):
        assert cb._is_capacity_error("Selected model is at capacity right now")

    def test_model_at_capacity(self):
        assert cb._is_capacity_error("The model is at capacity, please retry")

    def test_case_insensitive(self):
        assert cb._is_capacity_error("SELECTED MODEL IS AT CAPACITY")

    def test_unrelated_error_returns_false(self):
        assert not cb._is_capacity_error("connection reset by peer")
        assert not cb._is_capacity_error("invalid api key")

    def test_empty_string(self):
        assert not cb._is_capacity_error("")


# ---------------------------------------------------------------------------
# call() — fallback walk + thread_id preservation
# ---------------------------------------------------------------------------


def _make_backend(known_thread: dict | None = None) -> cb.CodexCliBackend:
    """Build a bare CodexCliBackend without invoking __init__ side effects."""
    backend = cb.CodexCliBackend.__new__(cb.CodexCliBackend)
    backend._configured_cli_path = "codex"
    backend._last_usage = {}
    backend._last_thread_id = ""
    backend._thread_ids_by_chat = dict(known_thread or {})
    return backend


class TestCodexCapacityFallback:
    async def test_success_on_first_attempt_skips_fallback(self, monkeypatch):
        backend = _make_backend()
        attempts: list[str] = []

        async def fake_once(**kwargs):
            attempts.append(kwargs["model"])
            return cb.CodexCallResult.success("ok", {"input_tokens": 3})

        monkeypatch.setattr(backend, "_call_once", fake_once)
        # Sleep would normally throttle inter-attempt; collapse it for speed.
        monkeypatch.setattr(cb.asyncio, "sleep", _no_sleep)

        response, usage = await backend.call(
            model="gpt-5.5",
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert response == "ok"
        assert usage == {"input_tokens": 3}
        assert attempts == ["gpt-5.5"]

    async def test_capacity_error_walks_to_first_fallback(self, monkeypatch):
        backend = _make_backend()
        attempts: list[str] = []

        async def fake_once(**kwargs):
            attempts.append(kwargs["model"])
            if kwargs["model"] == "gpt-5.5":
                return cb.CodexCallResult.error(
                    "[Codex CLI error: selected model is at capacity]"
                )
            return cb.CodexCallResult.success("recovered", {})

        monkeypatch.setattr(backend, "_call_once", fake_once)
        monkeypatch.setattr(cb.asyncio, "sleep", _no_sleep)

        response, _usage = await backend.call(
            model="gpt-5.5",
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert response == "recovered"
        # Primary then first preferred fallback (mini).
        assert attempts == ["gpt-5.5", "gpt-5.4-mini"]

    async def test_non_capacity_error_does_not_walk(self, monkeypatch):
        backend = _make_backend()
        attempts: list[str] = []

        async def fake_once(**kwargs):
            attempts.append(kwargs["model"])
            return cb.CodexCallResult.error("[Codex CLI error: invalid api key]")

        monkeypatch.setattr(backend, "_call_once", fake_once)
        monkeypatch.setattr(cb.asyncio, "sleep", _no_sleep)

        response, _ = await backend.call(
            model="gpt-5.5",
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
        )
        assert "invalid api key" in response
        assert attempts == ["gpt-5.5"]  # no retry

    async def test_capacity_chain_caps_at_three_attempts(self, monkeypatch):
        backend = _make_backend()
        attempts: list[str] = []

        async def fake_once(**kwargs):
            attempts.append(kwargs["model"])
            return cb.CodexCallResult.error(
                "[Codex CLI error: selected model is at capacity]"
            )

        monkeypatch.setattr(backend, "_call_once", fake_once)
        monkeypatch.setattr(cb.asyncio, "sleep", _no_sleep)

        response, _ = await backend.call(
            model="gpt-5.5",
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
        )
        # Implementation slices fallback_models[:3] → at most 3 attempts.
        assert len(attempts) == 3
        assert attempts[0] == "gpt-5.5"
        # Last response is still the capacity error string.
        assert "capacity" in response.lower()

    async def test_thread_id_preserved_across_fallback_for_chat(self, monkeypatch):
        """A chat with a previously-stored thread_id should resume the same
        thread on every capacity-fallback attempt — never start a fresh one."""
        backend = _make_backend({"chat-1": "thread-XYZ"})
        seen_threads: list[str] = []

        async def fake_once(**kwargs):
            seen_threads.append(kwargs["resume_thread_id"])
            if len(seen_threads) == 1:
                return cb.CodexCallResult.error(
                    "[Codex CLI error: selected model is at capacity]"
                )
            return cb.CodexCallResult.success("ok", {})

        monkeypatch.setattr(backend, "_call_once", fake_once)
        monkeypatch.setattr(cb.asyncio, "sleep", _no_sleep)

        await backend.call(
            model="gpt-5.5",
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            chat_id="chat-1",
            session_type="chat",
        )
        assert seen_threads == ["thread-XYZ", "thread-XYZ"]

    async def test_worker_calls_never_resume_thread(self, monkeypatch):
        """Workers must not piggy-back on a chat's thread_id, even on retry."""
        backend = _make_backend({"chat-1": "thread-XYZ"})
        seen_threads: list[str] = []

        async def fake_once(**kwargs):
            seen_threads.append(kwargs["resume_thread_id"])
            if len(seen_threads) == 1:
                return cb.CodexCallResult.error(
                    "[Codex CLI error: selected model is at capacity]"
                )
            return cb.CodexCallResult.success("ok", {})

        monkeypatch.setattr(backend, "_call_once", fake_once)
        monkeypatch.setattr(cb.asyncio, "sleep", _no_sleep)

        await backend.call(
            model="gpt-5.5",
            system="sys",
            messages=[{"role": "user", "content": "hi"}],
            chat_id="chat-1",
            session_type="worker",
            task_id="task-A",
        )
        assert seen_threads == ["", ""]


async def _no_sleep(_seconds):  # pragma: no cover - trivial helper
    """Replacement for asyncio.sleep to keep tests instantaneous."""
    return None
