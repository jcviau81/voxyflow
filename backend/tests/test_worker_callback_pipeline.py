import asyncio
import os
import sys
from contextlib import suppress
from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.chat_orchestration import ChatOrchestrator
from app.services.orchestration.layer_runners import LayerRunnersMixin
from app.services.orchestration.worker_pool import DeepWorkerPool


class _FakeClaude:
    def __init__(self, tokens):
        self.fast_model = "fast-test"
        self.deep_model = "deep-test"
        self._tokens = tokens

    async def chat_fast_stream(self, **kwargs):
        for token in self._tokens:
            yield token

    def consume_last_chat_usage(self, chat_id: str, layer: str):
        return None


class _Runner(LayerRunnersMixin):
    pass


def _make_pool():
    pool = DeepWorkerPool.__new__(DeepWorkerPool)
    pool._worker_events = {}
    pool._MAX_WORKER_EVENTS_PER_CHAT = 20
    pool._active_tasks = {}
    pool._task_meta = {}
    pool._stopped = False
    pool._ws = None
    pool._orchestrator = None
    return pool


def _make_runner(pool, tokens):
    runner = _Runner()
    runner._claude = _FakeClaude(tokens)
    runner._worker_pools = {"sess-1": pool}
    runner._handle_tool_call_fallback = AsyncMock()
    return runner


def _record_events(pool, count=1):
    for i in range(count):
        pool.record_worker_event(
            "chat-1",
            task_id=f"T{i}",
            intent="worker task",
            status="success",
            summary_line=f"summary {i}",
            completion={"status": "success", "summary": f"summary {i}"},
        )


def test_peek_does_not_consume():
    pool = _make_pool()
    _record_events(pool, count=2)

    first = pool.peek_worker_events("chat-1")
    second = pool.peek_worker_events("chat-1")

    assert [ev["task_id"] for ev in first] == ["T0", "T1"]
    assert [ev["task_id"] for ev in second] == ["T0", "T1"]
    assert len(pool._worker_events["chat-1"]) == 2


def test_ack_consumes_n_items():
    pool = _make_pool()
    _record_events(pool, count=5)

    peeked = pool.peek_worker_events("chat-1")
    assert len(peeked) == 5

    pool.ack_worker_events("chat-1", count=3)

    remaining = pool.peek_worker_events("chat-1")
    assert [ev["task_id"] for ev in remaining] == ["T3", "T4"]


@pytest.mark.asyncio
async def test_silent_callback_preserves_events(monkeypatch):
    pool = _make_pool()
    _record_events(pool, count=1)
    runner = _make_runner(pool, ["[SILENT]"])
    send_model_status = AsyncMock()
    websocket = MagicMock()
    send_and_fanout = AsyncMock()

    monkeypatch.setattr(
        "app.services.orchestration.layer_runners.ws_broadcast.send_and_fanout_chat",
        send_and_fanout,
    )

    ok = await runner._run_fast_layer(
        websocket=websocket,
        content="worker finished",
        message_id="msg-1",
        chat_id="chat-1",
        workspace_name=None,
        workspace_id=None,
        chat_level="workspace",
        project_context=None,
        card_context=None,
        project_names=[],
        session_id="sess-1",
        send_model_status=send_model_status,
        is_callback=True,
    )

    assert ok is True
    assert [ev["task_id"] for ev in pool.peek_worker_events("chat-1")] == ["T0"]
    send_and_fanout.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_callback_acks_events(monkeypatch):
    pool = _make_pool()
    _record_events(pool, count=1)
    runner = _make_runner(pool, ["Callback delivered."])
    send_model_status = AsyncMock()
    websocket = MagicMock()
    send_and_fanout = AsyncMock()

    monkeypatch.setattr(
        "app.services.orchestration.layer_runners.ws_broadcast.send_and_fanout_chat",
        send_and_fanout,
    )

    ok = await runner._run_fast_layer(
        websocket=websocket,
        content="worker finished",
        message_id="msg-1",
        chat_id="chat-1",
        workspace_name=None,
        workspace_id=None,
        chat_level="workspace",
        project_context=None,
        card_context=None,
        project_names=[],
        session_id="sess-1",
        send_model_status=send_model_status,
        is_callback=True,
    )

    assert ok is True
    assert pool.peek_worker_events("chat-1") == []
    assert send_and_fanout.await_count == 2
    assert send_and_fanout.await_args_list[-1].args[2] == "chat:response"
    assert send_and_fanout.await_args_list[-1].args[3]["done"] is True


@pytest.mark.asyncio
async def test_stale_callback_suppresses_buffered_response(monkeypatch):
    pool = _make_pool()
    _record_events(pool, count=1)
    runner = _make_runner(pool, ["Late callback."])
    runner.is_turn_current = MagicMock(return_value=False)
    send_model_status = AsyncMock()
    websocket = MagicMock()
    send_and_fanout = AsyncMock()

    monkeypatch.setattr(
        "app.services.orchestration.layer_runners.ws_broadcast.send_and_fanout_chat",
        send_and_fanout,
    )

    ok = await runner._run_fast_layer(
        websocket=websocket,
        content="worker finished",
        message_id="msg-1",
        chat_id="chat-1",
        workspace_name=None,
        workspace_id=None,
        chat_level="workspace",
        project_context=None,
        card_context=None,
        project_names=[],
        session_id="sess-1",
        send_model_status=send_model_status,
        is_callback=True,
        turn_generation=1,
    )

    assert ok is True
    send_and_fanout.assert_not_awaited()
    assert [ev["task_id"] for ev in pool.peek_worker_events("chat-1")] == ["T0"]


@pytest.mark.asyncio
async def test_stale_user_response_suppresses_before_first_token(monkeypatch):
    pool = _make_pool()
    runner = _make_runner(pool, ["Late user response."])
    runner.is_turn_current = MagicMock(return_value=False)
    send_model_status = AsyncMock()
    websocket = MagicMock()
    send_and_fanout = AsyncMock()

    monkeypatch.setattr(
        "app.services.orchestration.layer_runners.ws_broadcast.send_and_fanout_chat",
        send_and_fanout,
    )

    ok = await runner._run_fast_layer(
        websocket=websocket,
        content="old question",
        message_id="msg-old",
        chat_id="chat-1",
        workspace_name=None,
        workspace_id=None,
        chat_level="workspace",
        project_context=None,
        card_context=None,
        project_names=[],
        session_id="sess-1",
        send_model_status=send_model_status,
        is_callback=False,
        turn_generation=1,
    )

    assert ok is True
    send_and_fanout.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_turn_cancels_in_flight_callback_lock_holder(monkeypatch):
    claude = _FakeClaude([])
    orch = ChatOrchestrator(claude)
    callback_started = asyncio.Event()
    user_finished = asyncio.Event()

    async def fake_inner(**kwargs):
        if kwargs["is_callback"]:
            callback_started.set()
            await asyncio.sleep(10)
        user_finished.set()
        return []

    monkeypatch.setattr(orch, "_handle_message_inner", fake_inner)

    callback_task = asyncio.create_task(
        orch.handle_message(
            websocket=MagicMock(),
            content="[worker-callback]",
            message_id="wcb-1",
            chat_id="chat-1",
            workspace_id=None,
            is_callback=True,
            session_id="sess-1",
        )
    )
    await asyncio.wait_for(callback_started.wait(), timeout=1)

    result = await asyncio.wait_for(
        orch.handle_message(
            websocket=MagicMock(),
            content="are you locked?",
            message_id="user-1",
            chat_id="chat-1",
            workspace_id=None,
            is_callback=False,
            session_id="sess-1",
        ),
        timeout=1,
    )

    assert result == []
    assert user_finished.is_set()
    with suppress(asyncio.CancelledError):
        await callback_task
    assert callback_task.cancelled() or callback_task.done()


# ---------------------------------------------------------------------------
# Synthetic dispatcher prompts ([worker-callback] / [SYSTEM: Direct action])
# must be tagged + filtered so persisted history stays clean.
# ---------------------------------------------------------------------------

def test_is_synthetic_prompt_matches_orchestrator_prefixes():
    from app.services.claude_service import _is_synthetic_prompt

    assert _is_synthetic_prompt(
        "[worker-callback] Workers finished — see Worker activity block."
    )
    assert _is_synthetic_prompt(
        "[SYSTEM: Direct action 'card.list' completed. Present the information.]"
    )
    # Real user turns are never synthetic — even bracketed ones.
    assert not _is_synthetic_prompt("Hello, list my cards")
    assert not _is_synthetic_prompt("[SYSTEM design] review my doc")
    assert not _is_synthetic_prompt("")


def test_get_history_filters_synthetic_user_turns(monkeypatch):
    """Reloaded history must drop orchestrator-injected pseudo-user turns."""
    import app.services.claude_service as cs

    stored = [
        {"role": "user", "content": "real question", "timestamp": "t1"},
        {"role": "assistant", "content": "spawning a worker", "timestamp": "t2"},
        {"role": "user", "content": "[worker-callback] Workers finished — see Worker activity block.", "timestamp": "t3"},
        {"role": "assistant", "content": "worker summary", "timestamp": "t4"},
    ]
    monkeypatch.setattr(
        cs.session_store, "get_history_for_claude", lambda chat_id, limit=20: list(stored)
    )

    svc = cs.ClaudeService.__new__(cs.ClaudeService)
    svc._histories = {}
    history = svc.get_history("chat-synth")

    contents = [m["content"] for m in history]
    assert "[worker-callback] Workers finished — see Worker activity block." not in contents
    assert contents == ["real question", "spawning a worker", "worker summary"]
