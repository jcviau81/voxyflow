# Voxyflow Backend

FastAPI backend for Voxyflow — voice-first workspace management assistant.

## Stack

- **Python 3.12+**
- **FastAPI** — async web framework
- **SQLite** — lightweight persistent storage
- **Multi-provider LLM** — Claude CLI, Codex CLI, native SDK, or OpenAI-compatible providers
- **Pydantic** — data validation

## Structure

```
backend/
├── requirements.txt
├── .env.example
└── app/
    ├── main.py              # FastAPI app entry point
    ├── config.py            # Environment & settings
    ├── database.py          # SQLite connection & migrations
    ├── models/
    │   ├── card.py          # Kanban card models
    │   ├── chat.py          # Chat/message models
    │   ├── workspace.py       # Workspace models
    │   └── voice.py         # Voice/STT models
    ├── routes/
    │   ├── cards.py         # Card CRUD endpoints
    │   ├── chats.py         # Chat endpoints
    │   ├── workspaces.py      # Workspace endpoints
    │   └── voice.py         # Voice/TTS endpoints
    └── services/
        ├── agent_personas.py    # 7 specialist personas
        ├── agent_router.py      # Intent → agent routing
        ├── agent_router.py      # Agent routing
        ├── chat_orchestration.py # Dispatcher/worker orchestration
        ├── claude_service.py    # LLM orchestration singleton
        ├── memory_service.py    # Conversation memory
        ├── personality_service.py # SOUL.md personality
        └── tts_service.py       # Text-to-speech
```

## 🔐 API Key Setup

API keys are only needed for direct-SDK / non-CLI providers. The preferred path is the **Settings UI** (Settings → Models → Add Machine); keys entered there are saved to the app database.

For env/keyring setup instead:

### Option A: `.env` file
```env
ANTHROPIC_API_KEY=sk-ant-...
```

### Option B: OS keyring (optional)
```bash
# uses the `keyring` CLI (installed as a dep of python-keyring)
keyring set voxyflow claude_api_key
```

### Key lookup order (for the legacy `claude_api_key` slot):
1. Settings UI (per-endpoint, stored in app DB)
2. OS keyring (`voxyflow` service, `claude_api_key` key)
3. Environment variable (`ANTHROPIC_API_KEY` / `CLAUDE_API_KEY`)
4. `.env` file

For Docker/headless environments, use environment variables.

## Quick Start

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Configure provider settings in Settings > Models or .env

# Run development server
uvicorn app.main:app --reload --port 8000
```

## Upgrading

If you're updating an existing install across the **project → workspace rename**
(2026-05), stop the backend and run the one-shot migration before starting it
again:

```bash
cd backend
./venv/bin/python -m scripts.migrate_project_to_workspace             # dry-run
./venv/bin/python -m scripts.migrate_project_to_workspace --apply --backup
```

It renames the SQLite table/columns, ChromaDB collections, and the on-disk
sandbox layout. Idempotent — re-running after success is a no-op.

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send message, get AI response |
| GET | `/api/chat/history/{workspace_id}` | Get chat history |
| POST | `/api/voice/transcribe` | Transcribe audio |
| POST | `/api/voice/synthesize` | Text-to-speech |
| GET | `/api/workspaces` | List workspaces |
| POST | `/api/workspaces` | Create workspace |
| GET | `/api/cards/{workspace_id}` | Get workspace cards |
| POST | `/api/cards` | Create card |
| PATCH | `/api/cards/{id}` | Update card |

## Agent Personas

The backend routes messages to specialized AI agents:

- 🔥 **Coder** — Code implementation & debugging
- 🏗️ **Architect** — System design & patterns
- 🎨 **Designer** — UI/UX guidance
- 📊 **Analyst** — Data & metrics
- 🧪 **Tester** — Testing & QA
- 🛡️ **Security** — Security review
- 🎯 **Workspace Manager** — Planning & coordination

## Environment Variables

See `.env.example` for all required configuration.
