# Voxyflow Architecture

## Overview

Voxyflow is a **voice-first project management assistant** powered by Claude. It combines natural voice interaction with intelligent project management through specialized AI agent personas.

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
                      │ REST API
┌─────────────────────┼───────────────────────────┐
│                   Backend (FastAPI)              │
│  Python 3.12+ • Async • SQLite                   │
│                                                   │
│  ┌──────────────────┴──────────────────────────┐ │
│  │              Agent Router                    │ │
│  │  Analyzes intent → routes to specialist      │ │
│  └──┬───┬───┬───┬───┬───┬───┬──────────────────┘ │
│     │   │   │   │   │   │   │                    │
│  ┌──┴┐┌─┴─┐┌┴──┐┌─┴┐┌─┴─┐┌┴──┐┌───┐           │
│  │ 🔥││🏗️ ││🎨 ││📊││🧪 ││🛡️ ││🎯 │           │
│  │Cod││Arc││Des││Ana││Tes││Sec││Pro│           │
│  │eur││hit││ign││lys││teu││uri││jet│           │
│  │se ││ect││er ││te ││r  ││té ││   │           │
│  └───┘└───┘└───┘└───┘└───┘└───┘└───┘           │
│                                                   │
│  ┌─────────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Claude API  │ │ Memory   │ │ Personality  │  │
│  │ Service     │ │ Service  │ │ Service      │  │
│  └─────────────┘ └──────────┘ └──────────────┘  │
└─────────────────────────────────────────────────┘
```

## Key Design Decisions

### Voice-First, Not Voice-Only
- Primary input is voice (STT via Whisper WASM on desktop, Web Speech API on mobile)
- Text fallback always available
- TTS responses for conversational flow
- Visual kanban cards auto-generated from conversation

### Zero-Framework Frontend
- Vanilla TypeScript, no React/Vue/Angular
- Direct DOM manipulation for maximum performance
- Custom component system with lifecycle management
- EventBus pattern for decoupled communication

### Agent Personas (7 Specialists)
Each agent has a distinct personality and expertise:
1. **La Codeuse** 🔥 — Implementation, debugging, code review
2. **L'Architecte** 🏗️ — System design, patterns, scalability
3. **Le Designer** 🎨 — UI/UX, accessibility, visual design
4. **L'Analyste** 📊 — Data analysis, metrics, optimization
5. **Le Testeur** 🧪 — Testing strategy, QA, edge cases
6. **La Sécurité** 🛡️ — Security review, threat modeling
7. **Le Chef de Projet** 🎯 — Planning, priorities, coordination

### Memory & Context
- Conversation history persisted in SQLite
- Per-project context windows
- Personality consistency via SOUL.md injection
- Cross-session memory via memory service

## Data Flow

1. **Voice Input** → STT → Text → API → Agent Router
2. **Agent Router** → Intent Analysis → Specialist Selection
3. **Specialist** → Claude API (with persona prompt) → Response
4. **Response** → TTS (optional) + Chat Display + Card Generation
5. **Cards** → Kanban Board (auto-categorized by status)

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
└── frontend/
    ├── package.json
    ├── tsconfig.json
    ├── webpack.config.js
    ├── .env.example
    ├── README.md
    ├── public/
    │   ├── index.html
    │   ├── manifest.json
    │   └── sw.ts
    └── src/
        ├── main.ts
        ├── App.ts
        ├── types/
        ├── state/
        ├── services/
        ├── components/
        ├── styles/
        └── utils/
```
