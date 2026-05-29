# Voxyflow Runtime Toggles

This document lists the environment toggles that are **live** in the current
backend. Anything not in this list is either configured via Settings/UI
(`backend/app/config.py`) or has been retired.

If you add or remove a runtime toggle, update this file in the same PR.

---

## Live env toggles

### `VOXYFLOW_CLOSEOUT_PASS`

- **Default:** `1` (on)
- **Type:** `"1"` enables, anything else disables
- **Used in:** `backend/app/services/orchestration/worker_pool.py`
  (`DeepWorkerPool._run_closeout_pass`)
- **Purpose:** When a worker exits without calling
  `voxyflow.worker.complete`, the pool spawns a lightweight closeout
  subprocess that reads the worker's artifact and emits a structured
  completion on its behalf. Set to `0` only when debugging a runaway
  closeout loop — production should leave this on so the dispatcher always
  receives a structured deliverable.

### `DISPATCHER_WORKER_CALLBACK`

- **Default:** `1` (on)
- **Type:** `"1"` enables, anything else disables
- **Used in:** `backend/app/services/orchestration/worker_pool.py`
  (`DeepWorkerPool._maybe_trigger_callback`)
- **Purpose:** When a worker finishes, the pool schedules a debounced
  callback turn in the dispatcher chat so the dispatcher can react to the
  worker's completion (read the artifact, ack events, plan next steps).
  Disable to short-circuit the callback loop in tests or when running a
  dispatcher in pure manual mode. `MAX_CALLBACK_DEPTH` still applies on top.

### `VOXYFLOW_DEV_TASK`

- **Default:** unset (off)
- **Type:** `"1" | "true" | "yes"` enables, anything else disables
- **Used in:**
  - `backend/app/tools/system_tools.py` — gates writes/exec outside the
    sandbox so workers can edit the Voxyflow codebase itself.
  - `backend/app/services/llm/cli_backend.py` — propagated into the MCP
    server env when spawning `claude -p` for Voxyflow-codebase tasks.
- **Purpose:** Opt-in escape hatch for workers that legitimately need to
  read/write the Voxyflow source tree (e.g. self-refactor tasks like this
  one). Without it, `path.write`, `system.exec`, and friends restrict
  workers to `~/.voxyflow/sandbox/`. **Never set this globally** — scope
  it to the one process / task that needs codebase access.

---

## Retired toggles

These were live at some point and have been removed from the runtime:

- **`CLAUDE_USE_CLI`** (env) — superseded by the `claude_use_cli` setting in
  `backend/app/config.py`, surfaced in the Settings UI. The Pydantic
  settings layer still binds `CLAUDE_USE_CLI=…` to that field for backwards
  compatibility, but new code should reference `get_settings().claude_use_cli`.
- **`CLAUDE_PROXY_URL`** / `voxyflow-proxy` systemd unit — the standalone
  Claude Max HTTP proxy (`voxyflow-proxy-fork`) is no longer used. The
  systemd unit at `/etc/systemd/system/voxyflow-proxy.service` has been
  removed; the `claude_proxy_url` setting remains only as a fallback URL
  for OpenAI-compatible clients pointed at a self-hosted endpoint.

If you find a stale reference to either, file an issue or open a PR against
this list.
