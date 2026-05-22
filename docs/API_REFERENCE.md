# API REFERENCE — Every Endpoint

> Complete REST API reference for Voxyflow. Grouped by resource.

---

## Cards

### Workspace Cards

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/workspaces/{workspace_id}/cards` | Create a card in a workspace |
| `GET` | `/api/workspaces/{workspace_id}/cards` | List all cards for a workspace |

**POST /api/workspaces/{workspace_id}/cards**
```json
// Request
{
  "title": "string (required)",
  "description": "string",
  "status": "card|todo|in-progress|done (default: card)",
  "priority": "0-4 (default: 0)",
  "color": "yellow|blue|green|pink|purple|orange",
  "agent_type": "general|researcher|coder|designer|architect|writer|qa",
  "agent_context": "string",
  "recurrence": "daily|weekly|monthly",
  "recurrence_next": "ISO date string",
  "dependency_ids": ["card_id_1", "card_id_2"]
}
// Response: CardResponse (see DATA_MODEL.md)
```

**GET /api/workspaces/{workspace_id}/cards**
- Query params: `status` (filter), `agent_type` (filter)
- Response: `CardResponse[]`

### Home Cards (legacy "unassigned" path)

These endpoints proxy to the system Home workspace (`workspace_id="system-main"`).

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
| `PATCH` | `/api/cards/{card_id}/assign/{workspace_id}` | Move card to a workspace |
| `PATCH` | `/api/cards/{card_id}/unassign` | Move card back to Home (system workspace) |
| `POST` | `/api/cards/{card_id}/duplicate` | Duplicate card in same workspace |
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

## Workspaces

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/workspaces` | Create workspace |
| `GET` | `/api/workspaces` | List all workspaces |
| `GET` | `/api/workspaces/{workspace_id}` | Get workspace with cards |
| `PATCH` | `/api/workspaces/{workspace_id}` | Update workspace |
| `DELETE` | `/api/workspaces/{workspace_id}` | Delete workspace (irreversible) |
| `POST` | `/api/workspaces/{workspace_id}/archive` | Archive workspace |
| `POST` | `/api/workspaces/{workspace_id}/restore` | Restore archived workspace |
| `GET` | `/api/workspaces/{workspace_id}/export` | Export workspace as JSON |
| `POST` | `/api/workspaces/import` | Import workspace from JSON |
| `GET` | `/api/workspaces/templates` | List workspace templates |
| `POST` | `/api/workspaces/from-template/{template_id}` | Create from template |

**POST /api/workspaces**
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

**GET /api/workspaces**
- Query params: `status` (active|archived), `archived` (bool)
- Response: `WorkspaceResponse[]`

**Templates:** software, research, content, bugfix, launch

---

## Documents

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/workspaces/{workspace_id}/documents` | Upload document (multipart) |
| `GET` | `/api/workspaces/{workspace_id}/documents` | List workspace documents |
| `DELETE` | `/api/workspaces/{workspace_id}/documents/{document_id}` | Delete document |

**POST** accepts multipart file upload. Document is chunked and indexed in ChromaDB.

Response: `DocumentResponse` with `{id, workspace_id, filename, filetype, size_bytes, chunk_count, created_at, indexed_at}`

---

## Wiki

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/workspaces/{workspace_id}/wiki` | List wiki pages |
| `POST` | `/api/workspaces/{workspace_id}/wiki` | Create wiki page |
| `GET` | `/api/workspaces/{workspace_id}/wiki/{page_id}` | Get wiki page |
| `PUT` | `/api/workspaces/{workspace_id}/wiki/{page_id}` | Update wiki page |

**POST /api/workspaces/{workspace_id}/wiki**
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
- Query params: `q` (search query), `workspace_id`, `limit` (default: 20)
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
| `POST` | `/api/workspaces/{workspace_id}/standup` | Generate AI standup report |
| `POST` | `/api/workspaces/{workspace_id}/brief` | Generate AI workspace brief (Opus) |
| `POST` | `/api/workspaces/{workspace_id}/health` | AI workspace health check |
| `POST` | `/api/workspaces/{workspace_id}/prioritize` | AI card prioritization |
| `POST` | `/api/code/review` | AI code review |

**POST /api/code/review**
```json
{
  "code": "string (required)",
  "language": "string",
  "context": "string",
  "workspace_id": "string"
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

**Job types:** `agent_task`, `execute_card`, `execute_board`, `reminder`, `rag_index`

**POST /api/jobs**
```json
{
  "name": "string (required)",
  "type": "agent_task|execute_card|execute_board|reminder|rag_index (required)",
  "schedule": "cron expression or shorthand (required)",
  "enabled": true,
  "payload": {}
}
```

---

## Focus Sessions

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/focus-sessions` | Create focus session |
| `GET` | `/api/workspaces/{workspace_id}/focus` | Get workspace focus analytics |

---

## Tech Detection

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/tech/detect` | Detect tech stack from path |

Query params: `workspace_path` (filesystem path)

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
