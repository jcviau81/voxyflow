# Code Review Plan — 2026-04-17

Snapshot review of the Voxyflow codebase (~79 backend Python files, 121 TS/TSX frontend files, ~15k LOC in `backend/app/services/` alone). Findings are grouped by severity and ordered as an action plan. Each item carries the file:line reference needed to act on it.

**Overall grade: B+.** Solid separation of concerns, thoughtful project isolation, comprehensive tool surface — let down by monolithic core files, inverted module boundaries, missing tests around the LLM layer, and REST paths that skip the auth/isolation guards the WS path enforces.

---

## P0 — Do First (Correctness, Security, Blockers)

### Concurrency / correctness

- [x] **H1. Add `asyncio.Lock` to `EventBusRegistry.get_or_create()`** — `backend/app/services/event_bus.py:95-99`
  Classic check-then-act on `self._buses`. Concurrent WS connects for the same session can create duplicate buses; one overwrites the other, orphaning subscribers.
- [x] **H2. Lock `ChatOrchestrator._pending_confirms`** — `backend/app/services/chat_orchestration.py:908, 1146`
  Unprotected dict read/write for pending user confirmations. Concurrent users can drop or cross-wire confirmations.

### Security / isolation

- [x] **H3. Derive `chat_id` server-side in REST routes** — `backend/app/routes/chats.py:82-107`, `backend/app/routes/cards.py`
  CLAUDE.md §Project Isolation §4 mandates server-canonical `chat_id`. `main.py` enforces on the WS path but every `/api/chats/*` REST route accepts the client value. Add the same derivation to REST; reject mismatches. _Shipped `chat_id_utils.resolve_chat_id()`; WS path + smoke test updated. REST surface still relies on DB UUIDs — true coverage requires H4._
- [x] **H4. Add auth to sensitive endpoints** — `backend/app/services/auth_service.py`, `backend/app/routes/auth.py`
  Shipped bearer-token defense-in-depth: token auto-generated at `~/.voxyflow/auth_token` (0600), served to same-origin frontend via `GET /api/auth/bootstrap`, gated `PUT /api/settings`, personality file writes, `POST /api/backup/trigger`, and destructive `/api/github/*` routes with `Depends(verify_auth)`. Frontend `lib/authClient.ts` wraps protected fetches. Network posture tightened in lockstep: systemd unit binds uvicorn to `127.0.0.1:8000`; Caddyfile uses explicit `bind 100.96.26.98 127.0.0.1` (TCP-layer, not host-header) so LAN (192.168.1.x) can no longer reach port 18789 even with spoofed Host.
- [x] **H5. Harden `system.exec` blocklist + workspace confinement** — `backend/app/tools/system_tools.py:246-248`
  Substring-based blocklist is bypassable (`\rm`, env indirection) and hits false positives. Switch to regex/argv-based checks. Add an explicit "cwd must be under project workspace" assertion — currently a worker can walk out of the project root.

### Dead / broken tools

- [x] **H6. Register or delete `voxyflow.project.update`** — `backend/app/mcp_server.py:163-179` vs `backend/app/tools/registry.py`
  Schema and `_http` handler exist, but the tool is in neither `TOOLS_DISPATCHER` nor `TOOLS_WORKER`. Users can't update projects via MCP. Either add to `TOOLS_DISPATCHER` or remove the definition.
- [x] **M1. Delete duplicate `file_patch()`** — `backend/app/tools/system_tools.py:572` and `:821`
  Second definition shadows the first — first is dead. Delete the later block (lines 817-870).

---

## P1 — Architecture & Major Refactors

### Module boundaries

- [x] **H7. Invert `services → routes` imports**
  Offenders:
  - `backend/app/services/orchestration/worker_pool.py:24` → `services/settings_loader.py`
  - `backend/app/services/claude_service.py:246` → `services/settings_loader.py`
  - `backend/app/services/scheduler_service.py:422, 520, 911` → `services/job_runner.py` + `services/settings_loader.py`
  - `backend/app/services/llm/worker_class_resolver.py:12-13, 67` → `services/settings_loader.py` + `services/worker_classes.py`
  - `backend/app/services/direct_executor.py:135, 192` — still `from app.mcp_server import _find_tool, _call_api` (function-local). Moves into services when mcp_server is split (H8).
  - `backend/app/services/llm/tool_defs.py:128` — same, deferred to H8.

  Done: extracted `settings_loader.py`, `worker_classes.py`, `job_runner.py` as pure service modules; routes re-export for back-compat. Remaining two offenders are `app.mcp_server` (not `app.routes`) and are blocked on H8.

### Monolithic files

- [x] **H8. Split oversized files along natural seams**
  - `backend/app/mcp_server.py` 2,887 → 704 LOC.
  - `backend/app/services/chat_orchestration.py` 1,610 → 567 LOC; orchestration helpers moved under `services/orchestration/` (`delegate_dispatch.py`, `layer_runners.py`, `model_resolution.py`, `session_timeline.py`, `tool_call_fallback.py`, `worker_pool.py`).
  - `backend/app/services/memory_service.py` 1,498 → 661 LOC.
  - `backend/app/services/llm/cli_backend.py` 1,409 → 724 LOC; extracted `cli_persistent_chat.py`, `cli_rate_gate.py`, `cli_steerable.py`, `model_reload.py` alongside it under `services/llm/`.
  - `backend/app/services/claude_service.py` 1,392 → 1,228 LOC (dead `self.client` branch dropped; reload logic extracted to `services/llm/model_reload.py`).

### Duplication

- [x] **M2. Consolidate `_flatten_system()`** — `backend/app/services/llm/api_caller.py:68` and `backend/app/services/llm/cli_backend.py:171`
  Identical implementations. Promote to `backend/app/services/llm/model_utils.py` and import from both.
- [x] **M3. Remove buggy `projectIdFromSession`** — `frontend-react/src/contexts/ChatProvider.tsx:177` (vs correct `getProjectIdFromSession` at `:185`)
  First uses `split(':')[1]` — breaks for card chats (format `card:cardId:s-...`). Second uses `slice()` and is correct. Delete the first and its caller at line 465.
- [x] **M4. Remove dead `self.client`** — `backend/app/services/claude_service.py:205, 207`
  Set to `_OAI` or `None`, never read. Legacy single-client fallback. Delete.
- [x] **M5. De-duplicate coding-keyword / haiku-upgrade logic** — `backend/app/services/chat_orchestration.py:664-680` and `:822-835`
  Extracted to `services/orchestration/model_resolution.py:resolve_worker_model()`.
- [x] **M6. Centralize action/model whitelists** — `backend/app/services/direct_executor.py:28-66`, `backend/app/services/orchestration/worker_pool.py:29-43`, `backend/app/services/chat_orchestration.py:665`
  `CRUD_SIMPLE_INTENTS` now lives with `DIRECT_ACTION_MAP` in `direct_executor.py` and is imported by `model_resolution.py`; M5 eliminated the intra-file duplication.
- [x] **M7. Drop legacy `general:` chat prefix handling** — `frontend-react/src/components/Navigation/WorkerPanel.tsx:90-91, 390`
  Migration ran in `useSessionStore` but this component still branches on the old prefix.

---

## P2 — Testing, Provider Layer, Frontend Hardening

### Test coverage (H9)

- [ ] Add unit tests for every `backend/app/services/llm/providers/*` class (mock HTTP/SDK).
- [ ] Add integration tests for `chat_fast_stream()` and `chat_deep_stream()`.
- [ ] Add tests for `_redact_sensitive()` / `_merge_sensitive_on_save()` in `routes/settings.py`.
- [ ] Wire `backend/scripts/smoke_test_isolation.py` into CI.
- [ ] Target ≥60% coverage in CI; fail PRs that regress.

### LLM / provider layer

- [~] **M15. Wire the provider ABC through orchestration — Phase 1 landed.** — `backend/app/services/llm/providers/*`
  Decision: wire it up (not delete). **Phase 1** (this session): the ABC's `stream()` return type changed from `AsyncIterator[str]` to `AsyncIterator[StreamEvent]` with a tagged union of variants (`TextDelta`, `ToolUseBlock`, `ToolResult`, `StreamDone(stop_reason, usage)`) defined in `providers/base.py`. `AnthropicProvider` and `OpenAICompatProvider` (incl. Ollama) updated to emit events — tool-use args are buffered inside each provider and emitted as complete `ToolUseBlock`s only when the stream closes. New `providers/cli.py::CliProvider` wraps `ClaudeCliBackend` so the CLI path is now a first-class provider (retrievable via `get_provider("cli")`; factory no longer raises for the CLI type). M16 fixed as a side effect — tool_use blocks are no longer silently dropped from Anthropic streams. **Phase 2** still pending — see M15b.
- [ ] **M15b. Phase 2: migrate orchestration tool-use loops onto the provider ABC** — `backend/app/services/llm/api_caller.py`
  `api_caller._call_api_anthropic`, `_call_api_openai`, `_call_api_cli`, `_call_api_stream_anthropic`, `_call_api_stream_openai`, `_call_api_stream_cli`, `_call_api_stream_with_delegate`, and the server-tools fallback still drive SDK/subprocess calls directly. Migrate them to consume provider `complete()` / `stream()` events, keeping the agentic loop (cancel_event, message_queue steering, delegate collection, dispatcher-tool execution, prompt-cache logging) at the caller level. Once no caller hits the SDK directly, delete the redundant `_call_api_*` methods. Large: budget a dedicated session.
- [x] ~~**M16. Fix `AnthropicProvider.stream()` tool_use handling**~~ — resolved by M15 Phase 1.
  `AnthropicProvider.stream()` now pulls `tool_use` blocks off `stream.get_final_message()` after the text stream drains and yields them as `ToolUseBlock` events (followed by `StreamDone`). No more silent drops.
- [x] **M17. Centralize provider-type enum** — scattered as magic strings in `provider_factory.py:32-41`, `routes/models.py`, `capability_registry.py`, frontend `ModelPanel.tsx`. Introduce a single constant (backend + TS type mirror). Kill the silent fallback at `provider_factory.py:130-134`.
  Backend: introduced `ProviderType` class in `provider_factory.py` as the single source of truth for provider-type strings + `ALL`/`is_openai_compat()`/`is_known()` helpers. All internal references now go through it. Silent fallback for unknown types removed — `get_provider()` raises instead. Frontend TS mirror deferred (it only consumes the `/providers` API, so drift shows up server-side immediately).
- [x] **M18. Enforce `***` sentinel at every call site** — `backend/app/services/llm/client_factory.py:9, 18`
  `_sanitize_api_key()` helper drops the redacted sentinel before it reaches any SDK client; applied to all three factories (anthropic sync/async, openai-compat).
- [x] **M19. Release CLI worker slot on subprocess exit, not consumer exit** — `backend/app/services/llm/cli_backend.py` (`stream()`)
  Refactored with a decoupled drain task: a background `_drain_stdout()` coroutine pushes lines through an `asyncio.Queue` and releases the rate-gate semaphore the moment stdout closes (EOF sentinel), regardless of how long the consumer takes to iterate. Slow UI consumers no longer pin worker slots.
- [ ] **M20. Make tool callbacks consistent + wire into streaming CLI** — `backend/app/services/llm/api_caller.py:274-275, 645, 1081-1083, 1487-1493`
  Inconsistent async/sync checks; streaming CLI path accepts no `tool_callback`, so streaming chat gets no tool visibility.

### Frontend

- [x] ~~**L1. Sanitize `renderMarkdown()` output**~~ — `frontend-react/src/components/Projects/BriefSection.tsx:103`, `frontend-react/src/components/Projects/StandupSection.tsx:125`
  Resolved as non-issue: both `renderMarkdown()` implementations already pre-escape `&`, `<`, `>` before any tag-injecting regex runs (mirroring the `ChatSearch.tsx` pattern). User input can only appear as `&lt;`/`&gt;` entities — no injection surface. Load-bearing comment at the top of each function documents the ordering invariant.
- [x] **L2. Audit the 9+ `eslint-disable-next-line react-hooks/exhaustive-deps`** — each is a potential stale-closure.
  Audited every `exhaustive-deps` disable. All remaining suppressions are intentional (connect-ref sync, known wake-word capture gap, mount-once effects). Added load-bearing comments at `useWebSocket.ts:273` and `VoiceInput.tsx:429` documenting *why* the disable is safe so future readers don't re-litigate.
- [x] **L3. Centralize API HTTP client** — magic strings like `/api/models/capabilities`, `/api/models/list`, `/api/endpoints/test` are inline in `ModelPanel.tsx`.
  New `frontend-react/src/lib/apiClient.ts` exports shared `apiFetch<T>` + a `modelsApi` helper object (`providers`, `available`, `list`, `capabilities`, `test`, `benchmark`). `ModelPanel.tsx` now imports from the shared module; the local `apiFetch` and inline `/api/models/*` strings are gone.
- [x] **L4. Guard `crypto.randomUUID()`** — `frontend-react/src/components/Settings/ModelPanel.tsx:203`; utility with fallback already exists at `frontend-react/src/lib/utils.ts:9`.
  `newId()` now delegates to `generateId()` from `lib/utils`, which falls back to a Math.random-based UUIDv4 on insecure contexts.
- [x] **L5. Fix OnboardingGuard backend-failure bypass** — `frontend-react/src/components/OnboardingGuard.tsx:38, 54-56`
  Backend unreachable + no cached `onboarding_complete` flag → render a retry screen instead of granting completion silently. Cached `onboarding_complete=true` still allows offline loading.
- [x] ~~**M8. Remove unused heavy deps**~~ — `frontend-react/package.json`: `@huggingface/transformers`, `onnxruntime-web`.
  Resolved as non-issue: both are actively used by the wake-word / on-device voice stack (`workers/whisper.worker.ts`, `services/wakeWordService.ts`). Moved to the Not Actual Findings list.

---

## P3 — Hygiene, Observability, Docs

### Error handling

- [x] **M10. Replace silent `except Exception: logger.warning(...)` / `.catch(() => {})` patterns**
  - `memory_service.py` (`migrate_from_files`, both file-read sites): narrowed to `(OSError, UnicodeDecodeError)` with `logger.exception()`.
  - `ws_broadcast.py` `emit()` / `emit_to_others()`: narrowed to `(RuntimeError, ConnectionError, OSError)` with debug-level logging (WS disconnects are expected).
  - `direct_executor.py` `_resolve_card_by_title`: `logger.error(f"...{e}")` → `logger.exception(...)` so tracebacks are preserved.
  - Frontend: replaced every `.catch(() => {})` in `ChatProvider.tsx:682` and `ChatWindow.tsx` (4 call sites) with `.catch((e) => console.warn('[ctx] ...', e))`. Errors now surface in the dev console instead of being black-holed.
  - `cli_session_registry.py:112` left as-is: it's a best-effort cleanup on registry shutdown where log noise isn't useful.
- [x] **M11. Remove `asyncio.run()` fallback in `emit_sync()`** — `backend/app/services/ws_broadcast.py:70-79`
  `emit_sync()` now logs+drops when no loop is running instead of spinning up a second one.
- [x] **M12. Unblock async routes** — wrap `subprocess.run` in `routes/github.py:52-59` with `asyncio.create_subprocess_exec`; wrap `.read_text`/`.write_text` in `routes/settings.py:344-350` with `asyncio.to_thread`.
  `routes/settings.py`: wrapped every `path.read_text` / `path.write_text` inside `update_settings`, `preview_personality`, `read_personality_file`, `write_personality_file`, `reset_personality_file`, `init_personality_files` in `asyncio.to_thread`. `routes/github.py` subprocess.run at line 52-59 only runs inside sync `_load_pat()`, which is always called from sync wrappers (`_github_headers`, `_run_gh`, `_github_status_sync`) that the async routes already dispatch via `asyncio.to_thread` — no change needed.
- [x] ~~**M13. Wrap sync DB read with `asyncio.to_thread()`** — `backend/app/mcp_server.py:2299-2315` (`workers_get_result`).~~ Obsolete — handler is already async (`async_session()` + `await db.execute()`).
- [x] **M14. Replace raw SQL with ORM** — `backend/app/routes/settings.py`, `backend/app/services/settings_loader.py`.
  Added `AppSettings(Base)` ORM model in `database.py` (single-row KV under `key='app_settings'`). `settings_loader._load_settings_from_db()` now uses `select(AppSettings.value)` + scalar fetch. `settings.py._save_settings_to_db()` now uses `session.get(AppSettings, "app_settings")` with insert-or-update. All `sqlalchemy.text(...)` raw-SQL imports removed.

### Data / schema

- [x] **M21. Single source of truth for Card / Project / Chat**
  New `backend/app/models/_generated.py` uses `sqlalchemy.inspect()` to build Pydantic v2 bases (`CardBase`, `ProjectBase`, `ChatBase`, `MessageBase`, `DocumentBase`) at import time from the ORM column list — one source of truth for column set + nullability. Hand-written response models in `models/card.py`, `models/chat.py`, `models/project.py`, `models/document.py` now subclass those bases and only layer on *divergent* fields: `CardResponse.dependency_ids` / `total_minutes` / `checklist_progress` (synthesized from relationships), the `Card.files` JSON-text → `list[str]` override, `ChatResponse.messages`, `ChatListItem.message_count`, `ProjectWithCards.cards`, `DocumentListResponse.total`. `pydantic-sqlalchemy` evaluated and rejected (last release 2020, no Pydantic v2 support).
- [x] ~~**M22. Reconcile `MAX_WORKERS` vs `CLI_WORKER_CONCURRENT`**~~ — both default to 15 per CLAUDE.md `.env` example. Figure out which is authoritative and delete the other.
  Resolved as non-issue: they are not redundant. `MAX_WORKERS` caps a **per-session** `DeepWorkerPool` semaphore; `CLI_WORKER_CONCURRENT` caps **global** CLI subprocesses across all sessions via `CliRateGate`. Coincidental default of 15 hid the distinction. Clarified in `app/config.py` comments.

### Global state / singletons

- [x] **L6. Synchronize `SessionStore._file_locks` creation** — `backend/app/services/session_store.py:24-26`
  Replaced `defaultdict(threading.Lock)` with `_get_file_lock()` double-checked-locking helper backed by `_locks_guard`.
- [x] **L7. Lock `ClaudeService.__new__`** — `backend/app/services/claude_service.py:116-121`
  Added `_instance_lock` class attribute and double-checked-locking pattern inside `__new__`.
- [x] **L10. Move `_default_worker_model` module global to a service** — `backend/app/routes/settings.py:31-44`
  Done as part of H7 — state now lives in `app/services/settings_loader.py`; routes re-export.

### Infrastructure / ops

- [x] **L8. Extract `main.py` lifespan + startup migration** — `backend/app/main.py` → `backend/app/startup.py`.
  New `app/startup.py` exports `build_lifespan(claude_service, orchestrator)` plus private helpers (`_cleanup_stale_worker_tasks`, `_sync_settings_from_db`, `_init_personality_files`, `_init_memory_service`, `_load_scheduler_config`, `_periodic_cleanup`). `main.py` now just wires services together and passes the lifespan in. Verified app still imports with 153 routes intact.
- [x] **L9. Standardize route prefix layering** — `backend/app/main.py:362-380`; either all routers set their own prefix or all rely on the include-level `/api`, not both.
  Convention: every router in `app/routes/*.py` declares its own full `/api/...` prefix, and `app.include_router(...)` calls in `main.py` pass no `prefix=` argument. Verified all 151 routes attach at the same paths as before.
- [x] **L11. Remove or fallback `ToolListChangedNotification`** — `backend/app/mcp_server.py:2386-2391` (CLI doesn't support it).
  Downgraded the failure path to a debug log — CLI transport not supporting the notification is expected, not an error.
- [x] **L12. Make MCP log level env-configurable** — `backend/mcp_stdio.py:38`.
  `VOXYFLOW_MCP_LOG_LEVEL` env var (default `WARNING`) controls stdio log level.
- [x] **L13. Extend `/api/health`** — currently only process-liveness. Probe LLM reachability, DB writability, ChromaDB, scheduler.
  New `/api/health/live` route runs a live DB write probe and merges the scheduler's cached service state (LLM reachability via `claude_proxy`, ChromaDB, scheduler, etc.). Returns `status: ok | degraded | down` and `probe_ms`. Original `/api/health` still serves the cached snapshot (cheap, no I/O).
- [x] **L14. Document or demote heartbeat write from dispatcher** — `backend/app/tools/registry.py:37-38`.
  Added a load-bearing comment noting that `heartbeat.write` is a single-row upsert, instant and non-blocking, so it stays in the dispatcher set.
- [x] **L15. Pin dependencies + add lockfile** — `backend/requirements.txt`, `backend/requirements.lock`.
  Rewrote `requirements.txt` with 22 pinned-major ranges (e.g. `fastapi>=0.135,<0.200`, `sqlalchemy[asyncio]>=2.0,<3.0`, `chromadb>=1.5,<2.0`, `anthropic>=0.91,<1.0`). Generated `requirements.lock` from the maintainer venv as a `pip freeze` snapshot (153 lines). Header comment documents the regeneration workflow.
- [x] **M9. Delete or rewrite `backend/setup_keys.py`** — only handles `claude_api_key`, never called, `config.py._get_secret()` already does keyring.
  Deleted the script. Updated `backend/README.md` "API Key Setup" to point to Settings UI + raw `keyring set voxyflow claude_api_key`. Removed stale references in `docs/DEPLOYMENT.md:193` and `docs/SETUP.md:234`.

### Documentation

- [x] **M23. Fix CLAUDE.md tool count** — says "92 tools", actual is ~96-100. Add a CI assertion that grep-counts tools and asserts the documented number.
  CLAUDE.md now says 96 tools (verified via grep `^\s*"name":\s*"` against `_TOOL_DEFINITIONS` in `mcp_server.py`). CI-assert follow-up deferred until `mcp_server.py` is split in H8.
- [x] Document in-scope vs out-of-scope for `system.exec` (single-user local vs multi-tenant).
  Added a "Deployment scope" block to CLAUDE.md right after the worker-tools section. States that Voxyflow is a single-user local install, `system.exec` / `file.*` / `git.*` / `tmux.*` run with full OS-user privileges with no sandbox, and multi-tenant deployment is out of scope unless a sandbox layer is added.
- [x] Add structured logging (structlog or python-json-logger) + trace IDs across WS sessions and worker spawns.
  Added `backend/app/services/logging_config.py` (structlog + stdlib `ProcessorFormatter` bridge). `configure_logging()` wires a shared processor chain (contextvars merge, ISO timestamps, level) and picks JSON vs pretty console via `VOXYFLOW_LOG_JSON`. `app/main.py`, `backend/mcp_stdio.py` now use it. Trace IDs bound via `structlog.contextvars`: `request_id` + `http_path/method` in the HTTP timing middleware (also echoed in `x-request-id`); `ws_id` + per-message `ws_msg_type/session_id/project_id/card_id/chat_id/message_id` in the WS handler (cleared each iteration so stale ids don't leak); `cli_session_id` + `cli_pid` bound at the 3 `CliSession.register(...)` sites in `cli_backend.py` so every log line emitted during a CLI subprocess carries those. Added `structlog>=25.0,<26.0` and `python-json-logger>=4.0,<5.0` to `requirements.txt` and regenerated `requirements.lock`.
- [ ] Add metrics for LLM latencies, delegate queue depth, worker availability (extends `/api/metrics`).

---

## Not Actual Findings

These were flagged by the review but verified false:

- **`backend/app/tools/executor.py` and `backend/app/tools/response_parser.py`** are NOT unused. Imported in:
  - `backend/app/services/llm/api_caller.py:957-958, 1123-1124`
  - `backend/app/services/chat_orchestration.py:40-41`
  - `backend/app/services/orchestration/layer_runners.py:18`
- **`@huggingface/transformers` and `onnxruntime-web`** (M8) are NOT unused. Imported in:
  - `frontend-react/src/workers/whisper.worker.ts` — local Whisper transcription worker.
  - `frontend-react/src/services/wakeWordService.ts` — on-device wake-word detection.
  The `^1.25.0-dev.20260327-...` pin is intentional — it's a dev pre-release pinned to a known-working build of `onnxruntime-web`.

---

## Strengths Worth Preserving

- Role-based tool access (`TOOLS_DISPATCHER` vs `TOOLS_WORKER`) is well-designed and should stay as the guardrail.
- Project isolation via `VOXYFLOW_PROJECT_ID` env injection is thoughtful; the `smoke_test_isolation.py` regression test is the right pattern — just needs CI wiring.
- API-key redaction with the `***` sentinel is a clean pattern — just needs the enforcement gap in `client_factory` closed (M18).
- Multi-provider LLM abstraction has the right shape; just needs the unused ABC surface to be decided (M15) and a unified provider-type enum (M17).
