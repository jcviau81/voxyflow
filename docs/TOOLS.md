# TOOLS — Tool Registry & Execution

> Every tool registered in Voxyflow, how they're called, and who can use them.

---

## Tool Categories

Voxyflow tools are organized into 6 categories:

| Category | Prefix | Count | Purpose |
|----------|--------|-------|---------|
| voxyflow | `voxyflow.*` | 22 | Card/project/wiki/doc/job/AI operations |
| system | `system.*` | 1 | Shell command execution |
| web | `web.*` | 2 | Web search and page fetching |
| file | `file.*` | 3 | Filesystem read/write/list |
| git | `git.*` | 5 | Git operations |
| tmux | `tmux.*` | 6 | Terminal multiplexer control |

**Total: ~60 tools** (defined as MCP tools in `backend/app/mcp_server.py`)

---

## Layer Access Control

Not all layers can use all tools:

| Layer | Tool Set | Description |
|-------|----------|-------------|
| **Fast** (Sonnet) | `TOOLS_READ_ONLY` (11 tools) | Read/list/get operations only |
| **Analyzer** (Haiku) | `TOOLS_VOXYFLOW_CRUD` (19 tools) | Read + create/update/move |
| **Deep** (Opus) | `TOOLS_FULL` (30 tools) | Everything including exec, delete, commit |

### TOOLS_READ_ONLY (Fast layer)

```
voxyflow.health
voxyflow.card.list_unassigned
voxyflow.card.list, voxyflow.card.get
voxyflow.project.list, voxyflow.project.get
voxyflow.wiki.list, voxyflow.wiki.get
voxyflow.doc.list
voxyflow.jobs.list
```

### TOOLS_VOXYFLOW_CRUD (Analyzer layer) = READ_ONLY +

```
voxyflow.card.create_unassigned
voxyflow.card.create, voxyflow.card.update, voxyflow.card.move
voxyflow.card.duplicate, voxyflow.card.enrich
voxyflow.project.create
voxyflow.wiki.create, voxyflow.wiki.update
```

### TOOLS_FULL (Deep layer) = CRUD +

```
system.exec
file.write
voxyflow.project.delete, voxyflow.project.export
voxyflow.card.delete
voxyflow.doc.delete
voxyflow.ai.standup, voxyflow.ai.brief, voxyflow.ai.health
voxyflow.ai.prioritize, voxyflow.ai.review_code
voxyflow.jobs.create
git.commit
tmux.run, tmux.send, tmux.new, tmux.kill
```

### Dangerous Tools (require confirmation)

```
system.exec, file.write, git.commit
voxyflow.project.delete, voxyflow.card.delete, voxyflow.doc.delete
tmux.kill
```

---

## Complete Tool Reference

### Voxyflow — Card Operations

#### voxyflow.card.create_unassigned
Create a card on the Main Board (no project).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| content | string | yes | Title/text content |
| color | string | no | yellow, blue, green, pink, purple, orange |
| description | string | no | Longer description/body |

#### voxyflow.card.list_unassigned
List all cards on the Main Board. No parameters.

#### voxyflow.card.create
Create a card in a project.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |
| title | string | yes | Card title |
| description | string | no | Card description |
| status | string | no | idea, todo, in-progress, done (default: idea) |
| priority | integer | no | 0=none, 1=low, 2=medium, 3=high, 4=critical |
| agent_type | string | no | ember, researcher, coder, designer, architect, writer, qa |

#### voxyflow.card.list
List all cards for a project.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |

#### voxyflow.card.get
Get details of a specific card.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |

#### voxyflow.card.update
Update a card's fields.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |
| title | string | no | New title |
| description | string | no | New description |
| priority | integer | no | 0-4 |
| status | string | no | idea, todo, in-progress, done, archived |

#### voxyflow.card.move
Move a card to a different kanban column.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |
| new_status | string | yes | idea, todo, in-progress, done, archived |

#### voxyflow.card.delete
Delete a card (irreversible).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |

#### voxyflow.card.duplicate
Duplicate a card within the same project.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |

#### voxyflow.card.enrich
AI-enrich a card with better description, tags, and acceptance criteria.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |

---

### Voxyflow — Project Operations

#### voxyflow.project.create
Create a new project.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| title | string | yes | Project name |
| description | string | no | Project description |
| tech_stack | string | no | Technology stack (comma-separated) |
| github_url | string | no | GitHub repository URL |
| github_repo | string | no | GitHub repo in owner/repo format |
| local_path | string | no | Local filesystem path |

#### voxyflow.project.list
List all projects. No parameters.

#### voxyflow.project.get
Get project details including cards.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |

#### voxyflow.project.delete
Delete a project and all its cards (irreversible).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |

#### voxyflow.project.export
Export a project as JSON snapshot.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |

---

### Voxyflow — Wiki Operations

#### voxyflow.wiki.list
List all wiki pages for a project.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |

#### voxyflow.wiki.create
Create a new wiki page.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |
| title | string | yes | Page title |
| content | string | yes | Page content (Markdown) |
| tags | array | no | Optional tags |

#### voxyflow.wiki.get
Get wiki page content.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |
| page_id | string | yes | Wiki page ID |

#### voxyflow.wiki.update
Update a wiki page.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |
| page_id | string | yes | Wiki page ID |
| title | string | no | New title |
| content | string | no | New content (Markdown) |
| tags | array | no | Updated tags |

---

### Voxyflow — AI Operations

#### voxyflow.ai.standup
Generate AI daily standup report (done, in-progress, blocked).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |

#### voxyflow.ai.brief
Generate comprehensive AI project brief (uses Opus).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |

#### voxyflow.ai.health
AI project health check — risks, blockers, velocity.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |

#### voxyflow.ai.prioritize
AI smart-prioritize cards by value, complexity, dependencies.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |

#### voxyflow.ai.review_code
AI code review with feedback.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| code | string | yes | Code snippet to review |
| language | string | no | Programming language |
| context | string | no | Additional context |
| project_id | string | no | Optional project context |

---

### Voxyflow — Other

#### voxyflow.health
System health status. No parameters.

#### voxyflow.doc.list
List all documents for a project.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |

#### voxyflow.doc.delete
Delete a document from a project.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| document_id | string | yes | Document ID |

#### voxyflow.jobs.list
List all scheduled jobs. No parameters.

#### voxyflow.jobs.create
Create a new scheduled job.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| name | string | yes | Job name |
| type | string | yes | reminder, github_sync, rag_index, custom |
| cron | string | yes | Cron expression (e.g. '0 9 * * 1-5') |
| enabled | boolean | no | Whether enabled (default: true) |
| config | object | no | Job-specific configuration |

---

### System Tools

#### system.exec
Run a shell command. Returns stdout, stderr, exit_code, duration.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| command | string | yes | Shell command to execute |
| cwd | string | no | Working directory |
| timeout | integer | no | Timeout in seconds (default: 30, max: 300) |

---

### Web Tools

#### web.search
Search the web using Brave Search API.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | string | yes | Search query |
| count | integer | no | Number of results (default: 5, max: 20) |

#### web.fetch
Fetch a web page and extract readable content.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| url | string | yes | URL to fetch |
| max_chars | integer | no | Max characters (default: 5000) |

---

### File Tools

#### file.read
Read a file from the filesystem.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | string | yes | File path |
| offset | integer | no | Start line (1-indexed) |
| limit | integer | no | Max lines to read |

#### file.write
Write content to a file. Creates parent directories.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | string | yes | File path |
| content | string | yes | Content to write |
| mode | string | no | overwrite or append (default: overwrite) |

#### file.list
List files and directories.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | string | yes | Directory path |
| pattern | string | no | Glob pattern (default: '*') |
| recursive | boolean | no | List recursively (default: false) |

---

### Git Tools

#### git.status
Run git status.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | string | no | Git repo path (default: home dir) |

#### git.log
Show recent git commits (oneline format).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | string | no | Git repo path |
| limit | integer | no | Number of commits (default: 20) |

#### git.diff
Show git diff (working tree vs HEAD or staged).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | string | no | Git repo path |
| staged | boolean | no | Show staged changes only (default: false) |

#### git.branches
List all git branches (local and remote).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | string | no | Git repo path |

#### git.commit
Stage all changes and commit.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| message | string | yes | Commit message |
| path | string | no | Git repo path |

---

### Tmux Tools

#### tmux.list
List all tmux sessions. No parameters.

#### tmux.new
Create a new named tmux session.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session | string | yes | Session name |
| command | string | no | Command to run in session |

#### tmux.run
Run a command in a named tmux session (creates if needed).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session | string | yes | Session name |
| command | string | yes | Command to run |

#### tmux.send
Send keys to a tmux pane.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session | string | yes | Session name |
| keys | string | yes | Keys to send |

#### tmux.capture
Capture current output of a tmux pane.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session | string | yes | Session name |

#### tmux.kill
Kill a tmux session.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| session | string | yes | Session name |

---

## How Tools Are Injected Into Prompts

The `ToolPromptBuilder` generates a text block for the system prompt:

```markdown
## Available Tools

You have access to the following tools. To use a tool, include a <tool_call> block.

### Format
<tool_call>
{"name": "tool.name", "arguments": {"param1": "value1"}}
</tool_call>

### Rules
- You can call multiple tools in a single response
- After each tool call, you will receive the result in a <tool_result> block
- Use the result to continue your response or call another tool

### Tools
**voxyflow.card.create** — Create a new card/task in a project.
Parameters:
  - project_id (string, required): Project ID
  - title (string, required): Card title
  ...
```

Tools are filtered by both **layer** and **chat_level** before injection.

---

## How Tool Calls Are Parsed and Executed

### 1. LLM Generates Tool Call

The LLM includes `<tool_call>` blocks in its response text.

### 2. Parser Extracts

`ToolResponseParser.parse(response_text)` uses regex:
```python
r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
```
Returns `(text_content, [ParsedToolCall])` — text without tool blocks, plus structured calls.

### 3. Executor Dispatches

`ToolExecutor.execute(parsed_tool_call)`:
1. Looks up handler in `ToolRegistry`
2. Validates required parameters against JSON Schema
3. Calls handler with `asyncio.wait_for(timeout=30)`
4. Returns result dict `{success, result/error}`

### 4. Result Injected

Tool results are injected back into the conversation as `<tool_result>` blocks, and the LLM continues with the results.

---

## The Delegate Pattern

The **dispatcher** (Fast layer) uses `<delegate>` blocks instead of `<tool_call>`:

```xml
<delegate>
{"action": "create_card", "model": "haiku", "description": "...", "context": "..."}
</delegate>
```

These are parsed by `ChatOrchestrator`, converted to `ActionIntent` objects, and emitted to the `SessionEventBus`. Workers in the `DeepWorkerPool` pick them up and execute them with full tool access.

**Key difference:**
- `<tool_call>` = direct tool execution within the current layer
- `<delegate>` = dispatch to a background worker with its own tool access

> **⚠️ Exception: `model: "direct"` delegates bypass the worker pipeline entirely.**
>
> When a delegate has `model: "direct"`, the `DirectExecutor` calls the MCP tool handler inline — no `ActionIntent` is emitted, no worker is spawned, no LLM is involved. It's atomic CRUD, equivalent to a direct REST API call.
>
> Only delegates with `model: "haiku"` / `"sonnet"` / `"opus"` go through the full `SessionEventBus` → `DeepWorkerPool` → `ClaudeService.execute_worker_task()` pipeline.

---

## MCP Tools

The same tools are exposed via MCP (Model Context Protocol) for external AI clients:

- **SSE transport** — `/mcp/sse` for web clients
- **Stdio transport** — `backend/mcp_stdio.py` for Claude Code, Cursor, etc.

MCP tools are thin HTTP wrappers over the REST API. System tools (`system.exec`, `file.*`, `git.*`, `tmux.*`, `web.*`) execute directly via async handlers without going through REST.

---

_~60 MCP tools. See `backend/app/mcp_server.py` for the authoritative list._
