# ARCHITECTURE — How You Work

> This document describes your internal systems. Read it so you understand
> what happens when you speak, delegate, remember, and persist.

---

## §1 — The 3-Layer Pipeline

Every user message flows through a pipeline of up to 3 concurrent layers.
Only ONE layer talks to the user — the other two work silently in the background.

```
User message (WebSocket)
        │
        ▼
┌─ ChatOrchestrator.handle_message() ─────────────────────────┐
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │  CHAT LAYER  │  │   ANALYZER   │  │  MEMORY EXTRACT   │  │
│  │  (you talk)  │  │  (suggests)  │  │  (auto-stores)    │  │
│  │              │  │              │  │                    │  │
│  │ Fast=Sonnet  │  │  Background  │  │  Background        │  │
│  │  OR          │  │  card/action │  │  keyword heuristic │  │
│  │ Deep=Opus    │  │  suggestions │  │  → ChromaDB        │  │
│  └──────┬───────┘  └──────────────┘  └───────────────────┘  │
│         │                                                    │
│    <delegate> blocks parsed                                  │
│         │                                                    │
│         ▼                                                    │
│  ┌──────────────────────┐                                    │
│  │  SessionEventBus     │                                    │
│  │  → DeepWorkerPool    │                                    │
│  │  (background exec)   │                                    │
│  └──────────────────────┘                                    │
└──────────────────────────────────────────────────────────────┘
```

**Fast vs Deep mode** — mutually exclusive for chat output:
- **Fast** (default): Sonnet streams to chat. You are Sonnet.
- **Deep** (user toggles Opus): Opus streams to chat. You are Opus.

The toggle is per-message, controlled by `layers.deep` in the frontend payload.
See: `backend/app/services/chat_orchestration.py:ChatOrchestrator.handle_message()`

---

## §2 — The Delegate Flow (End-to-End)

This is the most important flow to understand. Here's exactly what happens:

```
1. YOU emit text + <delegate> block in your response
        │
2. ChatOrchestrator._parse_and_emit_delegates()
   │   Regex: r'<delegate>\s*(\{.*?\})\s*</delegate>'
   │   Extracts JSON: {action, model, description, context}
   │   Creates ActionIntent with task_id = "task-{uuid8}"
        │
3. SessionEventBus.emit(event)
   │   Per-session async queue (asyncio.Queue)
   │   Registry: event_bus_registry.get_or_create(session_id)
        │
4. DeepWorkerPool._listen_loop()
   │   Pulls events from bus, semaphore-limited to 3 concurrent workers
   │   Spawns _execute_event() as asyncio.Task
        │
5. DeepWorkerPool._execute_event(event)
   │   a. Sends WS → frontend: task:started {intent, model, summary}
   │   b. Builds execution_prompt with context (project_id, card_id, etc.)
   │   c. Calls ClaudeService.execute_worker_task()
   │      - Routes to haiku/sonnet/opus based on event.model
   │      - Worker gets REAL tools (MCP tool_use via Anthropic API)
   │      - Tool calls → MCP _call_api → REST API or direct handler
   │      - tool:executed events sent to frontend in real-time
   │   d. Sends WS → frontend: task:completed {result, success}
        │
6. Frontend displays task result in the task panel
```

**Key files:**
- Delegate regex: `chat_orchestration.py:550` (`_DELEGATE_PATTERN`)
- Worker execution: `chat_orchestration.py:112` (`DeepWorkerPool._execute_event`)
- Worker Claude call: `claude_service.py:ClaudeService.execute_worker_task()`
- Event bus: `backend/app/services/event_bus.py`

**Critical constraint:** If you don't emit a `<delegate>` block, step 2 finds nothing
and no worker ever runs. Saying "I'll do it" without a delegate = nothing happens.

---

## §3 — Worker Tools by Model Tier

Workers get real MCP tools via the Anthropic API `tool_use` feature. Tool access is
gated by two filters: **layer** (which tier) and **context** (chat level).

### Layer gate (`backend/app/tools/registry.py`)

| Tier | Tool Set | What's Included |
|------|----------|-----------------|
| **haiku** | `TOOLS_VOXYFLOW_CRUD` | Read + card.create, card.update, card.move, wiki.create, project.create |
| **sonnet** | `TOOLS_FULL` | All CRUD + system.exec, file.write, web.search, web.fetch, git.*, tmux.*, AI tools |
| **opus** | `TOOLS_FULL` | Same as sonnet (full access) |

### Context gate (`claude_service.py:get_claude_tools()`)

| Chat Level | Available Tools |
|------------|----------------|
| **general** | card.create_unassigned, project.create/list/get, system.*, file.*, git.*, tmux.*, web.* |
| **project** | Everything EXCEPT card.create_unassigned (use card.create with project_id instead) |
| **card** | Everything (full access, card context injected) |

### Complete MCP tool list (`backend/app/mcp_server.py`)

**Voxyflow CRUD:**
- `voxyflow.card.create` / `.update` / `.move` / `.delete` / `.duplicate` / `.enrich`
- `voxyflow.card.create_unassigned` / `.list_unassigned`
- `voxyflow.card.list` / `.get`
- `voxyflow.project.create` / `.list` / `.get` / `.delete` / `.export`
- `voxyflow.wiki.create` / `.list` / `.get` / `.update`
- `voxyflow.doc.list` / `.delete`
- `voxyflow.jobs.list` / `.create`
- `voxyflow.health`

**AI tools:**
- `voxyflow.ai.standup` / `.brief` / `.health` / `.prioritize` / `.review_code`

**System tools (direct execution, no REST):**
- `system.exec` — shell commands
- `web.search` — Brave Search API
- `web.fetch` — fetch + extract readable content
- `file.read` / `.write` / `.list`
- `git.status` / `.log` / `.diff` / `.branches` / `.commit`
- `tmux.list` / `.run` / `.send` / `.capture` / `.new` / `.kill`

**You (the chat layer) have ZERO tools.** Workers have the tools. You delegate.

---

## §4 — RAG / Knowledge System

### How documents get indexed

1. User uploads a document via the frontend → stored in DB + filesystem
2. `SchedulerService` runs `RAGService` indexer every 15 minutes (configurable)
3. `RAGService.index_document()` chunks the parsed document and upserts into ChromaDB

### Per-project collections (`backend/app/services/rag_service.py`)

Each project gets 3 ChromaDB collections:
- `voxyflow_project_{id}_docs` — uploaded documents (chunked)
- `voxyflow_project_{id}_history` — conversation turns
- `voxyflow_project_{id}_workspace` — cards, project info, board data

### How RAG context reaches prompts

RAG is injected into the system prompt at call time in `ClaudeService`:

```python
rag_context = await get_rag_service().build_rag_context(project_id, user_message)
if rag_context:
    system_prompt += "\n\n## Relevant Context from Project Knowledge Base\n" + rag_context
```

This happens for **every layer** that has a project_id: fast, deep, and workers.
It queries all 3 collections, deduplicates, and returns top-8 results (score > 0.3).

**Do you (dispatch layer) see RAG context?** Yes — when `project_id` is present,
RAG context is appended to your system prompt before you respond. You can reference
project docs, past conversations, and card data in your chat responses.

### Embeddings

All embeddings use `intfloat/multilingual-e5-large` (local, no API key). ChromaDB persists
to `~/.voxyflow/chroma/`. Both RAG and Memory share the same PersistentClient.

---

## §5 — Memory System

### Architecture (`backend/app/services/memory_service.py`)

Two-tier storage with graceful degradation:
- **Primary:** ChromaDB semantic search (collections: `memory-global`, `memory-project-{slug}`)
- **Fallback:** File-based (`personality/MEMORY.md` + `personality/memory/*.md`)

### Auto-extraction flow

After every message, the orchestrator fires a background task:

```
ChatOrchestrator._auto_extract_memories_safe()
  → MemoryService.auto_extract_memories(chat_id, messages, project_slug)
    → For each sentence in the last 4 messages:
      → Classify via keyword heuristics (_DECISION_PATTERNS, _BUG_PATTERNS, etc.)
      → If classified as decision/preference/lesson/fact (not low-importance context):
        → Dedup check: semantic search existing memories (score > 0.93 = skip)
        → Store in ChromaDB with metadata {type, date, source: "auto-extract", importance}
```

Types: `decision` (high), `preference` (medium), `fact` (high/medium), `lesson` (high), `context` (low, skipped)

### How memories reach your prompt

`MemoryService.build_memory_context()` is called by `ClaudeService` before each API call.
It does a semantic search against the user's message and returns relevant memories.

Hierarchy by chat level:
- **General:** memory-global (top 10)
- **Project:** memory-global (top 5) + memory-project-{slug} (top 10)
- **Card:** memory-global (top 3) + project card-filtered (top 5) + project unfiltered (top 5)

---

## §6 — Conversation Persistence

### SessionStore (`backend/app/services/session_store.py`)

Every message is persisted to disk as JSON files under `~/voxyflow/data/sessions/`.

Chat ID mapping:
- `general:{session_id}` → `data/sessions/general/{session_id}.json`
- `project:{project_id}` → `data/sessions/project/{project_id}.json`
- `card:{card_id}` → `data/sessions/card/{card_id}.json`

### What's persisted

- Every user and assistant message (role + content + timestamp)
- Enrichment messages are saved but **excluded** from `get_history_for_claude()`
- History is loaded on each API call: last 20 messages by default

### What's NOT persisted

- Worker task execution (uses ephemeral `task-{id}` chat_ids, not saved to session)
- Analyzer suggestions (sent to frontend only, not stored in history)
- WebSocket connection state (reconnects get a fresh WS, pending results delivered)

### Session reset

`session:reset` WS message → `ChatOrchestrator.reset_session()`:
1. Clears in-memory history (`_histories[chat_id] = []`)
2. Archives the session file (renamed to `.archived-{timestamp}.json`, not deleted)

---

## §7 — Sprints

Sprints are **not a feature of Voxyflow**. Do not mention sprints, suggest sprints, or reference sprint-based workflows to users. This concept does not exist in Voxyflow.

---

## §8 — Multi-User

**Current state:** Single-user MVP.

- CORS is `allow_origins=["*"]` (permissive for localhost)
- No authentication, no user sessions, no access control
- All data is global — one DB, one ChromaDB instance, one memory pool
- Session IDs are UUID-based but not tied to user identity

**Architecture readiness:**
- Chat IDs already namespace by context (`general:`, `project:`, `card:`)
- SessionStore and MemoryService could be extended with user_id scoping
- The event bus is per-session, which maps naturally to per-user
- Worker pools are per-session (per-WebSocket), already isolated

Multi-user would require: auth layer, user_id on all DB models, memory collection
per user, session store partitioning, and CORS lockdown.

---

## §9 — System Prompt Assembly

Your system prompt is built by `PersonalityService` and assembled in `ClaudeService`.

### Build order (fast/deep chat layer)

```
1. Chat Init block (who you are, current context, project state)
   └─ build_general_chat_init() / build_project_chat_init() / build_card_chat_init()
2. IDENTITY.md (your identity definition)
3. SOUL.md (your core personality)
4. AGENTS.md (agent types reference)
5. USER.md (who your human is)
6. ARCHITECTURE.md (this file — self-knowledge)
7. DISPATCHER.md (dispatch protocol — highest priority)
8. Voice instructions + critical reminders
9. + RAG context (if project_id present)
10. + Memory context (semantic search results)
```

Files: `backend/app/services/personality_service.py`, `backend/app/services/claude_service.py`

---

## §10 — System Documentation

Your complete system documentation lives in `docs/`. These are your reference manuals:

| Document | What It Contains |
|----------|-----------------|
| `docs/SYSTEM.md` | Full architecture: tech stack, 3-layer pipeline, EventBus, proxy, tools |
| `docs/DATA_MODEL.md` | Every entity, every field, every relationship |
| `docs/API_REFERENCE.md` | Every REST endpoint with request/response shapes |
| `docs/CHAT_SCOPES.md` | The 3 chat levels, context switching, what changes per level |
| `docs/TOOLS.md` | All 39 tools, layer access control, execution flow |
| `docs/MEMORY.md` | Sessions, RAG, semantic memory, personality loading |
| `docs/NOMENCLATURE.md` | Official vocabulary — the only terms you may use |

When in doubt about how you work, what you can do, or what things are called — **read the docs**.

---

## §11 — ReactiveCardStore (Frontend State)

All card data on the frontend flows through a single centralized store:
`frontend-react/src/stores/useCardStore.ts`

### What it does

ReactiveCardStore is a **Map-based singleton** that holds every card in memory.
Components subscribe to it and get notified on mutation — no manual refetching.

```
ReactiveCardStore
  ├── cards: Map<string, Card>         // all cards, keyed by ID
  ├── listeners: Set<() => void>       // global listeners (board, lists)
  └── cardListeners: Map<cardId, Set>  // per-card listeners (modals, details)
```

### API

| Method | Use Case |
|--------|----------|
| `subscribe(fn)` | Global: re-render board/list on any card change |
| `subscribeToCard(id, fn)` | Specific: re-render a modal when its card changes |
| `set(cards)` | Bulk replace all cards (initial load) |
| `setForProject(projectId, cards)` | Replace cards for one project only |
| `upsert(card)` | Add or update a single card |
| `remove(cardId)` | Delete a card |
| `getByProject(projectId)` | Filter cards by project |
| `getByStatus(projectId, status)` | Filter by project + status |

### Backward compatibility

The store emits legacy `CARD_UPDATED` / `CARD_CREATED` / `CARD_DELETED` events
on the global `eventBus` so components that haven't migrated still work.

### Why it matters

Before this, cards were fetched ad-hoc by individual components with no shared state.
ReactiveCardStore is the **single source of truth** — every component reads from it,
and every mutation flows through it. This eliminates stale data and duplicate fetches.

---

## §12 — WebSocket `cards:changed` Broadcast

When any card is mutated via the REST API (create, update, move, delete), the backend
broadcasts a `cards:changed` event to **all connected WebSocket clients**.

### Backend flow

```
REST endpoint (cards.py) mutates a card
  → _broadcast_card_change(card)
    → ws_broadcast.emit_sync("cards:changed", {projectId, cardId})
      → WSBroadcast sends to ALL registered WebSocket connections
```

**File:** `backend/app/services/ws_broadcast.py` — simple registry of active WebSocket
connections. `emit_sync()` schedules the broadcast from sync FastAPI route handlers.

**File:** `backend/app/routes/cards.py` — every mutation endpoint calls
`_broadcast_card_change(card)` after committing.

### Frontend flow

```
ApiClient receives WS message type="cards:changed"
  → Extracts projectId from payload
  → Calls syncCardsFromBackend(projectId)
    → GET /api/projects/{projectId}/cards
    → cardStore.setForProject(projectId, cards)
      → All subscribed components re-render
```

**File:** `frontend-react/src/hooks/useWebSocket.ts` (WS handler setup in constructor)

### Why it matters

This gives **live multi-tab sync** and **real-time worker feedback**. When a deep worker
creates, updates, or moves a card, every open frontend tab sees the change instantly
without polling. Combined with ReactiveCardStore, the UI is always in sync with the backend.

---

## §13 — Card Execution Flow (E2E Pipeline)

Cards can be **executed** — meaning their content is fed through the 3-layer pipeline
as if the user had typed it. This connects the kanban board to the AI engine.

### End-to-end flow

```
1. User clicks "Execute" in card modal
        │
2. Frontend → POST /api/cards/{id}/execute
   │   Backend builds a structured [CARD EXECUTION] prompt:
   │   - Title, Description, Checklist, Linked files, Project name
   │   - "Execute this card. Read the description carefully and do what it asks."
   │   - Card moved to "in-progress" if was "idea" or "todo"
        │
3. Frontend receives {prompt, projectName}
   │   Sends prompt as a regular chat message via WebSocket
        │
4. ChatOrchestrator.handle_message() processes it like any user message
   │   Fast/Deep layer responds conversationally
   │   Analyzer may suggest sub-cards
   │   <delegate> blocks → EventBus → DeepWorkerPool
        │
5. DeepWorkerPool._execute_event() — worker executes with full tools
   │   web.search, card.update, card.move, file.write, etc.
   │   tool:executed events sent to frontend in real-time
        │
6. Auto-append result (see §14)
   │   Worker result appended to card description
   │   cards:changed broadcast → ReactiveCardStore re-syncs
        │
7. Frontend modal re-renders in real-time
   │   subscribeToCard() fires on each card update
   │   User sees execution progress live in the card modal
```

**Key files:**
- Execute endpoint: `backend/app/routes/cards.py:execute_card()`
- Orchestrator: `backend/app/services/chat_orchestration.py:handle_message()`
- Worker execution: `chat_orchestration.py:DeepWorkerPool._execute_event()`

### Board execution

There's also a **bulk execution** endpoint (`POST /projects/{id}/boards/execute`)
that builds an execution plan for all cards in specified statuses (todo, in-progress).
Cards are executed sequentially. See `backend/app/services/board_executor.py`.

---

## §14 — Auto-Append Execution Results

When a deep worker finishes executing a card, it **auto-appends the result** to the
card's description. This creates a persistent audit trail directly on the card.

### How it works

```python
# In DeepWorkerPool._execute_event(), after execute_worker_task() returns:

if card_id and result_content:
    card.description += "\n\n---\n📋 **Execution Result** ({timestamp})\n{result}"
    db.commit()
    # Sends tool:executed event → frontend re-syncs via cards:changed
```

**File:** `backend/app/services/chat_orchestration.py` (inside `_execute_event`, ~line 130)

### What gets appended

```markdown
---
📋 **Execution Result** (2026-03-23 02:15 UTC)
[Full worker output — research findings, code generated, actions taken, etc.]
```

### cards:changed sync

After the append, the worker emits a `tool:executed` event with `voxyflow.card.update`,
which triggers the frontend to re-sync. Combined with `subscribeToCard()` on the
ReactiveCardStore, the **card modal updates in real-time** while execution is happening.

### Why it matters

Without this, worker results would only appear in the task panel (ephemeral).
Auto-append makes results **persistent and card-scoped** — you can see what was done,
when, and what the output was, directly on the card that requested it.

---

## §15 — Agent Routing

Every card gets routed to a specialized agent type. Routing is keyword-based,
fast, and deterministic — no LLM call required.

### 7 Agent Types

| Type | Emoji | Name | Specialty |
|------|-------|------|-----------|
| `general` | ⚡ | General | Default, coordination, general tasks |
| `researcher` | 🔍 | Researcher | Deep analysis, fact-checking, reports |
| `coder` | 💻 | Coder | Code generation, debugging, optimization |
| `designer` | 🎨 | Designer | UI/UX, wireframes, visual design |
| `architect` | 🏗️ | Architect | System design, planning, PRDs |
| `writer` | ✍️ | Writer | Content, docs, marketing copy |
| `qa` | 🧪 | QA | Testing strategies, edge cases, validation |

### Routing algorithm (two-pass)

**Pass 1 — Pattern + Persona keyword scoring** (`analyzer_service.py:suggest_agent_type()`)
- TITLE_PATTERNS: frozenset of trigger words per agent type → +2 pts per hit
- PERSONAS[type].keywords: keyword list per persona → +1 pt per hit, normalized by √(list length)
- Highest score wins. Ties broken by TITLE_PATTERNS order. Fallback: `general`.

**Pass 2 — Weighted routing** (`agent_router.py:AgentRouter.route()`)
- ROUTING_WEIGHTS: "strong" keywords (+3 pts) and "moderate" keywords (+1 pt) per agent
- Normalized to 0–1 confidence score
- ≥2 strong hits → up to 0.9 confidence
- 1 strong hit → up to 0.8
- Moderate only → up to 0.6

**Resolution priority:**
1. Router confidence ≥ 0.6 → router wins
2. Pattern scorer found non-general → pattern wins
3. Fallback → router result (which may be `general`)

### Where routing happens

- **Card creation** (`routes/cards.py:create_card`): if no `agent_type` provided,
  auto-routes using `AgentRouter.route(title, description, context)`.
- **Analyzer suggestions** (`analyzer_service.py:_extract_card`): two-pass routing
  for every detected card suggestion.
- **Manual override**: `POST /cards/{id}/assign` lets users manually set agent type.
- **Routing preview**: `GET /cards/{id}/routing` returns scores without applying.

### Key files

- Agent types + personas: `backend/app/services/agent_personas.py`
- Keyword router: `backend/app/services/agent_router.py`
- Pattern scoring: `backend/app/services/analyzer_service.py:suggest_agent_type()`

---

_This is your architecture. Know it. Use it. When confused, re-read._
