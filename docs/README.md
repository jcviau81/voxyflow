# Voxyflow

**AI-powered voice workspace assistant.** Talk to your workspaces. Get things done.

Voxyflow is a voice-first workspace management assistant that lives locally. You speak (or type), it understands the context of your current workspace or task card, and responds instantly via the Chat Agent (Dispatcher). Background Workers handle real execution (CRUD, research, code) without ever blocking the conversation.

---

## Key Features

- **Voice input** — Push-to-Talk via Web Speech API (fr-CA or en-US)
- **Dispatcher + Workers** — Chat Agent (Dispatcher) responds instantly, Workers execute in background
- **Workspace management** — Create workspaces with GitHub integration, tech stack auto-detection, and Kanban boards
- **Kanban boards** — Per-workspace boards with drag & drop, 4 columns, agent assignment
- **7 specialized agents** — Researcher, Coder, Designer, Architect, Writer, QA, plus a default general persona
- **Multi-provider LLM** — Claude CLI, Codex CLI, Anthropic API, OpenAI, OpenRouter, Groq, Mistral, Gemini, Ollama, LM Studio — per-layer and per-worker picks via Settings
- **Strict worker lifecycle** — Workers run `claim → work → complete` and deliver structured summaries (not raw dumps) to the dispatcher
- **RAG knowledge base** — Per-workspace ChromaDB collections; upload `.txt`/`.md` docs to inject into context
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
│  │  + Voice    │  │ + Workspaces   │  │   + RAG Docs  │  │
│  └──────┬──────┘  └──────┬───────┘  └───────┬───────┘  │
│         │ WebSocket /ws  │ REST /api         │          │
└─────────┼────────────────┼───────────────────┼──────────┘
          │                │                   │
┌─────────▼────────────────▼───────────────────▼──────────┐
│  FastAPI Backend (Python 3.12+)                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │  Chat Agent (Dispatcher)                          │   │
│  │  TOOLS_DISPATCHER or TOOLS_DISPATCHER_CODEX       │   │
│  │  Converses + inspects state + calls voxyflow.delegate │  │
│  └───────┬──────────────────────────────────────────┘   │
│          │ dispatches                                   │
│  ┌───────▼──────────────────────────────────────────┐   │
│  │  Background Workers — TOOLS_WORKER                │   │
│  │  Worker-class provider/model                      │   │
│  │  Strict lifecycle: claim → work → complete        │   │
│  │  Full MCP surface (exec, file, git, tmux, web…)   │   │
│  └───────┬──────────────────────────────────────────┘   │
│          │                                              │
│  ┌───────▼──────────────────────────────────────────┐   │
│  │  LLM Orchestration / ProviderFactory / RAGService │   │
│  └───────────────────────────┬───────────────────────┘   │
│                              │                           │
│  ┌───────────────────────────▼───────────────────────┐   │
│  │  SQLite (SQLAlchemy async) + ChromaDB + artifacts │   │
│  └───────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────┘
          │
┌─────────▼──────────────────────────────────────────┐
│  LLM provider (pluggable per layer):               │
│  cli (claude -p) | codex (codex exec) | anthropic │
│  openai | openrouter | groq | mistral | gemini    │
│  ollama | lmstudio                                 │
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
| AI | Pluggable provider (Claude CLI / Codex CLI / Anthropic / OpenAI / OpenRouter / Groq / Mistral / Gemini / Ollama / LM Studio) |
| Vector DB | ChromaDB + sentence-transformers (intfloat/multilingual-e5-large) |
| Key storage | keyring |
| Realtime | WebSocket (native FastAPI) |

### Infrastructure
| Component | Details |
|-----------|---------|
| Default LLM backend | Configurable in Settings > Models; local CLI paths include `claude -p` and `codex exec --json` |
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
| [CODEX_CLI.md](CODEX_CLI.md) | Native OpenAI Codex CLI provider and MCP behavior |
| [DATA_MODEL.md](DATA_MODEL.md) | SQLAlchemy models and schema |
