# Voxyflow Architecture

## Overview

Voxyflow is a **voice-first project management assistant** powered by Claude. It combines natural voice interaction with intelligent project management through a Dispatcher + Workers architecture.

## System Architecture

```
┌─────────────────────────────────────────────────┐
│                   Frontend (PWA)                 │
│  TypeScript • Vanilla DOM • Service Worker       │
│                                                   │
│  ┌──────────┐ ┌──────────┐ ┌──────────────────┐ │
│  │ Voice    │ │ Chat     │ │ Kanban Board     │ │
│  │ Input    │ │ Window   │ │ (Auto-generated) │ │
│  └────┬─────┘ └────┬─────┘ └────────┬─────────┘ │
│       │             │                │            │
│  ┌────┴─────────────┴────────────────┴─────────┐ │
│  │            State Management (AppState)       │ │
│  │            EventBus • StorageService         │ │
│  └──────────────────┬──────────────────────────┘ │
└─────────────────────┼───────────────────────────┘
                      │ REST + WebSocket
┌─────────────────────┼───────────────────────────┐
│                   Backend (FastAPI)              │
│  Python 3.12+ • Async • SQLite                   │
│                                                   │
│  ┌──────────────────┴──────────────────────────┐ │
│  │         Chat Agent (Dispatcher)              │ │
│  │  Zero tools • Converses • Dispatches work    │ │
│  │  Fast mode (Sonnet) / Deep mode (Opus)       │ │
│  └──┬───────────────────────────────┬──────────┘ │
│     │ <delegate> blocks             │ observes   │
│  ┌──▼──────────────────────┐  ┌────▼─────────┐  │
│  │   Background Workers    │  │   Analyzer    │  │
│  │  ┌───────┐ ┌─────────┐ │  │  Passive      │  │
│  │  │ Haiku │ │ Sonnet  │ │  │  observer     │  │
│  │  │ CRUD  │ │Research │ │  │  Card detect  │  │
│  │  └───────┘ └─────────┘ │  │  Patterns     │  │
│  │  ┌───────┐             │  │  Suggestions  │  │
│  │  │ Opus  │ ALL tools   │  └──────────────┘  │
│  │  │Complex│ here        │                     │
│  │  └───────┘             │                     │
│  └─────────────────────────┘                     │
│                                                   │
│  ┌─────────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Claude API  │ │ Memory   │ │ Personality  │  │
│  │ Service     │ │ Service  │ │ Service      │  │
│  └─────────────┘ └──────────┘ └──────────────┘  │
└─────────────────────────────────────────────────┘
```

### Core Architecture Principle

**The conversation is never blocked by running tasks.**

- The **Chat Agent (Dispatcher)** has zero tools. It reads, speaks, and dispatches.
- **Workers** run in the background, execute tasks with full tool access, and report results via WebSocket.
- The **Analyzer** passively observes conversations and surfaces opportunities (card suggestions, patterns) without interrupting.

## Key Design Decisions

### Voice-First, Not Voice-Only
- Primary input is voice (STT via Whisper WASM on desktop, Web Speech API on mobile)
- Text fallback always available
- TTS responses for conversational flow
- Visual kanban cards auto-generated from conversation

### React Frontend
- React 19 + TypeScript + Vite
- Zustand for state management, TanStack Query for data fetching
- Custom component system with lifecycle management
- EventBus pattern for decoupled communication

### Agent Personas (7 Specialists)
Cards and conversations can be routed to specialized agents:
1. **Ember** 🔥 — Default, general conversation, coordination
2. **Researcher** 🔍 — Deep analysis, fact-checking, long-form research
3. **Coder** 💻 — Code generation, debugging, optimization
4. **Designer** 🎨 — UI/UX thinking, visual design guidance
5. **Architect** 🏗️ — System design, planning, PRD writing
6. **Writer** ✍️ — Content, marketing, storytelling
7. **QA** 🧪 — Testing strategies, edge cases, validation

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

- **Frontend:** Static PWA hosted on any CDN/server
- **Backend:** FastAPI on VPS (thething) or container
- **Database:** SQLite (single-file, no external DB needed)
- **API:** Claude API direct (no OpenClaw overhead for voice latency)

## Directory Structure

```
voxyflow/
├── README.md
├── LICENSE
├── ARCHITECTURE.md
├── .gitignore
├── docs/
│   ├── ARCHITECTURE.md
│   ├── VOICE_FLOW.md
│   ├── DEPLOYMENT.md
│   ├── PERSONALITY.md
│   ├── AGENTS.md
│   └── FRONTEND_ARCHITECTURE.md
├── backend/
│   ├── requirements.txt
│   ├── .env.example
│   ├── README.md
│   └── app/
│       ├── main.py
│       ├── config.py
│       ├── database.py
│       ├── models/
│       ├── routes/
│       └── services/
└── frontend-react/
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── router.tsx
        ├── types/
        ├── stores/
        ├── hooks/
        ├── services/
        ├── contexts/
        ├── providers/
        ├── components/
        ├── pages/
        └── utils/
```
