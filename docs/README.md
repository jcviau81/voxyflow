# Voxyflow

**AI-powered voice project assistant.** Talk to your projects. Get things done.

Voxyflow is a voice-first, multi-model project management assistant that lives locally. You speak (or type), it understands the context of your current project or task card, and responds instantly — with a fast layer for immediacy, a deep layer for accuracy, and an analyzer layer that silently detects actionable items from your conversation and turns them into Kanban cards.

---

## Key Features

- **Voice input** — Push-to-Talk via Web Speech API (fr-CA or en-US)
- **3-layer multi-model chat** — Fast (immediate stream) + Deep (enrichment) + Analyzer (background card detection)
- **Project management** — Create projects with GitHub integration, tech stack auto-detection, and Kanban boards
- **Kanban boards** — Per-project boards with drag & drop, 4 columns, agent assignment
- **7 specialized agents** — Ember, Codeuse, Architecte, Recherchiste, Designer, Rédactrice, QA
- **RAG knowledge base** — Per-project ChromaDB collections; upload `.txt`/`.md` docs to inject into context
- **Free Board** — Sticky-note scratchpad for the general chat with 6 pastel colors
- **Opportunities panel** — AI-suggested cards from conversation analysis
- **Personality system** — Fully configurable bot name, tone, warmth, language, and personality files
- **PWA** — Installable, offline-capable service worker
- **Dark theme** — Responsive layout, toast notifications, keyboard shortcuts

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│  Browser (Voxyflow PWA)                                  │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  Chat UI    │  │ Kanban Board │  │   Settings    │  │
│  │  + Voice    │  │ + Projects   │  │   + RAG Docs  │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬───────┘  │
│         │ WebSocket /ws  │ REST /api         │          │
└─────────┼────────────────┼───────────────────┼──────────┘
          │                │                   │
┌─────────▼────────────────▼───────────────────▼──────────┐
│  FastAPI Backend (Python 3.12+)                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  WebSocket Handler  — 3-layer orchestration      │   │
│  │  ┌──────────┐  ┌──────────┐  ┌────────────────┐ │   │
│  │  │ Layer 1  │  │ Layer 2  │  │   Layer 3      │ │   │
│  │  │  Fast    │  │  Deep    │  │  Analyzer      │ │   │
│  │  │  Stream  │  │ Enrich   │  │  Card Detect   │ │   │
│  │  └────┬─────┘  └────┬─────┘  └───────┬────────┘ │   │
│  └───────┼─────────────┼────────────────┼───────────┘   │
│          │             │                │               │
│  ┌───────▼─────────────▼────────────────▼───────────┐   │
│  │  ClaudeService / AnalyzerService / RAGService     │   │
│  └───────────────────────────┬───────────────────────┘   │
│                              │                           │
│  ┌───────────────────────────▼───────────────────────┐   │
│  │  SQLite (SQLAlchemy async)  +  ChromaDB            │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
          │
┌─────────▼──────────────────────────────────────────┐
│  claude-max-api-proxy (or any OpenAI-compat proxy) │
│  http://localhost:3456/v1                          │
└────────────────────────────────────────────────────┘
```

---

## Tech Stack

### Frontend
| Layer | Technology |
|-------|-----------|
| Language | TypeScript 5.5 (Vanilla — no framework) |
| Build | Webpack 5 + ts-loader |
| Styles | Plain CSS with CSS variables |
| Markdown | marked + highlight.js + DOMPurify |
| PWA | Workbox (service worker) |
| Tests | Jest (unit) + Playwright (e2e) |

### Backend
| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| Framework | FastAPI + Uvicorn |
| Database | SQLite via SQLAlchemy (asyncio) |
| AI | Anthropic Claude (via OpenAI-compat proxy) |
| Vector DB | ChromaDB + sentence-transformers (all-MiniLM-L6-v2) |
| Key storage | keyring |
| Realtime | WebSocket (native FastAPI) |

### Infrastructure
| Component | Details |
|-----------|---------|
| API proxy | claude-max-api-proxy (localhost:3456) or any OpenAI-compat endpoint |
| STT | Web Speech API (client-side, browser-native) |
| TTS | XTTS v2 (optional, via HTTP service) or browser TTS |

---

## Quick Start

```bash
# Backend
cd backend && python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```

See [SETUP.md](SETUP.md) for the full installation guide.

---

## Documentation

| Doc | Contents |
|-----|---------|
| [FEATURES.md](FEATURES.md) | Complete feature reference |
| [SETUP.md](SETUP.md) | Installation & configuration |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Technical architecture deep-dive |
| [API.md](API.md) | REST & WebSocket API reference |
