"""Worker lifecycle — regression tests

Covers the strict claim → work → complete protocol enforced by:
- `WorkerSupervisor` (state machine)
- `handle_worker_claim` / `handle_worker_complete` MCP handlers (validation)
- `DeepWorkerPool._build_dispatcher_callback` (structured render)
- `DeepWorkerPool._clip_against_recent_bursts` (60s rolling burst cap)

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
# Dispatcher callback rendering
# ---------------------------------------------------------------------------

def _make_pool_for_rendering():
    """Build a DeepWorkerPool with the minimum needed for render helpers."""
    from app.services.orchestration.worker_pool import DeepWorkerPool

    pool = DeepWorkerPool.__new__(DeepWorkerPool)
    pool._recent_callback_chars = {}
    return pool


def test_build_dispatcher_callback_structured_payload():
    pool = _make_pool_for_rendering()
    payload = {
        "status": "success",
        "summary": "Wrote the migration and ran it in staging.",
        "findings": ["added table foo", "backfilled 50k rows"],
        "pointers": [{"label": "full log", "offset": 0, "length": 2000}],
        "next_step": "Monitor pg locks for 10 minutes.",
    }
    msg = pool._build_dispatcher_callback(
        task_id="T1",
        intent="migrate schema",
        payload=payload,
        artifact_path="/tmp/x.txt",
        raw_len=12345,
        fallback_text="raw",
    )
    assert "status: success" in msg
    assert "## Summary" in msg
    assert "Wrote the migration" in msg
    assert "## Key findings" in msg
    assert "added table foo" in msg
    assert "## Detail pointers" in msg
    assert 'voxyflow.workers.read_artifact(task_id="T1"' in msg
    assert "offset=0" in msg and "length=2000" in msg
    assert "## Worker's suggested next step" in msg


def test_build_dispatcher_callback_falls_back_to_raw_when_no_payload():
    pool = _make_pool_for_rendering()
    msg = pool._build_dispatcher_callback(
        task_id="T1",
        intent="do thing",
        payload=None,
        artifact_path="/tmp/x.txt",
        raw_len=200,
        fallback_text="raw output here",
    )
    assert "--- Worker Result ---" in msg
    assert "raw output here" in msg


def test_build_dispatcher_callback_respects_hard_cap():
    from app.services.orchestration import worker_pool as wp
    pool = _make_pool_for_rendering()
    huge_summary = "x" * (wp.MAX_DISPATCHER_PAYLOAD_CHARS + 5_000)
    payload = {
        "status": "success", "summary": huge_summary,
        "findings": [], "pointers": [], "next_step": None,
    }
    msg = pool._build_dispatcher_callback(
        task_id="T1", intent="i", payload=payload,
        artifact_path=None, raw_len=0, fallback_text="",
    )
    assert len(msg) <= wp.MAX_DISPATCHER_PAYLOAD_CHARS + 200  # +truncation marker
    assert "callback truncated" in msg


# ---------------------------------------------------------------------------
# Burst cap against a dispatcher chat
# ---------------------------------------------------------------------------

def test_clip_against_recent_bursts_under_cap_unchanged(monkeypatch):
    monkeypatch.setenv("VOXYFLOW_CALLBACK_BURST_CAP_CHARS", "40000")
    monkeypatch.setenv("VOXYFLOW_CALLBACK_WINDOW_S", "60")
    pool = _make_pool_for_rendering()
    msg = "a" * 5_000
    out = pool._clip_against_recent_bursts("chat-1", msg)
    assert out == msg


def test_clip_against_recent_bursts_clips_once_cap_exceeded(monkeypatch):
    monkeypatch.setenv("VOXYFLOW_CALLBACK_BURST_CAP_CHARS", "10000")
    monkeypatch.setenv("VOXYFLOW_CALLBACK_WINDOW_S", "60")
    pool = _make_pool_for_rendering()

    # Two callbacks at 4k each — both fit under 10k cap.
    first = pool._clip_against_recent_bursts("chat-1", "a" * 4_000)
    assert len(first) == 4_000
    second = pool._clip_against_recent_bursts("chat-1", "b" * 4_000)
    assert len(second) == 4_000

    # Third pushes past the 10k cap — should be clipped with the annotation.
    third = pool._clip_against_recent_bursts("chat-1", "c" * 8_000)
    assert len(third) < 8_000 + 500
    assert "dispatcher burst cap" in third


def test_clip_against_recent_bursts_is_per_chat(monkeypatch):
    monkeypatch.setenv("VOXYFLOW_CALLBACK_BURST_CAP_CHARS", "10000")
    monkeypatch.setenv("VOXYFLOW_CALLBACK_WINDOW_S", "60")
    pool = _make_pool_for_rendering()

    pool._clip_against_recent_bursts("chat-A", "a" * 9_000)
    # chat-B starts with a fresh budget — unaffected by chat-A's history.
    out_b = pool._clip_against_recent_bursts("chat-B", "b" * 5_000)
    assert len(out_b) == 5_000
    assert "dispatcher burst cap" not in out_b


def test_clip_against_recent_bursts_window_expires(monkeypatch):
    """Entries older than the window drop out — budget refreshes."""
    import time

    monkeypatch.setenv("VOXYFLOW_CALLBACK_BURST_CAP_CHARS", "10000")
    monkeypatch.setenv("VOXYFLOW_CALLBACK_WINDOW_S", "60")
    pool = _make_pool_for_rendering()

    # Seed an old, expired entry manually.
    pool._recent_callback_chars["chat-1"] = [(time.time() - 120, 9_000)]
    out = pool._clip_against_recent_bursts("chat-1", "x" * 5_000)
    # 9k entry is older than 60s — dropped — 5k fits under 10k budget.
    assert len(out) == 5_000
    assert "dispatcher burst cap" not in out
