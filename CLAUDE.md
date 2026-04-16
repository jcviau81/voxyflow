# Voxyflow — Project Context

## Architecture
Kanban + AI execution engine. Python/FastAPI backend, React frontend.
- **Backend**: `backend/app/` — services, routes, tools, MCP server
- **Frontend**: `frontend-react/src/` — React + Vite

## LLM Backend — Multi-Provider Architecture (April 2026)

Voxyflow supports multiple LLM backends through a provider abstraction layer.
Each layer (Fast/Deep) can independently use any provider via Settings UI or `backend/.env`.

### Provider Abstraction
- **Base class**: `backend/app/services/llm/providers/base.py` — `LLMProvider` ABC with `complete()`, `stream()`, `get_capabilities()`, `list_models()`
- **Factory**: `backend/app/services/llm/provider_factory.py` — `get_provider(provider_type, url, api_key)` with instance caching
- **Capability registry**: `backend/app/services/llm/capability_registry.py` — static database of 80+ models with tool-use, vision, context window flags; longest-prefix matching
- **Supported provider types**: `cli`, `anthropic`, `openai`, `ollama`, `groq`, `mistral`, `gemini`, `lmstudio`

### 1. CLI Subprocess (`provider_type: "cli"` or `CLAUDE_USE_CLI=true`) — DEFAULT
Spawns `claude -p` subprocesses. Uses Claude Max subscription directly.
- **File**: `backend/app/services/llm/cli_backend.py`
- Chat layers: streaming via `--output-format stream-json`, MCP tools for inline ops
- Workers: non-streaming with `--mcp-config` for full Voxyflow MCP tool access
- Delegates: XML `<delegate>` blocks in text (parsed by orchestrator)
- Personality mode: `native_tools="cli_mcp"` in personality_service.py
- Permissions: `--permission-mode bypassPermissions` (MCP tools are our own REST API)
- `--strict-mcp-config` prevents Claude Code's own MCP servers from polluting context
- **Rate gate**: `CliRateGate` in cli_backend.py — dual-semaphore concurrency limiter. Session (dispatcher/chat) and worker CLI calls have independent semaphores so workers never starve interactive chat. Configured via `CLI_SESSION_CONCURRENT` (default 5), `CLI_WORKER_CONCURRENT` (default 15), and `CLI_MIN_SPACING_MS` (default 0). Applied to all 5 CLI entry points: `call()`, `_call_with_tool_events()`, `stream_persistent()`, `call_steerable()`, `stream()`

### 2. Native Anthropic SDK (`provider_type: "anthropic"` or `CLAUDE_USE_NATIVE=true`)
Direct API calls via `anthropic` Python SDK. Requires API key.
- **File**: `backend/app/services/llm/providers/anthropic_provider.py`
- Uses `delegate_action` tool_use for dispatching (native tool blocks)
- Prompt caching via `cache_control: {type: ephemeral}`
- Converts OpenAI-format tool defs to Anthropic format automatically

### 3. OpenAI-Compatible Providers (`provider_type: "openai" | "groq" | "mistral" | "gemini" | "lmstudio"`)
Any endpoint speaking the OpenAI chat/completions API.
- **File**: `backend/app/services/llm/providers/openai_compat.py`
- Cloud: OpenAI, Groq, Mistral AI, Google Gemini (each with default URLs in factory)
- Local: LM Studio (localhost:1234), any custom OpenAI-compat server

### 4. Ollama (`provider_type: "ollama"`)
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
- `backend/app/services/claude_service.py` — ClaudeService singleton, 3 model tiers (fast/deep/haiku), `reload_models()` uses provider_factory
- `backend/app/services/llm/api_caller.py` — ApiCallerMixin, dispatch hub (`_call_api`, `_call_api_stream`)
- `backend/app/services/llm/cli_backend.py` — ClaudeCliBackend (subprocess management)
- `backend/app/services/llm/client_factory.py` — SDK client creation
- `backend/app/services/llm/provider_factory.py` — `get_provider()` factory, `infer_provider_type()`, provider instance cache
- `backend/app/services/llm/capability_registry.py` — Static model capability registry (80+ models), prefix matching, `lru_cache`
- `backend/app/services/llm/providers/base.py` — `LLMProvider` ABC, `CompletionRequest`, `CompletionResponse`
- `backend/app/services/llm/providers/openai_compat.py` — OpenAI-compatible provider (also used by Groq, Mistral, Gemini, LM Studio)
- `backend/app/services/llm/providers/ollama.py` — Ollama provider (extends OpenAI-compat + native `/api/tags`)
- `backend/app/services/llm/providers/anthropic_provider.py` — Native Anthropic SDK provider
- `backend/app/services/personality_service.py` — System prompts, 3 delegate modes
- `backend/app/services/chat_orchestration.py` — Orchestrator, delegate parsing
- `backend/app/routes/models.py` — Model discovery API (`/providers`, `/list`, `/capabilities`, `/available`, `/test`)
- `backend/app/routes/settings.py` — Settings CRUD, `ProviderEndpoint` model, API key redaction
- `backend/app/mcp_server.py` — MCP tool definitions (92 tools; dispatcher sees ~20, workers see all)
- `backend/app/tools/registry.py` — `TOOLS_DISPATCHER` / `TOOLS_WORKER` sets, role-based filtering
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

**This is a hard boundary.** Tool access is determined by role (dispatcher vs worker),
NOT by model. Fast and deep dispatchers get the SAME tools — the only difference is
which model handles the chat (Haiku vs Opus). Workers run in background subprocesses
and get full MCP tool access.

### Dispatcher (fast + deep chat) — `TOOLS_DISPATCHER`
Lightweight, non-blocking tools only. The dispatcher streams responses to the user
and must never block on heavy operations.

**Allowed:** read ops (`project.list/get`, `card.list/get`, `wiki.list/get`, `doc.list`,
`jobs.list`, `health`), basic CRUD (`card.create/update/move/archive`,
`card.create_unassigned`, `project.create`), memory (`memory.search/save`,
`knowledge.search`).

**NOT allowed:** `system.exec`, `file.*`, `git.*`, `tmux.*`, `web.*`, `kg.*`,
`voxyflow.ai.*`, destructive ops (`*.delete`, `*.export`), worker management tools.
These are worker-only.

### Worker — `TOOLS_WORKER`
Full MCP tool access. Workers run as background subprocesses spawned via
`delegate_action`. They can exec commands, read/write files, search the web,
manage git, use tmux, call AI features, and perform destructive operations.

### Key files
- `backend/app/tools/registry.py` — `TOOLS_DISPATCHER` and `TOOLS_WORKER` sets, `_ROLE_TOOL_SETS`
- `backend/app/services/llm/tool_defs.py` — `get_claude_tools(role=...)` for native SDK path
- `backend/app/tools/prompt_builder.py` — `build_tool_prompt(role=...)` for CLI path

### Invariant
When adding new tools: add to `TOOLS_WORKER` in `registry.py`. Only add to
`TOOLS_DISPATCHER` if the tool is instant, non-blocking, and safe for inline chat.
Never gate tools on model tier (fast/deep) — that is purely a model selection.

## Dispatcher Flow
1. User message → `chat_fast_stream()` or `chat_deep_stream()` (model selection only)
2. System prompt built (personality + dispatcher + delegate instructions)
3. CLI spawns `claude -p` with dispatcher tools + system prompt
4. Model responds conversationally + calls dispatcher tools inline + emits `<delegate>` for complex tasks
5. Orchestrator parses `<delegate>` blocks → spawns workers (with full `TOOLS_WORKER` access)

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
CLAUDE_DEEP_MODEL=claude-opus-4-6
CLI_SESSION_CONCURRENT=5
CLI_WORKER_CONCURRENT=15
CLI_MIN_SPACING_MS=0
MAX_WORKERS=15
```

---

## Project Isolation

Invariants to preserve when touching memory, MCP tools, or chat routing. Regressions here leak context across projects.

### 1. ChromaDB collections keyed by `project_id` (UUID)
- Memory store lives in `~/.voxyflow/chroma/`
- Per-project: `memory-project-{project_id}` — `project_id` is the **UUID**, never the title/slug
- Global cross-project: `memory-global` (constant `GLOBAL_COLLECTION` in `backend/app/services/memory_service.py`) — reserved for the **general/main chat only**
- System / general chat (no project) uses pseudo-project `system-main` → collection `memory-project-system-main`
- Slugs change on rename and orphan data — **never** use them as collection keys

### 1a. STRICT: project chats never query `memory-global`
- `memory_service._build_chromadb_context` Project Chat & Card Chat modes query the per-project collection ONLY. Do not add `GLOBAL_COLLECTION` to those branches.
- `mcp_server.memory_search` handler: when `VOXYFLOW_PROJECT_ID` is a real project UUID → `collections=[_project_collection(pid)]`. Global is added **only** when env is empty / `system-main`.
- `mcp_server.memory_search` handler mirrors the same rule (single implementation, no duplication).
- **Why:** `memory-global` holds cross-bot imports / user-globals that the user explicitly wants kept out of project work. A clean project must show zero knowledge from other contexts.
- **Regression guard:** `backend/scripts/smoke_test_isolation.py` test `_build_chromadb_context — Project Chat mode never queries memory-global` will fail if this is broken.

### 2. `search_memory()` requires explicit collections
- `backend/app/services/memory_service.py` — `search_memory()` raises `ValueError` if `collections=` is omitted. No silent fallback.
- Callers must pass the collections they want.
- `build_memory_context(project_id=...)` is the high-level helper — it picks the right collections based on `project_id`.

### 3. MCP tools auto-scope via env var
- MCP subprocess inherits `VOXYFLOW_PROJECT_ID` from `cli_backend._build_mcp_config(..., project_id=...)`
- Handlers in `backend/app/mcp_server.py` (`memory_search`, `memory_save`, `knowledge_search`) read `os.environ.get("VOXYFLOW_PROJECT_ID", "")` and scope automatically
- MCP tool schemas do **not** expose `project_id` — Voxy cannot override it. Scoping is enforced by the runtime, not by the LLM.
- Empty / missing env → falls back to `system-main` (general chat behavior)

### 4. `chat_id` is server-canonical, not client-trusted
- `backend/app/main.py` derives the canonical `chat_id` from server-side `project_id` / `card_id`:
  - card → `card:{card_id}`
  - project → `project:{project_id}`
  - general → `project:{SYSTEM_MAIN_PROJECT_ID}`
- Frontend-supplied `chatId` is accepted only if it equals the canonical id or starts with `canonical + ":"` (sub-sessions). Otherwise logged as `[WS] Rejected mismatched chatId=...` and replaced.
- Prevents a stale or malicious frontend from steering chat into the wrong session.

### 5. When you add a new tool / new chat path
- Tool touches memory or per-project data → **never** require the LLM to pass `project_id` as an arg. Read it from `os.environ["VOXYFLOW_PROJECT_ID"]` in the handler.
- New CLI entrypoint in `cli_backend.py` → thread `project_id` through to `_build_mcp_config(..., project_id=project_id)`
- New chat handler in `main.py` → derive `chat_id` from server-side ids, do not echo the frontend's `chatId` blindly

### 6. Drift detection
- `cli_backend.stream_persistent` logs `[CLI-persistent] PROJECT_ID DRIFT: ...` if a persistent chat process is reused with a different `project_id` than it was spawned with. If you see this in logs, something upstream is wrong.
