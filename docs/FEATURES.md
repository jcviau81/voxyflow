# Voxyflow — Feature Reference

Complete documentation of all shipped features, organized by area.

---

## Table of Contents

1. [Core Chat](#1-core-chat)
2. [Voice Input](#2-voice-input)
3. [Projects & Views](#3-projects--views)
4. [Card Management](#4-card-management)
5. [AI Features](#5-ai-features)
6. [RAG / Knowledge Base](#6-rag--knowledge-base)
7. [Agents](#7-agents)
8. [Settings](#8-settings)
9. [UI/UX](#9-uiux)
10. [Infrastructure](#10-infrastructure)

---

## 1. Core Chat

### 3-Layer Multi-Model Orchestration

Every chat message triggers three concurrent AI layers:

| Layer | Role | Model | Timing |
|-------|------|-------|--------|
| **Fast** (Layer 1) | Immediate streaming response | Configurable (default: claude-sonnet) | ~1s first token |
| **Deep** (Layer 2) | Enriches or corrects Fast response if needed | Configurable (default: claude-opus) | 2–5s, background |
| **Analyzer** (Layer 3) | Detects actionable items → card suggestions | Configurable (default: claude-haiku) | Background |

**Flow:**
1. User sends message
2. Deep + Analyzer tasks are launched in parallel (`asyncio.create_task`)
3. Fast layer streams tokens to the client immediately
4. When Fast finishes, Deep result is awaited (15s timeout)
5. If Deep decided to enrich/correct, a `chat:enrichment` event is sent
6. Analyzer card suggestions arrive as `card:suggestion` events

**Layer toggles:** Deep and Analyzer can each be disabled per-message via the ModelStatusBar toggle buttons. The Fast layer is always on.

---

### Streaming SSE / WebSocket Responses

Chat responses stream token-by-token over WebSocket (`/ws`). The client appends tokens as they arrive, creating a real-time typewriter effect.

**WebSocket message types (server → client):**

| Type | When |
|------|------|
| `chat:response` | Token chunk from Fast layer (`streaming: true, done: false`) |
| `chat:response` | Stream complete signal (`streaming: true, done: true`) |
| `chat:enrichment` | Deep layer correction/enrichment |
| `card:suggestion` | Analyzer detected an actionable card |
| `model:status` | Model state change (thinking/active/idle/error) |
| `tool:result` | Tool call executed (navigation, card creation, etc.) |
| `session:reset_ack` | Session cleared |

---

### Chat Hierarchy

Voxyflow maintains isolated conversation histories based on context:

| Context | Chat ID format | System prompt |
|---------|---------------|---------------|
| General (main tab) | `general:{sessionId}` | General assistant with personality |
| Project tab | `project:{projectId}` | Project-aware (title, description, tech stack) |
| Card detail | `card:{cardId}` | Card-specific (title, description, status, agent) |

This ensures each project/card gets its own independent memory.

---

### Session Management

- **Session isolation** — Each chat context (general/project/card) has its own conversation history
- **Persistence** — Session messages are persisted to disk via `SessionStore` (JSON files in `~/.voxyflow/sessions/`)
- **New session** — `/new` command clears history (sends `session:reset` to backend and wipes in-memory `_histories`)
- **Session restore** — `GET /api/sessions/{chat_id}` retrieves message history (up to 500 messages)

---

### Rich Chat (Markdown Rendering)

Messages are rendered with full markdown support:

- **Markdown** — Headers, bold, italic, lists, blockquotes, horizontal rules
- **Code blocks** — Syntax highlighting via highlight.js (auto-detected language)
- **Copy button** — Each code block has a one-click copy button
- **Inline code** — Styled distinctly from prose
- **Links** — Rendered as `<a target="_blank">` with security attributes
- **Sanitization** — All HTML is sanitized via DOMPurify before insertion
- **LaTeX** — Not yet implemented (roadmap)

---

### Slash Commands

Type `/` in the chat input to trigger the slash command menu with keyboard navigation (↑/↓/Enter/Escape).

| Command | Action |
|---------|--------|
| `/new` | Start a new session (clears history on frontend + backend) |
| `/clear` | Clear visible chat messages (visual only, history preserved on backend) |
| `/help` | Show available commands |
| `/agent [name]` | Switch agent persona for the session |
| `/meeting` | Extract action items from meeting notes and create cards |
| `/standup` | Generate a daily standup summary for the active project |

**Autocomplete:** The slash menu filters as you type. Mouse click or Enter selects a command.

---

### Layer Toggles

The Model Status Bar (below the input area) shows live status for each model layer. Deep and Analyzer have checkbox toggles:

- Toggle state is persisted in `localStorage` (`voxyflow_layer_toggles`)
- Each message includes the current `layers` object: `{ deep: bool, analyzer: bool }`
- Backend respects the toggle — skips the layer entirely if disabled

---

## 2. Voice Input

### Push-to-Talk (PTT)

The microphone button in the chat input activates Push-to-Talk:

1. Press and hold (or click) the mic button → starts `SttService.startRecording()`
2. Speak — transcripts appear live in the input area as you talk (interim results)
3. Release (or click again) → recording stops, final transcript fills the input
4. User reviews the transcribed text before pressing Send

**This is not auto-send.** Voice fills the input; the user decides when to send.

---

### Speech-to-Text (STT)

**Engine:** Web Speech API (browser-native)

- Uses `SpeechRecognition` (or `webkitSpeechRecognition` for Chromium-based browsers)
- `continuous: true` — keeps listening until explicitly stopped
- `interimResults: true` — live transcription shown as you speak
- Emits `VOICE_TRANSCRIPT` events for both interim and final results

**Language detection:**
- Reads `voxyflow_settings.personality.preferred_language` from localStorage
- `"fr"` → `fr-CA` (Quebec French)
- `"en"` → `en-US`
- Default: `en-US`

**Whisper fallback** (not yet shipped):  
`SttService` has a skeleton `startWhisperRecording()` path that captures audio via `MediaRecorder`, but Whisper WASM integration is a placeholder and not functional in Phase 1.

---

### Voice WebSocket (Backend)

A dedicated `/ws/voice/{chat_id}` WebSocket handles voice sessions (legacy, pre-general-WS):

- Accepts `WSTranscript` frames (text transcripts from client)
- Runs the same 3-layer pipeline
- Returns `WSAssistantText` + `WSAssistantAudio` (TTS via remote XTTS service)
- Background enrichment + card detection run as fire-and-forget tasks

**Note:** Primary UI uses the general `/ws` endpoint. The voice WS is an alternate pipeline for dedicated voice clients.

---

## 3. Projects & Views

### Project Creation & Editing

Projects are created via the **Project Form** modal (triggered by the `+` tab button or sidebar).

**Fields:**

| Field | Notes |
|-------|-------|
| Title | Required |
| Description | Free text, supports markdown |
| Tech Stack | Auto-detected or manually set (comma-separated) |
| GitHub Repo | `owner/repo` — validated against GitHub API |
| GitHub URL | Auto-populated from repo validation |
| Local Path | Local directory for tech stack detection |
| Context | Freeform requirements / notes injected into AI prompts |

**Editing:** `PATCH /api/projects/{project_id}` — partial updates, all fields optional.

---

### Project Templates

5 built-in templates that pre-populate a project with a curated set of cards:

- **API Service** — Backend service with standard setup, auth, testing, and deploy cards
- **Frontend App** — React/Vue app with component, routing, state, and build cards
- **Mobile App** — iOS/Android project with design, dev, testing, and release cards
- **Data Pipeline** — ETL/ML project with ingestion, processing, model, and monitoring cards
- **Open Source Lib** — Library project with API design, docs, tests, and publishing cards

**Usage:** `GET /api/templates` lists templates. `POST /api/from-template/{template_id}` creates a project from a template.

---

### Project Export / Import

Projects can be exported to a portable JSON file and re-imported:

- **Export** — `GET /api/projects/{id}/export` returns a full JSON payload (project + all cards + metadata)
- **Import** — `POST /api/projects/import` with the JSON payload creates a new project (new IDs assigned)
- Use for backup, migration between instances, or sharing project structures

---

### Project Tabs

Projects open in browser-like tabs at the top of the interface:

- **Main tab** — always open, non-closable (General chat + Notes board)
- **Project tabs** — open when a project is selected (closable with `×` or `Cmd+W`)
- **`+` button** — opens the New Project form
- **Tab switching** — click tab or `Ctrl+Tab` cycles through open tabs
- **Notification dot** — appears on a tab when a card suggestion arrives for that project
- **Persistence** — open tabs survive page refresh (stored in `localStorage`)

---

### Project Views

Each project has multiple view modes, accessible via tabs in the project header:

#### 📋 Kanban
Default view. 4-column board (Idea / Todo / In Progress / Done) with:
- **2-row header** — top row: view switcher + actions (Meeting Notes, Brief, Health, Standup, Prioritize); bottom row: filter bar (search + priority/agent/tag chips)
- Cards draggable between columns
- Opportunities panel (AI card suggestions)

#### 📊 Stats Dashboard
Project analytics and progress tracking:
- **Progress ring** — overall card completion percentage
- **Charts** — cards by status, priority distribution, velocity (cards completed over time)
- **Focus session analytics** — total Pomodoro time logged per project/card

#### 📅 Roadmap (Gantt)
Timeline view showing cards with due dates laid out on a Gantt chart. Useful for planning and visualizing project schedule.

#### 📖 Wiki
Per-project wiki with markdown pages:
- Create/edit/delete pages with full markdown rendering
- Page list with title and last-updated timestamp
- Suitable for project documentation, decisions, architecture notes

#### 🏃 Sprints
Agile sprint management:
- **Sprint list** — view all sprints (planned / active / completed)
- **Create sprint** — name, goal, start/end dates
- **Start sprint** — activates sprint; only one sprint can be active at a time
- **Complete sprint** — marks sprint done
- **Backlog** — cards not yet in a sprint
- Cards can be assigned to sprints (via card form or bulk actions)

#### 📚 Docs (RAG)
Document upload and knowledge base management (see [RAG / Knowledge Base](#6-rag--knowledge-base)):
- Upload documents for RAG context injection
- List and delete indexed documents

#### 📝 Notes Board (formerly Free Board)
A sticky-note scratchpad for brainstorming:
- Quick-add form
- 6 pastel colors
- Grid layout with delete and promote actions
- AI-suggested notes (via Analyzer layer)

---

### Tech Stack Auto-Detection

Voxyflow scans a local project directory and detects technologies from file signatures and dependency manifests.

**File signatures (17+ detected):**

| File | Technology |
|------|-----------|
| `requirements.txt`, `pyproject.toml`, `setup.py`, `Pipfile` | Python |
| `package.json` | Node.js |
| `tsconfig.json` | TypeScript |
| `Cargo.toml` | Rust |
| `go.mod` | Go |
| `Dockerfile` | Docker |
| `docker-compose.yml/yaml` | Docker Compose |
| `.github/workflows` | GitHub Actions |
| `.gitlab-ci.yml` | GitLab CI |
| `.eslintrc.json` | ESLint |
| `jest.config.js` | Jest |
| `playwright.config.ts` | Playwright |
| `webpack.config.js` | Webpack |
| `vite.config.ts` | Vite |
| `Makefile` | Make |
| `.env` | Environment Config |

**Deep scan — npm frameworks** (from `package.json` dependencies):  
React, Vue, Next.js, Express, Fastify, Playwright, Jest, TypeScript, Tailwind, Marked, Highlight.js, DOMPurify

**Deep scan — Python frameworks** (from `requirements.txt`):  
FastAPI, Django, Flask, SQLAlchemy, Pydantic, Pytest, Anthropic SDK, OpenAI SDK, Keyring

**Monorepo support:** Scans root + immediate subdirectories (excluding `node_modules`, `.git`, `__pycache__`, `venv`, `dist`).

**API:** `GET /api/tech/detect?project_path=~/projects/myapp`

---

## 4. Card Management

### Card Creation & Editing

Cards are created via the Card Form (click `+` in any column, or "Create from suggestion" in the Opportunities panel).

**Core fields:**

| Field | Notes |
|-------|-------|
| Title | Required |
| Description | Markdown-supported |
| Status | `idea` / `todo` / `in-progress` / `done` |
| Priority | 0=none, 1=low, 2=medium, 3=high, 4=critical |
| Agent | Chip selector for the 7 agent types |
| Context | Notes for the agent (injected as agent context) |
| Dependencies | Other cards this card depends on |
| Assignee | Person responsible for the card |
| Watchers | Comma-separated list of watchers |
| Recurrence | Daily / Weekly / Monthly — auto-recreates card on completion |

**Auto-routing:** If no agent is manually selected, the backend's `AgentRouter` detects the best agent from the card's title, description, and context (keyword matching).

---

### Card Detail Modal

Clicking a card opens a full detail modal with all card fields, plus:

- Inline editing
- Card-scoped chat panel (`chat_id = card:{cardId}`)
- Agent badge with emoji
- All sub-features listed below (checklist, comments, time, attachments, etc.)
- Context menu (`···`) for quick actions: duplicate, move, clone to project, delete

---

### Card Checklist ☑

Sub-tasks within a card:

- Add/remove checklist items inline
- Toggle each item completed/incomplete
- Progress bar shows `completed / total` at the top of the card
- Items are ordered by position; ordering can be adjusted

**API:** `GET/POST/PATCH/DELETE /api/cards/{id}/checklist` + `/{item_id}`

---

### Card Comments 💬

Per-card discussion thread:

- Add comments with author name and content
- Delete own comments
- Displayed newest-first

**API:** `GET/POST/DELETE /api/cards/{id}/comments`

---

### Card Attachments 📎

File attachments stored per-card:

- Drag & drop files onto the card detail or use the upload button
- Max 50 MB per file, any type accepted
- Files stored at `~/.voxyflow/attachments/{card_id}/`
- Download via direct link
- Delete attachment (removes file from disk + DB record)

**API:** `POST /api/cards/{id}/attachments` (multipart) · `GET /api/cards/{id}/attachments` · `GET /api/cards/{id}/attachments/{att_id}/download` · `DELETE /api/cards/{id}/attachments/{att_id}`

---

### Card Time Tracking ⏱

Manual time logging per card:

- Log time entries with duration (minutes) and an optional note
- Running total of all logged minutes shown on the card
- Delete individual entries

**API:** `POST/GET/DELETE /api/cards/{id}/time`

---

### Card Voting ▲

Community/team upvoting on cards:

- Vote button increments count; unvote decrements (min 0)
- Vote count visible on card face
- Useful for backlog prioritization

**API:** `POST /api/cards/{id}/vote` · `DELETE /api/cards/{id}/vote`

---

### Card History / Audit Log 📜

Automatic change tracking:

- Tracks changes to: `status`, `priority`, `title`, `description`, `assignee`, `agent_type`
- Each change records: field, old value, new value, timestamp, changed_by
- Displayed in card detail modal (newest-first, max 50 entries)

**API:** `GET /api/cards/{id}/history`

---

### Card Relations 🔗

Typed relationships between cards:

| Relation Type | Meaning |
|--------------|---------|
| `duplicates` | This card is a duplicate of another |
| `blocks` | This card blocks another |
| `is_blocked_by` | This card is blocked by another |
| `relates_to` | General relationship |
| `cloned_from` | Auto-created when cloning |

- Prevents duplicate relations of the same type
- Inverse relations are auto-computed when listing (e.g. if A blocks B, B sees "is_blocked_by A")

**API:** `POST/GET/DELETE /api/cards/{id}/relations`

---

### Card Dependencies Visualization 🔗

Cards can declare dependencies on other cards (cards that must be done first):

- Set via `dependency_ids` on card create/update
- Dependency badge shown on card face (count of blockers)
- Dependencies listed in card detail with link to dependent card

---

### Card Duplication 📋

Duplicate a card within the same project:

- Creates a copy with all fields; title gets ` (copy)` appended
- Votes reset to 0 on the copy
- Available via context menu (`···`) on card face or card detail

**API:** `POST /api/cards/{id}/duplicate`

---

### Card Clone / Move to Another Project

- **Clone** — Creates a copy in a target project with ` (cloned)` title suffix; also clones all checklist items; creates a `cloned_from` relation
- **Move** — Transfers the card (and all its comments, attachments, checklist) to another project

**API:** `POST /api/cards/{id}/clone-to/{target_project_id}` · `POST /api/cards/{id}/move-to/{target_project_id}`

---

### Card Bulk Actions ☑

Select Mode for batch operations:

- Enter Select Mode via the Kanban header button
- Checkbox appears on each card; click to select
- Bulk actions: change status, change priority, change agent, delete, move to project
- Select All / Deselect All controls

---

### Card Recurring 🔁

Automatic card regeneration:

- Set recurrence on a card: **Daily**, **Weekly**, or **Monthly**
- When the card is moved to `done`, a new copy is auto-created with the next scheduled date
- `recurrence_next` tracks the next due date

---

### AI Card Enrichment ✨

One-click AI enrichment of a card:

- Given just a card title, the fast model generates:
  - A 2-3 sentence description
  - 3-5 checklist items (concrete sub-tasks)
  - Effort estimate (XS / S / M / L / XL)
  - 2-4 tags
- Results are applied to the card with a single click
- Available via the `✨` button in the card detail modal

**API:** `POST /api/cards/{id}/enrich`

---

### Card Assignees & Watchers 👤

- **Assignee** — Single responsible person (free text name/email)
- **Watchers** — Comma-separated list of people interested in the card
- Both fields displayed on card face and detail modal

---

### Card Labels / Tags

- Tags are generated by AI enrichment or set manually
- Displayed as colored pills on the card face
- Filterable in the Kanban search/filter bar

---

### Opportunities Panel

The Opportunities panel appears in each project view and collects AI-suggested cards:

- **Source:** Analyzer layer (Layer 3) emits `card:suggestion` WebSocket events after analyzing each message
- **Display:** Suggestions queue in the panel with title, description, and suggested agent
- **Actions:** "Create Card" → calls `POST /api/projects/{id}/cards` with `auto_generated: true`; "Dismiss" removes from panel
- **Notification:** Tab gets a notification dot when a new suggestion arrives

---

## 5. AI Features

### Daily Standup `/standup`

Generates a concise standup summary for the active project using the fast model:

- **What was done** — recently completed cards (moved to `done`)
- **What's in progress** — current `in-progress` cards
- **Blockers** — cards with `blocks`/`is_blocked_by` relations or flagged blockers
- Output rendered in the chat and also available as a structured response

**API:** `POST /api/projects/{id}/standup`  
**Slash command:** `/standup` in project chat

---

### Meeting Notes `/meeting`

Extract action items from meeting notes and auto-create cards:

1. Paste meeting notes into the `/meeting` command or call the API with the transcript
2. AI (Deep/Opus model) extracts action items with: title, owner, priority, due date
3. Preview extracted items before confirming
4. On confirm, items are created as cards in the project

**API:** `POST /api/projects/{id}/meeting-notes` (extract) · `POST /api/projects/{id}/meeting-notes/confirm` (create cards)  
**Slash command:** `/meeting` in project chat

---

### Project Brief (Opus) 📄

Generate a comprehensive PRD (Product Requirements Document) using the Deep (Opus) model:

- Analyzes project title, description, context, tech stack, and all existing cards
- Outputs structured PRD sections: executive summary, goals, user stories, requirements, architecture notes, risks
- Rendered in chat as a rich markdown document

**API:** `POST /api/projects/{id}/brief`

---

### Health Check 🏥

AI-powered project health analysis:

- **Score** — 0–100 numeric score
- **Grade** — A / B / C / D / F
- **Strengths** — what's going well
- **Issues** — what needs attention
- **Recommendations** — concrete next steps
- Uses rule-based analysis (card distribution, velocity, blocker ratio) + AI reasoning for recommendations

**API:** `POST /api/projects/{id}/health`

---

### Smart Prioritization 🎯

Rule-based + AI scoring to prioritize the backlog:

- Scores each card on: priority, age, blocker status, effort, agent type
- AI reasoning layer adds contextual explanations per card
- Returns cards ranked by recommended priority with justification
- Useful before sprint planning

**API:** `POST /api/projects/{id}/prioritize`

---

### Code Review 🔍

AI code review on any code snippet:

- Submit code with optional language and context
- Deep (Opus) model returns structured review:
  - **Overall assessment** — 2-4 sentence summary
  - **Issues** — line number, severity (error/warning/info), description
  - **Suggestions** — up to 5 actionable improvements
- Rendered inline on code blocks in the chat UI (🔍 button on each code block)

**API:** `POST /api/code/review`

---

## 6. RAG / Knowledge Base

### Overview

Each project gets 3 isolated ChromaDB collections for retrieval-augmented generation:

| Collection | Purpose |
|-----------|---------|
| `voxyflow_project_{id}_docs` | Uploaded documents |
| `voxyflow_project_{id}_history` | Conversation history (future) |
| `voxyflow_project_{id}_workspace` | Cards, notes, board data (future) |

**Embeddings:** `all-MiniLM-L6-v2` (local, via `sentence-transformers` — no API key needed)  
**Persistence:** `~/.voxyflow/chroma/`

### Document Upload

**Supported formats:**
- `.txt`, `.md`, `.markdown` — Phase 1 (always available)
- `.pdf` — Phase 2 (requires `pypdf`)
- `.docx`, `.doc` — Phase 2 (requires `python-docx`)
- `.xlsx`, `.xls`, `.csv` — Phase 2 (requires `openpyxl`)

The `DocumentParserRegistry` auto-detects which parsers are available based on installed deps. Upload of Phase 2 types fails gracefully if the dep is missing.

Upload flow:
1. `POST /api/projects/{id}/documents` (multipart/form-data)
2. File is parsed into text chunks by the appropriate parser
3. Chunks are embedded and indexed into ChromaDB
4. Document metadata (filename, size, chunk count, indexed_at) stored in SQLite

**Response:**
```json
{
  "id": "uuid",
  "filename": "README.md",
  "filetype": ".md",
  "size_bytes": 4096,
  "chunk_count": 12,
  "indexed_at": "2025-01-01T00:00:00Z"
}
```

### Document Management

| Endpoint | Action |
|----------|--------|
| `GET /api/projects/{id}/documents` | List all documents for a project |
| `DELETE /api/projects/{id}/documents/{doc_id}` | Delete document + remove from ChromaDB |

### Context Injection

When RAG is enabled and a project has indexed documents, relevant chunks are retrieved and injected into the system prompt for each chat message in that project's context.

**Graceful degradation:** If `chromadb` is not installed, RAGService silently disables itself. Chat works normally; RAG context is just absent.

### Background RAG Indexing (APScheduler)

The scheduler automatically re-indexes project documents on a periodic basis (see [Infrastructure](#10-infrastructure)), ensuring the RAG index stays fresh after document updates.

---

## 7. Agents

### 7 Specialized Agent Personas

| Type | Name | Emoji | Specialty |
|------|------|-------|-----------|
| `ember` | Ember | 🔥 | Default — general tasks, fallback |
| `researcher` | Recherchiste | 🔍 | Deep analysis, fact-checking, reports |
| `coder` | Codeuse | 💻 | Code generation, debugging, optimization |
| `designer` | Designer | 🎨 | UI/UX, wireframes, design systems |
| `architect` | Architecte | 🏗️ | System design, PRDs, technical specs |
| `writer` | Rédactrice | ✍️ | Content, docs, marketing, storytelling |
| `qa` | QA | 🧪 | Testing, edge cases, bug hunting |

Each agent has:
- **System prompt** — Specialized instructions injected before the conversation
- **Strengths** — List of areas the agent excels at
- **Keywords** — Trigger words for auto-routing (e.g. "debug", "test", "design")

### Agent Chip Selector

The card form renders all 7 agents as clickable chips. Clicking a chip selects that agent for the card. The selected chip is visually highlighted.

### `/agent` Slash Command

`/agent coder` — Switches the active agent persona for the current chat session. Emits `AGENT_SWITCH` event which the frontend uses to prefix future messages with the selected agent's system prompt.

### Analyzer Auto-Suggests Agent

When the Analyzer (Layer 3) detects a card suggestion, it also suggests an appropriate agent type based on the card content. This is included in the `card:suggestion` WebSocket event's `agentType` field.

### Auto-Routing

When creating a card without an agent selection, `AgentRouter.route()` runs keyword matching:

1. Checks card title + description + context against each agent's keyword list
2. Returns the best match with a confidence score
3. Falls back to `ember` if no keywords match

`GET /api/cards/{card_id}/routing` — Get routing suggestion without applying it.

---

## 8. Settings

Accessible via the gear icon or `EVENTS.SETTINGS_OPEN`.

### Personality Configuration

| Setting | Options | Effect |
|---------|---------|--------|
| Bot Name | Free text | Replaces "Assistant" in UI and system prompt |
| Tone | casual / balanced / formal | Adjusts Claude's prose style |
| Warmth | cold / warm / hot | Adjusts emotional expressiveness |
| Language | en / fr / both | Sets STT language + system prompt language hint |
| Custom Instructions | Markdown text | Appended to every system prompt |
| Environment Notes | Markdown text | Injected as context (tech setup, preferences) |

### Personality File Editor

The Settings page includes an inline editor for 4 personality files stored in `voxyflow/personality/`:

| File | Purpose |
|------|---------|
| `SOUL.md` | Core personality — how the bot behaves |
| `USER.md` | Info about the user — preferences, context |
| `AGENTS.md` | Agent operating rules |
| `IDENTITY.md` | Bot identity — name, emoji, avatar |

**API:**
- `GET /api/settings/personality/files/{filename}` — Read file content
- `PUT /api/settings/personality/files/{filename}` — Write file content  
- `POST /api/settings/personality/files/{filename}/reset` — Reset to default template
- `GET /api/settings/personality/preview` — Preview all 4 files (first 300 chars each)

**Allowed files:** `SOUL.md`, `USER.md`, `AGENTS.md`, `IDENTITY.md`, `MEMORY.md`

### Appearance Settings

| Setting | Options | Effect |
|---------|---------|--------|
| Theme | Dark / Light | Toggle dark/light mode (🌙/☀️) |
| Accent Color | Color picker | Primary accent color throughout UI |
| Font Size | Small / Medium / Large | Global font size scale |
| Density | Compact / Comfortable / Spacious | UI density/spacing |
| Animations | On / Off | Enable/disable transitions and motion |

### Models Configuration

Configure each of the 3 model layers independently:

| Layer | Default Provider URL | Default Model |
|-------|---------------------|---------------|
| Fast | `http://localhost:3456/v1` | `claude-sonnet-4` |
| Deep | `http://localhost:3456/v1` | `claude-opus-4` |
| Analyzer | `http://localhost:3456/v1` | `claude-haiku-4` |

Each layer has: `provider_url`, `api_key`, `model`, `enabled`

This allows mixing providers (e.g. Ollama for Fast, Anthropic API for Deep).

### Jobs / Cron Management

Schedule recurring background tasks via the Settings → Jobs panel:

- **Types:** `reminder`, `github_sync`, `rag_index`, `custom`
- **Schedule:** Cron expression or shorthand (`every_5min`, `every_1h`)
- **Enable/disable** individual jobs without deleting them
- **Manual trigger:** Run any job immediately via the "▶ Run" button
- Jobs persisted to `~/.voxyflow/jobs.json`

**API:** `GET/POST /api/jobs` · `PUT/DELETE /api/jobs/{id}` · `POST /api/jobs/{id}/run`

### Health Status Bar

A live service health indicator in the Settings footer (and optionally in the sidebar):

- **Status:** `ok` / `degraded` / `down`
- **Per-service detail:** scheduler, database, RAG service, ChromaDB — each with last-check timestamp
- Powered by APScheduler heartbeat checks

**API:** `GET /api/health` · `GET /api/health/services`

### GitHub PAT Setup

- `POST /api/github/token` — Save a GitHub Personal Access Token
- `DELETE /api/github/token` — Remove saved token
- `GET /api/github/status` — Check GitHub CLI auth status

Token is stored in `settings.json` under the `github.token` key.

---

## 9. UI/UX

### Dark / Light Theme Toggle 🌙/☀️

Full dark and light themes implemented via CSS variables. Toggle via the moon/sun icon in the header or Settings → Appearance. Preference persisted in `localStorage`.

### Command Palette (Ctrl+K)

Global command palette accessible anywhere:

- Search and execute any action: navigate to project, create card, open settings, switch agent, etc.
- Fuzzy search across commands
- Keyboard navigable (↑/↓/Enter/Escape)

### Keyboard Shortcuts Modal (?)

Press `?` anywhere to open the keyboard shortcuts reference modal — a full list of all keyboard shortcuts.

### Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Enter` | Send message |
| `Shift+Enter` | New line in input |
| `Alt+V` | Toggle voice input |
| `Ctrl+B` | Toggle sidebar |
| `Cmd+W` / `Ctrl+W` | Close current project tab |
| `Ctrl+Tab` | Cycle through open tabs |
| `Ctrl+1` | Switch to Chat view |
| `Ctrl+2` | Switch to Kanban view |
| `Ctrl+3` | Switch to Projects view |
| `Ctrl+K` | Open Command Palette |
| `?` | Open keyboard shortcuts modal |
| `Ctrl+Shift+F` | Open chat history search |

### Kanban Search & Filter

The Kanban view includes a persistent filter bar below the column headers:

- **Search** — full-text search across card titles and descriptions
- **Priority chips** — filter by priority level (Critical / High / Medium / Low)
- **Agent chips** — filter by assigned agent
- **Tag chips** — filter by card tags
- Filters stack (AND logic)

### Smart Suggestions

Context-aware quick reply chips below the chat input:

- AI generates 3-5 relevant suggestions based on the current conversation context
- Click a chip to pre-fill the input
- Suggestions update after each message

### Chat History Search (Ctrl+Shift+F)

Full-text search across message history for the current chat context:

- Opens a search overlay
- Results show message snippet with context
- Click a result to jump to that point in the conversation

### Focus Mode 🎯 (Pomodoro)

Built-in Pomodoro timer for focused work:

- Start a focus session linked to a card or project
- Configurable work duration (default 25 min) and break duration
- Visual countdown timer
- Session logged to database on completion (for analytics)
- Progress tracked in Stats Dashboard

**API:** `POST /api/focus-sessions` · `GET /api/projects/{id}/focus`

### Notification Center 🔔

Persistent notification center (bell icon in header):

- Collects: card suggestions, job completions, AI analysis results, system messages
- **Quick actions** directly from the notification (e.g. "Create Card" from a suggestion)
- Unread badge count on bell icon
- Mark all read / clear all

### Activity Feed

Per-project activity timeline:

- Card created / moved / completed / commented events
- Agent assignments and reassignments
- AI actions (enrichment, health checks, standup generation)
- Displayed in the project sidebar or a dedicated tab

### TTS 🔊

Text-to-speech on assistant messages:

- 🔊 button on each assistant message plays the message via TTS
- Backend: configurable TTS engine (sherpa-onnx, XTTS v2 remote, or none)
- TTS failures are non-fatal

### Connection Status Indicator 🟢/🟡/🔴

Persistent connection indicator (bottom-left corner or status bar):

- 🟢 Connected — WebSocket active
- 🟡 Reconnecting — attempting reconnection with exponential backoff
- 🔴 Disconnected — connection lost

Auto-reconnects: base 1s, max 30s, up to 10 attempts. Heartbeat ping every 30s.

### Welcome Flow (3 Levels)

Context-appropriate onboarding when a chat is empty:

| Mode | When | Content |
|------|------|---------|
| `general` | Main tab, no project | App intro, prompt suggestions |
| `project` | Project tab opened | Project name, in-progress cards, todo count |
| `card` | Card detail opened | Card title, description, status, agent info |

### Model Status Bar

Persistent bar below the chat input showing the state of each model layer:

| State | Display | Color |
|-------|---------|-------|
| `idle` | "idle" | Dim dot |
| `thinking` | "thinking..." | Amber dot |
| `active` | "responding" | Green dot |
| `error` | "error" | Red dot |

Toggles for Deep and Analyzer rendered as checkboxes.

### Toast Notifications

`Toast` component handles ephemeral notifications:

- **Types:** `success`, `error`, `info`, `warning`
- **Duration:** 4000ms default, configurable per toast
- Stack-able (multiple toasts visible simultaneously)

### Responsive Layout

- **Mobile breakpoint:** 768px
- **Tablet breakpoint:** 1024px
- Sidebar collapses on mobile
- Chat input stays accessible on all screen sizes

### PWA

- `manifest.json` — installable as standalone app
- Service worker via Workbox — caches assets for offline use
- Runs without browser chrome when installed to home screen

---

## 10. Infrastructure

### APScheduler

Background task scheduler running within the FastAPI process:

- **Heartbeat job** — periodic health checks of all services (DB, RAG, ChromaDB)
  - Updates `SchedulerService.health_status` dict with per-service status + last-check timestamp
  - Powers the `GET /api/health` and `GET /api/health/services` endpoints
- **RAG indexing job** — periodic re-indexing of project documents to keep ChromaDB collections fresh
- **User-defined jobs** — cron and interval jobs configurable via Settings → Jobs (see above)

### ChromaDB RAG

Per-project isolated vector collections:

- Embeddings: `all-MiniLM-L6-v2` (sentence-transformers, runs locally)
- Storage: `~/.voxyflow/chroma/` (persistent)
- 3 collections per project: docs, history, workspace
- Context injection into chat prompts when relevant chunks exist
- Graceful degradation if `chromadb` is not installed

### Document Parser

`DocumentParserRegistry` maps file extensions to parser instances with graceful fallback:

| Parser | Extensions | Dep Required |
|--------|-----------|--------------|
| TextParser | `.txt`, `.md`, `.markdown` | None (always available) |
| PdfParser | `.pdf` | `pypdf` |
| DocxParser | `.docx`, `.doc` | `python-docx` |
| XlsxParser | `.xlsx`, `.xls`, `.csv` | `openpyxl` |

Parsers split documents into text chunks for embedding. Missing deps log a warning and skip the parser.

### MCP Architecture (Planned)

Model Context Protocol (MCP) integration is planned for a future phase:

- Voxyflow will expose an MCP server so external AI agents can interact with projects/cards
- Planned MCP tools: `create_card`, `update_card`, `list_cards`, `get_project_context`, `search_docs`
- Will allow Claude Desktop and other MCP clients to manage Voxyflow projects directly

### Focus Sessions (DB)

`FocusSession` table tracks Pomodoro sessions:
- `card_id` and `project_id` FK links
- `duration_minutes`, `completed` flag, `started_at`, `ended_at`
- Analytics aggregated per-project for Stats Dashboard
