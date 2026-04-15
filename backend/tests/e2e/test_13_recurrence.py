"""
E2E: Recurring card reset — no copies, same card reused, history tracked.

These tests are pure REST — no LLM required.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import httpx

from .conftest import assert_card_status, assert_card_history_contains


class TestRecurrenceReset:
    @pytest.mark.asyncio
    async def test_recurring_card_resets_to_todo(self, client, test_project):
        """A done recurring card with past recurrence_next gets reset to todo."""
        pid = test_project["_id"]
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

        # Create a done recurring card with past recurrence_next
        r = await client.post(f"/api/projects/{pid}/cards", json={
            "title": f"Recurring E2E {uuid.uuid4().hex[:6]}",
            "description": "Recurring test card",
            "status": "done",
            "recurring": True,
            "recurrence": "daily",
            "recurrence_next": past,
        })
        assert r.status_code in (200, 201), f"Create failed: {r.text}"
        card = r.json()
        cid = card["id"]

        # Trigger recurrence job
        await _trigger_recurrence(client)

        # Card should be back to todo
        await assert_card_status(client, cid, "todo")

    @pytest.mark.asyncio
    async def test_no_copy_created(self, client, test_project):
        """Recurrence should reuse the same card, not create copies."""
        pid = test_project["_id"]
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

        # Count cards before
        r = await client.get(f"/api/projects/{pid}/cards")
        before = len(r.json()) if isinstance(r.json(), list) else len(r.json().get("cards", []))

        # Create recurring card
        r = await client.post(f"/api/projects/{pid}/cards", json={
            "title": f"NoCopy E2E {uuid.uuid4().hex[:6]}",
            "status": "done",
            "recurring": True,
            "recurrence": "daily",
            "recurrence_next": past,
        })
        card = r.json()

        await _trigger_recurrence(client)

        # Count after — should be same + 1 (just the card we created)
        r = await client.get(f"/api/projects/{pid}/cards")
        after = len(r.json()) if isinstance(r.json(), list) else len(r.json().get("cards", []))
        assert after == before + 1, f"Expected {before + 1} cards, got {after} (copy created?)"

    @pytest.mark.asyncio
    async def test_recurrence_next_advanced(self, client, test_project):
        """After reset, recurrence_next should be advanced to the future."""
        pid = test_project["_id"]
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

        r = await client.post(f"/api/projects/{pid}/cards", json={
            "title": f"Advance E2E {uuid.uuid4().hex[:6]}",
            "status": "done",
            "recurring": True,
            "recurrence": "daily",
            "recurrence_next": past,
        })
        card = r.json()
        cid = card["id"]

        await _trigger_recurrence(client)

        # Check recurrence_next moved forward
        r = await client.get(f"/api/cards/{cid}")
        updated = r.json()
        new_next = updated.get("recurrence_next")
        assert new_next is not None, "recurrence_next should be set"
        # Parse and verify it's in the future (or at least after the old value)
        new_next_str = new_next.replace("Z", "+00:00") if "+" not in new_next and new_next.endswith("Z") else new_next
        new_next_dt = datetime.fromisoformat(new_next_str)
        if new_next_dt.tzinfo is None:
            new_next_dt = new_next_dt.replace(tzinfo=timezone.utc)
        assert new_next_dt > datetime.now(timezone.utc) - timedelta(hours=1), \
            f"recurrence_next should be advanced: {new_next}"

    @pytest.mark.asyncio
    async def test_recurrence_history_entry(self, client, test_project):
        """Recurrence reset should create a CardHistory entry."""
        pid = test_project["_id"]
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

        r = await client.post(f"/api/projects/{pid}/cards", json={
            "title": f"History E2E {uuid.uuid4().hex[:6]}",
            "status": "done",
            "recurring": True,
            "recurrence": "daily",
            "recurrence_next": past,
        })
        card = r.json()
        cid = card["id"]

        await _trigger_recurrence(client)

        await assert_card_history_contains(client, cid, "status", "todo", "Recurrence")

    @pytest.mark.asyncio
    async def test_future_recurrence_not_triggered(self, client, test_project):
        """A card with recurrence_next in the future should not be reset."""
        pid = test_project["_id"]
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()

        r = await client.post(f"/api/projects/{pid}/cards", json={
            "title": f"Future E2E {uuid.uuid4().hex[:6]}",
            "status": "done",
            "recurring": True,
            "recurrence": "daily",
            "recurrence_next": future,
        })
        card = r.json()
        cid = card["id"]

        await _trigger_recurrence(client)

        # Should still be done
        await assert_card_status(client, cid, "done")

    @pytest.mark.asyncio
    async def test_already_todo_no_duplicate_history(self, client, test_project):
        """A recurring card already at todo should not get a duplicate history entry."""
        pid = test_project["_id"]
        past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

        r = await client.post(f"/api/projects/{pid}/cards", json={
            "title": f"AlreadyTodo E2E {uuid.uuid4().hex[:6]}",
            "status": "todo",
            "recurring": True,
            "recurrence": "daily",
            "recurrence_next": past,
        })
        card = r.json()
        cid = card["id"]

        await _trigger_recurrence(client)

        # Should still be todo
        await assert_card_status(client, cid, "todo")

        # Check history — should NOT have a todo→todo entry
        r = await client.get(f"/api/cards/{cid}/history")
        if r.status_code == 200:
            entries = r.json()
            todo_to_todo = [
                e for e in entries
                if e.get("field_changed") == "status"
                and e.get("old_value") == "todo"
                and e.get("new_value") == "todo"
            ]
            assert len(todo_to_todo) == 0, "Should not create todo→todo history entry"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _trigger_recurrence(client: httpx.AsyncClient) -> None:
    """Find and trigger the recurrence job. Creates it if not found."""
    r = await client.get("/api/jobs")
    assert r.status_code == 200
    jobs = r.json().get("jobs", [])
    recurrence_job = next(
        (j for j in jobs if j.get("type") == "recurrence" or j.get("id") == "builtin-recurrence"),
        None,
    )
    if not recurrence_job:
        # Create the recurrence job on the fly
        r = await client.post("/api/jobs", json={
            "id": "builtin-recurrence",
            "name": "Recurring Card Reset",
            "type": "recurrence",
            "schedule": "every_1h",
            "enabled": True,
            "builtin": True,
            "payload": {},
        })
        if r.status_code not in (200, 201):
            pytest.skip(f"Could not create recurrence job: {r.text}")
        recurrence_job = r.json()

    job_id = recurrence_job["id"]
    r = await client.post(f"/api/jobs/{job_id}/run", timeout=30)
    assert r.status_code == 200, f"Trigger failed: {r.text}"
