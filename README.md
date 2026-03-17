# 🎙️ Voxyflow

**Voice-first project management assistant with multi-model orchestration.**

Talk to Voxyflow. It listens, understands, responds with voice, and auto-generates project cards from your conversation. Under the hood, Claude Haiku gives you instant responses while Opus thinks deeper in the background.

## Architecture

```
Browser (PWA) ↔ WebSocket ↔ thething (FastAPI) → Claude API
                                                → TTS (local CPU)
                                                → SQLite
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full architecture document.

## Quick Start

```bash
cd backend

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your Claude API key

# Run
python -m app.main
# or: uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs at: http://localhost:8000/docs

## Project Structure

```
voxyflow/
├── backend/
│   ├── app/
│   │   ├── main.py          — FastAPI app entry point
│   │   ├── config.py        — Settings from .env
│   │   ├── database.py      — SQLAlchemy models + DB setup
│   │   ├── models/          — Pydantic request/response schemas
│   │   │   ├── chat.py
│   │   │   ├── project.py
│   │   │   ├── card.py
│   │   │   └── voice.py     — WebSocket message types
│   │   ├── routes/           — API endpoints
│   │   │   ├── chats.py
│   │   │   ├── projects.py
│   │   │   ├── cards.py
│   │   │   └── voice.py     — WebSocket voice handler
│   │   └── services/         — Business logic
│   │       ├── chat_service.py
│   │       ├── claude_service.py    — Haiku + Opus layers
│   │       ├── tts_service.py       — Sherpa-ONNX / remote
│   │       └── analyzer_service.py  — Card detection
│   ├── requirements.txt
│   └── .env.example
├── frontend/                 — PWA (future)
├── docs/
│   └── ARCHITECTURE.md       — Full architecture document
└── README.md
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/api/chats` | Create a chat |
| `GET` | `/api/chats` | List chats |
| `GET` | `/api/chats/{id}` | Get chat with messages |
| `POST` | `/api/chats/{id}/messages` | Add message |
| `POST` | `/api/projects` | Create project |
| `GET` | `/api/projects` | List projects |
| `GET` | `/api/projects/{id}` | Get project with cards |
| `PATCH` | `/api/projects/{id}` | Update project |
| `POST` | `/api/projects/{id}/cards` | Create card |
| `GET` | `/api/projects/{id}/cards` | List cards |
| `PATCH` | `/api/cards/{id}` | Update card |
| `DELETE` | `/api/cards/{id}` | Delete card |
| `WS` | `/api/ws/voice/{chat_id}` | Voice WebSocket |

## Multi-Model Architecture

1. **Haiku (Layer 1):** Instant conversational response (<1s)
2. **Opus (Layer 2):** Background deep analysis, enriches when it has something better
3. **Analyzer (Layer 3):** Watches for task opportunities, suggests cards

## Tech Stack

- **Backend:** FastAPI + SQLAlchemy (async)
- **Database:** SQLite (MVP) → Postgres
- **LLM:** Claude Haiku + Opus via API
- **TTS:** Sherpa-ONNX (CPU) or remote endpoint
- **STT:** Web Speech API (browser) + Whisper fallback
- **Transport:** WebSocket for real-time voice

## Status

🟡 **MVP Scaffold** — Structure complete, services stubbed, ready for implementation.

### Next Steps

1. Frontend PWA with voice capture
2. Wire Claude API calls (add API key)
3. Set up Sherpa-ONNX TTS model
4. Define WebSocket binary audio protocol
5. Build card/kanban board UI
