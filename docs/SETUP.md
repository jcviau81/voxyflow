# Voxyflow — Setup Guide

> ⚠️ **AVERTISSEMENT DE SÉCURITÉ**
> Voxyflow n'a **pas de système d'authentification** (pas de login/password). Il doit être utilisé derrière des portes closes.
> **Configurations recommandées :**
> - 🔒 **Tunnel Tailscale** (recommandé) — accès sécurisé via réseau privé
> - 🏠 **Réseau local uniquement** — non exposé sur internet
> - 💻 **Machine personnelle uniquement** — usage solo local
>
> **Ne PAS exposer Voxyflow directement sur internet sans protection supplémentaire.**

---

## Path Conventions

All paths in this documentation and in Voxyflow docs use the **default install locations**. Both can be overridden via environment variables:

| Variable | Default | What it controls |
|----------|---------|-----------------|
| `VOXYFLOW_DIR` | `~/voxyflow` | App directory (code, personality files, docs) |
| `VOXYFLOW_DATA_DIR` | `~/.voxyflow` | Data directory (database, ChromaDB, sessions, jobs) |

Set these before starting the backend if your install is in a different location:

```bash
export VOXYFLOW_DIR=/opt/voxyflow
export VOXYFLOW_DATA_DIR=/var/lib/voxyflow
uvicorn app.main:app ...
```

> Paths like `~/voxyflow/personality/` and `~/.voxyflow/voxyflow.db` shown throughout this documentation are examples based on the defaults.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Node.js | 18+ | Frontend build & dev server |
| Python | 3.12+ | Backend (`asyncio`, type hints, `match` statements) |
| Claude CLI (`claude`) | any | For CLI backend (`CLAUDE_USE_CLI=true`, recommended) |
| Git | any | |
| `gh` CLI | any | Optional — for GitHub repo integration |

**Optional (for RAG/knowledge base):**
- `chromadb` + `sentence-transformers` — installed by default via `requirements.txt`
- Downloads ~2.2GB model on first run (`intfloat/multilingual-e5-large`), cached in `~/.cache/huggingface/`

**Optional (for high-quality TTS):**
- XTTS v2 server — separate GPU machine or container (see [§7 TTS Setup](#7-optional-tts-setup))
- Without it, TTS falls back to browser `speechSynthesis` (works out of the box)

---

## 1. Clone the Repo

```bash
git clone https://github.com/jcviau81/voxyflow.git
cd voxyflow
```

---

## 2. Backend Setup

### Create and activate virtual environment

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  # Windows
```

### Install dependencies

```bash
pip install -r requirements.txt
```

**Core dependencies installed:**
- `fastapi` + `uvicorn` — web framework
- `sqlalchemy[asyncio]` + `aiosqlite` — async SQLite
- `httpx` — HTTP client
- `keyring` + `keyrings.alt` — secure key storage
- `apscheduler` — background task scheduler (heartbeat, RAG indexing, recurring cards)
- `chromadb` + `sentence-transformers` — RAG (optional but installed by default)
- `pypdf` + `python-docx` + `openpyxl` — document parsing (PDF, DOCX, XLSX)

### Configure environment

```bash
cp .env.example .env
```

Edit `.env` as needed. Minimal recommended config:

```env
# LLM Backend — CLI subprocess (recommended, uses Claude Max subscription)
CLAUDE_USE_CLI=true
CLAUDE_FAST_MODEL=claude-haiku-4-5-20251001
CLAUDE_SONNET_MODEL=claude-sonnet-4-6
CLAUDE_DEEP_MODEL=claude-opus-4-6

# CLI rate limiter (prevents 529 rate limit errors on Max subscription)
CLI_MAX_CONCURRENT=2    # Max simultaneous CLI API calls (default: 2)
CLI_MIN_SPACING_MS=500  # Min delay between calls in ms (default: 500)
```

> **Config ownership rules:**
>
> | What | Where | Examples |
> |------|-------|---------|
> | Infrastructure | `.env` (or env vars) | `DATABASE_URL`, `HOST`, `PORT`, API keys |
> | App preferences | Settings UI → DB (`app_settings` table) | Models, TTS config, personality, UI prefs |
> | Defaults | `config.py` | Sensible XDG-compliant fallbacks (never instance-specific) |
>
> **Database location:** `~/.voxyflow/voxyflow.db` (created automatically on first run).
> ChromaDB data is stored at `~/.voxyflow/chroma/`.

### Run the backend

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Expected output:
```
INFO  🚀 Voxyflow starting up...
INFO  ✅ Database initialized
INFO  ✅ RAGService initialized (ChromaDB + intfloat/multilingual-e5-large)
INFO  Application startup complete.
INFO  Uvicorn running on http://0.0.0.0:8000
```

If ChromaDB is not installed:
```
WARNING ⚠️  RAGService disabled (chromadb not installed)
```
Chat still works — RAG context injection is simply skipped.

---

## 3. Frontend Setup

```bash
cd ../frontend-react
npm install
```

### Configure environment (optional)

```bash
cp .env.example .env
```

```env
# Override if backend is not on localhost:8000
# VOXYFLOW_API_URL=http://<your-server-ip>:8000
# VOXYFLOW_WS_URL=ws://<your-server-ip>:8000/ws
```

By default, the frontend proxies API and WebSocket requests to `localhost:8000` via Vite dev server config.

### Run the dev server

```bash
npm run dev
```

Opens at `http://localhost:3000`. Hot module replacement enabled.

### Production build

```bash
npm run build
```

Output in `dist/` — static files ready to serve via any web server (Nginx, Caddy, etc.).

---

## 4. LLM Backend Setup

### CLI Subprocess — Recommended (`CLAUDE_USE_CLI=true`)

Uses your Claude Max subscription by spawning `claude -p` subprocesses. No API key needed.

1. Install the Claude CLI: https://docs.anthropic.com/en/docs/claude-cli
2. Sign in: `claude login`
3. Set in `backend/.env`:
   ```env
   CLAUDE_USE_CLI=true
   CLAUDE_FAST_MODEL=claude-haiku-4-5-20251001
   CLAUDE_SONNET_MODEL=claude-sonnet-4-6
   CLAUDE_DEEP_MODEL=claude-opus-4-6
   ```

**Rate limiting:** The CLI backend includes a built-in rate gate (`CliRateGate`) that prevents 529 "overloaded" errors from the Max subscription. It limits concurrent API calls and enforces minimum spacing between requests. Configure via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `CLI_MAX_CONCURRENT` | `2` | Maximum simultaneous CLI API calls across all layers and workers |
| `CLI_MIN_SPACING_MS` | `500` | Minimum delay (ms) between consecutive API calls to prevent bursts |

Increase `CLI_MAX_CONCURRENT` if you have headroom on your subscription and want faster parallel worker execution. Decrease it if you share your Max subscription across multiple machines or sessions.

### Native Anthropic SDK (`CLAUDE_USE_NATIVE=true`)

Direct API calls via the `anthropic` Python SDK. Requires an API key.

1. Set in `backend/.env`:
   ```env
   CLAUDE_USE_NATIVE=true
   CLAUDE_API_KEY=sk-ant-...
   ```

Or store the key in the system keyring:

```bash
python setup_keys.py
```

### OpenAI-Compatible Proxy (deprecated fallback)

Legacy path using a proxy at `localhost:3457`. Being deprecated — avoid for new installs.

```env
CLAUDE_PROXY_URL=http://localhost:3457/v1
```

---

## 5. Optional: ChromaDB & RAG

RAG is automatically enabled when `chromadb` and `sentence-transformers` are installed (they are in `requirements.txt` by default).

**First-run note:** `sentence-transformers` downloads the `intfloat/multilingual-e5-large` model (~2.2GB) on first use. This is a one-time download, cached at `~/.cache/huggingface/`.

**To disable RAG:**
```bash
pip uninstall chromadb sentence-transformers
```
RAGService will silently disable itself on next startup.

---

## 6. Optional: GitHub Integration

Voxyflow uses the `gh` CLI for GitHub repo validation and cloning.

```bash
# Install gh CLI (https://cli.github.com/)
# Ubuntu/Debian:
sudo apt install gh

# Authenticate
gh auth login
```

Without `gh`, GitHub-related features (repo validation, project GitHub linking) will return 503 errors.

---

## 7. Optional: TTS Setup

Voxyflow supports two TTS backends. No configuration is required for basic voice output — the browser handles it by default.

### Backend 1: Browser speechSynthesis (default, no setup)

Works out of the box in Chrome, Edge, Firefox, and Safari. Uses the operating system's built-in voice engine. Quality varies by platform.

No configuration needed — TTS is enabled by default in Settings → Voice.

### Backend 2: XTTS v2 Server (high-quality, GPU recommended)

XTTS v2 (Coqui TTS) produces significantly more natural speech and supports voice cloning. It runs as a separate HTTP server, typically on a machine with a GPU.

#### Install the XTTS server

The server is not included in this repo. Install Coqui TTS with the XTTS v2 model:

```bash
pip install TTS
```

#### Create a server script

Save as `tts_server.py` on your TTS machine:

```python
from TTS.api import TTS
from flask import Flask, request, send_file
import io, torch

app = Flask(__name__)
device = "cuda" if torch.cuda.is_available() else "cpu"
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)

@app.route("/speak", methods=["POST"])
def speak():
    data = request.json
    text = data.get("text", "")
    language = data.get("language", "en")
    buf = io.BytesIO()
    tts.tts_to_file(
        text=text,
        language=language,
        speaker="Claribel Dervla",  # or any XTTS speaker
        file_path=buf,
    )
    buf.seek(0)
    return send_file(buf, mimetype="audio/wav")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5500)
```

```bash
python tts_server.py
```

On first run, XTTS v2 downloads its model (~2GB), cached in `~/.local/share/tts/`.

#### Connect Voxyflow to the server

In Voxyflow, go to **Settings → Voice** and set the **TTS Server URL** to the address of your XTTS server:

```
http://localhost:5500
```

The backend proxies TTS requests to avoid CORS and mixed-content issues — the frontend calls `/api/settings/tts/speak`, and the backend forwards to your XTTS server.

**Streaming:** Voxyflow uses sentence-by-sentence SSE streaming (`/api/settings/tts/speak_stream`). Sentences are synthesized sequentially and audio starts playing before the full response is ready. It first tries the XTTS native `/tts_stream` endpoint, then falls back to `/speak`.

**Fallback behavior:** If the XTTS server is unreachable, TTS automatically falls back to browser `speechSynthesis`. TTS failures are non-fatal — text responses are always delivered.

### STT (Speech-to-Text)

STT is also configured via **Settings → Voice**:

| Engine | Setup | Privacy | Quality |
|--------|-------|---------|---------|
| Web Speech API (default) | None — works in Chrome/Edge | Audio sent to Google | Good, real-time |
| Whisper WASM | Select model in Settings → Voice | 100% local, no server | Excellent, slight delay |

**Whisper WASM:** Runs in a browser WebWorker. Select a HuggingFace model ID in Settings → Voice (e.g. `onnx-community/whisper-small`). The model downloads to browser cache (~150MB–750MB depending on size). No server or GPU needed.

---

## 8. First Run & Onboarding

### Start both servers

```bash
# Terminal 1 — Backend
cd voxyflow/backend && source venv/bin/activate
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd voxyflow/frontend-react
npm run dev
```

Open `http://localhost:3000`.

### Verify backend health

```bash
curl http://localhost:8000/health
# → {"status":"ok","service":"voxyflow"}
```

### Onboarding checklist

- [ ] Backend running at `http://localhost:8000`
- [ ] `GET /health` returns `{"status": "ok"}`
- [ ] Frontend running at `http://localhost:3000`
- [ ] WebSocket connects (browser console shows `[ApiClient] WebSocket connected`)
- [ ] LLM backend responds to a test message in chat
- [ ] **Settings → General** — set your name and the assistant's name
- [ ] **Settings → Personality** — review or edit `IDENTITY.md` and `USER.md`
- [ ] **Settings → Voice** — choose STT engine, configure TTS server URL if using XTTS

### Personality files

On first run, `IDENTITY.md` and `USER.md` are generated automatically in `voxyflow/personality/` using your name and the assistant name from Settings. `SOUL.md` and `AGENTS.md` must exist in the repo (they are checked in).

To regenerate `USER.md` or `IDENTITY.md` from the default template:
**Settings → Personality → Reset to Default**

Files you can edit via the Settings UI:
- `USER.md` — information about you (language, preferences, timezone)
- `IDENTITY.md` — assistant name, emoji, vibe

Files edited directly (not via UI):
- `SOUL.md` — core behavior and traits
- `AGENTS.md` — agent operating rules and safety constraints

---

## Running in Production

```bash
# Backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
# Note: workers=1 required — WebSocket sessions use in-memory state

# Frontend — build and serve static files
cd frontend-react && npm run build
# Serve dist/ via Caddy or Nginx
```

### Caddy config (recommended)

```caddyfile
voxyflow.example.com {
  handle /api/* { reverse_proxy localhost:8000 }
  handle /ws    { reverse_proxy localhost:8000 }
  handle        { root * /path/to/frontend-react/dist; file_server }
}
```

Caddy handles TLS automatically via Let's Encrypt. For LAN with self-signed cert:

```caddyfile
voxyflow.local {
  tls internal
  handle /api/* { reverse_proxy localhost:8000 }
  handle /ws    { reverse_proxy localhost:8000 }
  handle        { root * /path/to/frontend-react/dist; file_server }
}
```

**WebSocket behind HTTPS:** Update the frontend `.env` before building:
```env
VOXYFLOW_WS_URL=wss://voxyflow.example.com/ws
```

**HTTPS requirements:** Web Speech API, microphone access, and service worker all require HTTPS in production.

### systemd service (backend)

```ini
# ~/.config/systemd/user/voxyflow-backend.service
[Unit]
Description=Voxyflow Backend
After=network.target

[Service]
Type=simple
WorkingDirectory=/home/youruser/voxyflow/backend
EnvironmentFile=/home/youruser/voxyflow/backend/.env
ExecStart=/home/youruser/voxyflow/backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now voxyflow-backend
journalctl --user -u voxyflow-backend -f
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `WebSocket connection failed` | Check backend is running; verify `VOXYFLOW_WS_URL` in frontend `.env` |
| `chromadb not found` | `pip install chromadb sentence-transformers` |
| `RAGService init failed` | Check `~/.voxyflow/chroma/` permissions |
| `GitHub: gh not installed` | Install `gh` CLI or configure PAT in Settings |
| No LLM response | Check `CLAUDE_USE_CLI=true` in `.env` and `claude` CLI is installed and authenticated |
| `529 rate_limit` / chat hangs | Too many concurrent CLI calls — lower `CLI_MAX_CONCURRENT` or close other Claude sessions |
| STT not working | Chrome/Edge required for Web Speech API; check microphone permissions; HTTPS required in production |
| TTS silent | Check TTS Server URL in Settings → Voice is reachable; check backend logs for proxy errors |
| Whisper WASM won't load | Set a valid HuggingFace model ID in Settings → Voice (e.g. `onnx-community/whisper-small`) |
| Personality files missing | Auto-generated on startup — check `voxyflow/personality/`; or use Settings → Personality → Reset |
| Scheduler not running | `GET /api/health` should show `scheduler_running: true`; check `apscheduler` is installed |
| Jobs not executing | Check `~/.voxyflow/jobs.json` is writable; trigger manually via `POST /api/jobs/{id}/run` |
