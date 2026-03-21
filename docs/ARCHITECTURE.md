# Voxyflow — Technical Architecture

---

## System Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser (Voxyflow PWA)                                              │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │  App Shell (App.ts)                                            │  │
│  │  ┌──────────┐  ┌──────────────────────────────────────────┐   │  │
│  │  │ TopBar   │  │  TabBar  [Main] [Project A] [Project B+]  │   │  │
│  │  └──────────┘  └──────────────────────────────────────────┘   │  │
│  │  ┌──────────┐  ┌──────────────────────────────────────────┐   │  │
│  │  │ Sidebar  │  │  Content Area (view-routed)              │   │  │
│  │  │          │  │  ┌────────────┐ ┌──────────┐ ┌────────┐ │   │  │
│  │  │ Projects │  │  │ ChatWindow │ │  Kanban  │ │Settings│ │   │  │
│  │  │ list     │  │  │ + Voice    │ │  Board   │ │        │ │   │  │
│  │  │          │  │  │ + Welcome  │ │ + Opport.│ │        │ │   │  │
│  │  └──────────┘  │  └────────────┘ └──────────┘ └────────┘ │   │  │
│  │                │  ┌────────────────────────────────────┐  │   │  │
│  │                │  │  ModelStatusBar  ⚡🧠🔍 toggles   │  │   │  │
│  │                │  └────────────────────────────────────┘  │   │  │
│  │                └──────────────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│    ApiClient (WebSocket /ws  +  REST /api/*)                         │
└────────────────────────────┬─────────────────────────────────────────┘
                             │
              WebSocket      │      HTTP REST
              ───────────────┼──────────────────
                             │
┌────────────────────────────▼─────────────────────────────────────────┐
│  FastAPI Backend                                                      │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  /ws  General WebSocket Handler (main.py)                       │ │
│  │                                                                 │ │
│  │  ping/pong  ──►  pong                                           │ │
│  │  chat:message ──► Chat Agent (Dispatcher)                       │ │
│  │                   ├── Dispatcher streams response (zero tools)  │ │
│  │                   ├── <delegate> blocks → Background Workers    │ │
│  │                   └── Analyzer observes → card suggestions      │ │
│  │  task:steer ──► Steer active worker                             │ │
│  │  session:reset ──► clear history                                │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌──────────┐ ┌───────────┐ ┌───────────┐ ┌──────────┐ ┌────────┐  │
│  │ /api/    │ │ /api/     │ │ /api/     │ │ /api/    │ │ /api/  │  │
│  │ chats    │ │ projects  │ │ cards     │ │ documents│ │sessions│  │
│  └──────────┘ └───────────┘ └───────────┘ └──────────┘ └────────┘  │
│  ┌──────────┐ ┌───────────┐ ┌───────────┐ ┌──────────┐             │
│  │ /api/    │ │ /api/     │ │ /api/     │ │ /api/    │             │
│  │ settings │ │ github    │ │ tech      │ │ tools    │             │
│  └──────────┘ └───────────┘ └───────────┘ └──────────┘             │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │  Services                                                       │ │
│  │  ClaudeService  AnalyzerService  RAGService  PersonalityService │ │
│  │  SessionStore   TtsService       AgentRouter  AgentPersonas     │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌──────────────────────┐  ┌──────────────────────────────────────┐  │
│  │  SQLite              │  │  ChromaDB                            │  │
│  │  voxyflow.db         │  │  ~/.voxyflow/chroma/                 │  │
│  │  chats, messages,    │  │  per-project collections             │  │
│  │  projects, cards,    │  │  (docs, history, workspace)          │  │
│  │  documents           │  │                                      │  │
│  └──────────────────────┘  └──────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────┘
                             │
              ┌──────────────▼──────────────┐
              │  claude-max-api-proxy        │
              │  http://localhost:3456/v1    │
              │  (or any OpenAI-compat API) │
              └─────────────────────────────┘
```

---

## Frontend Architecture

### Technology

- **Vanilla TypeScript** — No framework (React, Vue, etc.)
- **Webpack 5** — Build system with `ts-loader`, CSS extraction, Workbox
- **CSS Variables** — Theme system via custom properties
- **EventBus** — Custom pub/sub replacing framework reactivity

### Directory Structure

```
frontend/src/
├── App.ts                    # Root — mounts all components, sets up routing
├── main.ts                   # Entry point — imports App, mounts to #root
│
├── components/
│   ├── Chat/
│   │   ├── ChatWindow.ts     # Message rendering, input, streaming
│   │   ├── MessageBubble.ts  # Single message bubble (markdown, copy btn)
│   │   ├── SlashCommands.ts  # Slash command menu + parser
│   │   ├── VoiceInput.ts     # PTT button, STT integration
│   │   ├── WelcomePrompt.ts  # Context-aware welcome (general/project/card)
│   │   └── EmojiPicker.ts   # Emoji picker (chat input accessory)
│   ├── Kanban/
│   │   ├── KanbanBoard.ts   # Board container, drag-and-drop coordination
│   │   ├── KanbanColumn.ts  # Single column (idea/todo/in-progress/done)
│   │   ├── KanbanCard.ts    # Card tile in the board
│   │   ├── CardForm.ts      # Create/edit card form (with agent chips)
│   │   └── CardDetailModal.ts # Full card view + card-scoped chat
│   ├── Projects/
│   │   ├── ProjectList.ts   # Sidebar project listing
│   │   ├── ProjectForm.ts   # Create/edit project modal
│   │   └── TechStack.ts     # Tech stack display + auto-detect UI
│   ├── FreeBoard/
│   │   └── FreeBoard.ts     # Sticky note board for main chat
│   ├── Ideas/
│   │   └── IdeaBoard.ts     # Ideas from analyzer (alternate view)
│   ├── Opportunities/
│   │   └── OpportunitiesPanel.ts # AI card suggestions panel
│   ├── Navigation/
│   │   ├── TopBar.ts        # App header
│   │   ├── Sidebar.ts       # Left sidebar (project list, nav)
│   │   ├── TabBar.ts        # Browser-style project tabs
│   │   └── ModelStatusBar.ts # Model layer status + toggles
│   ├── Settings/
│   │   └── SettingsPage.ts  # Personality, models, GitHub config
│   └── Shared/
│       ├── Toast.ts         # Toast notification stack
│       └── LoadingSpinner.ts
│
├── services/
│   ├── ApiClient.ts         # WebSocket + REST client (reconnect, ping)
│   ├── ChatService.ts       # Chat message handling, streaming
│   ├── ProjectService.ts    # Project CRUD
│   ├── CardService.ts       # Card CRUD
│   ├── SttService.ts        # Speech-to-text (Web Speech API + Whisper stub)
│   ├── AudioService.ts      # Audio playback (TTS responses)
│   └── StorageService.ts    # IndexedDB wrapper
│
├── state/
│   └── AppState.ts          # Global mutable state + localStorage persistence
│
├── utils/
│   ├── EventBus.ts          # Typed pub/sub event system
│   ├── constants.ts         # EVENTS, SHORTCUTS, AGENT_TYPE_INFO, CARD_STATUSES
│   ├── helpers.ts           # createElement, generateId, deepClone, etc.
│   └── markdown.ts          # marked + highlight.js + DOMPurify pipeline
│
└── types/
    └── index.ts             # TypeScript interfaces (Message, Project, Card, Tab...)
```

### State Management

**AppState** (`state/AppState.ts`) is a simple class that:
- Holds all mutable app state in a single object
- Persists to `localStorage` (`voxyflow_state`) on every mutation
- Emits `STATE_CHANGED` events via EventBus on mutations
- Has typed getters and setters for each state field

There is no immutable state or reactivity framework — components read state directly and re-render on EventBus notifications.

**Key state fields:**
```typescript
{
  currentView: 'chat' | 'kanban' | 'projects' | 'settings',
  currentProjectId: string | null,
  selectedCardId: string | null,
  messages: Message[],
  projects: Project[],
  cards: Card[],
  openTabs: Tab[],
  activeTab: string,
  ideas: Idea[],
  connectionState: 'connecting' | 'connected' | 'disconnected' | 'reconnecting',
  voiceActive: boolean,
}
```

### Event Bus

**EventBus** (`utils/EventBus.ts`) is a typed pub/sub singleton:

```typescript
eventBus.emit(EVENTS.CARD_CREATED, { card });
const unsub = eventBus.on(EVENTS.CARD_CREATED, (data) => { ... });
unsub(); // unsubscribe
```

All component-to-component communication goes through EventBus. No direct references between sibling components.

---

## Backend Architecture

### Directory Structure

```
backend/app/
├── main.py              # FastAPI app, WebSocket handler, Dispatcher + Workers
├── config.py            # Settings via pydantic-settings + .env
├── database.py          # SQLAlchemy models + engine + session factory
│
├── routes/
│   ├── chats.py         # Chat & message CRUD
│   ├── projects.py      # Project CRUD
│   ├── cards.py         # Card CRUD + agent routing endpoints
│   ├── documents.py     # Document upload + RAG indexing
│   ├── settings.py      # App settings + personality file CRUD
│   ├── sessions.py      # Session persistence API
│   ├── github.py        # GitHub status, PAT management, repo validate/clone
│   ├── techdetect.py    # Tech stack auto-detection
│   ├── tools.py         # Tool execution API (for external/direct calls)
│   └── voice.py         # Voice WebSocket (legacy/alternate pipeline)
│
├── services/
│   ├── claude_service.py      # Dispatcher + Worker model orchestration
│   ├── analyzer_service.py    # Background Analyzer (passive card detection)
│   ├── rag_service.py         # ChromaDB index/query wrapper
│   ├── personality_service.py # System prompt builder (loads personality files)
│   ├── session_store.py       # JSON file session persistence
│   ├── agent_personas.py      # Agent type definitions + system prompts
│   ├── agent_router.py        # Keyword-based agent selection
│   ├── tts_service.py         # TTS synthesis (local or remote)
│   ├── chat_service.py        # Chat context management
│   └── document_parser.py     # File parsing + chunking registry
│
├── tools/
│   ├── registry.py        # Tool definition + execution registry
│   ├── card_tools.py      # create_card, update_card tools
│   ├── project_tools.py   # create_project, list_projects tools
│   ├── navigation_tools.py # open_project, focus_card navigation tools
│   ├── github_tools.py    # GitHub tool wrappers
│   └── info_tools.py      # get_context, list_cards info tools
│
└── models/               # Pydantic request/response schemas
    ├── chat.py
    ├── project.py
    ├── card.py
    ├── document.py
    └── voice.py
```

### Database Models (SQLite via SQLAlchemy async)

```
Chat         id, title, project_id, created_at, updated_at
  └── Message  id, chat_id, role, content, audio_url, model_used, tokens_used, latency_ms
Project      id, title, description, status, context, github_*, local_path
  ├── Card     id, project_id, title, description, status, priority, position,
  │            agent_type, agent_assigned, agent_context, auto_generated
  │   └── card_dependencies (self-referential many-to-many)
  └── Document id, project_id, filename, filetype, size_bytes, chunk_count, indexed_at
```

---

## WebSocket Protocol

All realtime communication goes through `ws://host:8000/ws` (one shared connection).

### Client → Server

```json
// Heartbeat
{ "type": "ping", "timestamp": 1234567890 }

// Chat message
{
  "type": "chat:message",
  "payload": {
    "content": "What should I build next?",
    "messageId": "uuid",
    "projectId": "uuid",      // optional
    "cardId": "uuid",         // optional
    "chatLevel": "project",   // "general" | "project" | "card"
    "sessionId": "uuid",
    "layers": { "deep": true, "analyzer": true }
  }
}

// Reset session
{
  "type": "session:reset",
  "payload": {
    "projectId": "uuid",
    "sessionId": "uuid",
    "chatLevel": "project"
  }
}
```

### Server → Client

```json
// Pong
{ "type": "pong", "timestamp": 1234567890 }

// Token stream (Chat Agent / Dispatcher)
{
  "type": "chat:response",
  "payload": {
    "messageId": "uuid",
    "content": "token text",
    "model": "fast",
    "streaming": true,
    "done": false
  }
}

// Stream complete
{
  "type": "chat:response",
  "payload": {
    "messageId": "uuid",
    "content": "",
    "model": "fast",
    "streaming": true,
    "done": true,
    "latency_ms": 450
  }
}

// Deep mode enrichment
{
  "type": "chat:enrichment",
  "payload": {
    "messageId": "uuid",
    "content": "Here's a more complete answer...",
    "model": "deep",
    "action": "enrich",   // "enrich" | "correct"
    "done": true
  }
}

// Card suggestion (Analyzer)
{
  "type": "card:suggestion",
  "payload": {
    "title": "Add authentication middleware",
    "description": "JWT-based auth for API routes",
    "agentType": "coder",
    "agentName": "Codeuse",
    "projectId": "uuid"
  }
}

// Model state change
{
  "type": "model:status",
  "payload": {
    "model": "deep",
    "state": "thinking"   // "thinking" | "active" | "idle" | "error"
  }
}

// Tool execution result
{
  "type": "tool:result",
  "payload": {
    "tool": "create_card",
    "success": true,
    "data": { "card_id": "uuid" },
    "ui_action": "navigate_to_card"
  }
}

// Session cleared
{
  "type": "session:reset_ack",
  "payload": { "chatId": "project:uuid" }
}
```

---

## Dispatcher + Workers Pipeline

```
User Message
     │
     ▼
┌─────────────────────────────────────────────────┐
│  Chat Agent (Dispatcher)                        │
│                                                 │
│  1. Resolve chat_id from (projectId, cardId)    │
│  2. Load project/card context from DB           │
│  3. Check layer toggles (deep, analyzer)        │
│                                                 │
│  ─── Dispatcher Response ──────────────────     │
│  async for token in chat_stream():              │
│    send(chat:response, streaming=True)          │
│  send(chat:response, done=True)                 │
│  NOTE: Dispatcher has ZERO tools                │
│                                                 │
│  ─── Delegate Parsing ─────────────────────     │
│  Parse <delegate>{...}</delegate> blocks        │
│  from Dispatcher response                       │
│  → Launch background Worker (haiku/sonnet/opus) │
│  → Worker has FULL tool access                  │
│  → Worker reports results via WebSocket         │
│                                                 │
│  ─── Analyzer (background, passive) ───────     │
│  Observes conversation passively                │
│  cards = await analyzer_task                    │
│  for card in cards:                             │
│    send(card:suggestion)                        │
│                                                 │
│  KEY: Conversation is NEVER blocked.            │
│  Workers and Analyzer run in the background.    │
└─────────────────────────────────────────────────┘
```

### Worker Model Routing

| Task Type | Worker Model | Use Case |
|-----------|-------------|----------|
| Simple CRUD | Haiku | create/update/delete card, move card |
| Research | Sonnet | web search, file analysis, git operations |
| Complex | Opus | multi-step tasks, architecture, code writing |

The Chat Agent selects the appropriate worker model based on task complexity and includes it in the `<delegate>` block.

**Context isolation:** `chat_id` is derived from the incoming payload:
- `cardId` present → `card:{cardId}` (card-level isolation)
- `projectId` present → `project:{projectId}` (project-level isolation)  
- Neither → `general:{sessionId}` (general chat)

---

## RAG Pipeline

```
Document Upload:
  File bytes
    └── DocumentParser.parse() → ParsedDocument { chunks: str[] }
          └── RAGService.index_document()
                └── chromadb.get_or_create_collection(project_docs)
                      └── collection.add(documents=chunks, ids=[...])

Chat with RAG:
  User message
    └── RAGService.query(project_id, message, top_k=5)
          └── collection.query(query_texts=[message], n_results=5)
                └── relevant_chunks: str[]
                      └── PersonalityService.build_system_prompt()
                            └── system_prompt += "\n\n[Relevant context]\n" + chunks
                                  └── claude_service.chat_fast_stream(system=...)
```

Collections per project:
- `voxyflow_project_{id}_docs` — uploaded .txt/.md files
- `voxyflow_project_{id}_history` — conversation history (future)
- `voxyflow_project_{id}_workspace` — cards/notes (future)

---

## Personality System

System prompts are built by `PersonalityService.build_system_prompt()`:

```
System Prompt = [IDENTITY.md content]
              + [SOUL.md content]
              + [USER.md content]
              + tone modifier (casual/balanced/formal)
              + warmth modifier (cold/warm/hot)
              + custom_instructions (from settings.json)
              + environment_notes (from settings.json)
              + chat-level context injection:
                  project → project title + description + tech stack
                  card    → card title + description + status + agent
              + RAG context chunks (if enabled and relevant)
              + agent system prompt (if non-default agent active)
```

**Caching:** Each personality file is cached by `mtime`. Reading only happens when the file changes. Settings JSON is similarly cached.

**File isolation:** Personality files live at `voxyflow/personality/` (within the repo), **not** the OpenClaw workspace. This prevents context leakage between the two systems.
