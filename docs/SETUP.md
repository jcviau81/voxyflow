# Voxyflow — Setup Guide

> **SECURITY WARNING**
> Voxyflow has **no authentication system** (no login/password). It must be run behind closed doors.
> **Recommended configurations:**
> - **Tailscale tunnel** — secure access via private network
> - **Local network only** — not exposed to the internet
> - **Personal machine only** — single-user local setup
>
> **Do NOT expose Voxyflow directly to the internet without additional protection.**

---

## Path Conventions

All paths in this documentation use **default install locations**. Both can be overridden via environment variables:

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
| Git | any | |

**LLM backend (at least one):**
- Claude CLI (`claude`) — for CLI backend (recommended with Claude Max subscription)
- Anthropic API key — for native Anthropic SDK
- Any OpenAI-compatible endpoint — Ollama, LM Studio, Groq, Mistral, OpenAI, Gemini, OpenRouter

**Optional (for RAG/knowledge base):**
- `chromadb` + `sentence-transformers` — installed by default via `requirements.txt`
- Downloads ~2.2GB model on first run (`intfloat/multilingual-e5-large`), cached in `~/.cache/huggingface/`

**Optional (for high-quality TTS):**
- XTTS v2 server — separate GPU machine or container (see [TTS Setup](#7-optional-tts-setup))
- Without it, TTS falls back to browser `speechSynthesis` (works out of the box)

---

## Manual Setup

### 1. Clone the Repo

```bash
git clone https://github.com/your-org/voxyflow.git
cd voxyflow
```

### 2. Backend Setup

#### Create and activate virtual environment

```bash
cd backend
python3.12 -m venv venv
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  # Windows
```

#### Install dependencies

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

#### Configure environment

```bash
cp .env.example .env
```

Edit `.env` as needed. Minimal config (CLI backend):

```env
CLAUDE_USE_CLI=true
CLAUDE_FAST_MODEL=claude-haiku-4-5-20251001
CLAUDE_SONNET_MODEL=claude-sonnet-4-6
CLAUDE_DEEP_MODEL=claude-opus-4-7
```

> **Config ownership rules:**
>
> | What | Where | Examples |
> |------|-------|---------|
> | Infrastructure | `.env` (or env vars) | `DATABASE_URL`, `HOST`, `PORT`, API keys |
> | App preferences | Settings UI (stored in DB) | Models, TTS config, personality, UI prefs |
> | Defaults | `config.py` | Sensible XDG-compliant fallbacks (never instance-specific) |
>
> **Database location:** `~/.voxyflow/voxyflow.db` (created automatically on first run).
> ChromaDB data is stored at `~/.voxyflow/chroma/`.

#### Run the backend

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Expected output:
```
INFO  Voxyflow starting up...
INFO  Database initialized
INFO  RAGService initialized (ChromaDB + intfloat/multilingual-e5-large)
INFO  Application startup complete.
INFO  Uvicorn running on http://0.0.0.0:8000
```

If ChromaDB is not installed:
```
WARNING  RAGService disabled (chromadb not installed)
```
Chat still works — RAG context injection is simply skipped.

### 3. Frontend Setup

```bash
cd ../frontend-react
npm install
```

#### Configure environment (optional)

```bash
cp .env.example .env
```

```env
# Override if backend is not on localhost:8000
# VOXYFLOW_API_URL=http://<your-server-ip>:8000
# VOXYFLOW_WS_URL=ws://<your-server-ip>:8000/ws
```

By default, the frontend proxies API and WebSocket requests to `localhost:8000` via Vite dev server config.

#### Run the dev server

```bash
npm run dev
```

Opens at `http://localhost:3000`. Hot module replacement enabled.

#### Production build

```bash
npm run build
```

Output in `dist/` — static files ready to serve via any web server (Nginx, Caddy, etc.).

---

## 4. LLM Provider Setup

Voxyflow supports multiple LLM providers through a provider abstraction layer. Each chat layer (Fast and Deep) can independently use any provider. Providers are configured via the **Settings > Models** UI or via environment variables.

### Supported Providers

| Provider | Type | API Key | Local | Default URL |
|----------|------|---------|-------|-------------|
| Claude CLI | `cli` | No (uses Max subscription) | Yes | — |
| Anthropic (Claude) | `anthropic` | Yes | No | `https://api.anthropic.com` |
| OpenAI | `openai` | Yes | No | `https://api.openai.com/v1` |
| Ollama | `ollama` | No | Yes | `http://localhost:11434` |
| Groq | `groq` | Yes | No | `https://api.groq.com/openai/v1` |
| Mistral AI | `mistral` | Yes | No | `https://api.mistral.ai/v1` |
| Google Gemini | `gemini` | Yes | No | `https://generativelanguage.googleapis.com/v1beta/openai` |
| LM Studio | `lmstudio` | No | Yes | `http://localhost:1234/v1` |
| OpenRouter | `openrouter` | Yes | No | `https://openrouter.ai/api/v1` |

### Option A: Claude CLI (recommended for Claude Max subscribers)

Uses your Claude Max subscription by spawning `claude -p` subprocesses. No API key needed.

1. Install the Claude CLI: https://docs.anthropic.com/en/docs/claude-cli
2. Sign in: `claude login`
3. Set in `backend/.env`:
   ```env
   CLAUDE_USE_CLI=true
   CLAUDE_FAST_MODEL=claude-haiku-4-5-20251001
   CLAUDE_SONNET_MODEL=claude-sonnet-4-6
   CLAUDE_DEEP_MODEL=claude-opus-4-7
   ```

**Rate limiting:** The CLI backend uses a dual-semaphore rate gate (`CliRateGate`) that gives session (dispatcher/chat) and worker CLI calls independent concurrency pools, so background workers never starve interactive chat. Configure via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `CLI_SESSION_CONCURRENT` | `5` | Maximum simultaneous CLI calls for dispatcher/chat sessions |
| `CLI_WORKER_CONCURRENT` | `15` | Maximum simultaneous CLI calls for background workers |
| `CLI_MIN_SPACING_MS` | `0` | Minimum delay (ms) between consecutive API calls |
| `MAX_WORKERS` | `15` | Maximum parallel workers in DeepWorkerPool (per session) |

Increase `CLI_WORKER_CONCURRENT` and `MAX_WORKERS` if you have headroom on your subscription. Decrease them if you share your Max subscription across multiple machines.

### Option B: Anthropic API (direct SDK)

Direct API calls via the `anthropic` Python SDK. Requires an API key.

1. Set in `backend/.env`:
   ```env
   CLAUDE_USE_NATIVE=true
   CLAUDE_API_KEY=sk-ant-...
   ```

Or store the key in the system keyring:
```bash
keyring set voxyflow claude_api_key
```

### Option C: Settings UI (any provider)

The most flexible approach — configure providers entirely through the web UI. No `.env` changes needed beyond the basic app config.

1. Start Voxyflow with default settings
2. Go to **Settings > Models**
3. **Add a Machine** — save a named endpoint (e.g. "My Ollama", "Groq Cloud"):
   - Pick a provider type (Ollama, OpenAI, Groq, etc.)
   - Enter the base URL (auto-filled for known providers)
   - Add an API key if required
4. **Configure layers** — assign a provider and model to each layer (Fast / Deep):
   - Select a saved machine or enter provider details directly
   - Pick a model from the auto-discovered list
5. **Configure worker classes** (optional) — route specific task types to dedicated LLMs (e.g. "Coding" tasks to a powerful model, "Research" tasks to a fast model)

The UI shows live reachability status for each configured endpoint and displays model capabilities (tool use, vision, context window).

### Examples: Local Models

**Ollama:**
```bash
# Install Ollama (https://ollama.com)
ollama pull qwen2.5:14b
# Ollama serves at http://localhost:11434 by default
```
Then in Settings > Models, add a machine with type "Ollama" and assign the model to a layer.

**LM Studio:**
```bash
# Install LM Studio (https://lmstudio.ai)
# Download a model and start the local server
# LM Studio serves at http://localhost:1234 by default
```

### Examples: Cloud Providers

**Groq:**
1. Get an API key from https://console.groq.com
2. In Settings > Models, add a machine with type "Groq", paste your API key
3. Select a model (e.g. `llama-3.3-70b-versatile`) for the Fast layer

**OpenRouter:**
1. Get an API key from https://openrouter.ai/keys
2. In Settings > Models, add a machine with type "OpenRouter", paste your API key
3. Access hundreds of models from various providers through a single endpoint

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

No configuration needed — TTS is enabled by default in Settings > Voice.

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

In Voxyflow, go to **Settings > Voice** and set the **TTS Server URL** to the address of your XTTS server:

```
http://localhost:5500
```

The backend proxies TTS requests to avoid CORS and mixed-content issues — the frontend calls `/api/settings/tts/speak`, and the backend forwards to your XTTS server.

**Streaming:** Voxyflow uses sentence-by-sentence SSE streaming (`/api/settings/tts/speak_stream`). Sentences are synthesized sequentially and audio starts playing before the full response is ready. It first tries the XTTS native `/tts_stream` endpoint, then falls back to `/speak`.

**Fallback behavior:** If the XTTS server is unreachable, TTS automatically falls back to browser `speechSynthesis`. TTS failures are non-fatal — text responses are always delivered.

### STT (Speech-to-Text)

STT is also configured via **Settings > Voice**:

| Engine | Setup | Privacy | Quality |
|--------|-------|---------|---------|
| Web Speech API (default) | None — works in Chrome/Edge | Audio sent to Google | Good, real-time |
| Whisper WASM | Select model in Settings > Voice | 100% local, no server | Excellent, slight delay |

**Whisper WASM:** Runs in a browser WebWorker. Select a HuggingFace model ID in Settings > Voice (e.g. `onnx-community/whisper-small`). The model downloads to browser cache (~150MB-750MB depending on size). No server or GPU needed.

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
# {"status":"ok","service":"voxyflow"}
```

### Onboarding checklist

- [ ] Backend running at `http://localhost:8000`
- [ ] `GET /health` returns `{"status": "ok"}`
- [ ] Frontend running at `http://localhost:3000`
- [ ] WebSocket connects (browser console shows `[ApiClient] WebSocket connected`)
- [ ] LLM backend responds to a test message in chat
- [ ] **Settings > General** — set your name and the assistant's name
- [ ] **Settings > Models** — configure at least one LLM provider
- [ ] **Settings > Personality** — review or edit `IDENTITY.md` and `USER.md`
- [ ] **Settings > Voice** — choose STT engine, configure TTS server URL if using XTTS

### Personality files

On first run, `IDENTITY.md` and `USER.md` are generated automatically in `voxyflow/personality/` using your name and the assistant name from Settings. `SOUL.md` and `AGENTS.md` must exist in the repo (they are checked in).

To regenerate `USER.md` or `IDENTITY.md` from the default template:
**Settings > Personality > Reset to Default**

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
  handle /ws/*  { reverse_proxy localhost:8000 }
  handle        { root * /path/to/frontend-react/dist; file_server }
}
```

Caddy handles TLS automatically via Let's Encrypt. For LAN with self-signed cert:

```caddyfile
voxyflow.local {
  tls internal
  handle /api/* { reverse_proxy localhost:8000 }
  handle /ws    { reverse_proxy localhost:8000 }
  handle /ws/*  { reverse_proxy localhost:8000 }
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
| No LLM response | Check provider configuration in Settings > Models; verify API keys and endpoint reachability |
| `529 rate_limit` / chat hangs | Too many concurrent CLI calls — lower `CLI_SESSION_CONCURRENT` / `CLI_WORKER_CONCURRENT` or close other Claude sessions |
| Provider unreachable | Use Settings > Models to test endpoint connectivity; check firewall/network |
| STT not working | Chrome/Edge required for Web Speech API; check microphone permissions; HTTPS required in production |
| TTS silent | Check TTS Server URL in Settings > Voice is reachable; check backend logs for proxy errors |
| Whisper WASM won't load | Set a valid HuggingFace model ID in Settings > Voice (e.g. `onnx-community/whisper-small`) |
| Personality files missing | Auto-generated on startup — check `voxyflow/personality/`; or use Settings > Personality > Reset |
| Scheduler not running | `GET /api/health` should show `scheduler_running: true`; check `apscheduler` is installed |
| Jobs not executing | Check `~/.voxyflow/jobs.json` is writable; trigger manually via `POST /api/jobs/{id}/run` |
