"""Worker pool ↔ session_store sync — regression tests

Symptom: the DB ledger flips to ``done`` / ``cancelled`` / ``failed`` but the
file-store ``worker_sessions/<task>.json`` stays on ``status=running``. After
``RUNNING_TIMEOUT_SECONDS`` (1800s), ``check_timeouts`` then flips the stale
``running`` entry to ``timed_out`` and the UI reports a phantom timeout.

Root cause: any terminal-status path in ``DeepWorkerPool`` that updates the
DB ledger via ``_ledger_update`` must also update the file-store via
``worker_session_store.update_status``. The two stores are independent and
neither one mirrors the other.

The terminal sites in ``worker_pool.py`` are:

  * ``DeepWorkerPool.stop`` — backend / session shutdown (loop)
  * ``DeepWorkerPool.cancel_task`` (zombie branch)
  * ``DeepWorkerPool.cancel_task`` (live branch) — user-initiated cancel
  * ``_handle_action_intent`` — ``except asyncio.CancelledError`` (worker cancel)
  * ``_handle_action_intent`` — happy-path completion (status="done")
  * ``_handle_action_intent`` — ``except Exception`` (worker failure)

These tests pin the invariant: every terminal status change updates BOTH
stores, regardless of which path got there.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.event_bus import SessionEventBus
from app.services.orchestration.worker_pool import DeepWorkerPool
from app.services.worker_session_store import get_worker_session_store


# ---------------------------------------------------------------------------
# Static audit — every terminal `_ledger_update` site must have a sibling
# `update_status` call (within ~25 lines). Tripwire test: any future refactor
# that drops the wss call at a terminal site fails the suite without needing
# to spin up an async pool.
# ---------------------------------------------------------------------------

_WORKER_POOL_PATH = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "services"
    / "orchestration"
    / "worker_pool.py"
)


def _find_terminal_ledger_update_sites(src: str) -> list[int]:
    """Return line numbers (1-indexed) of `_ledger_update(...)` calls with a
    terminal status (cancelled/done/failed), excluding the method definition
    itself."""
    lines = src.splitlines()
    out: list[int] = []
    for idx, line in enumerate(lines, start=1):
        if re.search(r"async def\s+_ledger_update", line):
            continue
        if not re.search(r"\b_ledger_update\s*\(", line):
            continue
        window = " ".join(lines[idx - 1 : idx + 3])
        if re.search(r'"(?:cancelled|done|failed|timed_out)"', window):
            out.append(idx)
    return out


def test_every_terminal_ledger_update_has_nearby_update_status():
    """Static guarantee that no future edit forgets the file-store sync."""
    src = _WORKER_POOL_PATH.read_text()
    lines = src.splitlines()

    sites = _find_terminal_ledger_update_sites(src)
    assert len(sites) >= 5, (
        "Expected at least 5 terminal _ledger_update sites; "
        f"found {len(sites)}: {sites}"
    )

    missing: list[int] = []
    for site_line in sites:
        start = max(0, site_line - 26)
        end = min(len(lines), site_line + 25)
        window = "\n".join(lines[start:end])
        if not re.search(r"\b(?:[_a-zA-Z]\w*\.)?update_status\s*\(", window):
            missing.append(site_line)

    assert not missing, (
        "Terminal _ledger_update calls without a nearby update_status sync "
        f"(file-store will drift into phantom timed_out): lines {missing}"
    )


# ---------------------------------------------------------------------------
# Functional — cancellation paths sync the file-store session
# ---------------------------------------------------------------------------


def _make_pool() -> DeepWorkerPool:
    bus = SessionEventBus(session_id=f"sess-{uuid4().hex[:8]}")
    return DeepWorkerPool(claude_service=None, bus=bus, websocket=None)


@pytest.mark.asyncio
async def test_cancel_task_live_syncs_session_store():
    pool = _make_pool()
    task_id = f"task-{uuid4().hex[:8]}"

    store = get_worker_session_store()
    store.register(
        task_id=task_id,
        session_id=pool._bus.session_id,
        intent="test",
        summary="sync probe",
    )

    async def _hang():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return  # simulate worker whose CancelledError handler doesn't sync wss

    real_task = asyncio.create_task(_hang())
    pool._active_tasks[task_id] = real_task

    with patch.object(DeepWorkerPool, "_ledger_update", new=AsyncMock()) as mock_ledger, \
         patch.object(pool, "_send_task_event", new=AsyncMock()):
        await pool.cancel_task(task_id)

    session = store.get_session(task_id)
    assert session is not None
    assert session["status"] == "cancelled", (
        f"file-store session_store left task on status={session['status']!r} "
        f"after cancel_task — it would later flip to timed_out"
    )
    mock_ledger.assert_any_await(task_id, "cancelled", error="User cancelled")

    store._sessions.pop(task_id, None)
    store._cleanup_file(task_id)


@pytest.mark.asyncio
async def test_stop_syncs_session_store_for_active_tasks():
    pool = _make_pool()
    task_id = f"task-{uuid4().hex[:8]}"

    store = get_worker_session_store()
    store.register(
        task_id=task_id,
        session_id=pool._bus.session_id,
        intent="test",
        summary="sync probe (stop)",
    )

    async def _hang():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            return

    real_task = asyncio.create_task(_hang())
    pool._active_tasks[task_id] = real_task

    with patch.object(DeepWorkerPool, "_ledger_update", new=AsyncMock()) as mock_ledger, \
         patch.object(DeepWorkerPool, "_cancel_session_tasks", new=AsyncMock(return_value=0)):
        await pool.stop()

    session = store.get_session(task_id)
    assert session is not None
    assert session["status"] == "cancelled", (
        f"DeepWorkerPool.stop left task on status={session['status']!r} — "
        f"file-store will later flip to timed_out"
    )
    mock_ledger.assert_any_await(
        task_id, "cancelled", error="Session closed — task cancelled"
    )

    store._sessions.pop(task_id, None)
    store._cleanup_file(task_id)
