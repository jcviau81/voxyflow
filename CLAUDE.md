# Voxyflow — Project Context

## Architecture
Kanban + AI execution engine. Python/FastAPI backend, React frontend.
- **Backend**: `backend/app/` — services, routes, tools, MCP server
- **Frontend**: `frontend-react/src/` — React + Vite

## LLM Backend — Three Paths (April 2026)

Voxyflow supports three LLM backend paths, configured via `backend/.env`:

### 1. CLI Subprocess (`CLAUDE_USE_CLI=true`) — ACTIVE
Spawns `claude -p` subprocesses. Uses Claude Max subscription directly.
- **File**: `backend/app/services/llm/cli_backend.py`
- Chat layers: streaming via `--output-format stream-json`, MCP tools for inline ops
- Workers: non-streaming with `--mcp-config` for full Voxyflow MCP tool access
- Delegates: XML `<delegate>` blocks in text (parsed by orchestrator)
- Personality mode: `native_tools="cli_mcp"` in personality_service.py
- Permissions: `--permission-mode bypassPermissions` (MCP tools are our own REST API)
- `--strict-mcp-config` prevents Claude Code's own MCP servers from polluting context
- **Rate gate**: `CliRateGate` in cli_backend.py — global semaphore (max concurrent) + min spacing between calls. Prevents 529 rate limit errors on Max subscription. Configured via `CLI_MAX_CONCURRENT` (default 2) and `CLI_MIN_SPACING_MS` (default 500). Applied to all 5 CLI entry points: `call()`, `_call_with_tool_events()`, `stream_persistent()`, `call_steerable()`, `stream()`

### 2. Native Anthropic SDK (`CLAUDE_USE_NATIVE=true`)
Direct API calls via `anthropic` Python SDK. Requires API key.
- Uses `delegate_action` tool_use for dispatching (native tool blocks)
- Prompt caching via `cache_control: {type: ephemeral}`

### 3. OpenAI-Compatible Proxy (default fallback)
Proxy at `localhost:3457`. Being deprecated (Anthropic cutting third-party harness access).

## Key Files
- `backend/app/services/claude_service.py` — ClaudeService singleton, 4 layers (fast/deep/haiku/analyzer)
- `backend/app/services/llm/api_caller.py` — ApiCallerMixin, dispatch hub (`_call_api`, `_call_api_stream`)
- `backend/app/services/llm/cli_backend.py` — ClaudeCliBackend (subprocess management)
- `backend/app/services/llm/client_factory.py` — SDK client creation
- `backend/app/services/personality_service.py` — System prompts, 3 delegate modes
- `backend/app/services/chat_orchestration.py` — Orchestrator, delegate parsing
- `backend/app/mcp_server.py` — MCP tool definitions (86 individual, consolidated to 40 via MCP)
- `backend/app/services/knowledge_graph_service.py` — Temporal KG (entities, triples, attributes)
- `backend/mcp_stdio.py` — MCP stdio transport entry point
- `backend/app/config.py` — Settings (env vars + keyring)

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

## Dispatcher Flow
1. User message → `chat_fast_stream()` or `chat_deep_stream()`
2. System prompt built (personality + dispatcher + delegate instructions)
3. CLI spawns `claude -p` with MCP tools + system prompt
4. Model responds conversationally + calls MCP tools inline + emits `<delegate>` for complex tasks
5. Orchestrator parses `<delegate>` blocks → spawns workers

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
CLI_MAX_CONCURRENT=2
CLI_MIN_SPACING_MS=500
```

---

## Dispatcher Rules — Comportement de Voxy

### Project Scope — Isolation stricte
- Quand tu dispatches un worker dans le contexte d'un projet, **toujours** passer le `project_id` explicitement dans le prompt
- **Interdire explicitement** l'accès aux autres projets dans chaque delegate
- Ne jamais laisser un worker explorer librement sans contrainte de scope
- Template minimal pour tout worker :
  - Nom du projet + project_id
  - "N'accède pas aux autres projets"
  - Objectif concret + outils autorisés

### Tool Awareness — Inline vs Déléguer
- Les tools MCP suivants sont **inline directs** — ne pas déléguer inutilement :
  - `card_list/get/create/update/move/archive`
  - `wiki_list/get/create/update`
  - `memory_search/save`, `knowledge_search`
  - `project_list/get`
  - `workers_list/get_result`
  - `task_peek/cancel/steer`
- **Déléguer seulement pour :** filesystem read/write, bash, web search, analyse code multi-fichiers, tâches multi-étapes

### Proactivité
- Créer des cartes immédiatement quand un bug ou feature est identifié
- Mettre à jour les statuts de cartes au fil du travail
- Sauvegarder les décisions importantes via `memory_save` sans attendre qu'on le demande
- Proposer les prochaines étapes logiques après chaque action
- Toujours accompagner un `<delegate>` d'au moins une phrase de contexte visible (éviter la bulle vide)

### Erreurs connues à éviter
| Erreur | Fix |
|--------|-----|
| Worker accède à d'autres projets | Toujours spécifier project_id + interdire les autres |
| Worker bloqué sur sudo | Utiliser `sudo -n` ou éviter les commandes interactives |
| Worker lit et recrache sans agir | Demander une action concrète dans le prompt |
| Worker déclaré mort trop tôt | Ne pas tuer un worker silencieux — attendre le timeout |
| Bulle de réponse vide | Toujours ajouter du texte avant le delegate |

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
- `tool_defs._execute_inline_tool` memory_search branch mirrors the same rule.
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
