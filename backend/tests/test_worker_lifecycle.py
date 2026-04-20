"""Worker lifecycle — regression tests

Covers the strict claim → work → complete protocol enforced by:
- `WorkerSupervisor` (state machine)
- `handle_worker_claim` / `handle_worker_complete` MCP handlers (validation)
- `DeepWorkerPool` ambient worker-event buffer (replaces the old dispatcher
  callback path — worker completions no longer re-enter the dispatcher as a
  turn).

Invariant from CLAUDE.md: workers must claim first and deliver a structured
completion; any other code path (legacy task.complete / auto / closeout) must
still produce the same payload shape downstream.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.worker_supervisor import (
    WorkerSupervisor,
    handle_task_complete,
    handle_worker_claim,
    handle_worker_complete,
    _MIN_SUMMARY_CHARS,
)


# ---------------------------------------------------------------------------
# Supervisor state machine
# ---------------------------------------------------------------------------

def test_register_starts_in_spawned_phase():
    sup = WorkerSupervisor()
    sup.register_task("T1")
    state = sup.get_status("T1")
    assert state["phase"] == "spawned"
    assert state["status"] == "active"
    assert sup.is_claimed("T1") is False
    assert sup.is_structured_complete("T1") is False
    assert sup.get_completion_payload("T1") is None


def test_claim_transitions_to_claimed_phase():
    sup = WorkerSupervisor()
    sup.register_task("T1")
    sup.mark_claimed("T1", "Read the artifact and summarize it.")
    assert sup.is_claimed("T1") is True
    state = sup.get_status("T1")
    assert state["phase"] == "claimed"
    assert state["claim_plan"].startswith("Read the artifact")
    assert state["claimed_at"] is not None


def test_tool_calls_since_register_counts_only_recorded_calls():
    sup = WorkerSupervisor()
    sup.register_task("T1")
    assert sup.tool_calls_since_register("T1") == 0
    sup.record_tool_call("T1", "file.read", {"path": "x"})
    sup.record_tool_call("T1", "file.read", {"path": "y"})
    assert sup.tool_calls_since_register("T1") == 2
    # Unknown task returns 0, never raises.
    assert sup.tool_calls_since_register("unknown") == 0


def test_structured_complete_happy_path():
    sup = WorkerSupervisor()
    sup.register_task("T1")
    sup.mark_claimed("T1", "plan")
    sup.mark_completed(
        "T1",
        summary="Did the thing and verified it worked.",
        status="success",
        findings=["finding A", "finding B"],
        pointers=[{"label": "diff", "offset": 0, "length": 500}],
        next_step="Run the test suite.",
        source="worker.complete",
    )
    assert sup.is_structured_complete("T1") is True
    payload = sup.get_completion_payload("T1")
    assert payload["status"] == "success"
    assert payload["summary"].startswith("Did the thing")
    assert payload["findings"] == ["finding A", "finding B"]
    assert payload["pointers"][0]["label"] == "diff"
    assert payload["next_step"] == "Run the test suite."
    assert payload["plan"] == "plan"


def test_legacy_task_complete_not_flagged_as_structured():
    """task.complete / auto / closeout must NOT register as structured."""
    sup = WorkerSupervisor()
    sup.register_task("T1")
    sup.mark_completed("T1", "a legacy summary of sorts", source="task.complete")
    assert sup.is_structured_complete("T1") is False
    # But the payload is still available (uniform shape downstream).
    payload = sup.get_completion_payload("T1")
    assert payload is not None
    assert payload["summary"].startswith("a legacy")

    sup.register_task("T2")
    sup.mark_completed("T2", "auto-synthesized", source="auto")
    assert sup.is_structured_complete("T2") is False


# ---------------------------------------------------------------------------
# worker.claim handler validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_claim_requires_task_id_and_plan(monkeypatch):
    from app.services import worker_supervisor as ws_mod

    fresh = WorkerSupervisor()
    monkeypatch.setattr(ws_mod, "_supervisor", fresh)
    fresh.register_task("T1")

    r = await handle_worker_claim({"plan": "do x"})
    assert r["success"] is False and "task_id" in r["error"]

    r = await handle_worker_claim({"task_id": "T1"})
    assert r["success"] is False and "plan" in r["error"]

    r = await handle_worker_claim({"task_id": "T1", "plan": "   "})
    assert r["success"] is False and "plan" in r["error"]

    r = await handle_worker_claim({"task_id": "T1", "plan": "A real plan."})
    assert r["success"] is True
    assert fresh.is_claimed("T1") is True


# ---------------------------------------------------------------------------
# worker.complete handler validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_worker_complete_rejects_short_or_empty_summary(monkeypatch):
    from app.services import worker_supervisor as ws_mod

    fresh = WorkerSupervisor()
    monkeypatch.setattr(ws_mod, "_supervisor", fresh)
    fresh.register_task("T1")
    fresh.mark_claimed("T1", "plan")

    r = await handle_worker_complete({"task_id": "T1", "status": "success", "summary": ""})
    assert r["success"] is False and "summary" in r["error"]

    r = await handle_worker_complete({"task_id": "T1", "status": "success", "summary": "ok"})
    assert r["success"] is False
    assert f"<{_MIN_SUMMARY_CHARS}" in r["error"]

    # Still not completed — short summaries never mark the task.
    assert fresh.is_structured_complete("T1") is False


@pytest.mark.asyncio
async def test_worker_complete_rejects_invalid_status(monkeypatch):
    from app.services import worker_supervisor as ws_mod

    fresh = WorkerSupervisor()
    monkeypatch.setattr(ws_mod, "_supervisor", fresh)
    fresh.register_task("T1")
    fresh.mark_claimed("T1", "plan")

    r = await handle_worker_complete({
        "task_id": "T1", "status": "completed",  # not in enum
        "summary": "a real summary that is long enough",
    })
    assert r["success"] is False and "status" in r["error"]


@pytest.mark.asyncio
async def test_worker_complete_happy_path_marks_structured(monkeypatch):
    from app.services import worker_supervisor as ws_mod

    fresh = WorkerSupervisor()
    monkeypatch.setattr(ws_mod, "_supervisor", fresh)
    fresh.register_task("T1")
    fresh.mark_claimed("T1", "plan")

    r = await handle_worker_complete({
        "task_id": "T1",
        "status": "success",
        "summary": "Implemented the feature and added tests; everything green.",
        "findings": ["added X", "verified Y", {"text": "coerced from dict"}],
        "pointers": [
            {"label": "diff", "offset": 0, "length": 500},
            {"label": "noop"},  # no offset/length — accepted
            "invalid",          # dropped
        ],
        "next_step": "Restart the backend to pick up the change.",
    })
    assert r["success"] is True
    payload = fresh.get_completion_payload("T1")
    assert payload["findings"] == ["added X", "verified Y", "coerced from dict"]
    labels = [p["label"] for p in payload["pointers"]]
    assert "diff" in labels and "noop" in labels
    assert fresh.is_structured_complete("T1") is True


@pytest.mark.asyncio
async def test_worker_complete_accepts_without_prior_claim(monkeypatch):
    """Skipping claim logs a warning but does not block completion."""
    from app.services import worker_supervisor as ws_mod

    fresh = WorkerSupervisor()
    monkeypatch.setattr(ws_mod, "_supervisor", fresh)
    fresh.register_task("T1")

    r = await handle_worker_complete({
        "task_id": "T1",
        "status": "success",
        "summary": "Completed without calling claim first — still works.",
    })
    assert r["success"] is True
    assert fresh.is_structured_complete("T1") is True


@pytest.mark.asyncio
async def test_legacy_task_complete_still_works(monkeypatch):
    from app.services import worker_supervisor as ws_mod

    fresh = WorkerSupervisor()
    monkeypatch.setattr(ws_mod, "_supervisor", fresh)
    fresh.register_task("T1")

    r = await handle_task_complete({
        "task_id": "T1", "status": "success",
        "summary": "legacy path",
    })
    assert r["success"] is True
    # Legacy must not count as structured — that triggers the closeout upgrade path.
    assert fresh.is_structured_complete("T1") is False
    assert fresh.get_status("T1")["completion_source"] == "task.complete"


# ---------------------------------------------------------------------------
# Ambient worker-event buffer (turn isolation)
#
# Worker completions no longer re-trigger the dispatcher. Instead they're
# recorded against the dispatcher_chat_id and drained on the next real turn.
# ---------------------------------------------------------------------------

from collections import deque


def _make_pool_for_events():
    """Build a bare DeepWorkerPool with the buffers a unit test needs."""
    from app.services.orchestration.worker_pool import DeepWorkerPool

    pool = DeepWorkerPool.__new__(DeepWorkerPool)
    pool._worker_events = {}
    pool._MAX_WORKER_EVENTS_PER_CHAT = 20
    pool._active_tasks = {}
    pool._task_meta = {}
    pool._stopped = False
    pool._ws = None
    pool._orchestrator = None
    return pool


def test_record_worker_event_stores_completion():
    pool = _make_pool_for_events()
    pool.record_worker_event(
        "chat-1",
        task_id="T1", intent="refactor auth",
        status="success", summary_line="Rewrote login handler.",
    )
    buf = pool._worker_events["chat-1"]
    assert len(buf) == 1
    ev = buf[0]
    assert ev["task_id"] == "T1"
    assert ev["intent"] == "refactor auth"
    assert ev["status"] == "success"
    assert ev["summary_line"] == "Rewrote login handler."
    assert isinstance(ev["finished_at"], float)


def test_record_worker_event_ignores_empty_chat_id():
    pool = _make_pool_for_events()
    pool.record_worker_event(
        "", task_id="T1", intent="x", status="success", summary_line="s",
    )
    pool.record_worker_event(
        None, task_id="T2", intent="x", status="success", summary_line="s",
    )
    assert pool._worker_events == {}


def test_record_worker_event_caps_per_chat_oldest_dropped():
    pool = _make_pool_for_events()
    pool._MAX_WORKER_EVENTS_PER_CHAT = 3
    for i in range(5):
        pool.record_worker_event(
            "chat-1", task_id=f"T{i}", intent="x",
            status="success", summary_line=f"summary {i}",
        )
    tids = [ev["task_id"] for ev in pool._worker_events["chat-1"]]
    # Oldest two dropped (deque maxlen).
    assert tids == ["T2", "T3", "T4"]


def test_drain_worker_events_pops_in_order_and_clears_chat():
    pool = _make_pool_for_events()
    for i in range(3):
        pool.record_worker_event(
            "chat-1", task_id=f"T{i}", intent="x",
            status="success", summary_line=f"s{i}",
        )
    out = pool.drain_worker_events("chat-1")
    assert [ev["task_id"] for ev in out] == ["T0", "T1", "T2"]
    # Chat key removed once empty so subsequent turns don't see stale data.
    assert "chat-1" not in pool._worker_events


def test_drain_worker_events_respects_max_items():
    pool = _make_pool_for_events()
    for i in range(5):
        pool.record_worker_event(
            "chat-1", task_id=f"T{i}", intent="x",
            status="success", summary_line=f"s{i}",
        )
    out = pool.drain_worker_events("chat-1", max_items=2)
    assert [ev["task_id"] for ev in out] == ["T0", "T1"]
    # Remainder stays for the next turn.
    assert len(pool._worker_events["chat-1"]) == 3


def test_drain_worker_events_empty_for_unknown_chat():
    pool = _make_pool_for_events()
    assert pool.drain_worker_events("nothing-here") == []


def test_record_worker_event_is_per_chat():
    pool = _make_pool_for_events()
    pool.record_worker_event(
        "chat-A", task_id="T1", intent="x", status="success", summary_line="a",
    )
    pool.record_worker_event(
        "chat-B", task_id="T2", intent="x", status="success", summary_line="b",
    )
    assert [ev["task_id"] for ev in pool.drain_worker_events("chat-A")] == ["T1"]
    assert [ev["task_id"] for ev in pool.drain_worker_events("chat-B")] == ["T2"]


def test_count_active_for_chat_matches_dispatcher_id():
    pool = _make_pool_for_events()
    pool._task_meta = {
        "T1": {"dispatcher_chat_id": "chat-A"},
        "T2": {"dispatcher_chat_id": "chat-A"},
        "T3": {"dispatcher_chat_id": "chat-B"},
        "T4": {},  # no dispatcher_chat_id
    }
    # Only tasks in _active_tasks count — T4 excluded on purpose.
    pool._active_tasks = {"T1": object(), "T2": object(), "T3": object(), "T4": object()}
    assert pool.count_active_for_chat("chat-A") == 2
    assert pool.count_active_for_chat("chat-B") == 1
    assert pool.count_active_for_chat("chat-C") == 0
    assert pool.count_active_for_chat("") == 0


def test_record_worker_event_truncates_long_summary_line():
    pool = _make_pool_for_events()
    pool.record_worker_event(
        "chat-1", task_id="T1", intent="x",
        status="success", summary_line="a" * 500,
    )
    ev = pool._worker_events["chat-1"][0]
    # 200-char cap prevents any single completion from blowing up the block.
    assert len(ev["summary_line"]) == 200


# ---------------------------------------------------------------------------
# Debounced dispatcher callback
#
# Workers no longer hand full results back to the dispatcher — they only
# re-enter the dispatcher turn with a thin signal (the ambient worker-events
# block). Multiple completions for the same chat within the debounce window
# must coalesce into ONE callback turn so 10 parallel workers don't produce
# 10 dispatcher re-entries.
# ---------------------------------------------------------------------------

import asyncio
from unittest.mock import AsyncMock, MagicMock


def _make_pool_for_callbacks(orchestrator=None, ws=None, debounce=0.05):
    """Bare DeepWorkerPool wired for callback unit tests."""
    from app.services.orchestration.worker_pool import DeepWorkerPool

    pool = DeepWorkerPool.__new__(DeepWorkerPool)
    pool._worker_events = {}
    pool._MAX_WORKER_EVENTS_PER_CHAT = 20
    pool._active_tasks = {}
    pool._task_meta = {}
    pool._stopped = False
    pool._ws = ws
    pool._orchestrator = orchestrator
    pool._callback_debouncers = {}
    pool._CALLBACK_DEBOUNCE_SECONDS = debounce
    return pool


def _fake_orchestrator(max_depth=5):
    """Mock orchestrator with an AsyncMock handle_message + configured depth cap."""
    orch = MagicMock()
    orch.MAX_CALLBACK_DEPTH = max_depth
    orch.handle_message = AsyncMock(return_value=[])
    return orch


def _fake_live_ws():
    from starlette.websockets import WebSocketState
    ws = MagicMock()
    ws.client_state = WebSocketState.CONNECTED
    return ws


def _make_event(task_id="T1", chat_id="chat-1", callback_depth=0):
    from app.services.event_bus import ActionIntent
    return ActionIntent(
        task_id=task_id,
        intent_type="complex",
        intent="do stuff",
        summary="...",
        session_id="sess-1",
        model="fast",
        data={
            "dispatcher_chat_id": chat_id,
            "project_id": "proj-1",
            "chat_level": "project",
        },
        callback_depth=callback_depth,
    )


@pytest.mark.asyncio
async def test_callback_fires_once_after_debounce(monkeypatch):
    monkeypatch.setenv("DISPATCHER_WORKER_CALLBACK", "1")
    orch = _fake_orchestrator()
    pool = _make_pool_for_callbacks(orchestrator=orch, ws=_fake_live_ws())
    event = _make_event()

    pool._schedule_dispatcher_callback("chat-1", event)
    # Debounce is 0.05s — wait a bit longer than that.
    await asyncio.sleep(0.15)

    orch.handle_message.assert_awaited_once()
    kwargs = orch.handle_message.await_args.kwargs
    assert kwargs["chat_id"] == "chat-1"
    assert kwargs["is_callback"] is True
    assert kwargs["callback_depth"] == 0
    # Debouncer bookkeeping is cleared after firing.
    assert "chat-1" not in pool._callback_debouncers


@pytest.mark.asyncio
async def test_callback_coalesces_burst_into_one_turn(monkeypatch):
    """Five worker completions for the same chat within the debounce window
    must produce exactly ONE dispatcher callback turn."""
    monkeypatch.setenv("DISPATCHER_WORKER_CALLBACK", "1")
    orch = _fake_orchestrator()
    pool = _make_pool_for_callbacks(orchestrator=orch, ws=_fake_live_ws(), debounce=0.1)

    for i in range(5):
        pool._schedule_dispatcher_callback("chat-1", _make_event(task_id=f"T{i}"))
        await asyncio.sleep(0.02)  # well under debounce (0.1s)

    # At this point all 5 scheduling calls re-armed the same timer.
    await asyncio.sleep(0.2)

    assert orch.handle_message.await_count == 1


@pytest.mark.asyncio
async def test_callback_skipped_at_depth_cap(monkeypatch):
    monkeypatch.setenv("DISPATCHER_WORKER_CALLBACK", "1")
    orch = _fake_orchestrator(max_depth=5)
    pool = _make_pool_for_callbacks(orchestrator=orch, ws=_fake_live_ws())

    pool._schedule_dispatcher_callback("chat-1", _make_event(callback_depth=5))
    await asyncio.sleep(0.15)

    orch.handle_message.assert_not_awaited()
    assert pool._callback_debouncers == {}


@pytest.mark.asyncio
async def test_callback_skipped_when_ws_dead(monkeypatch):
    from starlette.websockets import WebSocketState
    monkeypatch.setenv("DISPATCHER_WORKER_CALLBACK", "1")

    dead_ws = MagicMock()
    dead_ws.client_state = WebSocketState.DISCONNECTED
    orch = _fake_orchestrator()
    pool = _make_pool_for_callbacks(orchestrator=orch, ws=dead_ws)

    pool._schedule_dispatcher_callback("chat-1", _make_event())
    await asyncio.sleep(0.15)

    # pending_store / ambient-event block handles this case; no headless model call.
    orch.handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_disabled_via_env(monkeypatch):
    monkeypatch.setenv("DISPATCHER_WORKER_CALLBACK", "0")
    orch = _fake_orchestrator()
    pool = _make_pool_for_callbacks(orchestrator=orch, ws=_fake_live_ws())

    pool._schedule_dispatcher_callback("chat-1", _make_event())
    await asyncio.sleep(0.15)

    orch.handle_message.assert_not_awaited()
    assert pool._callback_debouncers == {}


@pytest.mark.asyncio
async def test_callback_debouncers_cancelled_on_stop(monkeypatch):
    """A pending debouncer must not survive pool shutdown and fire a
    headless model call against a torn-down orchestrator."""
    monkeypatch.setenv("DISPATCHER_WORKER_CALLBACK", "1")
    orch = _fake_orchestrator()
    pool = _make_pool_for_callbacks(orchestrator=orch, ws=_fake_live_ws(), debounce=5.0)

    pool._schedule_dispatcher_callback("chat-1", _make_event())
    assert "chat-1" in pool._callback_debouncers
    deb = pool._callback_debouncers["chat-1"]

    # Inline the cancel behavior from pool.stop() without touching the bus.
    pool._stopped = True
    for _, t in list(pool._callback_debouncers.items()):
        if not t.done():
            t.cancel()
    pool._callback_debouncers.clear()

    with pytest.raises(asyncio.CancelledError):
        await deb
    orch.handle_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_parallel_chats_do_not_coalesce(monkeypatch):
    """Debounce is per-chat: two independent chats each get their own turn."""
    monkeypatch.setenv("DISPATCHER_WORKER_CALLBACK", "1")
    orch = _fake_orchestrator()
    pool = _make_pool_for_callbacks(orchestrator=orch, ws=_fake_live_ws())

    pool._schedule_dispatcher_callback("chat-A", _make_event(chat_id="chat-A"))
    pool._schedule_dispatcher_callback("chat-B", _make_event(chat_id="chat-B"))
    await asyncio.sleep(0.15)

    assert orch.handle_message.await_count == 2
    chats = {call.kwargs["chat_id"] for call in orch.handle_message.await_args_list}
    assert chats == {"chat-A", "chat-B"}
