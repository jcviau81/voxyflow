# ⚡ Voxyflow

> ⚠️ **Alpha v0.0.1** — Very early software. It works (I use it daily), but expect rough edges. Moving fast. **Contributors welcome — see below.**

**Your personal AI bot for getting projects done.**

Select a card. Say "execute this." The AI reads the full context — project, description, checklist, linked files — and *does the work*. Not a generic chatbot. A personal agent that knows exactly where it is in your workflow.

Built as a Progressive Web App. Runs locally. No cloud lock-in.

---

## Why Voxyflow?

Most tools solve half the problem:

| Tool | What it does well | What's missing |
|------|-------------------|----------------|
| **Linear / Jira** | Organizes your work | Can't execute anything |
| **Cursor / Copilot** | Executes code tasks | Has no idea what your project is or what needs doing |
| **ChatGPT / Claude** | Answers questions | Generic — zero project context, freezes while working |

**Voxyflow is the bridge.** It's your kanban board *and* your execution engine in one — with the full context of your project always available to the AI.

> Think: **Linear + Cursor in one app**, on your own machine, with no subscription or cloud lock-in.

---

## The Killer Feature: Execute Card

Every card in Voxyflow is a rich context object:

- Title, description, priority
- Checklist items with completion tracking
- Attachments and linked documents
- Comments, history, relations

When you click a card and say **"execute this"**, the AI agent doesn't just see a card title — it gets the **full card context**, the **project context**, and your **personality/memory files**. It knows what the card is for, what's been done, and what needs doing next.

This is context-scoped execution at 3 levels:

```
General Chat  →  Project Chat  →  Card Chat
   (broad)       (project context)   (execute this exact task)
```

At the card level, the agent has maximum context and minimum ambiguity. It doesn't ask what you mean — it executes.

---

## Non-Blocking Architecture: The Conversation Never Freezes

This is a core design principle, not a nice-to-have.

Most AI tools work like this: you ask something → the app freezes → 30 seconds later, you get a response. If the task is complex, you wait 2, 5, even 10 minutes staring at a spinner.

**Voxyflow doesn't work that way.**

```
You ──────────────────────────────────────────────────────▶ (always talking)
        │                                                  ▲
        │ dispatch                                         │ result arrives
        ▼                                                  │
   Worker ──── working in background (30s, 2min, 5min) ───┘
```

The **Dispatcher** (Chat Agent) handles your conversation — always responsive, zero tools, pure dialogue. When it detects a task, it spawns a **Worker** in the background. The Worker executes (research, CRUD, code, whatever), and when it's done, the result arrives in your conversation naturally.

You never wait. You keep talking, thinking, planning — and results show up when they're ready.

This is what it means to have a **truly non-blocking** AI assistant.

---

## Architecture

```
┌─────────────────────────────────┐
│  Browser (PWA)                  │
│  React 19 + Vite + Tailwind    │
│  HTTPS :3000                    │
└────────────┬────────────────────┘
             │ REST + WebSocket
┌────────────▼────────────────────┐
│  FastAPI Backend :8000          │
│  ├─ Chat Agent (Dispatcher)    │
│  ├─ Workers (background exec)  │
│  ├─ Analyzer (passive observer)│
│  ├─ Tool System (workers only) │
│  ├─ MCP Server (SSE + stdio)   │
│  ├─ RAG (ChromaDB)             │
│  ├─ APScheduler                │
│  └─ SQLite (aiosqlite)         │
└────────────┬────────────────────┘
             │ CLI subprocess (claude -p)
             │ or deprecated proxy :3457
┌────────────▼────────────────────┐
│  Claude Max (CLI backend)       │
│  → Haiku / Sonnet / Opus        │
└─────────────────────────────────┘
             │
┌────────────▼────────────────────┐
│  XTTS v2 (Corsair, GPU)        │
│  → Voice synthesis              │
└─────────────────────────────────┘
```

---

## Features

### ⚡ Execute Card (Context-Scoped Execution)

- Select any card on the kanban board
- The chat context shifts to **Card Chat** — the AI has full card context
- Say "execute this", "implement this", "write the tests for this card"
- The Worker agent reads the entire card (title, description, checklist, attachments, history) and executes
- Result streams back to your conversation without blocking anything

### 💬 Dispatcher + Workers (Non-Blocking)

- **Chat Agent (Dispatcher)** — Pure conversation. No tools. Always responsive. Dispatches work to Workers.
- **Workers** — Background agents that execute real tasks (CRUD, research, code, file ops) without blocking the conversation.
  - Routed by model: Haiku (simple CRUD), Sonnet (research), Opus (complex multi-step)
  - Workers can run for 30 seconds, 2 minutes, 5 minutes — you keep talking the whole time
- **Analyzer** — Passive background observer that watches conversations and auto-detects opportunities (card suggestions, patterns, action items)
- Results arrive in conversation when ready — no polling, no waiting, no frozen UI

### 📋 Project Management

- **Kanban Board** — Drag-and-drop columns: Idea → Todo → In Progress → Done → Archived
- **Stats Dashboard** — Progress charts and velocity metrics
- **Wiki** — Markdown documentation pages per project
- **Docs / RAG** — Upload documents (txt, md, pdf, docx, xlsx) for AI context
- **GitHub Panel** — Link repos, view issues and PRs
- **Tech Stack Detection** — Auto-detect and display project technologies
- **Export / Import** — Full project snapshots as JSON

### 🃏 Cards (The Unified Data Model)

Cards are the core unit of everything:

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

- Cards that live outside any project (unassigned)
- Same Card model as project cards — unified and consistent
- Color-coded cards (yellow, blue, green, pink, purple, orange)
- Detail modal for expanded view

### 🎤 Voice Control (Hands-Free)

Voice is a differentiator — not the core, but genuinely useful:

- **STT:** Web Speech API (browser-native) + server-side Whisper fallback
- **TTS:** XTTS v2 on GPU (primary, port 5500) with browser speechSynthesis fallback
- Push-to-talk voice input component
- Say "execute this card" hands-free while reading code

### 🤖 Agent Personas (7)

Cards and conversations can be routed to specialized agents:

| Agent | Role |
|-------|------|
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

### 🔧 MCP Server (~60 tools)

Built-in [Model Context Protocol](https://modelcontextprotocol.io/) server with two transport modes:

- **SSE** — For web clients (mounted at `/api/mcp/`)
- **Stdio** — For Claude Code, Cursor, and other MCP clients

**Tool categories:**

| Category | Tools |
|----------|-------|
| Main Board | `card.create_unassigned`, `card.list_unassigned` |
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

## Prerequisites & Installation

Follow these steps when installing Voxyflow from scratch.

### 1. Clone Voxyflow

```bash
git clone https://github.com/jcviau81/voxyflow.git
cd voxyflow
```

> **LLM Backend:** Voxyflow primarily uses the CLI subprocess backend (`CLAUDE_USE_CLI=true`), which spawns `claude -p` processes and uses your Claude Max subscription directly. No proxy needed. The OpenAI-compatible proxy at `:3457` is a deprecated legacy fallback.

### 2. Backend Setup

```bash
cd ~/voxyflow/backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure Settings

```bash
cp settings.json.example settings.json   # if example exists, else edit settings.json directly
cp backend/.env.example backend/.env     # then fill in your values
```

Key settings in `backend/.env`:

```bash
CLAUDE_USE_CLI=true                          # Primary backend: CLI subprocess (Claude Max)
CLAUDE_FAST_MODEL=claude-haiku-4-5-20251001
CLAUDE_SONNET_MODEL=claude-sonnet-4-6
CLAUDE_DEEP_MODEL=claude-opus-4-6
TTS_SERVICE_URL=http://192.168.1.59:5500     # XTTS v2 GPU server
```

### 4. Frontend Setup

```bash
cd ~/voxyflow/frontend-react
npm install
npm run build        # production build
# or
npm run dev          # watch mode (development)
```

### 5. Start the Backend

```bash
cd ~/voxyflow/backend
source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open `https://localhost:3000` in your browser.

---

## Configuration Reference

### settings.json

```json
{
  "personality": {
    "soul_file": "personality/SOUL.md",
    "user_file": "personality/USER.md",
    "agents_file": "personality/AGENTS.md",
    "identity_file": "personality/IDENTITY.md",
    "memory_file": "personality/MEMORY.md"
  },
  "models": {
    "fast": "claude-haiku-4-20250514",
    "deep": "claude-opus-4-20250514",
    "analyzer": "claude-haiku-4-5-20251001"
  },
  "scheduler": {
    "enabled": true,
    "heartbeat_interval_minutes": 2,
    "rag_index_interval_minutes": 15
  }
}
```

**Architecture note:** The `fast` and `deep` models power the Chat Agent (Dispatcher), which has zero tools and only converses + dispatches. Workers are launched in the background and select their own model (haiku/sonnet/opus) based on task complexity. The `analyzer` model powers the passive background observer.

### Environment Variables (backend/.env)

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `false` | Enable debug mode |
| `DATABASE_URL` | `sqlite+aiosqlite:///./voxyflow.db` | Database connection string |
| `CLAUDE_USE_NATIVE` | `false` | Use Anthropic SDK directly (vs proxy) |
| `ANTHROPIC_API_KEY` | — | API key (also loaded from keyring) |
| `CLAUDE_PROXY_URL` | `http://localhost:3457/v1` | OpenAI-compatible proxy URL |
| `CLAUDE_FAST_MODEL` | `claude-haiku-4-20250514` | Chat Agent (Dispatcher) — Fast mode |
| `CLAUDE_SONNET_MODEL` | `claude-sonnet-4-20250514` | Worker model (research tasks) |
| `CLAUDE_DEEP_MODEL` | `claude-opus-4-20250514` | Chat Agent (Dispatcher) — Deep mode / Worker model (complex tasks) |
| `CLAUDE_ANALYZER_MODEL` | `claude-haiku-4-5-20251001` | Background Analyzer model |
| `CLAUDE_MAX_TOKENS` | `1024` | Max response tokens |
| `TTS_SERVICE_URL` | `http://192.168.1.59:5500` | TTS server endpoint |
| `TTS_ENGINE` | `remote` | TTS engine: `remote` or `sherpa-onnx` |
| `STT_ENGINE` | `browser` | STT engine: `browser` or `whisper` |
| `WHISPER_MODEL` | `turbo` | Whisper model size for server-side STT |
| `FAST_CONTEXT_MESSAGES` | `20` | Context window for Chat Agent (Fast mode) |
| `DEEP_CONTEXT_MESSAGES` | `100` | Context window for Chat Agent (Deep mode) |
| `ANALYZER_ENABLED` | `true` | Enable background Analyzer (passive card detection) |

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
│   │   ├── mcp_server.py           # MCP server (~60 tools, SSE + stdio)
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
│   │   │   ├── analyzer_service.py # Background Analyzer (passive card detection)
│   │   │   ├── chat_service.py     # Conversation management
│   │   │   ├── claude_service.py   # Dispatcher + Worker model orchestration
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
├── frontend-react/
│   ├── public/                     # Static assets, PWA icons
│   ├── src/
│   │   ├── main.tsx                # Entry point
│   │   ├── App.tsx                 # Root component
│   │   ├── stores/                 # Zustand state stores
│   │   ├── components/             # React components
│   │   ├── hooks/                  # Custom React hooks
│   │   ├── services/               # API client, audio, TTS, STT, etc.
│   │   ├── types/                  # TypeScript type definitions
│   │   └── utils/                  # Helpers
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── package.json
├── personality/                     # AI personality files
│   ├── SOUL.md
│   ├── USER.md
│   ├── AGENTS.md
│   ├── IDENTITY.md
│   └── MEMORY.md
├── docs/                           # Documentation
│   ├── FEATURES.md
│   ├── API.md
│   ├── SETUP.md
│   ├── DEPLOYMENT.md
│   ├── CONTEXT_GUIDE.md
│   ├── UI_GUIDE.md
│   ├── PERSONALITY.md
│   ├── TOOLS.md
│   ├── VOICE_FLOW.md
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
cd frontend-react && npm test

# E2E tests (Playwright)
cd frontend-react && npm run test:e2e

# Type checking
cd frontend-react && npm run type-check

# Linting
cd frontend-react && npm run lint
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | React 19, TypeScript, Vite, Zustand, TanStack Query, Tailwind CSS (PWA) |
| **Backend** | Python 3.11+, FastAPI, SQLAlchemy (async), Pydantic |
| **Database** | SQLite (aiosqlite) |
| **AI** | Claude Haiku + Sonnet + Opus via CLI subprocess (`claude -p`, Claude Max) |
| **RAG** | ChromaDB + sentence-transformers |
| **TTS** | XTTS v2 (GPU, port 5500) with browser speechSynthesis fallback |
| **STT** | Web Speech API (browser) / Whisper (server fallback) |
| **MCP** | Model Context Protocol (SSE + stdio) |
| **Scheduler** | APScheduler |
| **Testing** | pytest, Vitest, Playwright |

---

## License

MIT — see [LICENSE](LICENSE)

---

**Built by** JC Viau · **Started** March 2025 · **Status** Active development

---

## ⚠️ Status: Alpha v0.0.1

This is very early software. It works (I use it daily), but expect rough edges, missing features, and things that break. **Version 0.0.1 — moving fast.**

We're actively building and need help:
- 🐛 **Bug reports** — open an issue, we'll fix it fast
- 🛠️ **Contributors** — frontend (TypeScript), backend (Python/FastAPI), UX
- 💡 **Ideas** — what would make this your daily driver?

If you're excited about local-first agentic AI, **join the journey.**
