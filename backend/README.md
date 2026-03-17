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
        ├── analyzer_service.py  # Message analysis
        ├── chat_service.py      # Chat orchestration
        ├── claude_service.py    # Claude API client
        ├── memory_service.py    # Conversation memory
        ├── personality_service.py # SOUL.md personality
        └── tts_service.py       # Text-to-speech
```

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

- 🔥 **La Codeuse** — Code implementation & debugging
- 🏗️ **L'Architecte** — System design & patterns
- 🎨 **Le Designer** — UI/UX guidance
- 📊 **L'Analyste** — Data & metrics
- 🧪 **Le Testeur** — Testing & QA
- 🛡️ **La Sécurité** — Security review
- 🎯 **Le Chef de Projet** — Planning & coordination

## Environment Variables

See `.env.example` for all required configuration.
