# Contributing to Voxyflow

Welcome, and thanks for your interest in contributing. Voxyflow is a voice-first AI project management assistant — a Kanban board that actually understands what you're doing, delegates tasks to background AI workers, and talks back. If that sounds like your kind of project, you're in the right place.

This document covers everything you need to get started: setting up a dev environment, understanding the codebase, and the contribution workflow we use.

---

## Quick Dev Setup

For a full step-by-step setup (Python version, system dependencies, TTS server, etc.), see [`docs/SETUP.md`](docs/SETUP.md). The short version:

```bash
# 1. Clone
git clone https://github.com/your-org/voxyflow.git
cd voxyflow

# 2. Backend
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit .env — see LLM Backend section below

# 3. Frontend
cd ../frontend-react
npm install

# 4. Run backend (dev mode)
cd ../backend
uvicorn app.main:app --reload --port 8000

# 5. Run frontend (dev mode)
cd ../frontend-react
npm run dev
```

### LLM Backend

Voxyflow supports three LLM backends, configured in `backend/.env`:

- **Option 1 (recommended): Claude CLI subprocess** — install `claude` CLI, run `claude login`, set `CLAUDE_USE_CLI=true`. Uses your Claude Max subscription, no API key needed.
- **Option 2: Native Anthropic SDK** — set `CLAUDE_USE_NATIVE=true` and provide `CLAUDE_API_KEY`.
- **Option 3: OpenAI-compatible proxy** — legacy path, being deprecated.

See `backend/.env.example` for the full config reference.

---

## Project Structure

```
voxyflow/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app entry point, router registration
│   │   ├── config.py                # Settings loader (env vars + keyring)
│   │   ├── database.py              # SQLAlchemy models and DB session
│   │   ├── mcp_server.py            # ~60 MCP tool definitions (Claude's tool interface)
│   │   ├── routes/                  # FastAPI routers — one file per domain
│   │   └── services/                # Business logic — chat, memory, workers, etc.
│   │       ├── claude_service.py    # ClaudeService singleton, 4 model layers
│   │       ├── chat_orchestration.py # Orchestrator, delegate block parsing
│   │       ├── personality_service.py # System prompt builder (loads personality/ files)
│   │       ├── agent_personas.py    # 7 agent persona definitions
│   │       ├── agent_router.py      # Keyword-based agent routing logic
│   │       └── llm/                 # LLM backend adapters (CLI, SDK, proxy)
│   └── mcp_stdio.py                 # MCP stdio transport entry point
├── frontend-react/
│   └── src/
│       ├── components/              # React UI components
│       │   ├── Chat/                # Message bubbles, chat input, message list
│       │   ├── Kanban/              # KanbanBoard and KanbanCard
│       │   └── Board/               # FreeBoard main grid view
│       ├── services/                # Frontend services: TTS, STT, WebSocket
│       ├── stores/                  # Zustand state stores (cards, messages, projects)
│       ├── hooks/                   # TanStack Query hooks (useCards, useProjects, etc.)
│       ├── types/                   # TypeScript types for Card, Project, Message
│       └── pages/                   # Top-level pages (MainPage, ProjectPage, JobsPage)
├── personality/                     # System prompt files loaded at runtime
│   ├── SOUL.md                      # Core personality and tone
│   ├── AGENTS.md                    # 7 agent persona definitions
│   ├── DISPATCHER.md                # Dispatcher behavior and delegate rules
│   ├── WORKER.md                    # Worker instructions
│   └── MEMORY.md                    # Memory service instructions
├── docs/                            # Reference documentation
│   ├── SETUP.md                     # Full dev setup guide
│   ├── ARCHITECTURE.md              # System architecture overview
│   └── API.md                       # REST API reference
└── tests/                           # Backend integration and e2e tests
```

---

## How to Contribute

### Branch naming

Work on a feature branch, never directly on `main`:

```
feat/short-description
fix/short-description
docs/short-description
refactor/short-description
chore/short-description
```

### Commit style

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add card duplication to MCP tools
fix: prevent duplicate WebSocket events on reconnect
docs: add MCP tool authoring guide to CONTRIBUTING
refactor: extract delegate parsing into its own module
chore: bump anthropic SDK to 0.49
```

Keep the first line under 72 characters. Add a body if the "why" isn't obvious from the subject.

### Pull Request process

1. Fork the repo and create a feature branch from `main`.
2. Make your changes. Test them manually (and run the test suite if relevant).
3. Open a PR with:
   - A clear description of what changed and why
   - Steps to test it manually
   - A link to the related issue, if one exists
4. Do not push directly to `main`. PRs need at least one review before merge.

---

## Common Contribution Patterns

### Adding an MCP Tool

MCP tools are how Claude interacts with Voxyflow at runtime. All tools are defined in `backend/app/mcp_server.py` as entries in the `_TOOL_DEFINITIONS` list.

**Step 1 — Add the REST endpoint** (if it doesn't exist yet):

Create or extend a route file in `backend/app/routes/` and register it in `backend/app/main.py`:

```python
# backend/app/main.py
from app.routes import your_module
app.include_router(your_module.router, prefix="/api")
```

**Step 2 — Define the MCP tool** in `_TOOL_DEFINITIONS` in `mcp_server.py`:

```python
{
    "name": "voxyflow.thing.do_something",
    "description": "Clear, one-sentence description for Claude to understand when to use this.",
    "inputSchema": {
        "type": "object",
        "required": ["field_name"],
        "properties": {
            "field_name": {"type": "string", "description": "What this field does"},
        },
    },
    "_http": ("POST", "/api/things/{field_name}", lambda p: {"key": p["field_name"]}),
}
```

The `_http` tuple is `(method, path_template, payload_transformer)`. Path params are interpolated from the input dict. `payload_transformer` maps the input params to the request body (use `None` for GET requests with no body).

**Step 3 — Test it:**

```bash
# Start the MCP server in stdio mode
cd backend
python mcp_stdio.py

# Or test via the REST endpoint directly
curl -X POST http://localhost:8000/api/things/foo -H "Content-Type: application/json" -d '{"key": "foo"}'
```

If you want the tool available to the Dispatcher (not just Workers), remove or set `_role` to `"all"`. Tools tagged `_role="worker"` are hidden from the fast chat layer.

---

### Adding or Modifying an Agent Persona

Voxyflow has 6 specialist agents (Researcher, Coder, Designer, Architect, Writer, QA) plus a General default. They're defined in two places:

1. **`backend/app/services/agent_personas.py`** — Python definitions (name, keywords, routing weight, model preference). This drives the automatic agent routing logic.
2. **`personality/AGENTS.md`** — Natural language descriptions injected into the system prompt. This is what Claude actually reads to adopt a persona.

If you're adding a new persona, update both files. If you're just tuning the tone or focus of an existing one, `personality/AGENTS.md` is usually enough.

---

### Adding a REST Endpoint

1. Find the appropriate route file in `backend/app/routes/` (or create a new one for a new domain).
2. Define your route using FastAPI conventions — async handler, Pydantic models for request/response bodies, proper HTTP status codes.
3. Register the router in `backend/app/main.py` if it's a new file:

```python
from app.routes import your_new_module
app.include_router(your_new_module.router, prefix="/api")
```

4. Add or update the corresponding Pydantic schemas in `backend/app/models/` if needed.
5. If this endpoint should be accessible to Claude, add a corresponding MCP tool (see above).

---

## Running Tests

```bash
# Backend tests (from repo root)
cd backend
pytest ../tests/ -v

# Specific test file
pytest ../tests/test_context_isolation.py -v

# Frontend tests
cd frontend-react
npm test
```

The e2e tests in `tests/e2e/` require a running backend. Make sure `uvicorn` is running on port 8000 before running them.

---

## Code Style

### Python

- **Type hints everywhere** — functions, return types, class attributes.
- **Async/await** — all I/O must be async. No blocking calls in request handlers.
- **No `print()`** — use `import logging; logger = logging.getLogger(__name__)`.
- **No files over 500 lines** without a compelling reason to keep them together.
- Formatting: we use `black` defaults. Run `black app/` before committing if you've touched Python files.

### TypeScript / React

- **No `any`** — if you don't know the type, define one or use `unknown`.
- **Functional components only** — no class components.
- **Zustand for global state** — don't introduce new patterns (Context, Redux, etc.) without discussion.
- **Immer is intentional** — Zustand uses the Immer middleware. Don't remove it.
- Keep components focused. If a component is doing too much, split it.

---

## Questions?

If something isn't clear, the codebase behaves unexpectedly, or you want to discuss an idea before building it — [open an issue](https://github.com/your-org/voxyflow/issues). We'd rather have the conversation early than review a PR that goes in the wrong direction.
