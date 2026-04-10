# iMessage → Voxyflow Bridge

Route incoming iMessages to Voxyflow's AI chat and send the response back — automatically.

## How it works

```
imsg watch --json
      │
      │  (one JSON line per new message)
      ▼
  Filter: handle == $IMSG_CONTACT && is_from_me == false
      │
      │  (deduplicate via .state.json cursor)
      ▼
  WebSocket → ws://localhost:8000/ws
  {"type": "chat:message", "payload": {"content": "...", ...}}
      │
      │  (streaming chat:response tokens, done=true signals end)
      ▼
  Collect full AI response text
      │
      ▼
  imsg send --to $IMSG_CONTACT --text "<response>" --service imessage
```

**Architecture:** `imsg watch (JSON)` → `Python bridge` → `Voxyflow WS API` → `Claude response` → `imsg send`

## Prerequisites

### ⚠️ Hardware & Apple ID Requirement — Read This First

> **This bridge requires TWO separate Mac computers, each signed into a DIFFERENT Apple ID.**

| Mac | Role | Apple ID |
|-----|------|----------|
| **Mac A** (host) | Runs the bridge script + Voxyflow backend | Apple ID A (e.g. `host@example.com`) |
| **Mac B** (sender) | Sends iMessages to Mac A | Apple ID B (e.g. `sender@example.com`) |

**Why two Macs?**
iMessage routes messages within the same Apple ID to all devices sharing that account — so a message sent *to* your own Apple ID never appears as an incoming message on the same Mac.
The bridge works by watching Mac A's `Messages.app` for **incoming** iMessages from Mac B's Apple ID. If both Macs share the same Apple ID, the message will be delivered as an outgoing message on both devices and the bridge will never trigger.

> **Summary:** Mac B sends an iMessage to Mac A's Apple ID → Mac A receives it as an incoming message → the bridge picks it up → queries Voxyflow → replies back to Mac B.

---

### Software dependencies

```bash
# 1. Install imsg (macOS iMessage CLI)
brew install steipete/tap/imsg

# 2. Install websockets Python package
pip3 install websockets

# 3. Grant permissions to Messages.app
#    System Settings → Privacy & Security → Full Disk Access → add Terminal
#    System Settings → Privacy & Security → Automation → Terminal → Messages ✓

# 4. Voxyflow must be running at localhost:8000 (or configure VOXYFLOW_WS_URL)
```

## Files

| File | Description |
|------|-------------|
| `imessage_bridge.py` | Main bridge script |
| `com.voxyflow.imessage_bridge.plist` | launchd Login Agent plist (auto-start at login) |
| `.state.json` | Auto-created — cursor + seen message IDs (dedup) |
| `bridge.log` | Bridge script log |
| `launchd_stdout.log` | launchd stdout (when running as Login Agent) |
| `launchd_stderr.log` | launchd stderr (when running as Login Agent) |

## Quick Start

### 1. Copy the bridge script

```bash
mkdir -p ~/bridge
cp imessage_bridge.py ~/bridge/
```

### 2. Test manually first

```bash
IMSG_CONTACT="you@example.com" python3 ~/bridge/imessage_bridge.py
```

Send yourself an iMessage from the configured contact and watch the logs. The bridge will connect to `ws://localhost:8000/ws`, query Voxyflow, and send back the AI response.

### 3. Install as a Login Agent (auto-start)

```bash
# Copy and edit the plist — replace YOUR_USERNAME and set IMSG_CONTACT
cp com.voxyflow.imessage_bridge.plist ~/Library/LaunchAgents/
nano ~/Library/LaunchAgents/com.voxyflow.imessage_bridge.plist

# Load it
launchctl load ~/Library/LaunchAgents/com.voxyflow.imessage_bridge.plist

# Verify it's running
launchctl list | grep voxyflow

# Watch logs
tail -f ~/bridge/bridge.log
```

### 4. Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.voxyflow.imessage_bridge.plist
rm ~/Library/LaunchAgents/com.voxyflow.imessage_bridge.plist
```

## Configuration

All options can be set as environment variables or by editing the plist's `EnvironmentVariables` section.

| Variable | Default | Description |
|----------|---------|-------------|
| `IMSG_CONTACT` | `you@example.com` | Apple ID or phone number to watch |
| `VOXYFLOW_WS_URL` | `ws://localhost:8000/ws` | Voxyflow WebSocket endpoint |
| `VOXYFLOW_PROJECT` | `system-main` | Voxyflow project ID for chat context |
| `IMSG_SERVICE` | `imessage` | Send service: `imessage`, `sms`, or `auto` |
| `IMSG_BIN` | `/opt/homebrew/bin/imsg` | Path to the `imsg` binary |
| `STATE_FILE` | `~/bridge/.state.json` | Cursor + dedup state (survives restarts) |
| `LOG_FILE` | `~/bridge/bridge.log` | Log output path |

## Voxyflow WebSocket Protocol

The bridge speaks Voxyflow's native WebSocket protocol on `ws://localhost:8000/ws`.

**Sending a message:**
```json
{
  "type": "chat:message",
  "id": "<uuid>",
  "payload": {
    "content": "user message text",
    "projectId": "system-main",
    "chatLevel": "general",
    "sessionId": "imessage-bridge-you-example-com",
    "chatId": "project:system-main"
  },
  "timestamp": 1712000000000
}
```

**Receiving the streamed response:**
```json
{"type": "chat:response", "payload": {"messageId": "abc", "content": "token", "streaming": true, "done": false}}
...
{"type": "chat:response", "payload": {"messageId": "abc", "content": "", "streaming": true, "done": true}}
```

The bridge accumulates all tokens for the primary `messageId` and sends the full text once `done: true` is received.

## Reliability features

- **Deduplication** — message IDs are stored in `.state.json`; already-processed messages are skipped on restart.
- **Auto-reconnect** — if `imsg watch` exits or the WebSocket drops, the bridge restarts automatically (with a 5 s delay).
- **Response timeout** — if Voxyflow takes > 120 s, the bridge sends a partial reply and moves on.
- **Message truncation** — responses over 2,000 characters are truncated to fit iMessage limits.
- **Error acknowledgment** — if Voxyflow returns nothing, the contact receives a ⚠️ error notice instead of silence.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `imsg: Binary not found` | `brew install steipete/tap/imsg` |
| `Missing dependency: websockets` | `pip3 install websockets` |
| `Cannot connect to Voxyflow` | Ensure Voxyflow is running: `cd backend && uvicorn app.main:app --port 8000` |
| Bridge sees messages but doesn't reply | Check `IMSG_CONTACT` matches the sender's Apple ID exactly |
| `launchctl list` shows no entry | Re-run `launchctl load ~/Library/LaunchAgents/com.voxyflow.imessage_bridge.plist` |
| Messages re-processed on restart | `.state.json` may be corrupt — delete it to reset the cursor |

## Security notes

- The bridge only responds to a **single configured contact** (`IMSG_CONTACT`). All other senders are ignored.
- The `sessionId` is stable across restarts (`imessage-bridge-<contact-slug>`), so Voxyflow maintains conversation memory for the iMessage thread.
- No credentials are stored in this script — it connects to a locally-running Voxyflow instance over WebSocket.
