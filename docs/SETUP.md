# Voxyflow — Setup Guide

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Node.js | 18+ | Frontend build & dev server |
| Python | 3.12+ | Backend (uses `asyncio`, type hints, `match` statements) |
| claude-max-api-proxy | any | Or any OpenAI-compatible API proxy |
| Git | any | |
| `gh` CLI | any | Optional — for GitHub repo integration |

**Optional (for RAG/knowledge base):**
- ChromaDB-compatible system (runs on any modern Linux/macOS/Windows)
- `sentence-transformers` downloads ~2.2GB model on first run (intfloat/multilingual-e5-large)

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
- `httpx` — HTTP client for Claude API calls
- `keyring` + `keyrings.alt` — secure key storage
- `openai` — OpenAI-compatible client (used for Claude proxy)
- `python-multipart` — file upload support
- `apscheduler` — background task scheduler (heartbeat + RAG indexing + user-defined jobs)
- `chromadb` + `sentence-transformers` — RAG (optional but installed by default)
- `pypdf` — PDF document parsing for RAG (Phase 2, optional)
- `python-docx` — DOCX document parsing for RAG (Phase 2, optional)
- `openpyxl` — XLSX/Excel document parsing for RAG (Phase 2, optional)

### Configure environment

```bash
cp .env.example .env
```

Edit `.env` as needed. See `.env.example` for all available variables.

> **Config ownership rules:**
>
> | What | Where | Examples |
> |------|-------|---------|
> | Infrastructure | `.env` (or env vars) | `DATABASE_URL`, `HOST`, `PORT`, `CLAUDE_PROXY_URL`, API keys |
> | App preferences | Settings UI → DB (`app_settings` table) | Model names, TTS config, personality, UI prefs |
> | Defaults | `config.py` | Sensible XDG-compliant fallbacks (never instance-specific) |
>
> **Database location:** `~/.voxyflow/voxyflow.db` (created automatically on first run).
> The directory `~/.voxyflow/` follows the XDG user data pattern and also stores ChromaDB data at `~/.voxyflow/chroma/`.
> Do **not** use a relative path like `./voxyflow.db` — this causes the DB to land in different locations depending on the working directory.

Key `.env` variables:

```env
# Database (default: ~/.voxyflow/voxyflow.db — usually no override needed)
# DATABASE_URL=sqlite+aiosqlite:////home/youruser/.voxyflow/voxyflow.db

# Network
HOST=0.0.0.0
PORT=8000

# Claude proxy
CLAUDE_PROXY_URL=http://localhost:3457/v1
```

### Store API keys securely (recommended)

Voxyflow uses the system keyring to store API keys rather than plain `.env` files.

```bash
python setup_keys.py
```

This will prompt for your Anthropic API key (or proxy key) and store it in the system keyring (`service=voxyflow`).

**Alternative (headless/CI):** Set `ANTHROPIC_API_KEY` as an environment variable.

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
WARNING ⚠️  RAGService disabled (chromadb not installed — install chromadb + sentence-transformers to enable)
```
Chat still works; RAG context injection is simply skipped.

---

## 3. Frontend Setup

```bash
cd ../frontend
npm install
```

### Configure environment (optional)

```bash
cp .env.example .env
```

```env
# Override if backend is not on localhost:8000
# VOXYFLOW_API_URL=http://192.168.1.100:8000
# VOXYFLOW_WS_URL=ws://192.168.1.100:8000/ws
```

By default, the frontend proxies API and WebSocket requests to `localhost:8000` via Webpack DevServer config.

### Run the dev server

```bash
npm run dev
```

Opens at `http://localhost:3000` (or next available port). Hot module replacement enabled.

### Production build

```bash
npm run build
```

Output in `dist/` — static files ready to serve via any web server (Nginx, Caddy, etc.).

---

## 4. Claude Proxy Setup

Voxyflow uses an OpenAI-compatible API endpoint to call Claude. The default setup expects `claude-max-api-proxy` running at `http://localhost:3456`.

### Using claude-max-api-proxy

```bash
# Install
npm install -g claude-max-api-proxy  # or your preferred install method

# Start
claude-max-api-proxy
# Runs at http://localhost:3456
```

### Using the Anthropic API directly

If you have a direct Anthropic API key, configure the backend to use `https://api.anthropic.com/v1` instead:

1. Open Voxyflow → Settings → Models
2. Set **Provider URL** to `https://api.anthropic.com/v1`
3. Set **API Key** to your `sk-ant-...` key
4. Set appropriate model names (`claude-3-5-sonnet-20241022`, etc.)

### Using Ollama (local models)

```bash
# Start Ollama
ollama serve

# Configure in Settings → Models
# Provider URL: http://localhost:11434/v1
# API Key: (leave empty)
# Model: qwen2.5:7b (or any installed model)
```

---

## 5. Optional: ChromaDB & RAG

RAG is automatically enabled if `chromadb` and `sentence-transformers` are installed (they are in `requirements.txt`).

**First-run note:** `sentence-transformers` downloads the `intfloat/multilingual-e5-large` model (~2.2GB) on first use. This happens once and is cached in `~/.cache/huggingface/`.

**ChromaDB storage:** Data persists to `~/.voxyflow/chroma/`. This directory is created automatically.

**To disable RAG:** Simply uninstall chromadb:
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

# Or: configure a PAT in Voxyflow Settings → GitHub
```

Without `gh`, GitHub-related features (repo validation, project GitHub linking) will return 503 errors.

---

## 7. Optional: TTS (Text-to-Speech)

The voice WebSocket pipeline optionally generates audio responses via a TTS service.

**Default:** `TTS_ENGINE=sherpa-onnx` — expects a local sherpa-onnx HTTP server.

**XTTS v2 (recommended for high quality):**
```env
TTS_ENGINE=remote
TTS_SERVICE_URL=http://localhost:5500
```

**Disable TTS:** Set `TTS_ENGINE=none` or leave the service URL unreachable. TTS failures are non-fatal — text responses are still sent.

---

## 8. First Run Checklist

- [ ] Backend running at `http://localhost:8000`
- [ ] `GET http://localhost:8000/health` returns `{"status": "ok"}`
- [ ] Frontend running at `http://localhost:3000`
- [ ] WebSocket connects (check browser console — `[ApiClient] WebSocket connected`)
- [ ] API proxy running (Fast model responds to a test message)
- [ ] Settings → Models configured with correct provider URL and model names
- [ ] (Optional) Upload a `.md` file to test RAG

### Verify backend health

```bash
curl http://localhost:8000/health
# → {"status":"ok","service":"voxyflow"}

curl http://localhost:8000/api/tech/detect?project_path=.
# → {"path":"...","technologies":[...],"file_counts":{...}}
```

---

## Personality Setup

On first run, the personality directory (`voxyflow/personality/`) may be empty. Go to **Settings → Personality** and click **Reset to Default** for each file to generate the default templates.

Or create files manually at `voxyflow/personality/`:
- `SOUL.md` — personality and behavior
- `USER.md` — info about you
- `AGENTS.md` — agent operating rules
- `IDENTITY.md` — bot name, emoji, avatar

---

## Running in Production

For a production deployment:

```bash
# Backend
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
# Note: Use workers=1 for WebSocket sessions (no shared in-memory state with multiple workers)

# Frontend — build and serve static files
cd frontend && npm run build
# Serve dist/ via Caddy/Nginx
```

### HTTPS Setup

For HTTPS (strongly recommended in production), use a reverse proxy. Example Caddy config (`/etc/caddy/Caddyfile`):

```
voxyflow.example.com {
  # API + WebSocket → backend
  handle /api/* {
    reverse_proxy localhost:8000
  }
  handle /ws {
    reverse_proxy localhost:8000
  }
  # Static frontend
  handle {
    root * /path/to/frontend/dist
    file_server
  }
}
```

Caddy handles TLS certificate provisioning automatically (Let's Encrypt). For self-signed certs on LAN:

```
voxyflow.local {
  tls internal
  handle /api/* { reverse_proxy localhost:8000 }
  handle /ws    { reverse_proxy localhost:8000 }
  handle        { root * /path/to/frontend/dist; file_server }
}
```

**WebSocket note:** When running behind HTTPS, update the frontend `.env`:
```env
VOXYFLOW_WS_URL=wss://voxyflow.example.com/ws
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `WebSocket connection failed` | Check backend is running and `WS_URL` in constants.ts points to correct host |
| `chromadb not found` | `pip install chromadb sentence-transformers` |
| `RAGService init failed` | Check `~/.voxyflow/chroma/` permissions |
| `GitHub: gh not installed` | Install `gh` CLI or configure PAT in Settings |
| No API response | Check proxy is running at `provider_url` in Settings → Models |
| STT not working | Chrome/Edge required for Web Speech API; check microphone permissions |
| TTS silent | Check `TTS_SERVICE_URL` is reachable; TTS failures are non-fatal |
| PDF/DOCX upload fails | `pip install pypdf python-docx openpyxl` for Phase 2 document support |
| Scheduler not running | Check `apscheduler` is installed; `GET /api/health` should show `scheduler_running: true` |
| Jobs not executing | Check `~/.voxyflow/jobs.json` is writable; trigger manually via `POST /api/jobs/{id}/run` |
