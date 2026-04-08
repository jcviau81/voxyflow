# Voxyflow Architecture

## Overview

Voxyflow is a **voice-first project management assistant** powered by Claude. It combines natural voice interaction with intelligent project management through a Dispatcher + Workers architecture.

## System Architecture

```
┌─────────────────────────────────────────────────┐
│                   Frontend (PWA)                 │
│  React 19 • TypeScript • Vite • Service Worker   │
│                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ Voice    │ │ Chat     │ │ Kanban Board     │ │
│  │ Input    │ │ Window   │ │ (Auto-generated) │ │
│  └────┬─────┘ └────┬─────┘ └────────┬─────────┘ │
│       │             │                │            │
│  ┌────┴─────────────┴────────────────┴─────────┐ │
│  │     Zustand Stores • TanStack Query          │ │
│  │     WebSocket Provider • EventBus            │ │
│  └──────────────────┬──────────────────────────┘ │
└─────────────────────┼───────────────────────────┘
                      │ REST + WebSocket
┌─────────────────────┼───────────────────────────┐
│                   Backend (FastAPI)              │
│  Python 3.12+ • Async • SQLite                   │
│                                                   │
│  ┌──────────────────┴──────────────────────────┐ │
│  │         Chat Agent (Dispatcher)              │ │
│  │  Inline tools (card CRUD, memory, knowledge) │ │
│  │  Fast mode (Haiku) / Deep mode (Opus)        │ │
│  └──┬───────────────────────────────┬──────────┘ │
│     │ <delegate> blocks             │ observes   │
│  ┌──▼──────────────────────┐  ┌────▼─────────┐  │
│  │   Background Workers    │  │   Analyzer    │  │
│  │  ┌───────┐ ┌─────────┐ │  │  Passive      │  │
│  │  │ Haiku │ │ Sonnet  │ │  │  observer     │  │
│  │  │ CRUD  │ │Research │ │  │  Card detect  │  │
│  │  └───────┘ └─────────┘ │  │  Patterns     │  │
│  │  ┌───────┐             │  │  Suggestions  │  │
│  │  │ Opus  │ ALL MCP     │  └──────────────┘  │
│  │  │Complex│ tools here  │                     │
│  │  └───────┘             │                     │
│  └─────────────────────────┘                     │
│                                                   │
│  ┌─────────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ CLI Backend │ │ Memory   │ │ Personality  │  │
│  │ (claude -p) │ │ Service  │ │ Service      │  │
│  └─────────────┘ └──────────┘ └──────────────┘  │
└─────────────────────────────────────────────────┘
```

### Core Architecture Principle

**The conversation is never blocked by running tasks.**

- The **Chat Agent (Dispatcher)** has inline tools (card CRUD, memory, knowledge search) for fast operations, and emits `<delegate>` blocks for complex tasks.
- **Workers** run in the background via `claude -p` subprocesses with full MCP tool access (~60 tools), and report results via WebSocket.
- The **Analyzer** passively observes conversations and surfaces opportunities (card suggestions, patterns) without interrupting.

## Key Design Decisions

### Voice-First, Not Voice-Only
- **STT:** Web Speech API (browser-native, default on all platforms) or Whisper WASM (opt-in, runs locally in a WebWorker — no server needed)
- Text input always available
- **TTS:** XTTS v2 server (optional, GPU-accelerated, sentence-by-sentence SSE streaming) with browser speechSynthesis fallback
- **Wake word:** "Voxy" triggers continuous recording mode without touching the keyboard

### LLM Backend — CLI Subprocess (Active)
- Spawns `claude -p` subprocesses using Claude Max subscription
- Chat layers: streaming via `--output-format stream-json`
- Workers: non-streaming with `--mcp-config` for full MCP tool access (~60 tools)
- Permissions: `--permission-mode bypassPermissions` (MCP tools are our own REST API)
- Alternative paths available: Native Anthropic SDK, OpenAI-compatible proxy (deprecated)

### React Frontend
- React 19 + TypeScript + Vite (PWA via vite-plugin-pwa)
- Zustand + Immer for state management, TanStack Query for server state
- WebSocket provider for real-time sync
- EventBus pattern for decoupled communication

### Agent Personas (6 Specialists)
Cards and conversations can be routed to specialized agents:
1. **Researcher** 🔍 — Deep analysis, fact-checking, long-form research
2. **Coder** 💻 — Code generation, debugging, optimization
3. **Designer** 🎨 — UI/UX thinking, visual design guidance
4. **Architect** 🏗️ — System design, planning, PRD writing
5. **Writer** ✍️ — Content, marketing, storytelling
6. **QA** 🧪 — Testing strategies, edge cases, validation

Auto-routing detects the best agent from card title/description via two-pass keyword scoring (no LLM call).

### ReactiveCardStore (Single Source of Truth)
All card data on the frontend flows through `useCardStore` (`frontend-react/src/stores/useCardStore.ts`), a centralized Map-based singleton. Components subscribe to global or per-card changes and re-render automatically. This replaces ad-hoc fetching patterns and eliminates stale data.

### WebSocket Live Sync (`cards:changed`)
When any card is mutated via REST (create/update/move/delete), the backend broadcasts a `cards:changed` event to all connected WebSocket clients via `WSBroadcast` (`backend/app/services/ws_broadcast.py`). The frontend receives this, re-fetches the affected project's cards, and updates the ReactiveCardStore — giving real-time multi-tab sync and instant worker feedback.

### Card Execution Pipeline (E2E)
Cards can be **executed**: "Execute" button → `POST /api/cards/{id}/execute` → backend builds a `[CARD EXECUTION]` prompt → sent through the 3-layer pipeline → Fast/Deep layer responds + workers execute with full tools → worker result auto-appended to card description → card moved to "done" → `cards:changed` broadcast → frontend modal updates in real-time via ReactiveCardStore.

### Agent Routing (Keyword-Based)
Every card is auto-routed to a specialized agent type via two-pass keyword scoring (no LLM call). Pass 1: pattern + persona-keyword scoring (`analyzer_service.py:suggest_agent_type()`). Pass 2: weighted routing (`agent_router.py:AgentRouter.route()`). Resolution: high-confidence router wins, else pattern scorer, else fallback to general.

### Memory & Context
- Conversation history persisted in SQLite
- Per-project context windows
- Personality consistency via SOUL.md injection
- Cross-session memory via memory service

## Data Flow

1. **Voice Input** → STT → Text → WebSocket → Chat Agent (Dispatcher)
2. **Chat Agent** → Responds conversationally + emits `<delegate>` blocks for actions
3. **Dispatcher** → Routes delegate to background Worker (Haiku/Sonnet/Opus based on task)
4. **Worker** → Executes task with tools → Reports result via WebSocket
5. **Analyzer** → Passively observes conversation → Emits card suggestions
6. **Response** → TTS (optional) + Chat Display + Worker results + Card suggestions
7. **Cards** → Kanban Board (auto-categorized by status)

## Deployment

- **Frontend:** Static PWA built with Vite, served via Caddy reverse proxy
- **Backend:** FastAPI (uvicorn on port 8000) via systemd user unit
- **Database:** SQLite at `~/.voxyflow/voxyflow.db` (single-file, no external DB needed)
- **TTS:** XTTS v2 server (systemd user unit, GPU, port 5500)
- **LLM:** CLI subprocess (`claude -p`) using Claude Max subscription — no API key needed

## Directory Structure

```
voxyflow/
├── ARCHITECTURE.md
├── CLAUDE.md                    # Project context for Claude Code
├── personality/                 # System prompt files (loaded by personality_service)
│   ├── SOUL.md                  # Core personality
│   ├── IDENTITY.md              # Identity priming
│   ├── USER.md                  # User context
│   ├── DISPATCHER.md            # Dispatch protocol (inline tools, delegate rules)
│   ├── WORKER.md                # Worker instructions
│   ├── ANALYZER.md              # Analyzer behavior
│   ├── AGENTS.md                # 7 agent personas
│   └── MEMORY.md                # Memory service instructions
├── docs/                        # Reference documentation
├── backend/
│   ├── requirements.txt
│   ├── .env                     # Active config (CLI mode, model selection)
│   ├── mcp_stdio.py             # MCP stdio transport entry point
│   └── app/
│       ├── main.py              # FastAPI app + WebSocket handlers
│       ├── config.py            # Settings (env vars + keyring)
│       ├── database.py          # SQLAlchemy models
│       ├── mcp_server.py        # MCP tool definitions (~60 tools)
│       ├── models/              # Pydantic schemas
│       ├── routes/              # REST API endpoints
│       └── services/
│           ├── claude_service.py       # ClaudeService singleton (4 layers)
│           ├── chat_orchestration.py   # Orchestrator, delegate parsing
│           ├── personality_service.py  # System prompt builder
│           ├── board_executor.py       # Sequential board execution
│           └── llm/
│               ├── cli_backend.py      # CLI subprocess management
│               ├── api_caller.py       # API dispatch hub
│               └── client_factory.py   # SDK client creation
└── frontend-react/
    ├── package.json
    ├── vite.config.ts
    └── src/
        ├── App.tsx
        ├── types/               # Card, Project, Message types
        ├── stores/              # Zustand stores (cards, messages, projects)
        ├── hooks/api/           # TanStack Query hooks (useCards, useProjects)
        ├── services/            # TTS, WebSocket, utilities
        ├── contexts/            # ChatProvider
        ├── providers/           # WebSocketProvider
        ├── components/
        │   ├── Chat/            # MessageBubble, ChatInput, MessageList
        │   ├── Kanban/          # KanbanBoard, KanbanCard
        │   ├── Board/           # FreeBoard (Main Board grid view)
        │   └── Settings/        # VoicePanel, AboutPanel
        └── pages/               # MainPage, ProjectPage, JobsPage
```
