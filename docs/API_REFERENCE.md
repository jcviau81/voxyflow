# API REFERENCE — Every Endpoint

> Complete REST API reference for Voxyflow. Grouped by resource.

---

## Cards

### Project Cards

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/projects/{project_id}/cards` | Create a card in a project |
| `GET` | `/api/projects/{project_id}/cards` | List all cards for a project |

**POST /api/projects/{project_id}/cards**
```json
// Request
{
  "title": "string (required)",
  "description": "string",
  "status": "card|todo|in-progress|done (default: card)",
  "priority": "0-4 (default: 0)",
  "color": "yellow|blue|green|pink|purple|orange",
  "agent_type": "ember|researcher|coder|designer|architect|writer|qa",
  "agent_context": "string",
  "recurrence": "daily|weekly|monthly",
  "recurrence_next": "ISO date string",
  "dependency_ids": ["card_id_1", "card_id_2"]
}
// Response: CardResponse (see DATA_MODEL.md)
```

**GET /api/projects/{project_id}/cards**
- Query params: `status` (filter), `agent_type` (filter)
- Response: `CardResponse[]`

### Home Cards (legacy "unassigned" path)

These endpoints proxy to the system Home project (`project_id="system-main"`).

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/cards/unassigned` | Create a card in Home |
| `GET` | `/api/cards/unassigned` | List all Home cards |

**POST /api/cards/unassigned**
```json
// Request
{
  "title": "string (required)",
  "description": "string",
  "color": "yellow|blue|green|pink|purple|orange"
}
// Response: CardResponse (status defaults to "card")
```

### Card Operations

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/cards/{card_id}` | Get card details |
| `PATCH` | `/api/cards/{card_id}` | Update card fields |
| `DELETE` | `/api/cards/{card_id}` | Delete card (irreversible) |
| `PATCH` | `/api/cards/{card_id}/assign/{project_id}` | Move card to a project |
| `PATCH` | `/api/cards/{card_id}/unassign` | Move card back to Home (system project) |
| `POST` | `/api/cards/{card_id}/duplicate` | Duplicate card in same project |
| `POST` | `/api/cards/{card_id}/enrich` | AI-enrich card description |

**PATCH /api/cards/{card_id}**
```json
// Request (all fields optional)
{
  "title": "string",
  "description": "string",
  "status": "card|todo|in-progress|done|archived",
  "priority": "0-4",
  "color": "string",
  "agent_type": "string",
  "agent_context": "string",
  "assignee": "string",
  "watchers": "string",
  "votes": "integer",
  "sprint_id": "string",
  "recurrence": "string",
  "recurrence_next": "string"
}
```

### Card Sub-Resources

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/cards/{card_id}/time` | Log time entry |
| `POST` | `/api/cards/{card_id}/comments` | Add comment |
| `GET` | `/api/cards/{card_id}/comments` | List comments |
| `POST` | `/api/cards/{card_id}/checklist` | Add checklist item |
| `PATCH` | `/api/cards/{card_id}/checklist/{item_id}` | Update checklist item |
| `POST` | `/api/cards/{card_id}/attachments` | Upload attachment |

### Agents

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/agents` | List all agent personas |

Response: `[{type, name, emoji, description, strengths, keywords}]`

---

## Projects

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/projects` | Create project |
| `GET` | `/api/projects` | List all projects |
| `GET` | `/api/projects/{project_id}` | Get project with cards |
| `PATCH` | `/api/projects/{project_id}` | Update project |
| `DELETE` | `/api/projects/{project_id}` | Delete project (irreversible) |
| `POST` | `/api/projects/{project_id}/archive` | Archive project |
| `POST` | `/api/projects/{project_id}/restore` | Restore archived project |
| `GET` | `/api/projects/{project_id}/export` | Export project as JSON |
| `POST` | `/api/projects/import` | Import project from JSON |
| `GET` | `/api/projects/templates` | List project templates |
| `POST` | `/api/projects/from-template/{template_id}` | Create from template |

**POST /api/projects**
```json
{
  "title": "string (required)",
  "description": "string",
  "context": "string",
  "github_repo": "owner/repo",
  "github_url": "string",
  "github_branch": "string",
  "github_language": "string",
  "local_path": "string"
}
```

**GET /api/projects**
- Query params: `status` (active|archived), `archived` (bool)
- Response: `ProjectResponse[]`

**Templates:** software, research, content, bugfix, launch

---

## Documents

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/projects/{project_id}/documents` | Upload document (multipart) |
| `GET` | `/api/projects/{project_id}/documents` | List project documents |
| `DELETE` | `/api/projects/{project_id}/documents/{document_id}` | Delete document |

**POST** accepts multipart file upload. Document is chunked and indexed in ChromaDB.

Response: `DocumentResponse` with `{id, project_id, filename, filetype, size_bytes, chunk_count, created_at, indexed_at}`

---

## Wiki

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/projects/{project_id}/wiki` | List wiki pages |
| `POST` | `/api/projects/{project_id}/wiki` | Create wiki page |
| `GET` | `/api/projects/{project_id}/wiki/{page_id}` | Get wiki page |
| `PUT` | `/api/projects/{project_id}/wiki/{page_id}` | Update wiki page |

**POST /api/projects/{project_id}/wiki**
```json
{
  "title": "string (required)",
  "content": "string (Markdown, required)",
  "tags": ["string"]
}
```

---

## Sessions

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/sessions` | List all sessions |
| `GET` | `/api/sessions/{chat_id}` | Get session messages |
| `DELETE` | `/api/sessions/{chat_id}` | Clear/archive session |
| `GET` | `/api/sessions/search/messages` | Search across messages |

**GET /api/sessions**
- Query params: `prefix` (filter by chat ID prefix)
- Response: `[{chat_id, updated_at, message_count, path}]`

**GET /api/sessions/{chat_id}**
- Query params: `limit` (default: 50)
- Response: `{chat_id, messages: [], count}`

**GET /api/sessions/search/messages**
- Query params: `q` (search query), `project_id`, `limit` (default: 20)
- Response: `[{message_id, chat_id, role, content, snippet, created_at}]`

---

## Chats

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/chats` | Create chat session |
| `GET` | `/api/chats` | List chat sessions |
| `GET` | `/api/chats/{chat_id}` | Get chat with messages |
| `POST` | `/api/chats/{chat_id}/messages` | Add message to chat |

---

## Settings

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/settings` | Get all app settings |
| `PUT` | `/api/settings` | Save all app settings |
| `GET` | `/api/settings/personality/preview` | Preview personality files |
| `GET` | `/api/settings/personality/files/{filename}` | Read personality file |
| `PUT` | `/api/settings/personality/files/{filename}` | Write personality file |
| `POST` | `/api/settings/personality/files/{filename}/reset` | Reset to default |

---

## GitHub Integration

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/github/status` | Check GitHub auth status |
| `POST` | `/api/github/token` | Save GitHub token |
| `DELETE` | `/api/github/token` | Delete GitHub token |
| `GET` | `/api/github/validate/{owner}/{repo}` | Validate repo exists |
| `POST` | `/api/github/clone` | Clone repository |
| `GET` | `/api/github/repo/{owner}/{repo}` | Get repo info |
| `GET` | `/api/github/repo/{owner}/{repo}/issues` | List repo issues |
| `GET` | `/api/github/repo/{owner}/{repo}/pulls` | List repo PRs |
| `GET` | `/api/github/repo/{owner}/{repo}/status` | Get repo CI/status |

---

## AI Operations

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/projects/{project_id}/standup` | Generate AI standup report |
| `POST` | `/api/projects/{project_id}/brief` | Generate AI project brief (Opus) |
| `POST` | `/api/projects/{project_id}/health` | AI project health check |
| `POST` | `/api/projects/{project_id}/prioritize` | AI card prioritization |
| `POST` | `/api/code/review` | AI code review |

**POST /api/code/review**
```json
{
  "code": "string (required)",
  "language": "string",
  "context": "string",
  "project_id": "string"
}
```

---

## Jobs (Scheduler)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/jobs` | List all jobs |
| `POST` | `/api/jobs` | Create job |
| `PUT` | `/api/jobs/{job_id}` | Update job |
| `DELETE` | `/api/jobs/{job_id}` | Delete job |
| `POST` | `/api/jobs/{job_id}/run` | Trigger job immediately |

**Job types:** `reminder`, `github_sync`, `rag_index`, `custom`

**POST /api/jobs**
```json
{
  "name": "string (required)",
  "type": "reminder|github_sync|rag_index|custom (required)",
  "cron": "cron expression (required)",
  "enabled": true,
  "config": {}
}
```

---

## Focus Sessions

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/focus-sessions` | Create focus session |
| `GET` | `/api/projects/{project_id}/focus` | Get project focus analytics |

---

## Tech Detection

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/tech/detect` | Detect tech stack from path |

Query params: `project_path` (filesystem path)

---

## Health

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/health` | System health status |
| `GET` | `/api/health/services` | Detailed service health |

Response: `{status, scheduler_running, services: {claude_proxy, chromadb, ...}}`

---

## MCP

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/mcp/sse` | MCP SSE transport (web clients) |
| `POST` | `/mcp/messages` | MCP message handler |
| `GET` | `/mcp/tools` | List MCP tools |
| `GET` | `/mcp/status` | MCP server status |

---

## WebSocket

| Endpoint | Purpose |
|----------|---------|
| `ws://localhost:8000/ws` | Main WebSocket for chat + events |

See `docs/SYSTEM.md` for WebSocket message types.

---

_Every endpoint documented. No omissions._
