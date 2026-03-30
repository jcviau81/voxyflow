#!/usr/bin/env python3
"""
Voxyflow E2E validation script.
Tests: WS connect, chat message, card listing, card move.
"""

import asyncio
import json
import sys
import time
import httpx

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000/ws"
VOXYFLOW_PROJECT_ID = "37125887-e7b5-4a74-9a64-3de7f234aa59"

results = []

def report(name: str, ok: bool, detail: str = ""):
    icon = "✅" if ok else "❌"
    results.append((name, ok, detail))
    print(f"{icon} {name}" + (f" — {detail}" if detail else ""))


async def test_ws_connect_and_chat():
    """Test 1: Connect to WS + send a chat message + wait for response."""
    import websockets

    try:
        async with websockets.connect(WS_URL, open_timeout=5) as ws:
            report("WS Connect", True)

            # Send a chat message to the Voxyflow project
            session_id = f"project:{VOXYFLOW_PROJECT_ID}"
            msg = {
                "type": "chat:message",
                "payload": {
                    "content": "Liste mes cartes",
                    "projectId": VOXYFLOW_PROJECT_ID,
                    "chatLevel": "project",
                    "sessionId": session_id,
                    "chatId": session_id,
                    "messageId": f"test-{int(time.time())}",
                },
            }
            await ws.send(json.dumps(msg))
            report("WS Send chat:message", True, "Sent 'Liste mes cartes'")

            # Wait for a response (chat:response with done=true or streaming chunks)
            got_response = False
            response_content = ""
            timeout = 60  # seconds — LLM can take a while
            deadline = time.time() + timeout

            while time.time() < deadline:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=2)
                    data = json.loads(raw)
                    msg_type = data.get("type")

                    if msg_type == "pong":
                        continue

                    if msg_type == "chat:response":
                        payload = data.get("payload", {})
                        content = payload.get("content", "")
                        done = payload.get("done", False)
                        streaming = payload.get("streaming", False)

                        if streaming and not done:
                            response_content += content
                        elif done:
                            response_content += content if content else ""
                            got_response = True
                            break
                        else:
                            # Non-streaming full response
                            response_content = content
                            got_response = True
                            break

                    elif msg_type in ("task:started", "task:progress", "task:completed"):
                        payload = data.get("payload", {})
                        if msg_type == "task:completed":
                            result = payload.get("result", "")
                            response_content = result
                            got_response = True
                            break

                except asyncio.TimeoutError:
                    # Send ping to keep alive
                    await ws.send(json.dumps({"type": "ping", "payload": {}, "timestamp": time.time()}))
                    continue

            if got_response:
                preview = response_content[:120].replace("\n", " ")
                report("Chat Response", True, f"Got response: {preview}...")
            else:
                report("Chat Response", False, f"No response within {timeout}s")

    except Exception as e:
        report("WS Connect", False, str(e))


async def test_card_list_via_api():
    """Test 2: List cards via REST API."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        resp = await client.get(f"/api/projects/{VOXYFLOW_PROJECT_ID}/cards")
        if resp.status_code == 200:
            cards = resp.json()
            report("REST Card List", True, f"{len(cards)} cards found")
            return cards
        else:
            report("REST Card List", False, f"HTTP {resp.status_code}")
            return []


async def test_card_move(cards):
    """Test 3: Move a card to in-progress then back."""
    if not cards:
        report("Card Move", False, "No cards to test with")
        return

    # Find a card that's not in-progress
    target = None
    for c in cards:
        if c.get("status") != "in-progress":
            target = c
            break

    if not target:
        # All cards in-progress, try moving one to todo
        target = cards[0]

    card_id = target["id"]
    original_status = target["status"]
    new_status = "in-progress" if original_status != "in-progress" else "todo"

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10) as client:
        # Move card
        resp = await client.patch(f"/api/cards/{card_id}", json={"status": new_status})
        if resp.status_code != 200:
            report("Card Move", False, f"PATCH returned {resp.status_code}")
            return

        updated = resp.json()
        if updated.get("status") == new_status:
            report("Card Move", True, f"'{target['title'][:40]}' → {new_status}")
        else:
            report("Card Move", False, f"Status not updated: {updated.get('status')}")

        # Move back to original
        resp2 = await client.patch(f"/api/cards/{card_id}", json={"status": original_status})
        if resp2.status_code == 200:
            report("Card Move Revert", True, f"Restored to {original_status}")
        else:
            report("Card Move Revert", False, f"Failed to restore: HTTP {resp2.status_code}")


async def main():
    print("=" * 60)
    print("Voxyflow E2E Validation")
    print("=" * 60)
    print()

    # Test REST first (quick)
    cards = await test_card_list_via_api()
    await test_card_move(cards)

    # Test WS chat (slower — involves LLM)
    await test_ws_connect_and_chat()

    print()
    print("=" * 60)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
