# NOMENCLATURE — Official Terms

> The canonical vocabulary of Voxyflow. Use these terms exactly. No synonyms. No improvisation.

---

## Core Entity: Card

**Everything is a Card.** There is ONE entity type for work items.

| Term | Definition | NEVER Say |
|------|-----------|-----------|
| **Card** | Any work item in Voxyflow | "note", "task" (as entity name), "item", "ticket" |
| **Main Board Card** | Card with `project_id = null`. Free-floating. | "note", "sticky note" |
| **Project Card** | Card assigned to a project. Has status, priority, agent. | "task" (use "card") |

### Card Statuses

| Status Value | Display Name | Where Used |
|-------------|-------------|------------|
| `card` | Card | Main Board (default for unassigned cards) |
| `idea` | Idea | Project Kanban — ideation column |
| `todo` | Todo | Project Kanban — ready for work |
| `in-progress` | In Progress | Project Kanban — currently active |
| `done` | Done | Project Kanban — completed |
| `archived` | Archived | Both — hidden from active views |

### Card Priority Values

| Value | Label |
|-------|-------|
| `0` | None |
| `1` | Low |
| `2` | Medium |
| `3` | High |
| `4` | Critical |

### Card Colors (Main Board)

`yellow`, `blue`, `green`, `pink`, `purple`, `orange`

---

## Project

| Term | Definition |
|------|-----------|
| **Project** | A container for cards, wiki pages, documents, and sprints |
| **Active Project** | A project with `status = "active"` |
| **Archived Project** | A project with `status = "archived"` |

---

## Boards & Views

| Term | Definition | Context |
|------|-----------|---------|
| **Main Board** | The default board showing unassigned cards | 📝 Board tab in main chat |
| **Kanban** | Column-based card view within a project | 📋 Kanban tab in project |
| **Stats** | Progress dashboard with charts | 📊 Stats tab in project |
| **Roadmap** | Timeline/Gantt view of cards | 📅 Roadmap tab in project |
| **Wiki** | Markdown documentation pages | 📖 Wiki tab in project |
| **Sprints** | Time-boxed card groupings | 🏃 Sprints tab in project |
| **Docs** | Uploaded files for AI context (RAG) | 📚 Docs tab in project |
| **Knowledge** | Unified view of Wiki + Docs + RAG sources | 🧠 Knowledge tab in project |
| **Freeboard** | Free-form spatial canvas | Canvas mode |

---

## Chat Levels

| Level | Trigger | Chat ID Format |
|-------|---------|---------------|
| **General** | No project selected, main tab active | `general:{sessionId}` |
| **Project** | Project tab active, no card selected | `project:{projectId}` |
| **Card** | Card selected within a project | `card:{cardId}` |

---

## AI Model Layers

| Layer | Model | Role | Tool Access |
|-------|-------|------|-------------|
| **Fast** | Sonnet (`claude-sonnet-4-20250514`) | Chat responses, dispatching | Read-only |
| **Deep** | Opus (`claude-opus-4-20250514`) | Background workers, complex tasks | Full |
| **Analyzer** | Haiku (`claude-haiku-4-20250514`) | Card detection, suggestions | CRUD |

---

## Agent Types

| Type | Name | Emoji | Specialty |
|------|------|-------|-----------|
| `ember` | Ember | 🔥 | Default generalist — no specialization |
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
| `<delegate>` | `{"action": "...", "model": "...", "description": "...", "context": "..."}` | Dispatcher (dispatch to worker) |
| `<tool_result>` | Tool execution result | System (injected after tool call) |

---

## Session Terms

| Term | Definition |
|------|-----------|
| **Session** | A conversation thread within a context (general/project/card) |
| **Tab** | A project tab at the top level (or "main" tab) |
| **Active Session** | The currently visible session within a tab |
| **Chat ID** | Backend identifier for a session: `{level}:{id}` |
| **Session ID** | Frontend identifier for message routing |

---

## System Components

| Component | What It Is |
|-----------|-----------|
| **ChatOrchestrator** | Orchestrates the 3-layer pipeline |
| **ClaudeService** | Manages Claude API calls across all layers |
| **SessionEventBus** | Per-session async queue for dispatcher→worker communication |
| **DeepWorkerPool** | Per-session async worker pool (max 3 workers) |
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
| "sticky note" | **Main Board Card** |
| "task" (as entity) | **Card** |
| "ticket" | **Card** |
| "notebook" | **Wiki** |
| "folder" | **Project** |
| "channel" | **Session** |
| "assistant" | **Voxy** (she is family, not an assistant) |

---

_Use these terms. Every time. No exceptions._
