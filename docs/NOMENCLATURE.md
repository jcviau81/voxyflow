# NOMENCLATURE — Official Terms

> The canonical vocabulary of Voxyflow. Use these terms exactly. No synonyms. No improvisation.

---

## Core Entity: Card

**Everything is a Card.** There is ONE entity type for work items.

| Term | Definition | NEVER Say |
|------|-----------|-----------|
| **Card** | Any work item in Voxyflow | "note", "task" (as entity name), "item", "ticket" |
| **Home Card** | Card in the Home workspace (`workspace_id = "system-main"`). Quick reminder. | "note", "sticky note", "Main Board card" |
| **Workspace Card** | Card assigned to a regular workspace. Has status, priority, agent. | "task" (use "card") |

### Card Statuses

| Status Value | Display Name | Where Used |
|-------------|-------------|------------|
| `backlog` | Backlog | Backlog card (Backlog view — internal view id: `freeboard`) |
| `todo` | Todo | Kanban — ready for work |
| `in-progress` | In Progress | Kanban — currently active |
| `done` | Done | Kanban — completed |
| `archived` | Archived | Both — hidden from active views |

### Card Priority Values

| Value | Label |
|-------|-------|
| `0` | None |
| `1` | Low |
| `2` | Medium |
| `3` | High |
| `4` | Critical |

### Card Colors (Home cards)

`yellow`, `blue`, `green`, `pink`, `purple`, `orange`

---

## Workspace

| Term | Definition |
|------|-----------|
| **Workspace** | A container for cards, wiki pages, documents, and sprints |
| **Home** | The system workspace (`id = "system-main"`, `is_system = true`). Default workspace, locked from edit. Surfaces as the 🏠 Home tab. |
| **Active Workspace** | A workspace with `status = "active"` |
| **Archived Workspace** | A workspace with `status = "archived"` |

---

## Boards & Views

| Term | Definition | Context |
|------|-----------|---------|
| **Home** | The default workspace (system workspace). Quick cards live here. | 🏠 Home tab |
| **Kanban** | Column-based card view within a workspace | 📋 Kanban tab in workspace |
| **Stats** | Progress dashboard with charts | 📊 Stats tab in workspace |
| **Roadmap** | Timeline/Gantt view of cards | 📅 Roadmap tab in workspace |
| **Wiki** | Markdown documentation pages | 📖 Wiki tab in workspace |
| **Sprints** | Time-boxed card groupings | 🏃 Sprints tab in workspace |
| **Docs** | Uploaded files for AI context (RAG) | 📚 Docs tab in workspace |
| **Knowledge** | Unified view of Wiki + Docs + RAG sources | 🧠 Knowledge tab in workspace |
| **Backlog** | Workspace backlog (cards with status `backlog`; internal view id: `freeboard`) | Backlog tab in workspace |

---

## Chat Levels

| Level | Trigger | Chat ID Format |
|-------|---------|---------------|
| **General / Home** | Home tab active (system workspace, `workspace_id = "system-main"`) | `workspace:system-main:{sessionId}` |
| **Workspace** | Workspace tab active, no card selected | `workspace:{workspaceId}` |
| **Card** | Card selected within a workspace | `card:{cardId}` |

---

## AI Model Layers

"Fast" and "Deep" are **dispatcher model slots**, not tool tiers. Both dispatcher
modes share the same `TOOLS_DISPATCHER` set — switching between them changes
model only (typically Haiku vs Opus), not tool access.

| Layer | Default model | Role |
|-------|---------------|------|
| **Fast** | `claude-haiku-4-6` | Chat dispatcher — quick responses |
| **Sonnet** | `claude-sonnet-4-6` | Worker research / balanced tasks (worker-side only) |
| **Deep** | `claude-opus-4-7` | Chat dispatcher — harder reasoning |

Any layer can be redirected to a different provider via Settings → Models or
via `backend/.env` (`CLAUDE_FAST_MODEL` / `CLAUDE_SONNET_MODEL` /
`CLAUDE_DEEP_MODEL`). Tool access for the dispatcher layer is governed by
`TOOLS_DISPATCHER` in `backend/app/tools/registry.py`.

---

## Agent Types

| Type | Name | Emoji | Specialty |
|------|------|-------|-----------|
| `general` | General | ⚡ | Default — no specialization |
| `researcher` | Researcher | 🔍 | Deep analysis, fact-checking, literature review |
| `coder` | Coder | 💻 | Code generation, debugging, implementation |
| `designer` | Designer | 🎨 | UI/UX design, visual design, user experience |
| `architect` | Architect | 🏗️ | System design, architecture, planning |
| `writer` | Writer | ✍️ | Content creation, documentation, copywriting |
| `qa` | QA | 🧪 | Testing, validation, quality assurance |

---

## Worker Types

| Worker Tier | Model Used | Task Types |
|------------|-----------|------------|
| `haiku` | Haiku | Simple CRUD: create/update/delete/move cards |
| `sonnet` | Sonnet | Research: web search, file analysis, git ops, reading code |
| `opus` | Opus | Complex: architecture, code writing, multi-step, destructive ops |

---

## Communication Patterns

| Pattern | Format | Used By |
|---------|--------|---------|
| `<tool_call>` | `{"name": "...", "arguments": {...}}` | Workers (direct tool execution) |
| `voxyflow.delegate` | `{"action": "...", "description": "...", "complexity": "simple\|standard\|complex"}` | Dispatcher → MCP tool_use (dispatch to worker) |
| `<tool_result>` | Tool execution result | System (injected after tool call) |

---

## Session Terms

| Term | Definition |
|------|-----------|
| **Session** | A conversation thread within a context (general/workspace/card) |
| **Tab** | A workspace tab at the top level (or the 🏠 Home tab) |
| **Active Session** | The currently visible session within a tab |
| **Chat ID** | Backend identifier for a session: `{level}:{id}` |
| **Session ID** | Frontend identifier for message routing |

---

## System Components

| Component | What It Is |
|-----------|-----------|
| **ChatOrchestrator** | Orchestrates the 3-layer pipeline |
| **ClaudeService** | Manages LLM provider calls across all layers |
| **SessionEventBus** | Per-session async queue for dispatcher→worker communication |
| **DeepWorkerPool** | Per-session async worker pool (configurable via `MAX_WORKERS`, default 15) |
| **ToolRegistry** | Central registry of all tool definitions and handlers |
| **ToolPromptBuilder** | Generates tool blocks for system prompts |
| **ToolResponseParser** | Extracts `<tool_call>` blocks from LLM text |
| **ToolExecutor** | Dispatches tool calls to handlers |
| **PersonalityService** | Loads and caches personality files |
| **RAGService** | ChromaDB-backed document retrieval |
| **MemoryService** | Semantic memory (decisions, lessons, facts) |
| **SessionStore** | File-based chat history persistence |
| **SchedulerService** | APScheduler-based background jobs |

---

## Prohibited Terms

| NEVER Say | ALWAYS Say |
|-----------|-----------|
| "note" | **Card** |
| "sticky note" | **Home Card** |
| "Main Board" / "Main workspace" | **Home** |
| "task" (as entity) | **Card** |
| "ticket" | **Card** |
| "notebook" | **Wiki** |
| "folder" | **Workspace** |
| "channel" | **Session** |
| "assistant" | **Voxy** (she is family, not an assistant) |

---

_Use these terms. Every time. No exceptions._
