# Voxyflow — API Reference

All REST endpoints are prefixed with `/api`. WebSocket is at `/ws`.

> **Note:** The API works with all LLM backends (CLI subprocess, native SDK, or deprecated proxy). The CLI subprocess backend (`CLAUDE_USE_CLI=true`) is the recommended and active configuration.

---

## Table of Contents

1. [WebSocket](#websocket)
2. [Health](#health)
3. [Chats](#chats)
4. [Projects](#projects)
5. [Cards & Agents](#cards--agents)
6. [Documents (RAG)](#documents-rag)
7. [Settings](#settings)
8. [Sessions](#sessions)
9. [GitHub](#github)
10. [Tech Detection](#tech-detection)
11. [Tools](#tools)
12. [Voice WebSocket](#voice-websocket)
13. [Focus Sessions](#focus-sessions)
14. [Jobs / Cron](#jobs--cron)
15. [Code Review](#code-review)

---

## WebSocket

### `WS /ws`

Primary real-time channel. One connection per browser session.

**Client → Server frames:**

| Type | Payload | Description |
|------|---------|-------------|
| `ping` | `{}` | Keepalive |
| `chat:message` | See below | Send a chat message through the Dispatcher + Workers pipeline |
| `session:reset` | `{ projectId?, sessionId?, chatLevel? }` | Clear conversation history |

**`chat:message` payload:**
```json
{
  "content": "string",
  "messageId": "string",
  "projectId": "string | null",
  "cardId": "string | null",
  "chatLevel": "general | project | card",
  "sessionId": "string",
  "mode": { "deep": true, "analyzer": true }
}
```

**Server → Client frames:**

| Type | Description |
|------|-------------|
| `pong` | Response to ping |
| `chat:response` | Token chunk or stream-done signal from Chat Agent (Dispatcher) |
| `chat:enrichment` | Deep mode enrichment/correction |
| `card:suggestion` | Analyzer detected a card opportunity |
| `model:status` | Component state change (thinking/active/idle/error) |
| `tool:result` | Result of an AI-triggered tool call |
| `session:reset_ack` | Confirms session was cleared |
| `ack` | Generic acknowledgment for unknown message types |
| `chat:error` | Error during chat processing |

---

## Health

### `GET /health`

Returns service health (basic).

**Response:**
```json
{ "status": "ok", "service": "voxyflow" }
```

---

### `GET /api/health`

Overall health status powered by APScheduler heartbeat checks.

**Response:**
```json
{
  "status": "ok",
  "scheduler_running": true,
  "services": {
    "database": { "status": "ok", "last_check": "2025-01-01T00:00:00Z" },
    "rag": { "status": "ok", "last_check": "2025-01-01T00:00:00Z" }
  }
}
```

---

### `GET /api/health/services`

Detailed per-service health with last-check timestamps.

**Response:**
```json
{
  "status": "ok",
  "scheduler_running": true,
  "services": { "database": { ... }, "rag": { ... } }
}
```

---

## Chats

### `POST /api/chats`

Create a new chat.

**Request:**
```json
{ "title": "My Chat", "project_id": "uuid | null" }
```

**Response:** `201` — `ChatResponse`
```json
{
  "id": "uuid",
  "title": "My Chat",
  "project_id": null,
  "created_at": "2025-01-01T00:00:00Z",
  "updated_at": "2025-01-01T00:00:00Z",
  "messages": []
}
```

---

### `GET /api/chats`

List chats with message counts.

**Query params:** `limit` (default 50), `offset` (default 0)

**Response:** `200` — Array of `ChatListItem`
```json
[{
  "id": "uuid",
  "title": "My Chat",
  "project_id": null,
  "created_at": "...",
  "message_count": 42
}]
```

---

### `GET /api/chats/{chat_id}`

Get a chat with all messages.

**Response:** `200` — `ChatResponse` with `messages[]`  
**Error:** `404` — Chat not found

---

### `POST /api/chats/{chat_id}/messages`

Add a message to a chat.

**Request:**
```json
{
  "role": "user | assistant | system | analyzer",
  "content": "message text",
  "audio_url": "optional URL"
}
```

**Response:** `201` — `MessageResponse`  
**Error:** `404` — Chat not found

---

## Projects

### `GET /api/templates`

List all built-in project templates.

**Response:** `200` — Array of templates
```json
[{
  "id": "api-service",
  "name": "API Service",
  "description": "Backend API service with auth, testing, deploy cards",
  "card_count": 8
}]
```

---

### `POST /api/from-template/{template_id}`

Create a new project pre-populated with cards from a built-in template.

**Path param:** `template_id` — one of the IDs returned by `GET /api/templates`

**Request:**
```json
{ "title": "My API", "description": "Optional override" }
```

**Response:** `201` — `{ "project": ProjectResponse, "cards_created": 8 }`

---

### `GET /api/projects/{project_id}/export`

Export a project and all its cards as a JSON payload (for backup/migration).

**Response:** `200` — Full export object
```json
{
  "version": "1",
  "exported_at": "2025-01-01T00:00:00Z",
  "project": { ...ProjectResponse },
  "cards": [ ...CardResponse ]
}
```

---

### `POST /api/projects/import`

Import a project from an exported JSON payload. Creates a new project with new IDs.

**Request:** Export payload object (from `GET /export`)

**Response:** `201`
```json
{ "project_id": "uuid", "cards_imported": 12 }
```

---

### `POST /api/projects/{project_id}/meeting-notes`

Extract action items from meeting notes using AI.

**Request:**
```json
{ "transcript": "Meeting notes text..." }
```

**Response:** `200`
```json
{
  "action_items": [
    { "title": "Fix login bug", "owner": "Alice", "priority": 2, "due_date": "2025-01-15" }
  ]
}
```

---

### `POST /api/projects/{project_id}/meeting-notes/confirm`

Create cards from extracted meeting action items.

**Request:**
```json
{
  "action_items": [ { "title": "Fix login bug", "priority": 2 } ]
}
```

**Response:** `201`
```json
{ "cards_created": 3, "cards": [ ...CardResponse ] }
```

---

### `POST /api/projects/{project_id}/brief`

Generate a comprehensive AI project brief / PRD using the Opus model.

**Response:** `200`
```json
{
  "brief": "# Project Brief\n\n## Executive Summary\n..."
}
```

---

### `POST /api/projects/{project_id}/health`

Analyse project health and return a score, grade, strengths, issues, and recommendations.

**Response:** `200`
```json
{
  "score": 72,
  "grade": "B",
  "strengths": ["Good velocity", "Clear ownership"],
  "issues": ["3 cards blocked", "No done cards this week"],
  "recommendations": ["Resolve blockers first", "Set sprint goal"]
}
```

---

### `POST /api/projects/{project_id}/standup`

Generate a daily standup summary using the fast model.

**Response:** `200`
```json
{
  "standup": "**Done:** Closed auth bug.\n**In Progress:** API refactor.\n**Blockers:** None.",
  "done_cards": [...],
  "in_progress_cards": [...],
  "blockers": []
}
```

---

### `GET /api/projects/{project_id}/standup/schedule`

Get the standup schedule for a project (null if not configured).

**Response:** `200`
```json
{ "project_id": "uuid", "cron": "0 9 * * 1-5", "timezone": "America/Toronto" }
// or null
```

---

### `POST /api/projects/{project_id}/standup/schedule`

Create or update the daily standup schedule.

**Request:**
```json
{ "cron": "0 9 * * 1-5", "timezone": "America/Toronto" }
```

**Response:** `201` — Schedule object

---

### `POST /api/projects/{project_id}/prioritize`

Smart prioritization: rule-based scoring + AI reasoning to rank the backlog.

**Response:** `200`
```json
{
  "cards": [
    {
      "card_id": "uuid",
      "title": "Fix login bug",
      "score": 92,
      "reasoning": "Critical priority, blocking other work, aged 5 days."
    }
  ]
}
```

---

### Wiki Endpoints

#### `GET /api/projects/{project_id}/wiki`

List all wiki pages (id, title, updated_at).

**Response:** `200` — Array of `{ "id": "uuid", "title": "Architecture", "updated_at": "..." }`

#### `POST /api/projects/{project_id}/wiki`

Create a new wiki page.

**Request:** `{ "title": "Architecture", "content": "# Arch\n..." }`

**Response:** `201` — Full page object `{ "id", "title", "content", "created_at", "updated_at" }`

#### `GET /api/projects/{project_id}/wiki/{page_id}`

Get full content of a wiki page.

**Response:** `200` — Full page object  
**Error:** `404`

#### `PUT /api/projects/{project_id}/wiki/{page_id}`

Update a wiki page's title and/or content.

**Request:** `{ "title"?: "...", "content"?: "..." }`

**Response:** `200` — Updated page object

#### `DELETE /api/projects/{project_id}/wiki/{page_id}`

Delete a wiki page.

**Response:** `204`

---

### Sprint Endpoints

#### `GET /api/projects/{project_id}/sprints`

List all sprints for a project with card counts.

**Response:** `200` — Array of SprintResponse
```json
[{
  "id": "uuid",
  "name": "Sprint 1",
  "goal": "Ship auth",
  "status": "active",
  "start_date": "2025-01-01",
  "end_date": "2025-01-14",
  "card_count": 5
}]
```

#### `POST /api/projects/{project_id}/sprints`

Create a new sprint.

**Request:** `{ "name": "Sprint 1", "goal": "Ship auth", "start_date": "2025-01-01", "end_date": "2025-01-14" }`

**Response:** `201` — SprintResponse

#### `PUT /api/projects/{project_id}/sprints/{sprint_id}`

Update sprint name, goal, or dates.

**Response:** `200` — Updated SprintResponse

#### `DELETE /api/projects/{project_id}/sprints/{sprint_id}`

Delete a sprint. Cards in the sprint lose their sprint assignment.

**Response:** `204`

#### `POST /api/projects/{project_id}/sprints/{sprint_id}/start`

Activate a sprint. Only one sprint can be active at a time.

**Response:** `200` — Updated SprintResponse

#### `POST /api/projects/{project_id}/sprints/{sprint_id}/complete`

Mark a sprint as completed.

**Response:** `200` — Updated SprintResponse

---

### `POST /api/projects`

Create a new project.

**Request:**
```json
{
  "title": "Voxyflow",
  "description": "Voice-first AI assistant",
  "context": "FastAPI + TypeScript",
  "github_repo": "jcviau81/voxyflow",
  "github_url": "https://github.com/jcviau81/voxyflow",
  "github_branch": "main",
  "github_language": "TypeScript",
  "local_path": "~/projects/voxyflow"
}
```

All fields except `title` are optional.

**Response:** `201` — `ProjectResponse`

---

### `GET /api/projects`

List all projects, ordered by `updated_at` desc.

**Query params:** `status` (`active` | `archived`)

**Response:** `200` — Array of `ProjectResponse`
```json
[{
  "id": "uuid",
  "title": "Voxyflow",
  "description": "...",
  "status": "active",
  "github_repo": "jcviau81/voxyflow",
  "created_at": "...",
  "updated_at": "..."
}]
```

---

### `GET /api/projects/{project_id}`

Get a project with its cards.

**Response:** `200` — `ProjectWithCards` (includes `cards[]`)  
**Error:** `404` — Project not found

---

### `PATCH /api/projects/{project_id}`

Update project fields (partial update).

**Request:** Any subset of project fields.

**Response:** `200` — Updated `ProjectResponse`  
**Error:** `404` — Project not found

---

## Cards & Agents

### `GET /agents`

List all available agent personas.

**Response:** `200`
```json
[{
  "type": "coder",
  "name": "Codeuse",
  "emoji": "💻",
  "description": "Code generation, debugging, optimization...",
  "strengths": ["code generation", "debugging"],
  "keywords": ["code", "implement", "debug"]
}]
```

---

### `POST /api/projects/{project_id}/cards`

Create a card in a project.

**Request:**
```json
{
  "title": "Add auth middleware",
  "description": "JWT-based auth for API routes",
  "status": "todo",
  "priority": 2,
  "agent_type": "coder",
  "agent_context": "FastAPI app, routes in app/routes/",
  "dependency_ids": [],
  "auto_generated": false
}
```

All fields except `title` are optional. If `agent_type` is omitted, it's auto-detected.

**Response:** `201` — `CardResponse`  
**Error:** `404` — Project not found

---

### `GET /api/projects/{project_id}/cards`

List cards for a project, ordered by `position`.

**Query params:** `status` (filter by status), `agent_type` (filter by agent)

**Response:** `200` — Array of `CardResponse`
```json
[{
  "id": "uuid",
  "project_id": "uuid",
  "title": "Add auth middleware",
  "description": "...",
  "status": "todo",
  "priority": 2,
  "position": 0,
  "agent_type": "coder",
  "agent_assigned": "💻 Codeuse",
  "auto_generated": false,
  "dependency_ids": [],
  "created_at": "...",
  "updated_at": "..."
}]
```

---

### `PATCH /api/cards/{card_id}`

Update a card (partial update). Updating `agent_type` also updates `agent_assigned` display name.

**Request:** Any subset of card fields.

**Response:** `200` — Updated `CardResponse`  
**Error:** `404` — Card not found

---

### `POST /api/cards/{card_id}/assign`

Assign or reassign a card to a specific agent.

**Request:**
```json
{
  "agent_type": "architect",
  "agent_context": "optional context for this agent"
}
```

**Response:** `200` — Updated `CardResponse`  
**Error:** `404` — Card not found

---

### `GET /api/cards/{card_id}/routing`

Get the agent routing suggestion for a card without applying it.

**Response:**
```json
{
  "suggested_agent": "coder",
  "confidence": 0.85,
  "matched_keywords": ["code", "implement"],
  "current_agent_type": "ember",
  "current_agent_assigned": "🔥 Ember"
}
```

---

### `DELETE /api/cards/{card_id}`

Delete a card.

**Response:** `204` No Content  
**Error:** `404` — Card not found

---

### `POST /api/cards/{card_id}/duplicate`

Duplicate a card within the same project. Title gets ` (copy)` appended; votes reset to 0.

**Response:** `201` — New `CardResponse`

---

### `POST /api/cards/{card_id}/clone-to/{target_project_id}`

Clone a card to another project. Title gets ` (cloned)` appended; checklist items are cloned; a `cloned_from` relation is created.

**Response:** `201` — New `CardResponse`  
**Error:** `400` — Card already in target project  
**Error:** `404` — Card or project not found

---

### `POST /api/cards/{card_id}/move-to/{target_project_id}`

Move a card (with all comments, attachments, checklist) to another project.

**Response:** `200` — Updated `CardResponse`  
**Error:** `400` — Card already in target project

---

### `GET /api/cards/{card_id}/history`

Return card change history, newest first, max 50 entries.

Tracks changes to: `status`, `priority`, `title`, `description`, `assignee`, `agent_type`.

**Response:** `200`
```json
[{
  "id": "uuid",
  "card_id": "uuid",
  "field_changed": "status",
  "old_value": "todo",
  "new_value": "in-progress",
  "changed_at": "2025-01-01T00:00:00Z",
  "changed_by": "User"
}]
```

---

### `POST /api/cards/{card_id}/vote`

Increment vote count. Returns `{ "votes": <new_count> }`.

### `DELETE /api/cards/{card_id}/vote`

Decrement vote count (min 0). Returns `{ "votes": <new_count> }`.

---

### Card Comment Endpoints

#### `POST /api/cards/{card_id}/comments`

Add a comment to a card.

**Request:** `{ "author": "Alice", "content": "Looking good!" }`

**Response:** `201` — `{ "id", "card_id", "author", "content", "created_at" }`

#### `GET /api/cards/{card_id}/comments`

List all comments (newest first).

**Response:** `200` — Array of comment objects

#### `DELETE /api/cards/{card_id}/comments/{comment_id}`

Delete a comment.

**Response:** `204`

---

### Card Checklist Endpoints

#### `POST /api/cards/{card_id}/checklist`

Add a checklist item.

**Request:** `{ "text": "Write unit tests" }`

**Response:** `201` — `{ "id", "card_id", "text", "completed", "position", "created_at" }`

#### `GET /api/cards/{card_id}/checklist`

List all checklist items (ordered by position).

**Response:** `200` — Array of checklist item objects

#### `PATCH /api/cards/{card_id}/checklist/{item_id}`

Update a checklist item (toggle completed or edit text).

**Request:** `{ "completed"?: true, "text"?: "..." }`

**Response:** `200` — Updated item

#### `DELETE /api/cards/{card_id}/checklist/{item_id}`

Delete a checklist item.

**Response:** `204`

---

### Card Time Tracking Endpoints

#### `POST /api/cards/{card_id}/time`

Log time spent on a card.

**Request:** `{ "duration_minutes": 45, "note": "Debugging session" }`

**Response:** `201` — `{ "id", "card_id", "duration_minutes", "note", "logged_at" }`

#### `GET /api/cards/{card_id}/time`

List all time entries (newest first).

**Response:** `200` — Array of time entry objects

#### `DELETE /api/cards/{card_id}/time/{entry_id}`

Delete a time entry.

**Response:** `204`

---

### Card Attachment Endpoints

#### `POST /api/cards/{card_id}/attachments`

Upload a file attachment. Max 50 MB, any type.

**Content-Type:** `multipart/form-data`  
**Body:** `file` field

**Response:** `201`
```json
{
  "id": "uuid",
  "card_id": "uuid",
  "filename": "screenshot.png",
  "file_size": 204800,
  "mime_type": "image/png",
  "created_at": "2025-01-01T00:00:00Z"
}
```
**Error:** `413` — File too large  
**Error:** `404` — Card not found

#### `GET /api/cards/{card_id}/attachments`

List all attachments for a card (newest first).

**Response:** `200` — Array of attachment objects

#### `GET /api/cards/{card_id}/attachments/{attachment_id}/download`

Download an attachment file.

**Response:** File content with appropriate `Content-Type`  
**Error:** `404`

#### `DELETE /api/cards/{card_id}/attachments/{attachment_id}`

Delete an attachment (removes from disk and DB).

**Response:** `204`

---

### Card Relation Endpoints

#### `POST /api/cards/{card_id}/relations`

Add a typed relation from this card to another.

**Request:**
```json
{ "target_card_id": "uuid", "relation_type": "blocks" }
```

Valid types: `duplicates`, `blocks`, `is_blocked_by`, `relates_to`, `cloned_from`

**Response:** `201`
```json
{
  "id": "uuid",
  "source_card_id": "uuid",
  "target_card_id": "uuid",
  "relation_type": "blocks",
  "created_at": "...",
  "related_card_id": "uuid",
  "related_card_title": "Fix login",
  "related_card_status": "todo"
}
```
**Error:** `409` — Relation already exists  
**Error:** `400` — Invalid relation type or self-relation

#### `GET /api/cards/{card_id}/relations`

List all relations (both directions). Inverse types are auto-computed for target-direction relations.

**Response:** `200` — Array of relation objects

#### `DELETE /api/cards/{card_id}/relations/{relation_id}`

Delete a relation. Card must be either source or target.

**Response:** `204`

---

### `POST /api/cards/{card_id}/enrich`

AI enrichment: generates description, checklist items, effort estimate, and tags from just the card title.

**Response:** `200`
```json
{
  "description": "Implement JWT-based auth middleware...",
  "checklist_items": ["Define token schema", "Add middleware", "Write tests"],
  "effort": "M",
  "tags": ["auth", "security", "backend"]
}
```
**Error:** `500` — AI enrichment failed

---

## Documents (RAG)

### `POST /api/projects/{project_id}/documents`

Upload a document and index it into the project's RAG knowledge base.

**Content-Type:** `multipart/form-data`  
**Body:** `file` field with the file to upload

**Supported formats (auto-detected by installed deps):**
- `.txt`, `.md`, `.markdown` — always available
- `.pdf` — requires `pypdf`
- `.docx`, `.doc` — requires `python-docx`
- `.xlsx`, `.xls`, `.csv` — requires `openpyxl`

**Response:** `201` — `DocumentResponse`
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "filename": "README.md",
  "filetype": ".md",
  "size_bytes": 4096,
  "chunk_count": 12,
  "created_at": "...",
  "indexed_at": "..."
}
```

**Error:** `415` — Unsupported file type  
**Error:** `404` — Project not found  
**Error:** `422` — Parse failed

---

### `GET /api/projects/{project_id}/documents`

List all documents for a project.

**Response:** `200`
```json
{
  "documents": [{ ...DocumentResponse }],
  "total": 3
}
```

---

### `DELETE /api/projects/{project_id}/documents/{document_id}`

Delete a document and remove its chunks from ChromaDB.

**Response:** `204` No Content  
**Error:** `404` — Document or project not found

---

## Settings

### `GET /api/settings`

Get current settings (from `settings.json`).

**Response:** `200` — Full settings object
```json
{
  "personality": {
    "bot_name": "Assistant",
    "preferred_language": "both",
    "soul_file": "./personality/SOUL.md",
    "user_file": "./personality/USER.md",
    "agents_file": "./personality/AGENTS.md",
    "identity_file": "./personality/IDENTITY.md",
    "custom_instructions": "",
    "environment_notes": "",
    "tone": "casual",
    "warmth": "warm"
  },
  "models": {
    "fast": {
      "provider_url": "http://localhost:3456/v1",
      "api_key": "",
      "model": "claude-sonnet-4",
      "enabled": true
    },
    "deep": { ... },
    "analyzer": { ... }
  }
}
```

---

### `PUT /api/settings`

Save settings. Full object required.

**Request:** Full `AppSettings` object (see GET response above).

**Response:** `200` — `{ "status": "saved" }`

---

### `GET /api/settings/personality/preview`

Preview all 4 personality files (first 300 chars each).

**Response:**
```json
{
  "SOUL": { "path": "/path/SOUL.md", "exists": true, "preview": "# SOUL...", "size": 1200 },
  "USER": { ... },
  "AGENTS": { ... },
  "IDENTITY": { ... }
}
```

---

### `GET /api/settings/personality/files/{filename}`

Read a personality file content.

**Allowed filenames:** `SOUL.md`, `USER.md`, `AGENTS.md`, `IDENTITY.md`, `MEMORY.md`

**Response:**
```json
{ "filename": "SOUL.md", "content": "# SOUL...", "exists": true, "size": 1200 }
```

**Error:** `400` — File not allowed

---

### `PUT /api/settings/personality/files/{filename}`

Write a personality file.

**Request:** `{ "content": "# New content..." }`

**Response:** `200` — `{ "status": "saved", "filename": "SOUL.md", "size": 1200 }`

---

### `POST /api/settings/personality/files/{filename}/reset`

Reset a personality file to its default template.

**Response:** `200` — `{ "status": "reset", "filename": "SOUL.md", "size": 800 }`

---

## Sessions

### `GET /api/sessions`

List all persisted sessions.

**Query params:** `prefix` — Filter by chat_id prefix (e.g. `project:`)

**Response:**
```json
[{ "chat_id": "project:uuid", "message_count": 42, "last_updated": "..." }]
```

---

### `GET /api/sessions/{chat_id}`

Get messages for a specific session.

**Query params:** `limit` (default 50, max 500)

**Response:**
```json
{
  "chat_id": "project:uuid",
  "messages": [{ "role": "user", "content": "...", "timestamp": "..." }],
  "count": 42
}
```

---

### `DELETE /api/sessions/{chat_id}`

Clear (archive) a session's messages.

**Response:** `200` — `{ "status": "cleared", "chat_id": "project:uuid" }`

---

## GitHub

### `GET /api/github/status`

Check GitHub CLI and PAT configuration.

**Response:**
```json
{
  "gh_installed": true,
  "gh_authenticated": true,
  "username": "jcviau81",
  "token_configured": true,
  "method": "pat"
}
```

---

### `POST /api/github/token`

Save a GitHub Personal Access Token.

**Request:** `{ "token": "ghp_..." }`  
Token must start with `ghp_` or `github_pat_`.

**Response:** `200` — `{ "saved": true }`  
**Error:** `400` — Invalid token format

---

### `DELETE /api/github/token`

Remove saved GitHub PAT.

**Response:** `200` — `{ "deleted": true }`

---

### `GET /api/github/validate/{owner}/{repo}`

Validate a GitHub repository and return its info.

**Response:**
```json
{
  "valid": true,
  "full_name": "jcviau81/voxyflow",
  "description": "Voice-first AI assistant",
  "default_branch": "main",
  "language": "TypeScript",
  "stars": 0,
  "private": false,
  "html_url": "https://github.com/jcviau81/voxyflow",
  "clone_url": "https://github.com/jcviau81/voxyflow.git",
  "updated_at": "..."
}
```

**Error:** `401` — GitHub not configured  
**Error:** `404` — Repo not found  
**Error:** `503` — `gh` CLI not installed

---

### `POST /api/github/clone`

Clone a repository locally.

**Query params:** `owner`, `repo`, `target_dir` (optional, defaults to `~/projects/{repo}`)

**Response:**
```json
{ "status": "cloned", "path": "~/projects/voxyflow" }
// or
{ "status": "already_exists", "path": "..." }
```

---

## Tech Detection

### `GET /api/tech/detect`

Scan a directory and detect technologies.

**Query params:** `project_path` — Path to scan (supports `~` expansion)

**Response:**
```json
{
  "path": "/home/user/projects/myapp",
  "technologies": [
    { "name": "Python", "icon": "🐍", "category": "language", "source": "requirements.txt" },
    { "name": "FastAPI", "icon": "⚡", "category": "framework", "version": "0.115.0", "source": "requirements.txt" }
  ],
  "file_counts": { ".py": 42, ".ts": 89, ".md": 5 },
  "total_files": 143
}
```

**Error:** `200` with `{ "error": "Path not found", "technologies": [] }` if path doesn't exist

---

## Tools

### `POST /api/tools/execute`

Execute a registered tool by name (for external/debugging use).

**Request:**
```json
{
  "name": "create_card",
  "params": {
    "project_id": "uuid",
    "title": "New card",
    "status": "todo"
  }
}
```

**Response:**
```json
{
  "success": true,
  "data": { "card_id": "uuid" },
  "error": null,
  "ui_action": null
}
```

---

### `GET /api/tools/definitions`

List all registered tools and their JSON Schema definitions.

**Response:**
```json
[{
  "name": "create_card",
  "description": "Create a new card in a project",
  "parameters": {
    "type": "object",
    "properties": {
      "project_id": { "type": "string" },
      "title": { "type": "string" },
      "status": { "type": "string" }
    }
  }
}]
```

---

## Voice WebSocket

### `WS /api/ws/voice/{chat_id}`

Dedicated voice pipeline WebSocket (per chat_id).

**Client → Server:**

```json
// Send a transcript
{
  "type": "transcript",
  "text": "What should I build next?",
  "project_id": "uuid"
}

// Future: raw audio streaming
{ "type": "audio_chunk", "data": "base64..." }
```

**Server → Client:**

```json
// Status
{ "type": "status", "state": "listening | processing | speaking" }

// Text response
{
  "type": "assistant_text",
  "text": "Here are some ideas...",
  "model": "fast",
  "is_enrichment": false
}

// Audio response (base64 WAV/MP3)
{ "type": "assistant_audio", "data": "base64...", "format": "wav" }

// Card suggestion
{
  "type": "card_suggestion",
  "title": "Add dark mode",
  "description": "...",
  "priority": "medium",
  "confidence": 0.8
}

// Error
{ "type": "error", "message": "LLM error: ..." }
```

**Note:** Primary UI uses `/ws`. The `/api/ws/voice/{chat_id}` endpoint is an alternate pipeline for dedicated voice clients or future mobile apps.

---

## Focus Sessions

### `POST /api/focus-sessions`

Log a completed or interrupted Pomodoro focus session.

**Request:**
```json
{
  "card_id": "uuid | null",
  "project_id": "uuid | null",
  "duration_minutes": 25,
  "completed": true,
  "started_at": "2025-01-01T09:00:00Z",
  "ended_at": "2025-01-01T09:25:00Z"
}
```

**Response:** `201`
```json
{
  "id": "uuid",
  "card_id": "uuid",
  "project_id": "uuid",
  "duration_minutes": 25,
  "completed": true,
  "started_at": "2025-01-01T09:00:00Z",
  "ended_at": "2025-01-01T09:25:00Z"
}
```
**Error:** `400` — Invalid duration or datetime format  
**Error:** `404` — Card or project not found

---

### `GET /api/projects/{project_id}/focus`

Return focus session analytics for a project.

**Response:** `200`
```json
{
  "total_sessions": 12,
  "total_minutes": 300,
  "completed_sessions": 10,
  "avg_session_minutes": 25.0,
  "by_card": [
    { "card_id": "uuid", "title": "Add auth", "sessions": 3, "minutes": 75 }
  ],
  "by_day": [
    { "date": "2025-01-01", "sessions": 2, "minutes": 50 }
  ]
}
```

`by_day` covers the last 7 days. `by_card` is all-time, sorted by minutes desc.

---

## Jobs / Cron

### `GET /api/jobs`

List all configured jobs.

**Response:** `200`
```json
{
  "jobs": [
    {
      "id": "uuid",
      "name": "Daily RAG index",
      "type": "rag_index",
      "schedule": "0 2 * * *",
      "enabled": true,
      "payload": {}
    }
  ],
  "total": 1
}
```

---

### `POST /api/jobs`

Create a new job.

**Request:**
```json
{
  "name": "Daily RAG index",
  "type": "rag_index",
  "schedule": "0 2 * * *",
  "enabled": true,
  "payload": { "project_id": "uuid" }
}
```

**Job types:** `reminder`, `github_sync`, `rag_index`, `custom`  
**Schedule formats:** cron expression (`"0 2 * * *"`) or shorthand (`"every_5min"`, `"every_1h"`)

**Response:** `201` — Job object

---

### `PUT /api/jobs/{job_id}`

Update an existing job (partial update).

**Request:** Any subset of `{ name, type, schedule, enabled, payload }`

**Response:** `200` — Updated job object  
**Error:** `404` — Job not found

---

### `DELETE /api/jobs/{job_id}`

Delete a job.

**Response:** `204`  
**Error:** `404` — Job not found

---

### `POST /api/jobs/{job_id}/run`

Trigger a job immediately (fire-and-forget).

**Response:** `200`
```json
{
  "status": "triggered",
  "job_id": "uuid",
  "name": "Daily RAG index",
  "result": { "status": "ok", "message": "RAG index triggered" }
}
```
**Error:** `404` — Job not found

---

## Code Review

### `POST /api/code/review`

Review a code snippet using the Opus model. Returns structured analysis.

**Request:**
```json
{
  "code": "def foo():\n    return 1/0",
  "language": "python",
  "context": "Utility function in our API"
}
```

**Response:** `200`
```json
{
  "review": "This function will always raise a ZeroDivisionError...",
  "issues": [
    { "line": 2, "severity": "error", "message": "Division by zero — always raises ZeroDivisionError" }
  ],
  "suggestions": [
    "Add a guard clause before the division",
    "Consider returning None or raising a custom exception"
  ]
}
```

**Issue severities:** `error` (bugs/security), `warning` (code smells/perf), `info` (style/clarity)  
**Limits:** Up to 10 issues, up to 5 suggestions
