# ⚡ Voxyflow

> ⚠️ **Alpha** — Early software. It works (I use it daily), but expect rough edges. Moving fast. **Contributors welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).**

**Your personal AI assistant for getting projects done.**

Select a card. Say "execute this." The AI reads the full context — project, description, checklist, linked files — and *does the work*. Not a generic chatbot. A personal agent that knows exactly where it is in your workflow.

Built as a Progressive Web App. Runs locally. No cloud lock-in.

---

## Why Voxyflow?

Most tools solve half the problem:

| Tool | What it does well | What's missing |
|------|-------------------|----------------|
| **Linear / Jira** | Organizes your work | Can't execute anything |
| **Cursor / Copilot** | Executes code tasks | No idea what your project is or what needs doing |
| **ChatGPT / Claude** | Answers questions | Generic — zero project context, freezes while working |

**Voxyflow is the bridge.** It's your kanban board *and* your execution engine — with the full context of your project always available to the AI.

> Think: **Linear + Cursor in one app**, on your own machine, with no subscription or cloud lock-in.

---

## The Killer Feature: Context-Scoped Execution

Every card in Voxyflow is a rich context object: title, description, priority, checklist, attachments, comments, history, relations.

When you click a card and say **"execute this"**, the AI doesn't just see a card title — it gets the **full card context**, the **project context**, and your **personality/memory files**. It knows what the card is for, what's been done, and what needs doing next.

```
General Chat  →  Project Chat  →  Card Chat
   (broad)       (project context)   (execute this exact task)
```

At the card level, the agent has maximum context and minimum ambiguity. It doesn't ask what you mean — it executes.

---

## Non-Blocking Architecture

Most AI tools freeze while working. Voxyflow doesn't.

```
You ──────────────────────────────────────────────────────▶ (always talking)
        │                                                  ▲
        │ dispatch                                         │ result arrives
        ▼                                                  │
   Worker ──── working in background (30s, 2min, 5min) ───┘
```

The **Dispatcher** (Chat Agent) handles your conversation — always responsive, zero tools, pure dialogue. When it detects a task, it spawns a **Worker** in the background. The Worker executes (research, CRUD, code, whatever), and when it's done, the result arrives in your conversation naturally.

You never wait. You keep talking, thinking, planning — and results show up when they're ready.

---

## Architecture

```
┌─────────────────────────────────┐
│  Browser (PWA)                  │
│  React 19 + Vite + Tailwind     │
└────────────┬────────────────────┘
             │ REST + WebSocket
┌────────────▼────────────────────┐
│  FastAPI Backend :8000          │
│  ├─ Chat Agent (Dispatcher)     │
│  ├─ Workers (background exec)   │
│  ├─ Analyzer (passive observer) │
│  ├─ MCP Server (SSE + stdio)    │
│  ├─ RAG (ChromaDB)              │
│  ├─ APScheduler                 │
│  └─ SQLite (aiosqlite)          │
└────────────┬────────────────────┘
             │ CLI subprocess (claude -p)
┌────────────▼────────────────────┐
│  Claude Max (Haiku/Sonnet/Opus) │
└────────────┬────────────────────┘
             │ optional
┌────────────▼────────────────────┐
│  XTTS v2 (GPU, optional)        │
│  Voice synthesis                │
└─────────────────────────────────┘
```

---

## Features

### ⚡ Dispatcher + Workers (Non-Blocking)

- **Chat Agent (Dispatcher)** — Pure conversation. No tools. Always responsive. Dispatches work to Workers.
- **Workers** — Background agents that execute real tasks (CRUD, research, code, file ops).
  - Routed by model: Haiku (simple CRUD), Sonnet (research), Opus (complex multi-step)
- **Analyzer** — Passive background observer that auto-detects card opportunities from conversation
- Results arrive in conversation when ready — no polling, no waiting, no frozen UI

### 📋 Project Management

- **Kanban Board** — Drag-and-drop columns: Idea → Todo → In Progress → Done
- **Stats Dashboard** — Progress charts, velocity metrics, AI standup, health score
- **Wiki** — Markdown documentation pages per project
- **Knowledge / RAG** — Upload documents (txt, md, pdf, docx, xlsx) for AI context injection
- **GitHub Integration** — Link repos, auth via `gh` CLI or PAT
- **Tech Stack Detection** — Auto-detect project technologies
- **Export / Import** — Full project snapshots as JSON

### 🃏 Cards

Cards are the core unit of everything:

- Title, description, status, priority (0–4), agent assignment
- **Checklist** with progress tracking
- **Attachments** (file uploads)
- **Comments** thread
- **Time tracking**
- **History** — full audit trail
- **Relations & Dependencies** between cards
- **Recurring cards** — auto-regenerate on a schedule (daily, weekdays, weekly, biweekly, monthly…)
- **AI Enrichment** — auto-generate descriptions, tags, acceptance criteria
- **Pomodoro Focus Mode** — timer-based focused work sessions
- **Duplicate** with one click, bulk actions toolbar

### 📝 Main Board (FreeBoard)

Unassigned sticky-note cards outside any project. Color-coded (6 colors). Same card model — unified data.

### 🤖 Agent Personas (7)

| Agent | Role |
|-------|------|
| 🔍 Researcher | Deep analysis, fact-checking, long-form |
| 💻 Coder | Code generation, debugging, optimization |
| 🎨 Designer | UI/UX thinking, visual design guidance |
| 🏗️ Architect | System design, planning, PRD writing |
| ✍️ Writer | Content, marketing, storytelling |
| 🧪 QA | Testing strategies, edge cases, validation |

Auto-routing detects the best agent from keywords and context.

### 🎤 Voice

- **STT:** Web Speech API (browser-native, default) or Whisper WASM (local, no server needed)
- **TTS:** XTTS v2 on GPU (optional, sentence-by-sentence streaming) with browser speechSynthesis fallback
- **Wake word** — Say "Voxy" to open the mic hands-free
- Push-to-talk (Alt+V) or wake word mode

### 🧠 Personality System

Customizable personality files in `personality/`:

| File | Purpose |
|------|---------|
| `SOUL.md` | Core personality, communication style, nomenclature |
| `USER.md` | User preferences and context (auto-generated, editable) |
| `AGENTS.md` | Operating rules and safety directives |
| `IDENTITY.md` | Bot name, emoji, vibe (auto-generated, editable) |

Editable directly or via **Settings → Personality** in the UI.

### 🔧 MCP Server (~60 tools)

Built-in [Model Context Protocol](https://modelcontextprotocol.io/) server — two transport modes:

- **SSE** — For web clients (`/api/mcp/`)
- **Stdio** — For Claude Code, Cursor, and other MCP clients

Tools span: card CRUD, project management, wiki, AI operations, web search, file ops, git, tmux, scheduler jobs.

### ⏰ Scheduler

- **Heartbeat** — Periodic health checks
- **RAG Indexing** — Auto-index uploaded documents
- **Recurring Cards** — Auto-create cards on schedule (checks every 5 minutes)
- **Board Run** — Scheduled execution of all cards in a project (cron-based)
- **Custom Jobs** — Create via Settings → Jobs or API

---

## Quick Start

```bash
git clone https://github.com/jcviau81/voxyflow.git
cd voxyflow

# Backend
cd backend
python3.12 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set CLAUDE_USE_CLI=true, install claude CLI first
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Frontend (separate terminal)
cd frontend-react
npm install && npm run dev
```

Full installation guide: [docs/SETUP.md](docs/SETUP.md)

---

## Project Structure

```
voxyflow/
├── backend/
│   ├── app/
│   │   ├── main.py                     # FastAPI app, startup, CORS
│   │   ├── config.py                   # Settings (env vars + keyring)
│   │   ├── database.py                 # SQLAlchemy async models
│   │   ├── mcp_server.py               # MCP tool definitions (~60 tools)
│   │   ├── mcp_stdio.py                # MCP stdio transport entry point
│   │   ├── routes/                     # API endpoints
│   │   └── services/                   # Business logic
│   │       ├── claude_service.py       # LLM orchestration (4 layers)
│   │       ├── chat_orchestration.py   # Dispatcher + delegate parsing
│   │       ├── personality_service.py  # System prompt builder
│   │       ├── llm/                    # CLI / SDK / proxy backends
│   │       ├── orchestration/          # Worker pool, session timeline
│   │       ├── rag_service.py          # ChromaDB vector search
│   │       ├── memory_service.py       # Persistent cross-session memory
│   │       └── scheduler_service.py    # APScheduler jobs
│   ├── requirements.txt
│   ├── .env.example
│   └── tests/
├── frontend-react/
│   └── src/
│       ├── components/                 # React components
│       ├── services/                   # TTS, STT, WebSocket client
│       ├── stores/                     # Zustand state stores
│       └── pages/                      # Top-level pages
├── personality/                        # AI personality files
│   ├── SOUL.md
│   ├── DISPATCHER.md
│   ├── WORKER.md
│   ├── AGENTS.md
│   ├── IDENTITY.md
│   └── USER.md
└── docs/                               # Documentation
    ├── SETUP.md                        # Installation guide
    ├── CONTEXT_GUIDE.md                # Context system + workflow examples
    ├── UI_GUIDE.md                     # Interface guide (view by view)
    ├── FEATURES.md                     # Complete feature reference
    ├── ARCHITECTURE.md                 # Technical deep-dive
    ├── API.md                          # REST & WebSocket API reference
    ├── AGENTS.md                       # Agent personas reference
    ├── VOICE_FLOW.md                   # Voice pipeline details
    └── TOOLS.md                        # MCP tool registry
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Frontend** | React 19, TypeScript, Vite, Zustand, TanStack Query, Tailwind CSS |
| **Backend** | Python 3.12+, FastAPI, SQLAlchemy (async), Pydantic |
| **Database** | SQLite (aiosqlite) |
| **AI** | Claude Haiku + Sonnet + Opus via `claude` CLI subprocess (Claude Max) |
| **RAG** | ChromaDB + sentence-transformers (intfloat/multilingual-e5-large) |
| **TTS** | XTTS v2 (GPU, optional) with browser speechSynthesis fallback |
| **STT** | Web Speech API (browser) / Whisper WASM (local, no server) |
| **MCP** | Model Context Protocol (SSE + stdio) |
| **Scheduler** | APScheduler |
| **PWA** | Vite PWA + Workbox |
| **Testing** | pytest, Playwright |

---

## Documentation

| Doc | Contents |
|-----|---------|
| [SETUP.md](docs/SETUP.md) | Full installation guide — LLM backend, XTTS, onboarding |
| [CONTEXT_GUIDE.md](docs/CONTEXT_GUIDE.md) | Context system + DailyOps workflow example |
| [UI_GUIDE.md](docs/UI_GUIDE.md) | Interface guide — every view explained |
| [FEATURES.md](docs/FEATURES.md) | Complete feature reference |
| [CONTRIBUTING.md](CONTRIBUTING.md) | How to contribute |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Technical architecture deep-dive |
| [API.md](docs/API.md) | REST & WebSocket API reference |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports, features, and PRs are welcome.

---

## License

MIT — see [LICENSE](LICENSE)

---

**Built by** JC Viau · **Started** March 2025 · **Status** Active development
