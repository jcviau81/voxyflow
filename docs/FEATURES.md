# Voxyflow — Feature Reference

Complete documentation of all shipped features, organized by area.

---

## Table of Contents

1. [Core Chat](#1-core-chat)
2. [Voice Input](#2-voice-input)
3. [Projects & Cards](#3-projects--cards)
4. [Free Board](#4-free-board)
5. [RAG / Knowledge Base](#5-rag--knowledge-base)
6. [Settings](#6-settings)
7. [Agents](#7-agents)
8. [UI/UX](#8-uiux)

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

## 3. Projects & Cards

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

### Project Tabs

Projects open in browser-like tabs at the top of the interface:

- **Main tab** — always open, non-closable (General chat + Free Board)
- **Project tabs** — open when a project is selected (closable with `×` or `Cmd+W`)
- **`+` button** — opens the New Project form
- **Tab switching** — click tab or `Ctrl+Tab` cycles through open tabs
- **Notification dot** — appears on a tab when a card suggestion arrives for that project
- **Persistence** — open tabs survive page refresh (stored in `localStorage`)

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

### Kanban Board

Each project has a Kanban board with 4 columns:

| Column | Status | Label |
|--------|--------|-------|
| 💡 Idea | `idea` | Ideas & backlog |
| 📋 Todo | `todo` | Planned work |
| 🔨 In Progress | `in-progress` | Active tasks |
| ✅ Done | `done` | Completed |

**Drag & Drop:**  
Cards support drag-and-drop between columns via native HTML5 drag events (`dragstart`, `dragover`, `drop`). Dropping a card on a column calls `PATCH /api/cards/{id}` to update the status.

---

### Card Creation & Editing

Cards are created via the Card Form (click `+` in any column, or "Create from suggestion" in the Opportunities panel).

**Fields:**

| Field | Notes |
|-------|-------|
| Title | Required |
| Description | Markdown-supported |
| Status | `idea` / `todo` / `in-progress` / `done` |
| Priority | 0=none, 1=low, 2=medium, 3=high, 4=critical |
| Agent | Chip selector for the 7 agent types |
| Context | Notes for the agent (injected as agent context) |
| Dependencies | Other cards this card depends on |

**Auto-routing:** If no agent is manually selected, the backend's `AgentRouter` detects the best agent from the card's title, description, and context (keyword matching).

---

### Card Detail Modal

Clicking a card opens a full detail modal with:

- All card fields displayed
- Inline editing (via card form in edit mode)
- Chat panel — card-scoped conversation (chat_id = `card:{cardId}`)
- Agent badge showing assigned agent with emoji
- Status/priority display

---

### Agent Assignment Per Card

Each card can be assigned to one of 7 agents. The agent chip selector renders all 7 agents as clickable chips in the card form.

**Auto-assignment:** If no agent is selected, the backend `AgentRouter` selects one based on keyword matching in the card title/description. This runs at card creation time.

**Manual assignment:** `POST /api/cards/{card_id}/assign` with `{ agent_type: "coder" }`

**Routing debug:** `GET /api/cards/{card_id}/routing` returns the suggested agent and confidence score without applying it.

---

### Opportunities Panel

The Opportunities panel appears in each project view and collects AI-suggested cards:

- **Source:** Analyzer layer (Layer 3) emits `card:suggestion` WebSocket events after analyzing each message
- **Display:** Suggestions queue in the panel with title, description, and suggested agent
- **Actions:** "Create Card" → calls `POST /api/projects/{id}/cards` with `auto_generated: true`; "Dismiss" removes from panel
- **Notification:** Tab gets a notification dot when a new suggestion arrives

---

## 4. Free Board

A sticky-note scratchpad attached to the General chat (main tab, no project selected).

### Features

- **Quick-add form** — Type a note and click "Add" or press Enter
- **6 pastel colors** — None, Yellow, Blue, Green, Pink, Purple, Orange
- **Color selector** — Radio-style color chips in the add form
- **Grid layout** — Notes arranged in a CSS grid
- **Delete** — Each note has an `×` delete button
- **Promote to project** — "Promote" button on each note (emits `IDEA_PROMOTE` event; wire-up to project creation is in progress)
- **AI-suggested notes** — Analyzer can suggest notes (via `IDEA_SUGGESTION` event) which are auto-added to the board with a toast notification

### Storage

Notes (`Idea` type) are stored in `AppState` and persisted to `localStorage` as part of the global app state.

---

## 5. RAG / Knowledge Base

### Overview

Each project gets 3 isolated ChromaDB collections for retrieval-augmented generation:

| Collection | Purpose |
|-----------|---------|
| `voxyflow_project_{id}_docs` | Uploaded documents (.txt, .md) |
| `voxyflow_project_{id}_history` | Conversation history (future) |
| `voxyflow_project_{id}_workspace` | Cards, notes, board data (future) |

**Embeddings:** `all-MiniLM-L6-v2` (local, via `sentence-transformers` — no API key needed)  
**Persistence:** `~/.voxyflow/chroma/`

### Document Upload (Phase 1)

**Supported formats:** `.txt`, `.md`, `.markdown`

Upload flow:
1. `POST /api/projects/{id}/documents` (multipart/form-data)
2. File is parsed into text chunks
3. Chunks are embedded and indexed into ChromaDB
4. Document metadata (filename, size, chunk count, indexed_at) stored in SQLite

```bash
curl -X POST http://localhost:8000/api/projects/{id}/documents \
  -F "file=@README.md"
```

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

### Phase 2 Roadmap

Future document types (parsers to be registered in `DocumentParserRegistry`):
- **PDF** — via `pypdf` or `pdfplumber`
- **DOCX** — via `python-docx`
- **XLSX** — via `openpyxl`

---

## 6. Settings

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

### Models Configuration

Configure each of the 3 model layers independently:

| Layer | Default Provider URL | Default Model |
|-------|---------------------|---------------|
| Fast | `http://localhost:3456/v1` | `claude-sonnet-4` |
| Deep | `http://localhost:3456/v1` | `claude-opus-4` |
| Analyzer | `http://localhost:3456/v1` | `claude-haiku-4` |

Each layer has: `provider_url`, `api_key`, `model`, `enabled`

This allows mixing providers (e.g. Ollama for Fast, Anthropic API for Deep).

### GitHub PAT Setup

- `POST /api/github/token` — Save a GitHub Personal Access Token
- `DELETE /api/github/token` — Remove saved token
- `GET /api/github/status` — Check GitHub CLI auth status

Token is stored in `settings.json` under the `github.token` key. When present, it's passed as `GH_TOKEN` env var to `gh` CLI commands.

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

`/agent coder` — Switches the active agent persona for the current chat session. Emits `AGENT_SWITCH` event which the frontend can use to prefix future messages with the selected agent's system prompt.

### Analyzer Auto-Suggests Agent

When the Analyzer (Layer 3) detects a card suggestion, it also suggests an appropriate agent type based on the card content. This is included in the `card:suggestion` WebSocket event's `agentType` field.

### Auto-Routing

When creating a card without an agent selection, `AgentRouter.route()` runs keyword matching:

1. Checks card title + description + context against each agent's keyword list
2. Returns the best match with a confidence score
3. Falls back to `ember` if no keywords match

`GET /api/cards/{card_id}/routing` — Get routing suggestion without applying it.

---

## 8. UI/UX

### Dark Theme

Full dark theme implemented via CSS variables in `main.css`. No light mode toggle currently shipped — dark only.

### Responsive Layout

- **Mobile breakpoint:** 768px
- **Tablet breakpoint:** 1024px
- Sidebar collapses on mobile
- Chat input stays accessible on all screen sizes
- `responsive.css` handles layout adjustments

### Welcome Flow (3 Levels)

The Welcome Prompt renders context-appropriate onboarding when a chat is empty:

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

Toggles for Deep and Analyzer are rendered as checkboxes in the status bar.

### Toast Notifications

`Toast` component handles ephemeral notifications:

- **Types:** `success`, `error`, `info`, `warning`
- **Duration:** 4000ms default, configurable per toast
- **Trigger:** `eventBus.emit(EVENTS.TOAST_SHOW, { message, type, duration })`
- Stack-able (multiple toasts can be visible simultaneously)

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

### Connection State

The app monitors WebSocket connection state and shows visual feedback:
- Auto-reconnects with exponential backoff (base 1s, max 30s, up to 10 attempts)
- Heartbeat ping every 30s to keep connection alive
- Connection state in `AppState` → `connecting`, `connected`, `disconnected`, `reconnecting`

### PWA

- `manifest.json` — installable as standalone app
- Service worker via Workbox — caches assets for offline use
- Runs without browser chrome when installed to home screen
