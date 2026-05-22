# Codex CLI Provider

Voxyflow supports OpenAI Codex as a native local CLI provider through `codex exec --json`. It can be selected anywhere a model layer can be configured: Fast dispatcher, Deep dispatcher, and worker classes.

## When to Use It

| Voxyflow role | Suggested model | Rationale |
|---------------|-----------------|-----------|
| Fast dispatcher | `gpt-5.4-mini` | Lowest-cost responsive routing and light state inspection |
| Deep dispatcher | `gpt-5.4` or `gpt-5.5` | Better planning and conversation quality when the user asks broad questions |
| Coder worker | `gpt-5.3-codex` | Coding-optimized model for implementation tasks |
| Architect / Researcher workers | `gpt-5.4` or `gpt-5.5` | Stronger long-context reasoning for design and analysis |
| Simple utility workers | `gpt-5.4-mini` | Cost-efficient for small CRUD or summarization tasks |

Model availability comes from the local Codex CLI account. Use `/model` inside Codex or test with `codex exec -m <model-id>` if a model fails.

Current built-in Voxyflow Codex choices:

- `gpt-5.5`
- `gpt-5.4`
- `gpt-5.4-mini`
- `gpt-5.3-codex`
- `gpt-5.2`

## Configuration

1. Install and sign in to the OpenAI Codex CLI.
2. Open **Settings > Models**.
3. Choose **Codex CLI** for any dispatcher layer or worker class.
4. Select one of the available Codex model IDs.
5. Use **Test model** to verify the selected CLI/model path.

Codex CLI is a local subprocess provider. It does not require a base URL or API key in Voxyflow settings.

## Runtime Path

The provider is implemented by:

- `backend/app/services/llm/codex_backend.py`
- `backend/app/services/llm/providers/codex.py`
- `backend/app/services/llm/api_caller.py`
- `backend/app/services/llm/provider_factory.py`
- `frontend-react/src/components/Settings/ModelPanel.tsx`

`CodexCliBackend` sends prompts on stdin to `codex exec --json`, then parses JSONL events for assistant messages, usage, command execution, MCP tool calls, and failures.

Worker lifecycle events are read from normal Codex output. As a fallback, workers can emit fenced JSON blocks:

```json
{"voxyflow_worker_claim": {"worker_id": "..."}}
```

```json
{"voxyflow_worker_complete": {"worker_id": "...", "summary": "..."}}
```

## MCP Tool Loading

Voxyflow does not mutate `~/.codex/config.toml` at runtime. Instead, it injects the Voxyflow MCP server per Codex call with `-c mcp_servers.*` overrides.

The injected server runs:

```bash
backend/venv/bin/python3 backend/mcp_stdio.py
```

Important scoped environment variables:

| Variable | Purpose |
|----------|---------|
| `VOXYFLOW_API_BASE` | Backend API base URL |
| `VOXYFLOW_MCP_ROLE` | Role-specific tool profile |
| `VOXYFLOW_WORKSPACE_ID` | Current workspace scope |
| `VOXYFLOW_CARD_ID` | Current card scope |
| `VOXYFLOW_CHAT_ID` | Current chat/session scope |
| `VOXYFLOW_WORKER_ID` | Worker lifecycle scope |
| `VOXYFLOW_DIR` | App directory |
| `VOXYFLOW_DATA_DIR` | Data directory |
| `VOXYFLOW_SANDBOX_DIR` | Workspace root exposed to tools |

## Dispatcher Tool Profile

Codex dispatchers use `VOXYFLOW_MCP_ROLE=dispatcher_codex`, backed by `TOOLS_DISPATCHER_CODEX` in `backend/app/tools/registry.py`.

This profile is intentionally read-only and delegation-oriented. It gives the dispatcher enough visibility to inspect workspaces, cards, wiki/doc metadata, memory, knowledge, sessions, worker status, and task state, but removes inline mutating actions. The expected behavior is:

1. Inspect current state.
2. Respond conversationally when no execution is needed.
3. Emit `<delegate>` for work that changes state, edits files, runs commands, searches the web, or performs multi-step execution.

Claude CLI dispatchers continue to use the broader `TOOLS_DISPATCHER` profile. Workers continue to use `TOOLS_WORKER`.

## Capacity Fallback

Codex can return:

```text
Selected model is at capacity. Please try a different model.
```

Voxyflow detects this condition, deduplicates repeated JSON error messages, and retries with a fallback model order:

1. `gpt-5.4-mini`
2. `gpt-5.3-codex`
3. `gpt-5.4`
4. `gpt-5.5`
5. `gpt-5.2`

For automatic worker callbacks, if all retries still fail only because of Codex capacity and the worker result is already persisted, Voxyflow suppresses the duplicate chat error.
