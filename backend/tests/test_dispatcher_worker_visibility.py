"""Axe B — the dispatcher sees what workers are doing and why they stopped.

Covers:
  - build_live_state_block renders each active worker's claim plan as its own
    bullet (not a count) and collapses the tail into "+N more".
  - active_intents_for_chat appends the worker's claim plan (from the
    supervisor) so the live-state block can show *what* each worker is doing.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.personality_service import build_live_state_block
from app.services.orchestration.worker_pool import DeepWorkerPool
from app.services.worker_supervisor import get_worker_supervisor


def test_live_state_block_lists_workers_with_plans():
    block = build_live_state_block(
        active_workers=4,
        running_worker_intents=[
            "research — find 3 sources on Redis 7",
            "feature — wire the upload endpoint",
            "fix — repair the failing import",
            "doc — update the README",
        ],
    )
    assert "Active workers: 4" in block
    # First three rendered as their own bullets with the plan text.
    assert "• research — find 3 sources on Redis 7" in block
    assert "• feature — wire the upload endpoint" in block
    assert "• fix — repair the failing import" in block
    # Fourth collapses into the tail.
    assert "+1 more" in block
    assert "doc — update the README" not in block


def test_live_state_block_plain_count_when_no_intents():
    block = build_live_state_block(active_workers=0)
    assert "Active workers: 0" in block
    assert "•" not in block


def test_active_intents_appends_claim_plan():
    pool = DeepWorkerPool.__new__(DeepWorkerPool)  # bypass heavy __init__
    pool._active_tasks = {"task-claimed": object(), "task-bare": object()}
    pool._task_meta = {
        "task-claimed": {"action": "research", "dispatcher_chat_id": "chat-1"},
        "task-bare": {"action": "feature", "dispatcher_chat_id": "chat-1"},
        # Different chat — must be excluded.
        "task-other": {"action": "fix", "dispatcher_chat_id": "chat-2"},
    }

    sup = get_worker_supervisor()
    sup.register_task("task-claimed")
    sup.mark_claimed("task-claimed", "find the root cause of the leak")
    sup.register_task("task-bare")  # registered but never claimed

    intents = pool.active_intents_for_chat("chat-1")

    claimed = next(i for i in intents if i.startswith("research"))
    assert claimed == "research — find the root cause of the leak"
    # Unclaimed worker shows the bare action label, no separator.
    assert "feature" in intents
    # Other chat's worker is not leaked.
    assert all("fix" not in i for i in intents)

    sup.cleanup_task("task-claimed")
    sup.cleanup_task("task-bare")
