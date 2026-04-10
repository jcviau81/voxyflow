#!/usr/bin/env python3
"""
iMessage → Voxyflow Bridge
==========================
Watches for incoming iMessages from a specific contact and routes them through
the Voxyflow AI chat (WebSocket API), then sends the AI response back via imsg.

Architecture:
  imsg watch --json  →  filter by sender  →  Voxyflow WS  →  imsg send

Configuration (env vars or edit defaults below):
  IMSG_CONTACT      Apple ID / phone to watch  (default: you@example.com)
  VOXYFLOW_WS_URL   WebSocket URL              (default: ws://localhost:8000/ws)
  VOXYFLOW_PROJECT  Voxyflow project ID        (default: system-main)
  IMSG_SERVICE      imsg service flag          (default: imessage)
  IMSG_BIN          path to imsg binary        (default: /opt/homebrew/bin/imsg)
  STATE_FILE        cursor/seen-ID state file  (default: ~/bridge/.state.json)
  LOG_FILE          log file path              (default: ~/bridge/bridge.log)

Requirements:
  pip install websockets
  brew install steipete/tap/imsg
"""

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
IMSG_CONTACT    = os.environ.get("IMSG_CONTACT",    "you@example.com")
VOXYFLOW_WS_URL = os.environ.get("VOXYFLOW_WS_URL", "ws://localhost:8000/ws")
VOXYFLOW_PROJECT= os.environ.get("VOXYFLOW_PROJECT","system-main")
IMSG_SERVICE    = os.environ.get("IMSG_SERVICE",    "imessage")
IMSG_BIN        = os.environ.get("IMSG_BIN",        "/opt/homebrew/bin/imsg")
STATE_FILE      = Path(os.environ.get("STATE_FILE",  str(Path.home() / "bridge" / ".state.json")))
LOG_FILE        = Path(os.environ.get("LOG_FILE",    str(Path.home() / "bridge" / "bridge.log")))

RECONNECT_DELAY = 5   # seconds between WebSocket reconnects
WS_RESPONSE_TIMEOUT = 120  # max seconds to wait for a complete AI response

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE),
    ],
)
log = logging.getLogger("imessage_bridge")

# ---------------------------------------------------------------------------
# State / cursor (avoid reprocessing on restart)
# ---------------------------------------------------------------------------

def load_state() -> dict:
    """Load persisted state from disk."""
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except Exception as e:
            log.warning(f"Could not load state file: {e}")
    return {"last_seen_id": None, "seen_ids": []}


def save_state(state: dict) -> None:
    """Persist state to disk (atomic write)."""
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    tmp.replace(STATE_FILE)


def mark_seen(state: dict, msg_id: str) -> None:
    """Record a message ID as processed."""
    if msg_id not in state["seen_ids"]:
        state["seen_ids"].append(msg_id)
        # Keep only the last 500 IDs to bound memory
        state["seen_ids"] = state["seen_ids"][-500:]
    state["last_seen_id"] = msg_id
    save_state(state)


def is_seen(state: dict, msg_id: str) -> bool:
    return msg_id in state["seen_ids"]

# ---------------------------------------------------------------------------
# Voxyflow WebSocket client
# ---------------------------------------------------------------------------

async def voxyflow_chat(message: str) -> Optional[str]:
    """
    Send a message to Voxyflow via WebSocket and collect the streamed response.

    Returns the full AI response text, or None on error.

    WebSocket protocol:
      SEND: {"type": "chat:message", "id": "<uuid>", "payload": {
               "content": "<text>",
               "projectId": "system-main",
               "chatLevel": "general",
               "sessionId": "<stable-session-uuid>",
               "chatId": "project:system-main"}}

      RECV: {"type": "chat:response", "payload": {
               "messageId": "...", "content": "<token>",
               "streaming": true, "done": false, ...}}
             ... (streaming tokens) ...
             {"type": "chat:response", "payload": {"done": true, ...}}
    """
    try:
        import websockets
    except ImportError:
        log.error("Missing dependency: pip install websockets")
        return None

    session_id = f"imessage-bridge-{IMSG_CONTACT.replace('@', '-')}"
    chat_id    = f"project:{VOXYFLOW_PROJECT}"
    msg_id     = uuid4().hex

    payload = {
        "type": "chat:message",
        "id": msg_id,
        "payload": {
            "content": message,
            "projectId": VOXYFLOW_PROJECT,
            "chatLevel": "general",
            "sessionId": session_id,
            "chatId": chat_id,
        },
        "timestamp": int(time.time() * 1000),
    }

    full_response = ""
    # Accumulate per-messageId buffers in case of concurrent streams
    buffers: dict[str, str] = {}
    primary_msg_id: Optional[str] = None

    try:
        async with websockets.connect(
            VOXYFLOW_WS_URL,
            open_timeout=10,
            ping_interval=30,
            ping_timeout=10,
        ) as ws:
            log.info(f"[WS] Connected to {VOXYFLOW_WS_URL}")

            # Send the chat message
            await ws.send(json.dumps(payload))
            log.info(f"[WS] Sent message id={msg_id}: {message[:80]!r}")

            deadline = asyncio.get_event_loop().time() + WS_RESPONSE_TIMEOUT
            done_ids: set[str] = set()

            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    log.warning("[WS] Response timeout — returning partial result")
                    break

                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=min(remaining, 30))
                except asyncio.TimeoutError:
                    log.debug("[WS] recv timeout, retrying…")
                    continue

                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning(f"[WS] Non-JSON frame: {raw[:120]}")
                    continue

                t = data.get("type", "")

                if t == "chat:response":
                    p = data.get("payload", {})
                    token   = p.get("content", "")
                    is_done = p.get("done", False)
                    rmid    = p.get("messageId", "")
                    sess    = p.get("sessionId", "")

                    # Only handle events belonging to our session
                    if sess and sess != session_id:
                        continue

                    if primary_msg_id is None and rmid:
                        primary_msg_id = rmid

                    if rmid == primary_msg_id or primary_msg_id is None:
                        buffers.setdefault(rmid, "")
                        if token:
                            buffers[rmid] += token
                        if is_done:
                            done_ids.add(rmid)
                            log.info(f"[WS] Stream done for messageId={rmid}")
                            # Primary stream finished → collect and exit
                            full_response = buffers.get(rmid, "")
                            break

                elif t in ("error",):
                    err = data.get("payload", {}).get("message", str(data))
                    log.error(f"[WS] Server error: {err}")
                    return None

                elif t == "ping":
                    await ws.send(json.dumps({"type": "pong"}))

                # Ignore task:started, task:progress, action:completed, etc.
                else:
                    log.debug(f"[WS] Ignored event type={t}")

    except (ConnectionRefusedError, OSError) as e:
        log.error(f"[WS] Cannot connect to Voxyflow: {e}")
        return None
    except Exception as e:
        log.exception(f"[WS] Unexpected error: {e}")
        return None

    return full_response.strip() if full_response else None

# ---------------------------------------------------------------------------
# imsg helpers
# ---------------------------------------------------------------------------

def send_imessage(to: str, text: str, service: str = IMSG_SERVICE) -> bool:
    """Send an iMessage via the imsg CLI. Returns True on success."""
    if not text:
        log.warning("Refusing to send empty message")
        return False

    # Truncate very long responses to avoid iMessage size limits
    if len(text) > 2000:
        log.warning(f"Truncating response from {len(text)} to 2000 chars")
        text = text[:1997] + "…"

    cmd = [IMSG_BIN, "send", "--to", to, "--text", text, "--service", service]
    log.info(f"[imsg] Sending to {to}: {text[:80]!r}")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            log.info("[imsg] Send OK")
            return True
        else:
            log.error(f"[imsg] Send failed (rc={result.returncode}): {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        log.error("[imsg] Send timed out")
        return False
    except FileNotFoundError:
        log.error(f"[imsg] Binary not found at {IMSG_BIN}. Install with: brew install steipete/tap/imsg")
        return False
    except Exception as e:
        log.exception(f"[imsg] Unexpected send error: {e}")
        return False

# ---------------------------------------------------------------------------
# Main watch loop
# ---------------------------------------------------------------------------

async def run_bridge():
    """
    Main loop: spawn `imsg watch --json`, parse each JSON line,
    filter for target contact, and dispatch to Voxyflow.
    """
    state = load_state()
    log.info(f"Bridge starting. Watching for messages from {IMSG_CONTACT!r}")
    log.info(f"State: last_seen_id={state.get('last_seen_id')}, seen_count={len(state.get('seen_ids', []))}")

    while True:
        log.info("[imsg] Launching: imsg watch --json")
        try:
            proc = await asyncio.create_subprocess_exec(
                IMSG_BIN, "watch", "--json",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError:
            log.error(f"[imsg] Binary not found at {IMSG_BIN}. Retrying in {RECONNECT_DELAY}s…")
            await asyncio.sleep(RECONNECT_DELAY)
            continue
        except Exception as e:
            log.error(f"[imsg] Failed to spawn: {e}. Retrying in {RECONNECT_DELAY}s…")
            await asyncio.sleep(RECONNECT_DELAY)
            continue

        log.info(f"[imsg] Watch process started (pid={proc.pid})")

        try:
            async for raw_line in proc.stdout:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                log.debug(f"[imsg] Raw: {line[:200]}")

                # Parse JSON
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    log.debug(f"[imsg] Non-JSON line: {line[:100]}")
                    continue

                # Extract fields
                msg_id      = str(msg.get("id") or msg.get("rowid") or "")
                handle      = (msg.get("handle") or msg.get("sender") or
                               msg.get("from") or "").lower().strip()
                is_from_me  = msg.get("is_from_me", msg.get("isFromMe", False))
                text        = (msg.get("text") or msg.get("body") or "").strip()

                log.debug(f"[msg] id={msg_id} handle={handle!r} from_me={is_from_me} text={text[:60]!r}")

                # Filter: only incoming messages from our contact
                if is_from_me:
                    continue
                if handle != IMSG_CONTACT.lower():
                    log.debug(f"[msg] Skipping message from {handle!r} (not {IMSG_CONTACT})")
                    continue
                if not text:
                    log.debug(f"[msg] Skipping empty message id={msg_id}")
                    continue

                # Dedup: skip already-processed messages
                if msg_id and is_seen(state, msg_id):
                    log.debug(f"[msg] Already processed id={msg_id}, skipping")
                    continue

                log.info(f"[msg] Incoming from {handle}: {text!r}")

                # Mark as seen before processing (prevent redelivery on crash-restart)
                if msg_id:
                    mark_seen(state, msg_id)

                # Query Voxyflow
                log.info("[voxy] Querying Voxyflow…")
                response = await voxyflow_chat(text)

                if response:
                    log.info(f"[voxy] Response ({len(response)} chars): {response[:120]!r}")
                    success = send_imessage(IMSG_CONTACT, response)
                    if not success:
                        log.warning("[imsg] Failed to send response; message was lost")
                else:
                    log.warning("[voxy] No response received from Voxyflow")
                    send_imessage(IMSG_CONTACT, "⚠️ Sorry, I couldn't get a response right now. Please try again.")

        except asyncio.CancelledError:
            log.info("[imsg] Watch cancelled, shutting down")
            proc.terminate()
            raise

        except Exception as e:
            log.exception(f"[imsg] Error in watch loop: {e}")

        finally:
            # Ensure process is cleaned up
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except Exception:
                pass

        log.warning(f"[imsg] Watch process ended (rc={proc.returncode}). Restarting in {RECONNECT_DELAY}s…")
        await asyncio.sleep(RECONNECT_DELAY)


def main():
    log.info("=" * 60)
    log.info("iMessage → Voxyflow Bridge")
    log.info(f"  Contact:    {IMSG_CONTACT}")
    log.info(f"  Voxyflow:   {VOXYFLOW_WS_URL}")
    log.info(f"  Project:    {VOXYFLOW_PROJECT}")
    log.info(f"  imsg bin:   {IMSG_BIN}")
    log.info(f"  State file: {STATE_FILE}")
    log.info(f"  Log file:   {LOG_FILE}")
    log.info("=" * 60)

    try:
        asyncio.run(run_bridge())
    except KeyboardInterrupt:
        log.info("Bridge stopped by user.")


if __name__ == "__main__":
    main()
