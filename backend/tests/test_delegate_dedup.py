"""Axe D4 — delegate dedup matches only live workers and points at the blocker.

The dedup guard refuses a delegate when an *active* worker is already doing the
same job. It must (a) not fire on a worker that has already finished, and
(b) when it does fire on a duplicate summary, surface the blocking task_id so
the dispatcher can read that worker's result instead of relaunching.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.orchestration.delegate_dispatch import DelegateDispatchMixin


class _FakePool:
    def __init__(self, active):
        self._active = active

    def get_active_tasks(self):
        # Mirrors DeepWorkerPool.get_active_tasks: "active" is live tasks only.
        return {"active": self._active, "completed": []}


def test_duplicate_summary_surfaces_blocking_task():
    pool = _FakePool([
        {"task_id": "abc12345", "action": "research", "description": "find gold rivers",
         "card_id": None, "running_seconds": 12},
    ])
    deduped, skipped = DelegateDispatchMixin._dedup_delegates(
        [{"action": "research", "description": "find gold rivers"}], pool,
    )
    assert deduped == []
    assert len(skipped) == 1
    assert skipped[0]["reason"] == "duplicate_summary"
    assert skipped[0]["blocking_task_id"] == "abc12345"
    assert skipped[0]["blocking_running_seconds"] == 12


def test_card_busy_refuses_parallel_spawn_on_same_card():
    pool = _FakePool([
        {"task_id": "card9999", "action": "audit", "description": "audit the card",
         "card_id": "card-1", "running_seconds": 5},
    ])
    deduped, skipped = DelegateDispatchMixin._dedup_delegates(
        [{"action": "different", "description": "something else", "card_id": "card-1"}], pool,
    )
    assert deduped == []
    assert skipped[0]["reason"] == "card_busy"
    assert skipped[0]["blocking_task_id"] == "card9999"


def test_distinct_task_passes_through():
    pool = _FakePool([
        {"task_id": "abc12345", "action": "research", "description": "find gold rivers",
         "card_id": None, "running_seconds": 12},
    ])
    deduped, skipped = DelegateDispatchMixin._dedup_delegates(
        [{"action": "summarize", "description": "summarize the report"}], pool,
    )
    assert len(deduped) == 1
    assert skipped == []


def test_no_active_workers_passes_everything():
    pool = _FakePool([])
    delegates = [{"action": "research", "description": "x"}, {"action": "code", "description": "y"}]
    deduped, skipped = DelegateDispatchMixin._dedup_delegates(delegates, pool)
    assert len(deduped) == 2
    assert skipped == []
