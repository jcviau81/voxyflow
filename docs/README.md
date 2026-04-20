# Voxyflow

**AI-powered voice project assistant.** Talk to your projects. Get things done.

Voxyflow is a voice-first project management assistant that lives locally. You speak (or type), it understands the context of your current project or task card, and responds instantly via the Chat Agent (Dispatcher). Background Workers handle real execution (CRUD, research, code) without ever blocking the conversation.

---

## Key Features

- **Voice input** — Push-to-Talk via Web Speech API (fr-CA or en-US)
- **Dispatcher + Workers** — Chat Agent (Dispatcher) responds instantly, Workers execute in background
- **Project management** — Create projects with GitHub integration, tech stack auto-detection, and Kanban boards
- **Kanban boards** — Per-project boards with drag & drop, 4 columns, agent assignment
- **7 specialized agents** — Researcher, Coder, Designer, Architect, Writer, QA, plus a default general persona
- **Multi-provider LLM** — CLI (Claude Max), Anthropic API, OpenAI, Groq, Mistral, Gemini, Ollama, LM Studio — per-layer pick via Settings
- **Strict worker lifecycle** — Workers run `claim → work → complete` and deliver structured summaries (not raw dumps) to the dispatcher
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
│  │  Chat Agent (Dispatcher) — TOOLS_DISPATCHER       │   │
│  │  Converses + inline CRUD + emits <delegate>       │   │
│  │  Fast (Haiku) / Deep (Opus)                       │   │
│  └───────┬──────────────────────────────────────────┘   │
│          │ dispatches                                   │
│  ┌───────▼──────────────────────────────────────────┐   │
│  │  Background Workers — TOOLS_WORKER                │   │
│  │  Worker-class model (Haiku / Sonnet / Opus)       │   │
│  │  Strict lifecycle: claim → work → complete        │   │
│  │  Full MCP surface (exec, file, git, tmux, web…)   │   │
│  └───────┬──────────────────────────────────────────┘   │
│          │                                              │
│  ┌───────▼──────────────────────────────────────────┐   │
│  │  ClaudeService / ProviderFactory / RAGService     │   │
│  └───────────────────────────┬───────────────────────┘   │
│                              │                           │
│  ┌───────────────────────────▼───────────────────────┐   │
│  │  SQLite (SQLAlchemy async) + ChromaDB + artifacts │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
          │
┌─────────▼──────────────────────────────────────────┐
│  LLM provider (pluggable per layer):               │
│  cli (claude -p) | anthropic | openai | groq |     │
│  mistral | gemini | ollama | lmstudio              │
└────────────────────────────────────────────────────┘
```

**Key principle:** The conversation is never blocked by running tasks. The Chat Agent dispatches, Workers execute in the background, and results stream back via WebSocket.

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
| AI | Pluggable provider (CLI / Anthropic / OpenAI / Groq / Mistral / Gemini / Ollama / LM Studio) |
| Vector DB | ChromaDB + sentence-transformers (intfloat/multilingual-e5-large) |
| Key storage | keyring |
| Realtime | WebSocket (native FastAPI) |

### Infrastructure
| Component | Details |
|-----------|---------|
| Default LLM backend | `claude -p` CLI subprocess (uses your Claude Max subscription; no API key) |
| Named endpoints | Any local or remote provider saved in Settings → Models and referenced by id |
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
cd frontend-react && npm install && npm run dev
```

See [SETUP.md](SETUP.md) for the full installation guide.

---

## Documentation

| Doc | Contents |
|-----|---------|
| [SETUP.md](SETUP.md) | Installation & configuration (LLM backend, XTTS, onboarding) |
| [CONTEXT_GUIDE.md](CONTEXT_GUIDE.md) | Context management, workflow examples, DailyOps setup |
| [FEATURES.md](FEATURES.md) | Complete feature reference |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Technical architecture deep-dive |
| [API.md](API.md) | REST & WebSocket API reference |
| [CHAT_SCOPES.md](CHAT_SCOPES.md) | Chat levels technical reference (tools, routing, session model) |
| [AGENTS.md](AGENTS.md) | 7 specialist agents — personas, routing, tool access |
| [MEMORY.md](MEMORY.md) | Memory service — persistent cross-session recall |
| [VOICE_FLOW.md](VOICE_FLOW.md) | Voice pipeline — STT engines, wake word, TTS streaming |
| [TOOLS.md](TOOLS.md) | MCP tool registry — categories, layer access control |
| [DATA_MODEL.md](DATA_MODEL.md) | SQLAlchemy models and schema |
