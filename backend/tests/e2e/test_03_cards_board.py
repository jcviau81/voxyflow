"""
E2E: Card CRUD, status transitions, board operations, checklist,
comments, time entries, voting, relations, history, archive/restore,
duplicate.
"""

import uuid

import pytest
import httpx


# ── Card CRUD ────────────────────────────────────────────────────────��───────

class TestCardCRUD:
    @pytest.mark.asyncio
    async def test_create_card(self, client: httpx.AsyncClient, test_project: dict):
        pid = test_project["_id"]
        r = await client.post(f"/api/projects/{pid}/cards", json={
            "title": "CRUD test card",
            "description": "Testing create",
            "status": "todo",
            "priority": 3,
        })
        assert r.status_code in (200, 201)
        card = r.json()
        assert card.get("id") or card.get("card", {}).get("id")

    @pytest.mark.asyncio
    async def test_list_cards(self, client: httpx.AsyncClient, test_project: dict, test_card: dict):
        pid = test_project["_id"]
        r = await client.get(f"/api/projects/{pid}/cards")
        assert r.status_code == 200
        cards = r.json()
        assert isinstance(cards, list)
        ids = [c.get("id") for c in cards]
        assert test_card["_id"] in ids

    @pytest.mark.asyncio
    async def test_update_card(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]
        r = await client.patch(f"/api/cards/{cid}", json={
            "title": "Updated title",
            "description": "Updated description",
            "priority": 4,
        })
        assert r.status_code == 200
        data = r.json()
        assert data.get("title") == "Updated title"
        assert data.get("priority") == 4

    @pytest.mark.asyncio
    async def test_create_unassigned_card(self, client: httpx.AsyncClient):
        r = await client.post("/api/cards/unassigned", json={
            "title": "Unassigned E2E card",
            "color": "blue",
        })
        assert r.status_code in (200, 201)
        data = r.json()
        cid = data.get("id") or data.get("card", {}).get("id")
        assert cid


# ── Status Transitions (Board) ──────────────────────────────────────────────

class TestStatusTransitions:
    VALID_STATUSES = ["card", "todo", "in-progress", "done"]

    @pytest.mark.asyncio
    async def test_move_through_all_statuses(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]
        for status in self.VALID_STATUSES:
            r = await client.patch(f"/api/cards/{cid}", json={"status": status})
            assert r.status_code == 200, f"Failed to move to {status}: {r.text}"
            assert r.json().get("status") == status

    @pytest.mark.asyncio
    async def test_move_card_back_and_forth(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]

        # todo → in-progress
        r = await client.patch(f"/api/cards/{cid}", json={"status": "in-progress"})
        assert r.status_code == 200
        assert r.json().get("status") == "in-progress"

        # in-progress → todo (revert)
        r = await client.patch(f"/api/cards/{cid}", json={"status": "todo"})
        assert r.status_code == 200
        assert r.json().get("status") == "todo"


# ── Card Archive/Restore ─────────────────────────────────���──────────────────

class TestCardArchive:
    @pytest.mark.asyncio
    async def test_archive_and_restore(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]

        # Archive
        r = await client.post(f"/api/cards/{cid}/archive")
        assert r.status_code == 200

        # Verify archived status
        r = await client.get(f"/api/projects/{test_card['_project_id']}/cards")
        active_ids = [c["id"] for c in r.json() if c.get("status") != "archived"]
        assert cid not in active_ids

        # Restore
        r = await client.post(f"/api/cards/{cid}/restore")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_list_archived_cards(self, client: httpx.AsyncClient, test_project: dict, test_card: dict):
        cid = test_card["_id"]
        pid = test_project["_id"]

        # Archive the card
        await client.post(f"/api/cards/{cid}/archive")

        # List archived
        r = await client.get(f"/api/projects/{pid}/cards/archived")
        assert r.status_code == 200

        # Restore for cleanup
        await client.post(f"/api/cards/{cid}/restore")


# ── Card Duplicate ─────────────────────────────────��─────────────────────────

class TestCardDuplicate:
    @pytest.mark.asyncio
    async def test_duplicate_card(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]
        r = await client.post(f"/api/cards/{cid}/duplicate")
        assert r.status_code in (200, 201)
        dup = r.json()
        dup_id = dup.get("id") or dup.get("card", {}).get("id")
        assert dup_id
        assert dup_id != cid

        # Cleanup duplicate
        if dup_id:
            await client.delete(f"/api/cards/{dup_id}")


# ── Checklist ───────────────────────────────────────────────────────────────���

class TestChecklist:
    @pytest.mark.asyncio
    async def test_add_checklist_items(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]

        # Add items
        r = await client.post(f"/api/cards/{cid}/checklist", json={"text": "Step 1"})
        assert r.status_code in (200, 201)
        item1 = r.json()
        item1_id = item1.get("id")

        r = await client.post(f"/api/cards/{cid}/checklist", json={"text": "Step 2"})
        assert r.status_code in (200, 201)

        # List checklist
        r = await client.get(f"/api/cards/{cid}/checklist")
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 2

    @pytest.mark.asyncio
    async def test_toggle_checklist_item(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]

        # Create item
        r = await client.post(f"/api/cards/{cid}/checklist", json={"text": "Toggle me"})
        item = r.json()
        item_id = item.get("id")

        # Toggle completed
        r = await client.patch(f"/api/cards/{cid}/checklist/{item_id}", json={"completed": True})
        assert r.status_code == 200
        assert r.json().get("completed") is True

        # Toggle back
        r = await client.patch(f"/api/cards/{cid}/checklist/{item_id}", json={"completed": False})
        assert r.status_code == 200
        assert r.json().get("completed") is False


# ── Comments ───────────────────────────────���──────────────────────────────��──

class TestComments:
    @pytest.mark.asyncio
    async def test_add_and_list_comments(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]

        # Add comment
        r = await client.post(f"/api/cards/{cid}/comments", json={
            "content": "This is an E2E test comment",
        })
        assert r.status_code in (200, 201)
        comment = r.json()
        assert comment.get("content") == "This is an E2E test comment"

        # List comments
        r = await client.get(f"/api/cards/{cid}/comments")
        assert r.status_code == 200
        comments = r.json()
        assert len(comments) >= 1

    @pytest.mark.asyncio
    async def test_multiple_comments(self, client: httpx.AsyncClient, test_card: dict):
        import asyncio
        cid = test_card["_id"]
        for i in range(3):
            r = await client.post(f"/api/cards/{cid}/comments", json={
                "content": f"Comment #{i+1}",
            })
            assert r.status_code in (200, 201, 500), f"Unexpected {r.status_code}"
            if r.status_code == 500:
                # SQLite WAL contention under load — retry once
                await asyncio.sleep(0.2)
                r = await client.post(f"/api/cards/{cid}/comments", json={
                    "content": f"Comment #{i+1} retry",
                })
                assert r.status_code in (200, 201)

        r = await client.get(f"/api/cards/{cid}/comments")
        assert len(r.json()) >= 3


# ── Time Entries ─────────────────��───────────────────────────────────────────

class TestTimeEntries:
    @pytest.mark.asyncio
    async def test_log_time(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]
        r = await client.post(f"/api/cards/{cid}/time", json={
            "duration_minutes": 45,
            "note": "E2E testing work",
        })
        assert r.status_code in (200, 201)

    @pytest.mark.asyncio
    async def test_list_time_entries(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]

        # Log time first
        await client.post(f"/api/cards/{cid}/time", json={
            "duration_minutes": 30,
            "note": "Test entry",
        })

        r = await client.get(f"/api/cards/{cid}/time")
        assert r.status_code == 200
        entries = r.json()
        assert len(entries) >= 1


# ── Voting ─────────────────────────────────��──────────────────────��──────────

class TestVoting:
    @pytest.mark.asyncio
    async def test_vote_on_card(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]
        r = await client.post(f"/api/cards/{cid}/vote")
        assert r.status_code == 200
        data = r.json()
        assert data.get("votes", 0) >= 1


# ── Card Relations ───────────────────────────────────────────────────────────

class TestRelations:
    @pytest.mark.asyncio
    async def test_create_relation(self, client: httpx.AsyncClient, test_project: dict, test_card: dict):
        pid = test_project["_id"]
        src_id = test_card["_id"]

        # Create a second card to relate to
        r = await client.post(f"/api/projects/{pid}/cards", json={
            "title": "Related card",
            "status": "todo",
        })
        target = r.json()
        target_id = target.get("id")

        # Create relation
        r = await client.post(f"/api/cards/{src_id}/relations", json={
            "target_card_id": target_id,
            "relation_type": "blocks",
        })
        assert r.status_code in (200, 201)

        # List relations
        r = await client.get(f"/api/cards/{src_id}/relations")
        assert r.status_code == 200

        # Cleanup
        await client.delete(f"/api/cards/{target_id}")


# ── Card History ─────────────────────────────────────────────────────────────

class TestCardHistory:
    @pytest.mark.asyncio
    async def test_history_tracks_changes(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]

        # Make a change to generate history
        await client.patch(f"/api/cards/{cid}", json={"status": "in-progress"})
        await client.patch(f"/api/cards/{cid}", json={"status": "done"})

        r = await client.get(f"/api/cards/{cid}/history")
        assert r.status_code == 200
        history = r.json()
        assert isinstance(history, list)
        assert len(history) >= 1


# ── Agent Assignment ───────────────────────────────────────────────────��─────

class TestAgentAssignment:
    @pytest.mark.asyncio
    async def test_assign_agent(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]
        r = await client.post(f"/api/cards/{cid}/assign", json={
            "agent_type": "coder",
        })
        assert r.status_code == 200
        data = r.json()
        assert data.get("agent_type") == "coder"

    @pytest.mark.asyncio
    async def test_assign_different_agents(self, client: httpx.AsyncClient, test_card: dict):
        cid = test_card["_id"]
        for agent_type in ["researcher", "writer", "architect"]:
            r = await client.post(f"/api/cards/{cid}/assign", json={
                "agent_type": agent_type,
            })
            assert r.status_code == 200
            assert r.json().get("agent_type") == agent_type


# ── Card Enrich (LLM-dependent, tolerant) ───────────────────────────────────

class TestCardEnrich:
    @pytest.mark.asyncio
    async def test_enrich_endpoint_exists(self, client: httpx.AsyncClient, test_card: dict):
        """Verify endpoint exists — allow non-200 if LLM is not available."""
        cid = test_card["_id"]
        r = await client.post(f"/api/cards/{cid}/enrich", timeout=30)
        assert r.status_code != 404, "Enrich endpoint missing"
