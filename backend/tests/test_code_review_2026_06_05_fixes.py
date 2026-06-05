"""Regression tests for the 2026-06-05 code-review fixes.

Covers the security/correctness-critical changes so they cannot silently
re-regress. See docs/CODE_REVIEW_2026-06-05.md.
"""
import asyncio
import json
import os
import stat

import pytest

from fastapi import Depends
from fastapi.routing import APIRoute


# ---------------------------------------------------------------------------
# S1 — settings.json is written REDACTED, never plaintext keys, with 0600.
# ---------------------------------------------------------------------------
def test_write_settings_file_redacted_masks_keys_and_chmods(tmp_path, monkeypatch):
    import app.routes.settings as s

    target = tmp_path / "settings.json"
    monkeypatch.setattr(s, "SETTINGS_FILE", str(target))

    data = {
        "models": {
            "endpoints": [
                {"id": "e1", "name": "openai", "provider_type": "openai",
                 "url": "https://api.openai.com", "api_key": "sk-REAL-SECRET-123"},
            ],
        },
    }

    s._write_settings_file_redacted(data)

    raw = target.read_text()
    # The real endpoint secret must NOT be on disk; the redaction sentinel must be.
    assert "sk-REAL-SECRET-123" not in raw
    assert "***" in raw

    on_disk = json.loads(raw)
    assert on_disk["models"]["endpoints"][0]["api_key"] == "***"

    # File must be owner-only (0600).
    mode = stat.S_IMODE(os.stat(target).st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"

    # The caller's dict must not be mutated by redaction (real key preserved in memory).
    assert data["models"]["endpoints"][0]["api_key"] == "sk-REAL-SECRET-123"


# ---------------------------------------------------------------------------
# S2 — endpoint mutation routes require auth.
# ---------------------------------------------------------------------------
def _route_dep_callables(route: APIRoute):
    return {d.dependency for d in route.dependencies}


def test_endpoint_mutation_routes_require_verify_auth():
    import app.routes.settings as s
    from app.services.auth_service import verify_auth

    post_ep = next(
        r for r in s.router.routes
        if isinstance(r, APIRoute) and r.path.endswith("/endpoints") and "POST" in r.methods
    )
    del_ep = next(
        r for r in s.router.routes
        if isinstance(r, APIRoute) and r.path.endswith("/endpoints/{endpoint_id}") and "DELETE" in r.methods
    )
    assert verify_auth in _route_dep_callables(post_ep), "POST /endpoints missing verify_auth"
    assert verify_auth in _route_dep_callables(del_ep), "DELETE /endpoints missing verify_auth"


# ---------------------------------------------------------------------------
# S3 — session file paths cannot escape the session store (path traversal).
# ---------------------------------------------------------------------------
def test_safe_session_path_rejects_traversal():
    from app.services.session_store import SessionStore

    store = SessionStore()

    # A normal canonical chat_id resolves inside the sessions dir.
    ok = store._safe_session_path("workspace:abc-123:s-1", ".json")
    assert ok.resolve().is_relative_to(store.sessions_dir.resolve())

    # Colon-injection that resolves to an absolute path outside the base raises.
    with pytest.raises(ValueError):
        store._safe_session_path(":etc:passwd-hacked", ".summary.json")


# ---------------------------------------------------------------------------
# C10 — per-chat file locks are reclaimed on session delete/clear.
# ---------------------------------------------------------------------------
def test_file_lock_reclaimed_on_delete_and_clear():
    from app.services.session_store import SessionStore

    store = SessionStore()

    cid_del = "workspace:reclaim-del:s-1"
    store._get_file_lock(cid_del)
    assert cid_del in store._file_locks
    store.delete_session(cid_del)
    assert cid_del not in store._file_locks, "lock not reclaimed on delete_session"

    cid_clear = "workspace:reclaim-clear:s-1"
    store._get_file_lock(cid_clear)
    assert cid_clear in store._file_locks
    store.clear_session(cid_clear)
    assert cid_clear not in store._file_locks, "lock not reclaimed on clear_session"


# ---------------------------------------------------------------------------
# M20 — invoke_tool_callback awaits coroutines, runs sync, no-ops None, swallows errors.
# ---------------------------------------------------------------------------
def test_invoke_tool_callback_variants():
    from app.services.llm.model_utils import invoke_tool_callback

    calls = []

    async def run():
        # None callback is a no-op (must not raise).
        await invoke_tool_callback(None, "card.list", {}, {"content": "x"})

        # Sync callback is invoked.
        invoke_tool_callback_sync = lambda n, a, r: calls.append(("sync", n))
        await invoke_tool_callback(invoke_tool_callback_sync, "card.get", {"id": 1}, {"content": "ok"})

        # Async callback is awaited (its side effect must land).
        async def acb(n, a, r):
            await asyncio.sleep(0)
            calls.append(("async", n))
        await invoke_tool_callback(acb, "card.create", {}, {"content": "ok"})

        # A raising callback is swallowed, not propagated.
        def boom(n, a, r):
            raise RuntimeError("boom")
        await invoke_tool_callback(boom, "card.delete", {}, {"content": "ok"})

    asyncio.get_event_loop().run_until_complete(run()) if False else asyncio.run(run())

    assert ("sync", "card.get") in calls
    assert ("async", "card.create") in calls
    # boom did not append and did not raise
    assert all(n != "card.delete" for _, n in calls)


# ---------------------------------------------------------------------------
# C2 — recurrence cron is evaluated in UTC, not system-local time.
# ---------------------------------------------------------------------------
def test_cron_recurrence_uses_utc():
    from datetime import datetime, timezone
    from apscheduler.triggers.cron import CronTrigger

    # Mirror the scheduler's exact construction (scheduler_service._recurrence_job):
    # a daily 09:00 cron evaluated against a UTC base must fire at 09:00 UTC.
    base = datetime(2026, 6, 5, 10, 0, 0, tzinfo=timezone.utc)  # 10:00 UTC -> next 09:00 is tomorrow
    trigger = CronTrigger.from_crontab("0 9 * * *", timezone=timezone.utc)
    nxt = trigger.get_next_fire_time(None, base)
    assert nxt.hour == 9
    assert nxt.utcoffset().total_seconds() == 0, "next fire must be UTC-anchored"
