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
- `backend/app/mcp_server.py` — MCP tool definitions (53 tools)
- `backend/mcp_stdio.py` — MCP stdio transport entry point
- `backend/app/config.py` — Settings (env vars + keyring)

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
- **Linger**: enabled for `jcviau` so user services start at boot without login

## .env (example)
```
CLAUDE_USE_CLI=true
CLAUDE_FAST_MODEL=claude-haiku-4-5-20251001
CLAUDE_SONNET_MODEL=claude-sonnet-4-6
CLAUDE_DEEP_MODEL=claude-opus-4-6
CLI_MAX_CONCURRENT=2
CLI_MIN_SPACING_MS=500
```
