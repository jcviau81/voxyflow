# Voxyflow — API Reference

All REST endpoints are prefixed with `/api`. WebSocket is at `/ws`.

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

---

## WebSocket

### `WS /ws`

Primary real-time channel. One connection per browser session.

**Client → Server frames:**

| Type | Payload | Description |
|------|---------|-------------|
| `ping` | `{}` | Keepalive |
| `chat:message` | See below | Send a chat message through 3-layer pipeline |
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
  "layers": { "deep": true, "analyzer": true }
}
```

**Server → Client frames:**

| Type | Description |
|------|-------------|
| `pong` | Response to ping |
| `chat:response` | Token chunk or stream-done signal from Fast layer |
| `chat:enrichment` | Deep layer enrichment/correction |
| `card:suggestion` | Analyzer detected a card opportunity |
| `model:status` | Layer state change (thinking/active/idle/error) |
| `tool:result` | Result of an AI-triggered tool call |
| `session:reset_ack` | Confirms session was cleared |
| `ack` | Generic acknowledgment for unknown message types |
| `chat:error` | Error during chat processing |

---

## Health

### `GET /health`

Returns service health.

**Response:**
```json
{ "status": "ok", "service": "voxyflow" }
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
  "status": "idea",
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

## Documents (RAG)

### `POST /api/projects/{project_id}/documents`

Upload a document and index it into the project's RAG knowledge base.

**Content-Type:** `multipart/form-data`  
**Body:** `file` field with the file to upload

**Supported:** `.txt`, `.md`, `.markdown`  
**Not yet supported:** `.pdf`, `.docx`, `.xlsx` (Phase 2)

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
    "status": "idea"
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
