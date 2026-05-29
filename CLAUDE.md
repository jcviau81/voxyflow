# Voxyflow — Workspace Context

## Architecture
Kanban + AI execution engine. Python/FastAPI backend, React frontend.
- **Backend**: `backend/app/` — services, routes, tools, MCP server
- **Frontend**: `frontend-react/src/` — React + Vite

## LLM Backend — Multi-Provider Architecture (May 2026)

Voxyflow supports multiple LLM backends through a provider abstraction layer.
Each layer (Fast/Deep) can independently use any provider via Settings UI or `backend/.env`.

### Provider Abstraction
- **Base class**: `backend/app/services/llm/providers/base.py` — `LLMProvider` ABC with `complete()`, `stream()`, `get_capabilities()`, `list_models()`
- **Factory**: `backend/app/services/llm/provider_factory.py` — `get_provider(provider_type, url, api_key)` with instance caching
- **Capability registry**: `backend/app/services/llm/capability_registry.py` — static database of 80+ models with tool-use, vision, context window flags; longest-prefix matching
- **Supported provider types**: `cli`, `codex`, `anthropic`, `openai`, `openrouter`, `ollama`, `groq`, `mistral`, `gemini`, `lmstudio`

### 1. Claude CLI Subprocess (`provider_type: "cli"` or `CLAUDE_USE_CLI=true`)
Spawns `claude -p` subprocesses. Uses Claude Max subscription directly.
- **File**: `backend/app/services/llm/cli_backend.py`
- Chat layers: streaming via `--output-format stream-json`, MCP tools for inline ops
- Workers: non-streaming with `--mcp-config` for full Voxyflow MCP tool access
- Delegates: `voxyflow.delegate` MCP tool_use (native tool call, no XML markup)
- Personality mode: `native_tools="claude_cli_mcp"` in personality_service.py
- Permissions: `--permission-mode bypassPermissions` (MCP tools are our own REST API)
- `--strict-mcp-config` prevents Claude Code's own MCP servers from polluting context
- **Rate gate**: `CliRateGate` in cli_backend.py — dual-semaphore concurrency limiter. Session (dispatcher/chat) and worker CLI calls have independent semaphores so workers never starve interactive chat. Configured via `CLI_SESSION_CONCURRENT` (default 5), `CLI_WORKER_CONCURRENT` (default 15), and `CLI_MIN_SPACING_MS` (default 0). Applied to all Claude CLI entry points.

### 2. Codex CLI Subprocess (`provider_type: "codex"`)
Spawns `codex exec --json` subprocesses. Uses the local Codex CLI login and can be selected for Fast dispatcher, Deep dispatcher, and worker classes.
- **File**: `backend/app/services/llm/codex_backend.py`
- Provider metadata: `backend/app/services/llm/providers/codex.py`
- Prompt input: stdin; output parsing: Codex JSONL events (`thread.started`, `turn.completed.usage`, `item.completed`, `mcp_tool_call`, `command_execution`, `turn.failed`)
- MCP loading: per-call `-c mcp_servers.*` overrides; never mutates `~/.codex/config.toml`
- Personality mode: `native_tools="codex_mcp"`
- Dispatcher MCP role: `dispatcher_codex`, backed by `TOOLS_DISPATCHER_CODEX` (same inline tools as the Claude dispatcher; the role stays separate only for the Codex-specific prompt)
- Worker lifecycle fallback: fenced JSON blocks `voxyflow_worker_claim` and `voxyflow_worker_complete`
- Capacity handling: detects `Selected model is at capacity`, dedupes repeated errors, and retries fallback models (`gpt-5.4-mini`, `gpt-5.3-codex`, `gpt-5.4`, `gpt-5.5`, `gpt-5.2`)

### 3. Native Anthropic SDK (`provider_type: "anthropic"` or `CLAUDE_USE_NATIVE=true`)
Direct API calls via `anthropic` Python SDK. Requires API key.
- **File**: `backend/app/services/llm/providers/anthropic_provider.py`
- Uses `delegate_action` tool_use for dispatching (native tool blocks)
- Prompt caching via `cache_control: {type: ephemeral}`
- Converts OpenAI-format tool defs to Anthropic format automatically

### 4. OpenAI-Compatible Providers (`provider_type: "openai" | "openrouter" | "groq" | "mistral" | "gemini" | "lmstudio"`)
Any endpoint speaking the OpenAI chat/completions API.
- **File**: `backend/app/services/llm/providers/openai_compat.py`
- Cloud: OpenAI, Groq, Mistral AI, Google Gemini (each with default URLs in factory)
- Local: LM Studio (localhost:1234), any custom OpenAI-compat server

### 5. Ollama (`provider_type: "ollama"`)
Extends OpenAI-compat with Ollama-specific features.
- **File**: `backend/app/services/llm/providers/ollama.py`
- Native model listing via `/api/tags` (with 10s TTL cache)
- Auto-normalises base URL (adds `/v1` for OpenAI-compat calls)

### Named Endpoints ("My Machines")
Users can save named LLM endpoints (local or remote machines) in Settings.
- Stored as `ProviderEndpoint` in `ModelsSettings.endpoints[]` (id, name, provider_type, url, api_key)
- Layers reference endpoints by `endpoint_id` — resolved dynamically at call time via `_resolve_endpoint_refs()`
- Reachability probed in parallel on `/api/models/available`

### Model Discovery API (`/api/models/`)
- `GET /providers` — list all supported provider types with metadata
- `GET /list?provider_type=X&url=Y` or `GET /list?endpoint_id=Z` — dynamic model listing per provider
- `GET /capabilities?model=X` — capability lookup from static registry
- `GET /available` — current layer config + live reachability probes (30s TTL cache)
- `POST /test` — send a ping to any provider/model, returns latency + reply

### API Key Security
- `GET /api/settings` redacts `api_key` fields to `***` via `_redact_sensitive()`
- `PUT /api/settings` preserves real keys when frontend sends `***` via `_merge_sensitive_on_save()`
- `_get_api_key_from_settings()` guards against the `***` sentinel leaking into runtime
- API keys are never sent in GET query params — resolved server-side from saved endpoints

## Key Files
- `backend/app/services/claude_service.py` — historical LLM orchestration singleton; dispatcher layers and worker classes resolve providers via `reload_models()` / provider_factory
- `backend/app/services/llm/api_caller.py` — ApiCallerMixin, dispatch hub (`_call_api`, `_call_api_stream`)
- `backend/app/services/llm/cli_backend.py` — ClaudeCliBackend (Claude CLI subprocess management)
- `backend/app/services/llm/codex_backend.py` — CodexCliBackend (Codex CLI subprocess management)
- `backend/app/services/llm/providers/codex.py` — Codex provider metadata/listing
- `backend/app/services/llm/client_factory.py` — SDK client creation
- `backend/app/services/llm/provider_factory.py` — `get_provider()` factory, `infer_provider_type()`, provider instance cache
- `backend/app/services/llm/capability_registry.py` — Static model capability registry (80+ models), prefix matching, `lru_cache`
- `backend/app/services/llm/providers/base.py` — `LLMProvider` ABC, `CompletionRequest`, `CompletionResponse`
- `backend/app/services/llm/providers/openai_compat.py` — OpenAI-compatible provider (also used by Groq, Mistral, Gemini, LM Studio)
- `backend/app/services/llm/providers/ollama.py` — Ollama provider (extends OpenAI-compat + native `/api/tags`)
- `backend/app/services/llm/providers/anthropic_provider.py` — Native Anthropic SDK provider
- `backend/app/services/personality_service.py` — System prompts, delegate modes, Claude/Codex MCP personalities
- `backend/app/services/chat_orchestration.py` — Orchestrator, delegate parsing
- `backend/app/routes/models.py` — Model discovery API (`/providers`, `/list`, `/capabilities`, `/available`, `/test`)
- `backend/app/routes/settings.py` — Settings CRUD, `ProviderEndpoint` model, API key redaction
- `backend/app/mcp_server.py` — MCP tool definitions (100+ definitions; filtered by role)
- `backend/app/tools/registry.py` — `TOOLS_DISPATCHER` / `TOOLS_DISPATCHER_CODEX` / `TOOLS_WORKER` sets, role-based filtering
- `backend/app/services/knowledge_graph_service.py` — Temporal KG (entities, triples, attributes)
- `backend/mcp_stdio.py` — MCP stdio transport entry point
- `backend/app/config.py` — Settings (env vars + keyring)
- `frontend-react/src/components/Settings/ModelPanel.tsx` — Models & Machines settings UI (machine cards, layer config, capability badges)

## Knowledge Graph — Temporal Model
The KG stores entities (persistent, not temporal) linked by **triples** (relationships)
and **attributes** (key-value properties), both with temporal bounds:

- `valid_from` (NOT NULL) — when the fact became true (set on INSERT)
- `valid_to` (NULL = active) — when the fact ended (set by `kg.invalidate`)

The pair forms a half-open interval **[valid_from, valid_to)**:
- `valid_to IS NULL` → fact is **current** (returned by `kg.query`, counted by `kg.stats`)
- `valid_to` set → fact is **historical** (only visible in `kg.timeline`)

To update a fact (e.g. "Redis version changed from 6 to 7"), invalidate the old
attribute and add a new one — this preserves the audit trail. `kg.timeline` shows
the full history; `kg.query` shows only the present state.

Memory context injection uses three tiers with token budgets:
- **L0** — pinned KG entities (attributes with `key='pinned', value='true'`)
- **L1** — high-importance ChromaDB memories
- **L2** — full semantic search (current behavior)

## Tool Access Architecture — Dispatcher vs Worker

**This is a hard boundary.** Tool access is determined by role, not by model tier. Fast and deep dispatchers normally get the same dispatcher tools; the model choice only changes reasoning/cost. Codex dispatchers use a distinct `dispatcher_codex` role, but it now carries the **same inline toolset** as the Claude dispatcher (it was formerly read-only, which made Codex spawn workers for trivial CRUD); the role stays separate only so the Codex prompt can differ. Workers run in background subprocesses and get full MCP tool access.

### Dispatcher (fast + deep chat) — `TOOLS_DISPATCHER`
Lightweight, non-blocking tools only. The dispatcher streams responses to the user
and must never block on heavy operations.

**Allowed:** read ops (`workspace.list/get`, `card.list/get`, `wiki.list/get`, `doc.list`,
`jobs.list`, `health`), full kanban CRUD on cards/workspaces/wiki including row-level
sub-resources (`card.checklist.*`, `card.relation.*`, `card.time.*`), worker
monitoring (`workers.list/get_result/read_artifact`, `task.peek/cancel`), memory
(`memory.search/save/get/delete`, `knowledge.search`), and whole-entity deletes
(`workspace.delete`, `workspace.export`, `card.delete`, `doc.delete`, `wiki.delete`).
Single-user deployment + the undo journal (`voxyflow.undo.*`) makes inline delete
safe — the user is always present and reversals are one tool-call away.

**NOT allowed:** `system.exec`, `file.*`, `git.*`, `tmux.*`, `web.*`,
`voxyflow.ai.*`, `voxyflow.card.enrich` (heavy AI), worker lifecycle
(`worker.claim/complete`), `tools.load`.
These are worker-only. (Notes: `task.steer` IS dispatcher-allowed — it pairs
with `task.peek`/`task.cancel` for worker control. `kg.*` is dispatcher-allowed
too — temporal model is local + reversible, no reason to spawn a worker.)

### Codex Dispatcher — `TOOLS_DISPATCHER_CODEX`
`TOOLS_DISPATCHER_CODEX = set(TOOLS_DISPATCHER)` — the Codex dispatcher gets the **same inline tools** as the Claude dispatcher (full kanban/memory/KG CRUD incl. row-level sub-resources and deletes, worker monitoring + `ack_artifact`, `task.peek`, `voxyflow.delegate`). It was formerly a read-only subset, but that made Codex spawn a worker for trivial ops (e.g. "clean up the cards" → delegate a worker to delete cards). The Codex prompt (`_build_codex_mcp_delegate_instructions`) steers it to do instant/local CRUD inline (single-user DB + undo journal make that safe) and delegate only subprocess/heavy work. The role stays separate so the Codex prompt — fenced-fallback handling, `voxyflow.workers` action surface — can differ.

### Worker — `TOOLS_WORKER`
Full MCP tool access. Workers run as background subprocesses spawned via
`delegate_action`. They can exec commands, read/write files, search the web,
manage git, use tmux, call AI features, and perform destructive operations.

### Deployment scope — `system.exec` and the broader worker toolset
Voxyflow is designed as a **single-user, local install**. `system.exec`, `file.*`,
`git.*`, and `tmux.*` all run with the full privileges of the OS user running the
backend process; there is no per-user sandbox and no command allow-list. This is
intentional — the user *is* the operator — but it means:

- Do not expose the backend to untrusted networks or share it across users.
- Do not treat a Voxyflow worker as a security boundary. A prompt-injected worker
  can do anything the OS user can do.
- Multi-tenant / shared-deployment mode is **out of scope**. If that becomes a
  goal, `system.exec` + friends need a real sandbox (e.g. per-workspace container,
  command allow-list, FS chroot) before they can be safely exposed.

### Key files
- `backend/app/tools/registry.py` — `TOOLS_DISPATCHER`, `TOOLS_DISPATCHER_CODEX`, and `TOOLS_WORKER` sets, `_ROLE_TOOL_SETS`
- `backend/app/services/llm/tool_defs.py` — `get_claude_tools(role=...)` for native SDK path
- `backend/app/tools/prompt_builder.py` — `build_tool_prompt(role=...)` for CLI path

### Invariant
When adding new tools: add to `TOOLS_WORKER` in `registry.py`. Only add to `TOOLS_DISPATCHER` if the tool is instant, non-blocking, and safe for inline chat. Only add to `TOOLS_DISPATCHER_CODEX` if it is read-only and helps a dispatcher decide whether to delegate. Never gate tools on model tier (fast/deep); use role sets instead.

## Dispatcher Flow
1. User message → `chat_fast_stream()` or `chat_deep_stream()` (model selection only)
2. System prompt built (personality + dispatcher + delegate instructions)
3. Provider path runs the selected dispatcher model (`claude -p`, `codex exec --json`, or API provider) with the matching dispatcher tool role
4. Model responds conversationally + calls allowed dispatcher tools inline + calls `voxyflow.delegate` for complex/action tasks
5. Orchestrator collects `voxyflow.delegate` tool_use calls → spawns workers (with full `TOOLS_WORKER` access)

## Dev Restart
Backend runs via systemd (uvicorn on port 8000), frontend built with Vite and served via a reverse proxy.

Example startup script pattern:
```bash
git pull
systemctl --user restart voxyflow-backend
cd frontend-react && npm run build
```

## Infrastructure
- **Backend**: systemd user service `voxyflow-backend.service` (uvicorn on port 8000)
- **Frontend**: Vite build served by Caddy reverse proxy
- **Caddy**: system service (`/etc/caddy/Caddyfile`), proxies `/api/*`, `/ws`, `/ws/*` to backend, serves static frontend
- **Linger**: enabled for the deploy user so user services start at boot without login

## .env (example)
```
CLAUDE_USE_CLI=true
CLAUDE_FAST_MODEL=claude-haiku-4-5-20251001
CLAUDE_SONNET_MODEL=claude-sonnet-4-6
CLAUDE_DEEP_MODEL=claude-opus-4-7
CLI_SESSION_CONCURRENT=5
CLI_WORKER_CONCURRENT=15
CLI_MIN_SPACING_MS=0
MAX_WORKERS=15
```

---

## Workspace Isolation

Invariants to preserve when touching memory, MCP tools, or chat routing. Regressions here leak context across workspaces.

### 1. ChromaDB collections keyed by `workspace_id` (UUID)
- Memory store lives in `~/.voxyflow/chroma/`
- Per-workspace: `memory-workspace-{workspace_id}` — `workspace_id` is the **UUID**, never the title/slug
- Global cross-workspace: `memory-global` (constant `GLOBAL_COLLECTION` in `backend/app/services/memory_service.py`) — reserved for the **general/main chat only**
- System / general chat (no workspace) uses pseudo-workspace `system-main` → collection `memory-workspace-system-main`
- Slugs change on rename and orphan data — **never** use them as collection keys

### 1a. STRICT: workspace chats never query `memory-global`
- `memory_service._build_chromadb_context` Workspace Chat & Card Chat modes query the per-workspace collection ONLY. Do not add `GLOBAL_COLLECTION` to those branches.
- `mcp_server.memory_search` handler: when `VOXYFLOW_WORKSPACE_ID` is a real workspace UUID → `collections=[_workspace_collection(pid)]`. Global is added **only** when env is empty / `system-main`.
- `mcp_server.memory_search` handler mirrors the same rule (single implementation, no duplication).
- **Why:** `memory-global` holds cross-bot imports / user-globals that the user explicitly wants kept out of workspace work. A clean workspace must show zero knowledge from other contexts.
- **Regression guard:** `backend/scripts/smoke_test_isolation.py` test `_build_chromadb_context — Workspace Chat mode never queries memory-global` will fail if this is broken.

### 2. `search_memory()` requires explicit collections
- `backend/app/services/memory_service.py` — `search_memory()` raises `ValueError` if `collections=` is omitted. No silent fallback.
- Callers must pass the collections they want.
- `build_memory_context(workspace_id=...)` is the high-level helper — it picks the right collections based on `workspace_id`.

### 3. MCP tools auto-scope via env var
- MCP subprocess inherits `VOXYFLOW_WORKSPACE_ID` from the local CLI backend MCP builder (`cli_backend._build_mcp_config(...)` for Claude CLI, `codex_backend._build_mcp_config_args(...)` for Codex CLI)
- Handlers in `backend/app/mcp_server.py` (`memory_search`, `memory_save`, `knowledge_search`) read `os.environ.get("VOXYFLOW_WORKSPACE_ID", "")` and scope automatically
- MCP tool schemas do **not** expose `workspace_id` — Voxy cannot override it. Scoping is enforced by the runtime, not by the LLM.
- Empty / missing env → falls back to `system-main` (general chat behavior)

### 4. `chat_id` is server-canonical, not client-trusted
- `backend/app/main.py` derives the canonical `chat_id` from server-side `workspace_id` / `card_id`:
  - card → `card:{card_id}`
  - workspace → `workspace:{workspace_id}`
  - general → `workspace:{SYSTEM_MAIN_WORKSPACE_ID}`
- Frontend-supplied `chatId` is accepted only if it equals the canonical id or starts with `canonical + ":"` (sub-sessions). Otherwise logged as `[WS] Rejected mismatched chatId=...` and replaced.
- Prevents a stale or malicious frontend from steering chat into the wrong session.

### 5. When you add a new tool / new chat path
- Tool touches memory or per-workspace data → **never** require the LLM to pass `workspace_id` as an arg. Read it from `os.environ["VOXYFLOW_WORKSPACE_ID"]` in the handler.
- New local CLI entrypoint → thread `workspace_id` through the provider's MCP config builder (`cli_backend` or `codex_backend`)
- New chat handler in `main.py` → derive `chat_id` from server-side ids, do not echo the frontend's `chatId` blindly

### 6. Drift detection
- `cli_backend.stream_persistent` logs `[CLI-persistent] WORKSPACE_ID DRIFT: ...` if a persistent chat process is reused with a different `workspace_id` than it was spawned with. If you see this in logs, something upstream is wrong.
