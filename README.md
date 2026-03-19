# 🎙️ Voxyflow

**AI-powered, voice-first project assistant.**

Talk to it. It listens, thinks, responds with voice, and turns your conversations into organized projects with cards, kanban boards, roadmaps, and docs. Three Claude models work together — one for fast chat, one for deep thinking, one for background analysis.

Built as a Progressive Web App. Runs locally. No cloud lock-in.

---

## Architecture

```
┌─────────────────────────────────┐
│  Browser (PWA)                  │
│  Vanilla TypeScript + Webpack   │
│  HTTPS :3000                    │
└────────────┬────────────────────┘
             │ REST + WebSocket
┌────────────▼────────────────────┐
│  FastAPI Backend :8000          │
│  ├─ Chat Pipeline (3 models)   │
│  ├─ Tool System (native)       │
│  ├─ MCP Server (SSE + stdio)   │
│  ├─ RAG (ChromaDB)             │
│  ├─ APScheduler                │
│  └─ SQLite (aiosqlite)         │
└────────────┬────────────────────┘
             │ OpenAI-compatible API
┌────────────▼────────────────────┐
│  claude-max-api proxy :3457     │
│  → Claude Sonnet / Opus         │
└─────────────────────────────────┘
             │
┌────────────▼────────────────────┐
│  XTTS v2 (Corsair, GPU)        │
│  → Voice synthesis              │
└─────────────────────────────────┘
```

## Features

### 💬 Multi-Model Chat Pipeline

- **Fast Model** (Sonnet) — Instant conversational responses, tool execution
- **Deep Model** (Opus) — Background supervisor, deep analysis, project briefs
- **Analyzer** (Sonnet) — Watches conversations, auto-detects cards and action items
- 3-level chat hierarchy: **General Chat → Project Chat → Card Chat**
- Streaming responses, session tabs, chat search, slash commands
- Smart suggestions, emoji picker, meeting notes export
- Welcome flow with context-aware prompts

### 🎤 Voice

- **STT:** Web Speech API (browser-native) + server-side Whisper fallback
- **TTS:** XTTS v2 on GPU (remote endpoint) or Sherpa-ONNX (CPU local)
- Push-to-talk voice input component
- Audio playback service for TTS responses

### 📋 Project Management

- **Kanban Board** — Drag-and-drop columns: Idea → Todo → In Progress → Done → Archived
- **Roadmap** — Gantt-style timeline view of cards
- **Sprint Planner** — Group cards into time-boxed sprints
- **Stats Dashboard** — Progress charts and velocity metrics
- **Wiki** — Markdown documentation pages per project
- **Docs / RAG** — Upload documents (txt, md, pdf, docx, xlsx) for AI context
- **GitHub Panel** — Link repos, view issues and PRs
- **Tech Stack Detection** — Auto-detect and display project technologies
- **Export / Import** — Full project snapshots as JSON

### 🃏 Cards

Cards are the unified data model — everything is a Card:

- Title, description, status, priority (0–4), agent assignment
- **Checklist** items with completion tracking
- **Attachments** (file uploads)
- **Comments** thread
- **Time tracking** with logged hours
- **Voting** (upvote/downvote)
- **History** (full audit trail of changes)
- **Relations & Dependencies** between cards
- **Pomodoro Focus Mode** — timer-based focused work sessions
- **AI Enrichment** — auto-generate descriptions, tags, acceptance criteria
- **Duplicate** cards with one click
- Bulk actions toolbar for multi-select operations

### 📝 Main Board (FreeBoard)

- Sticky notes that live outside any project
- Same Card model underneath — unified and consistent
- Color-coded notes (yellow, blue, green, pink, purple, orange)
- Detail modal for expanded view

### 🤖 Agent Personas (7)

Cards and conversations can be routed to specialized agents:

| Agent | Role |
|-------|------|
| 🔥 Ember | Default — general conversation, coordination |
| 🔍 Researcher | Deep analysis, fact-checking, long-form |
| 💻 Coder | Code generation, debugging, optimization |
| 🎨 Designer | UI/UX thinking, visual design guidance |
| 🏗️ Architect | System design, planning, PRD writing |
| ✍️ Writer | Content, marketing, storytelling |
| 🧪 QA | Testing strategies, edge cases, validation |

Auto-routing detects the best agent from keywords and context.

### 🧠 Personality System

Customizable personality files in `personality/`:

| File | Purpose |
|------|---------|
| `SOUL.md` | Core personality, communication style, nomenclature rules |
| `USER.md` | User preferences and context |
| `AGENTS.md` | Operating rules and safety directives |
| `IDENTITY.md` | Bot name, creature type, vibe, emoji |
| `MEMORY.md` | Persistent memory across sessions |

### 🔧 MCP Server (29 tools)

Built-in [Model Context Protocol](https://modelcontextprotocol.io/) server with two transport modes:

- **SSE** — For web clients (mounted at `/api/mcp/`)
- **Stdio** — For Claude Code, Cursor, and other MCP clients

**Tool categories:**

| Category | Tools |
|----------|-------|
| Notes | `note.add`, `note.list` |
| Projects | `project.create`, `project.list`, `project.get`, `project.delete`, `project.export` |
| Cards | `card.create`, `card.list`, `card.get`, `card.update`, `card.move`, `card.delete`, `card.duplicate`, `card.enrich` |
| Wiki | `wiki.list`, `wiki.create`, `wiki.get`, `wiki.update` |
| AI | `ai.standup`, `ai.brief`, `ai.health`, `ai.prioritize`, `ai.review_code` |
| Documents | `doc.list`, `doc.delete` |
| System | `health`, `jobs.list`, `jobs.create` |

### ⏰ Scheduler (APScheduler)

- **Heartbeat** — Periodic health checks (configurable interval)
- **RAG Indexing** — Auto-index uploaded documents into ChromaDB
- **Recurring Cards** — Auto-create cards on a cron schedule
- **Custom Jobs** — Create scheduled jobs via API (reminder, github_sync, rag_index, custom)

### 🎨 UI & UX

- **Command Palette** (Ctrl+K) — Quick access to everything
- **Keyboard Shortcuts** — Full shortcut reference modal
- **Dark / Light Theme** — Toggle with persistence
- **Font Size Scaling** — Accessibility setting
- **Responsive Design** — Mobile-friendly PWA
- **Service Worker** — Offline support via Workbox
- **Notification Center** — In-app notifications
- **Toast System** — Non-blocking feedback
- **Loading Spinners** — Consistent loading states
- **Activity Feed** — Real-time project activity stream

### 📄 Document Parsing

Upload and parse documents for RAG context:

- Plain text (`.txt`)
- Markdown (`.md`)
- PDF (`.pdf`) via pypdf
- Word documents (`.docx`) via python-docx
- Excel spreadsheets (`.xlsx`) via openpyxl

### 🔗 Integrations

- **GitHub** — Link repos, sync issues, view PRs per project
- **Code Review** — AI-powered code review via API endpoint
- **Templates** — 5 built-in project templates for quick setup

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- [claude-max-api](https://github.com/jcviau81/claude-max-api) proxy running on port 3457 (see Proxy Setup below)

### Backend

```bash
cd backend

# Virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env or use keyring (see Configuration below)

# Run
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: http://localhost:8000/docs

### Frontend

```bash
cd frontend

# Install dependencies
npm install

# Dev server (HTTPS on port 3000)
npm run dev
```

Open https://localhost:3000

### Proxy Setup (claude-max-api)

Voxyflow uses [claude-max-api](https://github.com/jcviau81/claude-max-api) as an OpenAI-compatible proxy to route requests to Claude models.

**⚠️ Important:** The proxy's working directory (`cwd`) **must** be `~/voxyflow/`. This is required for the proxy to correctly resolve relative paths in settings and personality files.

```bash
# Start the proxy (from the voxyflow directory)
cd ~/voxyflow
npx claude-max-api --port 3457
```

**Port assignment:**
- **Port 3457** — Voxyflow's proxy (this project)
- **Port 3456** — Reserved for OpenClaw (do NOT use for Voxyflow)

**Model names** (use these in `settings.json`):
- `claude-sonnet-4-20250514` (or `claude-sonnet-4`)
- `claude-opus-4-20250514` (or `claude-opus-4`)
- `claude-haiku-4-20250514` (or `claude-haiku-4`)

Update `settings.json` to point all models to `http://localhost:3457/v1`:

```json
{
  "models": {
    "fast": { "provider_url": "http://localhost:3457/v1", "model": "claude-sonnet-4-20250514" },
    "deep": { "provider_url": "http://localhost:3457/v1", "model": "claude-opus-4-20250514" },
    "analyzer": { "provider_url": "http://localhost:3457/v1", "model": "claude-sonnet-4-20250514" }
  }
}
```

### MCP Client Configuration

To use Voxyflow as an MCP server in Claude Code, Cursor, or other clients, add to your MCP config:

```json
{
  "mcpServers": {
    "voxyflow": {
      "command": "python",
      "args": ["backend/mcp_stdio.py"],
      "cwd": "/path/to/voxyflow",
      "env": {
        "VOXYFLOW_API_BASE": "http://localhost:8000"
      }
    }
  }
}
```

---

## Configuration

### settings.json (root)

Runtime configuration for personality and models:

```json
{
  "personality": {
    "bot_name": "Voxy",
    "preferred_language": "en",
    "soul_file": "./personality/SOUL.md",
    "user_file": "./personality/USER.md",
    "agents_file": "./personality/AGENTS.md",
    "identity_file": "./personality/IDENTITY.md",
    "tone": "casual",
    "warmth": "warm"
  },
  "models": {
    "fast": {
      "provider_url": "http://localhost:3457/v1",
      "model": "claude-sonnet-4-20250514",
      "enabled": true
    },
    "deep": {
      "provider_url": "http://localhost:3457/v1",
      "model": "claude-opus-4-20250514",
      "enabled": true
    },
    "analyzer": {
      "provider_url": "http://localhost:3457/v1",
      "model": "claude-sonnet-4-20250514",
      "enabled": true
    }
  },
  "scheduler": {
    "enabled": true,
    "heartbeat_interval_minutes": 2,
    "rag_index_interval_minutes": 15
  }
}
```

### Environment Variables (backend/.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `false` | Enable debug mode |
| `DATABASE_URL` | `sqlite+aiosqlite:///./voxyflow.db` | Database connection string |
| `CLAUDE_USE_NATIVE` | `false` | Use Anthropic SDK directly (vs proxy) |
| `ANTHROPIC_API_KEY` | — | API key (also loaded from keyring) |
| `CLAUDE_PROXY_URL` | `http://localhost:3457/v1` | OpenAI-compatible proxy URL |
| `CLAUDE_FAST_MODEL` | `claude-haiku-4-20250514` | Fast response model |
| `CLAUDE_SONNET_MODEL` | `claude-sonnet-4-20250514` | Balanced model |
| `CLAUDE_DEEP_MODEL` | `claude-opus-4-20250514` | Deep analysis model |
| `CLAUDE_ANALYZER_MODEL` | `claude-sonnet-4-20250514` | Background analyzer model |
| `CLAUDE_MAX_TOKENS` | `1024` | Max response tokens |
| `TTS_SERVICE_URL` | `http://192.168.1.59:5500` | TTS server endpoint |
| `TTS_ENGINE` | `remote` | TTS engine: `remote` or `sherpa-onnx` |
| `STT_ENGINE` | `browser` | STT engine: `browser` or `whisper` |
| `WHISPER_MODEL` | `turbo` | Whisper model size for server-side STT |
| `FAST_CONTEXT_MESSAGES` | `20` | Context window for fast model |
| `DEEP_CONTEXT_MESSAGES` | `100` | Context window for deep model |
| `ANALYZER_ENABLED` | `true` | Enable background card detection |

### Secure Key Storage

Voxyflow supports Python keyring for API keys (no plaintext in .env):

```bash
python backend/setup_keys.py
# Stores claude_api_key in system keyring under service "voxyflow"
```

Priority: keyring → environment variable → .env file → default

---

## Project Structure

```
voxyflow/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, startup, CORS
│   │   ├── config.py               # Pydantic settings (env + keyring)
│   │   ├── database.py             # SQLAlchemy async models + DB init
│   │   ├── mcp_server.py           # MCP server (29 tools, SSE + stdio)
│   │   ├── models/                 # Pydantic schemas
│   │   │   ├── card.py
│   │   │   ├── chat.py
│   │   │   ├── document.py
│   │   │   ├── project.py
│   │   │   └── voice.py
│   │   ├── routes/                 # API endpoints
│   │   │   ├── cards.py
│   │   │   ├── chats.py
│   │   │   ├── code.py
│   │   │   ├── documents.py
│   │   │   ├── focus_sessions.py
│   │   │   ├── github.py
│   │   │   ├── health.py
│   │   │   ├── jobs.py
│   │   │   ├── mcp.py
│   │   │   ├── projects.py
│   │   │   ├── sessions.py
│   │   │   ├── settings.py
│   │   │   ├── techdetect.py
│   │   │   ├── tools.py
│   │   │   └── voice.py
│   │   ├── services/               # Business logic
│   │   │   ├── agent_personas.py   # 7 agent types + auto-routing
│   │   │   ├── agent_router.py     # Keyword-based agent selection
│   │   │   ├── analyzer_service.py # Background card detection
│   │   │   ├── chat_service.py     # Conversation management
│   │   │   ├── claude_service.py   # Multi-model orchestration
│   │   │   ├── document_parser.py  # txt/md/pdf/docx/xlsx parsing
│   │   │   ├── memory_service.py   # Persistent memory
│   │   │   ├── personality_service.py
│   │   │   ├── rag_service.py      # ChromaDB vector search
│   │   │   ├── scheduler_service.py # APScheduler jobs
│   │   │   ├── session_store.py    # Chat session management
│   │   │   └── tts_service.py      # TTS (remote XTTS / local)
│   │   └── tools/                  # Native tool system
│   │       ├── card_tools.py
│   │       ├── github_tools.py
│   │       ├── info_tools.py
│   │       ├── navigation_tools.py
│   │       ├── project_tools.py
│   │       └── registry.py
│   ├── mcp_stdio.py                # MCP stdio transport entry point
│   ├── requirements.txt
│   ├── setup_keys.py               # Keyring setup helper
│   └── tests/
├── frontend/
│   ├── public/
│   │   ├── index.html
│   │   ├── manifest.json           # PWA manifest
│   │   ├── sw.ts                   # Service worker (Workbox)
│   │   └── icons/                  # PWA icons (16–512px)
│   ├── src/
│   │   ├── main.ts                 # Entry point
│   │   ├── App.ts                  # Root component
│   │   ├── state/AppState.ts       # Global state management
│   │   ├── components/
│   │   │   ├── Chat/               # Chat window, voice, search, sessions
│   │   │   ├── FreeBoard/          # Main board (sticky notes)
│   │   │   ├── FocusMode/          # Pomodoro focus sessions
│   │   │   ├── Ideas/              # Idea board
│   │   │   ├── Kanban/             # Kanban board, cards, drag-and-drop
│   │   │   ├── Navigation/         # Sidebar, tabs, top bar, model status
│   │   │   ├── Notifications/      # Notification center
│   │   │   ├── Opportunities/      # Opportunities panel
│   │   │   ├── Projects/           # Projects, roadmap, stats, wiki, docs
│   │   │   ├── RightPanel/         # Collapsible right panel
│   │   │   ├── Settings/           # Settings page
│   │   │   └── Shared/             # Command palette, shortcuts, toast
│   │   ├── services/               # API client, audio, TTS, STT, etc.
│   │   ├── styles/                 # CSS modules (16 stylesheets)
│   │   ├── types/                  # TypeScript type definitions
│   │   └── utils/                  # EventBus, markdown, helpers
│   ├── tests/                      # Unit + E2E tests (Playwright)
│   ├── webpack.config.js
│   ├── tsconfig.json
│   └── package.json
├── personality/                     # AI personality files
│   ├── SOUL.md
│   ├── USER.md
│   ├── AGENTS.md
│   ├── IDENTITY.md
│   └── MEMORY.md
├── docs/                           # Documentation
│   ├── ARCHITECTURE.md
│   ├── FEATURES.md
│   ├── FRONTEND_ARCHITECTURE.md
│   ├── API.md
│   ├── SETUP.md
│   ├── DEPLOYMENT.md
│   ├── VOICE_FLOW.md
│   ├── PERSONALITY.md
│   └── AGENTS.md
├── settings.json                   # Runtime config (models, personality, scheduler)
├── mcp.json                        # MCP client config example
└── tests/e2e/                      # Root-level E2E tests
```

---

## Testing

```bash
# Backend unit tests
cd backend && python -m pytest

# Frontend unit tests
cd frontend && npm test

# E2E tests (Playwright)
cd frontend && npm run test:e2e

# Type checking
cd frontend && npm run type-check

# Linting
cd frontend && npm run lint
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | Vanilla TypeScript, Webpack 5, CSS modules, Workbox (PWA) |
| **Backend** | Python 3.11+, FastAPI, SQLAlchemy (async), Pydantic |
| **Database** | SQLite (aiosqlite) |
| **AI** | Claude Sonnet + Opus via OpenAI-compatible proxy |
| **RAG** | ChromaDB + sentence-transformers |
| **TTS** | XTTS v2 (GPU, remote) / Sherpa-ONNX (CPU, local) |
| **STT** | Web Speech API (browser) / Whisper (server fallback) |
| **MCP** | Model Context Protocol (SSE + stdio) |
| **Scheduler** | APScheduler |
| **Testing** | pytest, Jest, Playwright |

---

## License

MIT — see [LICENSE](LICENSE)

---

**Built by** JC Viau · **Started** March 2025 · **Status** Active development
