import os
import sys
from collections import deque
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

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
