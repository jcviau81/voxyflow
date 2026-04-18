# Voxyflow Backend

FastAPI backend for Voxyflow — voice-first project management assistant.

## Stack

- **Python 3.12+**
- **FastAPI** — async web framework
- **SQLite** — lightweight persistent storage
- **Claude API** — AI conversation engine
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
    │   ├── project.py       # Project models
    │   └── voice.py         # Voice/STT models
    ├── routes/
    │   ├── cards.py         # Card CRUD endpoints
    │   ├── chats.py         # Chat endpoints
    │   ├── projects.py      # Project endpoints
    │   └── voice.py         # Voice/TTS endpoints
    └── services/
        ├── agent_personas.py    # 7 specialist personas
        ├── agent_router.py      # Intent → agent routing
        ├── agent_router.py      # Agent routing
        ├── chat_service.py      # Chat orchestration
        ├── claude_service.py    # Claude API client
        ├── memory_service.py    # Conversation memory
        ├── personality_service.py # SOUL.md personality
        └── tts_service.py       # Text-to-speech
```

## 🔐 API Key Setup

API keys are only needed for the direct-SDK / non-CLI providers. The preferred path is the **Settings UI** (Settings → Models → Add Machine); keys entered there are saved to the app database.

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
# Edit .env with your Claude API key

# Run development server
uvicorn app.main:app --reload --port 8000
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send message, get AI response |
| GET | `/api/chat/history/{project_id}` | Get chat history |
| POST | `/api/voice/transcribe` | Transcribe audio |
| POST | `/api/voice/synthesize` | Text-to-speech |
| GET | `/api/projects` | List projects |
| POST | `/api/projects` | Create project |
| GET | `/api/cards/{project_id}` | Get project cards |
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
- 🎯 **Project Manager** — Planning & coordination

## Environment Variables

See `.env.example` for all required configuration.
