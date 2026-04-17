# TOOLS — Tool Registry & Execution

> Every tool registered in Voxyflow, how they're called, and who can use them.

---

## Tool Categories

Voxyflow exposes ~100 MCP tools defined in `backend/app/mcp_server.py`. Broad grouping:

| Category | Prefix | Purpose |
|----------|--------|---------|
| voxyflow | `voxyflow.*` | Cards, projects, wiki, docs, jobs, AI ops, worker lifecycle, session/ledger |
| memory | `memory.*` | Long-term memory search/save/delete/get |
| knowledge | `knowledge.*` | RAG knowledge base search |
| kg | `kg.*` | Knowledge-graph triples/attributes (worker-only) |
| task | `task.*` | Worker supervision + legacy `task.complete` |
| system | `system.*` | Shell command execution (worker-only) |
| web | `web.*` | Web search / page fetching (worker-only) |
| file | `file.*` | Filesystem read/write/patch/list (worker-only) |
| git | `git.*` | Git operations (worker-only) |
| tmux | `tmux.*` | Terminal multiplexer (worker-only) |
| tools | `tools.*` | Dynamic tool loader (worker-only) |

Counts drift as tools are added — the source of truth is `_TOOL_DEFINITIONS` in
`backend/app/mcp_server.py` and the role sets in `backend/app/tools/registry.py`.

---

## Role-Based Access Control

Tool access is gated by **role**, not by model tier. Fast and Deep dispatchers
get the **same** tool set — the Haiku vs Opus choice is purely model selection.
Workers run in background subprocesses and get the full MCP surface.

| Role | Access | What it can do |
|------|--------|----------------|
| **Dispatcher** (fast + deep chat) | `TOOLS_DISPATCHER` | Read ops, basic card/project CRUD, memory search/save, worker monitoring. Never blocks. |
| **Worker** | `TOOLS_WORKER` (= dispatcher + everything else) | Exec, file/git/tmux, web, AI ops, destructive deletes, worker lifecycle. |

Source of truth: `TOOLS_DISPATCHER` / `TOOLS_WORKER` in
`backend/app/tools/registry.py`. The invariant (enforced by
`backend/tests/test_tool_role_boundary.py`): dispatcher is a strict subset of
worker, and none of `system.exec`, `file.write`, `file.patch`, `git.commit`,
`web.*`, `tmux.run/send/new/kill`, `memory.delete`, `kg.invalidate`, `task.steer`,
or any `*.delete` / `*.export` may leak into the dispatcher set.

### Dispatcher surface (high-level)

Read: `health`, `project.list/get`, `card.list/get/list_unassigned/list_archived`,
`wiki.list/get`, `doc.list`, `jobs.list`, `heartbeat.read/write`, `memory.search`,
`knowledge.search`, `workers.list/get_result/read_artifact`.
Create/update: `card.create/update/move/archive/create_unassigned`,
`project.create`, `memory.save`, `jobs.create/update/delete`.

### Worker-only (representative)

`system.exec`, `file.*`, `git.*`, `tmux.*`, `web.*`, `kg.*`, `voxyflow.ai.*`,
`voxyflow.worker.claim`, `voxyflow.worker.complete`, `task.complete` (legacy),
`task.steer`, `tools.load`, destructive `*.delete` and `voxyflow.project.export`.

---

## Complete Tool Reference

### Voxyflow — Card Operations

#### voxyflow.card.create_unassigned
Create a card in the Home project (`project_id="system-main"`). Legacy "unassigned" name kept for back-compat.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| content | string | yes | Title/text content |
| color | string | no | yellow, blue, green, pink, purple, orange |
| description | string | no | Longer description/body |

#### voxyflow.card.list_unassigned
List all cards in the Home project. No parameters.

#### voxyflow.card.create
Create a card in a project.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |
| title | string | yes | Card title |
| description | string | no | Card description |
| status | string | no | card, todo, in-progress, done (default: card) |
| priority | integer | no | 0=none, 1=low, 2=medium, 3=high, 4=critical |
| agent_type | string | no | general, researcher, coder, designer, architect, writer, qa |

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
| status | string | no | card, todo, in-progress, done, archived |

#### voxyflow.card.move
Move a card to a different kanban column.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |
| new_status | string | yes | card, todo, in-progress, done, archived |

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

#### voxyflow.card.archive
Archive a card (soft-delete). Card is hidden but recoverable.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |

#### voxyflow.card.enrich
AI-enrich a card with better description, tags, and acceptance criteria.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |

#### voxyflow.card.checklist.add
Add a single checklist item to a card.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |
| text | string | yes | Checklist item text |

#### voxyflow.card.checklist.add_bulk
Add multiple checklist items to a card in one call.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |
| items | array | yes | List of checklist item texts |

#### voxyflow.card.checklist.list
List all checklist items for a card.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |

#### voxyflow.card.checklist.update
Update a checklist item (toggle completed or edit text).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |
| item_id | string | yes | Checklist item ID |
| text | string | no | New text |
| completed | boolean | no | Toggle completion |

#### voxyflow.card.checklist.delete
Delete a checklist item.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| card_id | string | yes | Card ID |
| item_id | string | yes | Checklist item ID |

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

#### voxyflow.project.update
Update a project's fields (title, description, status, context, github_url, etc).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |
| title | string | no | New title |
| description | string | no | New description |
| status | string | no | active, archived |
| context | string | no | Project context for AI |
| github_url | string | no | GitHub URL |

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
| type | string | yes | agent_task, execute_card, execute_board, reminder, rag_index, github_sync, custom (board_run is a legacy alias for execute_board) |
| schedule | string | yes | Cron expression (e.g. '0 9 * * 1-5') or interval ('every_5min', 'every_1h') |
| enabled | boolean | no | Whether enabled (default: true) |
| payload | object | no | Job-specific configuration |

#### voxyflow.jobs.update
Update an existing scheduled job. Pass only the fields to change.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | string | yes | ID of the job to update |
| name | string | no | New job name |
| type | string | no | New job type |
| schedule | string | no | New cron expression or interval |
| enabled | boolean | no | Enable or disable the job |
| payload | object | no | New job-specific configuration |

#### voxyflow.jobs.delete
Delete a scheduled job permanently. Requires confirmation.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| job_id | string | yes | ID of the job to delete |

#### voxyflow.sessions.list
List active CLI subprocess sessions (chat and worker processes).
No parameters.

#### voxyflow.workers.list
List recent worker tasks from the Worker Ledger. Auto-scoped to the current
project via `VOXYFLOW_PROJECT_ID`; pass `scope="all"` to cross projects.

#### voxyflow.workers.get_result
Get the full details and result of a specific worker task.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| task_id | string | yes | Worker task ID |

#### voxyflow.workers.read_artifact
Fetch the full artifact (verbatim worker output) written to
`~/.voxyflow/worker_artifacts/{task_id}.md`. Supports paging.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| task_id | string | yes | Worker task ID |
| offset | integer | no | Byte offset into the artifact |
| length | integer | no | Max bytes to return |

---

### Voxyflow — Worker Lifecycle (worker-only)

Workers run a strict three-phase protocol enforced by `WorkerSupervisor` and the
orchestrator's `_tool_callback`. The dispatcher reads the structured completion
payload — not truncated raw text — so Voxy usually does not need to call
`read_artifact` just to understand a result.

```
voxyflow.worker.claim  →  (work with any MCP tools)  →  voxyflow.worker.complete
```

If a worker skips `voxyflow.worker.complete` or emits a malformed one, a
closeout-pass subprocess (`VOXYFLOW_CLOSEOUT_PASS=1`) reads the artifact and
synthesizes a structured completion. A local tier-3 fallback covers the degenerate
case where even the closeout fails. Per-message cap:
`MAX_DISPATCHER_PAYLOAD_CHARS` (15 000); 60 s rolling burst cap per dispatcher
chat via `VOXYFLOW_CALLBACK_BURST_CAP_CHARS` (40 000).

#### voxyflow.worker.claim
**First** tool a worker must call. Declares the plan and flips the supervisor
phase from `spawned` → `claimed`. A watchdog nudges workers that don't claim
within `WORKER_CLAIM_NUDGE_AFTER` (default 5) tool calls.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| task_id | string | yes | The task id injected into the worker prompt |
| plan | string | yes | One- or two-sentence plan the worker intends to execute |

#### voxyflow.worker.complete
**Last** tool a worker must call. Delivers the dispatcher-facing result.
The `summary` is the only text the dispatcher sees by default; findings and
pointers let it fetch detail out-of-band via `read_artifact`.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| task_id | string | yes | Worker task id |
| status | string | yes | `success` \| `partial` \| `failed` |
| summary | string | yes | ≥20 chars, ≤8000. Real prose — not "ok" / "done" |
| findings | string[] | no | Up to 20 short bullets (max 500 chars each) |
| pointers | object[] | no | Up to 20 `{label, offset, length}` pointers into the artifact |
| next_step | string | no | One-line suggestion for the dispatcher (≤500 chars) |

Validation: summary < 20 chars, missing `task_id`, invalid `status`, or
non-list `findings` / `pointers` all return `{success: false, error: ...}`.
Calling `worker.complete` without a prior `worker.claim` logs a warning but
still accepts the completion.

#### task.complete (legacy)
Kept for back-compat. Sets `completion_source="task.complete"`, which does
**not** count as a structured completion — the closeout pass will upgrade it.

---

### Memory & Knowledge Tools

#### memory.search
Semantic search across Voxy's long-term memory (global + project).
Returns `id`, `text`, `score`, `collection` per result, plus pagination metadata (`offset`, `limit`, `count`, `has_more`).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | string | yes | Natural language search query |
| limit | integer | no | Max results per page (default 10) |
| offset | integer | no | Skip first N results for pagination (default 0) |

#### memory.save
Save a fact, decision, preference, or lesson to long-term memory.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| text | string | yes | Information to remember |
| type | string | no | decision, preference, lesson, fact, context (default: fact) |
| importance | string | no | high, medium, low (default: medium) |
| project_id | string | no | Scope memory to a project (default: global) |

#### memory.delete
Delete a specific memory entry by ID.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| id | string | yes | Memory document ID (use memory.search to find it) |
| collection | string | no | Collection name (default: global) |

#### memory.get
List recent chat sessions with title, last message, and message count.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| limit | integer | no | Number of sessions to return (default 10, max 50) |

#### knowledge.search
Search the project knowledge base (RAG) for relevant context.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| project_id | string | yes | Project ID |
| query | string | yes | Search query |

---

### Task Supervision Tools

#### voxyflow.task.peek
Monitor a running worker task in real time (tools called, duration, status).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| task_id | string | yes | Worker task ID |

#### voxyflow.task.cancel
Cancel a running worker task immediately.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| task_id | string | yes | Worker task ID |

#### task.steer
Inject a steering message into a running worker task to redirect it mid-execution.
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| task_id | string | yes | Worker task ID |
| message | string | yes | Steering instruction to inject |

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

#### file.patch
Replace exact text in a file (surgical edit).
| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| path | string | yes | File path |
| old_text | string | yes | Text to find |
| new_text | string | yes | Replacement text |

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

## How Tools Work — CLI + MCP Architecture

The dispatcher (chat layer) runs as a `claude -p` CLI subprocess with MCP tools
loaded via `--mcp-config`. The CLI handles the tool loop internally:

1. **Model generates tool_use** — the CLI detects structured tool_use blocks
2. **CLI calls MCP server** — Voxyflow's stdio MCP server (`backend/mcp_stdio.py`)
   handles the call, routing to either HTTP REST API or async handler
3. **MCP returns result** — the CLI injects the tool_result back into the conversation
4. **Model continues** — generates text response or calls another tool

### Stream Parsing

The CLI emits newline-delimited JSON events. The stream parser in
`cli_backend.py` captures:
- `stream_event` → `content_block_delta` → `text_delta` (real-time streaming)
- `assistant` messages with `text` blocks (MCP tool-use path, non-streamed)
- `result` event (final text, usage stats)

Deduplication: `assistant` text blocks are only forwarded when no `stream_event`
deltas have been received (prevents double text when the CLI streams normally).

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

_66 MCP tools (47 dispatcher + 19 worker-only). See `backend/app/mcp_server.py` for the authoritative list._
