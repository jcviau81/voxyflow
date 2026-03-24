# SYSTEM — Voxyflow Architecture Bible

> This is the authoritative reference for how Voxyflow works.
> If you are Voxy, this is how YOU work. Read it. Know it. Live it.

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Backend | **FastAPI** (Python 3.11+) | REST API + WebSocket server |
| Frontend | **TypeScript** (zero-framework, Web Components) | PWA single-page application |
| Database | **SQLite** (via SQLAlchemy async + aiosqlite) | Persistent storage for all entities |
| Vector DB | **ChromaDB** (intfloat/multilingual-e5-large embeddings) | RAG retrieval, memory, document search |
| Real-time | **WebSocket** (`/ws`) | Chat streaming, task events, connection state |
| AI Models | **Anthropic Claude** (Sonnet, Opus, Haiku) | 3-layer AI pipeline |
| AI Proxy | **claude-max-api** (`localhost:3457`) | OpenAI-compatible proxy for Claude API |
| Scheduler | **APScheduler** | Background jobs (heartbeat, RAG indexing, recurrence) |
| MCP | **Model Context Protocol** | Tool exposure to external AI clients (Claude Code, Cursor) |

### Key Paths

| Path | Purpose |
|------|---------|
| `~/.voxyflow/voxyflow.db` | SQLite database |
| `~/.voxyflow/chroma/` | ChromaDB vector store |
| `~/.voxyflow/data/sessions/` | Chat session files (JSON) |
| `~/.voxyflow/jobs.json` | Scheduled jobs persistence |
| `~/voxyflow/personality/` | Personality files (SOUL.md, AGENTS.md, etc.) |
| `~/voxyflow/settings.json` | Application settings |

---

## The 3-Layer Chat Pipeline

This is the core of how Voxy processes every message.

```
User sends message via WebSocket
    │
    ▼
┌──────────────────────────────────────────────┐
│  LAYER 1: FAST (Sonnet)                      │
│  OR                                          │
│  LAYER 2: DEEP (Opus) — if deep_enabled      │
│                                              │
│  Streams response directly to chat.          │
│  Parses <delegate> blocks from response.     │
│  Emits ActionIntent to EventBus.             │
└──────────────────────────────────────────────┘
    │                           │
    ▼                           ▼
┌──────────────┐   ┌──────────────────────────┐
│  Chat output │   │  DeepWorkerPool          │
│  (streamed   │   │  (max 3 workers/session) │
│   to user)   │   │                          │
└──────────────┘   │  Picks up ActionIntents   │
                   │  Executes via Claude API   │
                   │  Has FULL tool access      │
                   │                          │
                   │  Emits:                   │
                   │  • task:started            │
                   │  • task:progress           │
                   │  • task:completed          │
                   └──────────────────────────┘
    │
    ▼
┌──────────────────────────────────────────────┐
│  LAYER 3: ANALYZER (Haiku)                   │
│  Runs in background on EVERY message.        │
│  Detects potential cards from conversation.   │
│  Emits card:suggestion events.               │
└──────────────────────────────────────────────┘
```

### Mutual Exclusivity

Fast and Deep are **mutually exclusive** for chat output:
- **Default mode**: Fast (Sonnet) streams to chat. Deep workers run in background.
- **Deep mode** (`deep_enabled=true`): Opus streams to chat instead. No Fast layer.
- **Analyzer always runs** in both modes (background card detection).

### Layer Models

| Layer | Default Model | Role | Tool Access |
|-------|--------------|------|-------------|
| Fast | `claude-sonnet-4-20250514` | Chat responses, dispatching | Read-only |
| Deep | `claude-opus-4-20250514` | Background workers, complex tasks | Full |
| Analyzer | `claude-haiku-4-20250514` | Card detection, suggestions | CRUD |

Models can be overridden in `settings.json` → `models.{layer}`.

---

## EventBus & SessionEventBus

### SessionEventBus (per-session)

Each chat session gets its own async event bus for Fast→Deep communication.

```python
class SessionEventBus:
    emit(ActionIntent)    # Push intent to queue
    listen()              # Async generator for consumers (workers)
    close()               # Graceful shutdown
    pending_count         # Queue size
```

### ActionIntent

```python
@dataclass
class ActionIntent:
    task_id: str          # Unique task identifier
    intent_type: str      # Type of action
    intent: str           # What to do
    summary: str          # Human-readable summary
    data: dict            # Contextual data
    session_id: str       # Owning session
    complexity: str       # "simple" | "moderate" | "complex"
    model: str            # "haiku" | "sonnet" | "opus"
```

### EventBusRegistry

Global registry mapping session IDs → SessionEventBus instances.

---

## DeepWorkerPool

Per-session async worker pool that executes background tasks.

- **MAX_WORKERS = 3** per session
- Listens on SessionEventBus for ActionIntent events
- Executes intents via `ClaudeService.execute_worker_task()`
- Workers have **full tool access** (unlike the chat layer)
- Sends WebSocket events: `task:started` → `task:progress` → `task:completed`
- If WebSocket disconnects, stores results in `PendingResults` for delivery on reconnect

---

## The Proxy: claude-max-api

**What it is:** An OpenAI-compatible HTTP proxy running at `http://localhost:3457/v1` that forwards requests to the Anthropic Claude API.

**What it does:**
- Translates OpenAI-format requests to Anthropic API format
- Handles authentication (API key management)
- Provides a fallback when native Anthropic SDK is unavailable

**What it does NOT do:**
- **NO tool forwarding** — Tools are handled entirely server-side by the tool system
- **NO streaming transformation** — Backend handles streaming directly
- The proxy is a simple pass-through for chat completions only

**Client modes in ClaudeService:**
- **Native** (primary): `anthropic.Anthropic()` — direct SDK calls
- **Proxy** (fallback): `openai.OpenAI(base_url="http://localhost:3457/v1")` — when native unavailable

---

## Server-Side Tool System

Tools are NOT forwarded through the proxy. The entire tool lifecycle is server-side.

### Architecture

```
System Prompt includes tool definitions
    │
    ▼
LLM generates <tool_call> blocks in response
    │
    ▼
ToolResponseParser extracts ParsedToolCall objects
    │
    ▼
ToolExecutor dispatches to registered handlers
    │
    ▼
Results injected back into conversation as <tool_result>
    │
    ▼
LLM continues with tool results
```

### Components

| Component | File | Purpose |
|-----------|------|---------|
| **ToolRegistry** | `tools/registry.py` | Central registry: name → handler + schema |
| **ToolPromptBuilder** | `tools/prompt_builder.py` | Generates tool instructions for system prompts |
| **ToolResponseParser** | `tools/response_parser.py` | Extracts `<tool_call>` blocks from LLM text |
| **ToolExecutor** | `tools/executor.py` | Dispatches calls to handlers, validates params |

### Layer-Based Access Control

| Layer | Tool Set | Access Level |
|-------|----------|-------------|
| Fast (Sonnet) | `TOOLS_READ_ONLY` | health, list, get operations only |
| Analyzer (Haiku) | `TOOLS_VOXYFLOW_CRUD` | read + create/update/move/duplicate |
| Deep (Opus) | `TOOLS_FULL` | everything including exec, delete, commit |

### Tool Call Format

```xml
<tool_call>
{"name": "voxyflow.card.create", "arguments": {"project_id": "abc", "title": "Fix bug"}}
</tool_call>
```

---

## Card Lifecycle

### Creation

Cards can be created in two places:
1. **Main Board** — `POST /api/cards/unassigned` — No project, free-floating
2. **Project Kanban** — `POST /api/projects/{project_id}/cards` — Assigned to project

### Status Flow

```
card → idea → todo → in-progress → done → archived
```

| Status | Meaning |
|--------|---------|
| `card` | Main Board card (default for unassigned) |
| `idea` | Project card in ideation phase |
| `todo` | Ready to work on |
| `in-progress` | Currently being worked on |
| `done` | Completed |
| `archived` | Hidden from active views |

### Movement Between Boards

- **Assign to project**: `PATCH /api/cards/{card_id}/assign/{project_id}`
- **Unassign from project**: `PATCH /api/cards/{card_id}/unassign` (back to Main Board)
- Cards can move freely between Main Board and any Project.

### Agent Assignment

Cards can be assigned to one of 7 agent types:
- **ember** (🔥) — Default generalist
- **researcher** (🔍) — Deep analysis
- **coder** (💻) — Code generation
- **designer** (🎨) — UI/UX design
- **architect** (🏗️) — System design
- **writer** (✍️) — Content/docs
- **qa** (🧪) — Testing/validation

Agent routing is automatic (BMAD-inspired keyword matching) but can be overridden.

---

## WebSocket vs REST

### WebSocket (`/ws`)

Used for **real-time, streaming interactions**:
- Chat messages (user → AI → streamed response)
- Task events (task:started, task:progress, task:completed)
- Card suggestions (analyzer results)
- Connection state management (ping/pong)
- Session reset

**Message types received:**
- `ping` → responds with `pong`
- `chat:message` → triggers 3-layer pipeline
- `session:reset` → clears session history

**Events sent to client:**
- `chat:response` — Streamed AI response chunks
- `chat:enrichment` — Deep layer enrichment results
- `task:started` / `task:progress` / `task:completed` — Worker status
- `card:suggestion` — Analyzer card suggestions
- `tool:result` — Tool execution feedback
- `model:status` — Layer state changes

### REST API

Used for **CRUD operations and data fetching**:
- All card/project/document/wiki CRUD
- Session history retrieval
- Settings management
- GitHub integration
- Health checks
- File uploads

See `docs/API_REFERENCE.md` for the complete endpoint list.

---

## Application Startup

1. **Database init** — SQLAlchemy engine + auto-migrations (add missing columns, update statuses)
2. **Service init** — ClaudeService, SchedulerService, RAGService (all graceful degradation)
3. **Tool registry** — Auto-register all tools from MCP definitions
4. **Scheduler start** — Heartbeat (2min), RAG indexer (15min), recurrence (1hr)
5. **MCP server** — Initialize if `mcp` package available
6. **CORS** — Allow all origins (development mode)
7. **Mount routes** — All API routers + WebSocket endpoint

---

## Configuration

### settings.json

```json
{
  "personality": {
    "bot_name": "Voxy",
    "preferred_language": "auto",
    "tone": "casual",
    "warmth": "warm"
  },
  "models": {
    "fast": { "model": "claude-sonnet-4-20250514" },
    "deep": { "model": "claude-opus-4-20250514", "enabled": true },
    "analyzer": { "model": "claude-haiku-4-20250514", "enabled": true }
  },
  "scheduler": {
    "enabled": true,
    "heartbeat_interval_minutes": 2,
    "rag_index_interval_minutes": 15
  }
}
```

### Environment & Secrets

- `CLAUDE_API_KEY` — from keyring, env var, or settings.json
- `claude_use_native` — `true` for Anthropic SDK, `false` for proxy fallback
- `VOXYFLOW_API_BASE` — MCP server target (default: `http://localhost:8000`)

---

_This is the system. Know it completely. Reference other docs/ files for specifics._
