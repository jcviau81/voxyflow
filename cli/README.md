# voxy — power CLI for Voxyflow

Chat, kanban, workers, jobs and skills from the terminal.

## Install

Editable into the backend venv (dev):

```bash
# from the repo root:
backend/venv/bin/pip install -e ./cli
```

Global install with pipx:

```bash
pipx install ./cli
# or editable, so `git pull` updates the CLI in place:
pipx install --editable ./cli
```

## Configuration

- **Base URL**: `VOXYFLOW_URL` env var (default `http://localhost:8000`).
- **Auth token**: read from `~/.voxyflow/auth_token`; if missing, fetched from
  `GET /api/auth/bootstrap` and cached back to that file (mode 0600).

## Commands

```
voxy status                          # health + counts overview
voxy use [WORKSPACE] [--clear]       # set/show/clear the default workspace
voxy chat "message" [-w WS] [--deep] # one-shot chat, streams live
voxy chat [-w WS]                    # interactive REPL (/quit, /deep)

voxy ws list [--json]                # › marks the `voxy use` workspace
voxy ws create TITLE [-d DESC]
voxy ws delete NAME_OR_ID [-y]

voxy cards list [-w WS] [--status S] [--json]
voxy cards add TITLE [-w WS] [-d DESC]
voxy cards move CARD_ID STATUS       # backlog / todo / in-progress / done
voxy cards done CARD_ID
voxy cards rm CARD_ID [-y]

voxy workers [list] [--status S] [--json]
voxy workers watch                   # live table, Ctrl-C to stop
voxy workers peek TASK_ID
voxy workers steer TASK_ID MESSAGE
voxy workers cancel TASK_ID

voxy jobs list [--json]
voxy jobs run JOB_ID

voxy skills list [--json]
voxy skills show NAME

voxy config show [--json]            # all settings (secrets redacted)
voxy config get PATH                 # e.g. voxy config get models.fast.model
voxy config set PATH VALUE           # read-modify-write; VALUE parsed as JSON when possible

voxy update [--check|--no-restart|--full]  # git pull + deps/build as needed + restart
voxy doctor [--fix]                  # diagnose install; --fix restarts/re-auths
```

### Default workspace (`voxy use`)

`voxy use myproject` persists a default workspace in `~/.voxyflow/cli.json`;
`chat` and `cards` then target it when `-w` is omitted. Explicit `-w` always
wins, `-w general` forces the general/main chat, and `voxy use --clear`
(or deleting the workspace) resets to general.

Workspace arguments (`-w`) accept either the workspace **id** or its **title**
(case-insensitive; unique prefixes work too).

All `list` commands take `--json` for scripting.

### Settings (`voxy config`)

Settings live in one document behind `/api/settings`. `get`/`set` address it by
dotted path (`models.fast.model`, `models.endpoints.0.url`, `voice.tts_enabled`).
Secrets come back redacted as `***` and are preserved server-side on save.

### Updating (`voxy update`)

On an editable install, `voxy update` pulls the repo (`--ff-only`), then only
runs the steps the diff requires: pip install when requirements changed,
frontend rebuild when `frontend-react/` changed, backend restart when
`backend/` changed — and waits for `/health` to go green. `--check` just
reports how far behind origin you are; `--full` forces every step.

### Diagnostics (`voxy doctor`)

Checks backend reachability, per-service health, auth token, websocket,
systemd units, running-commit vs checkout (stale code), frontend build,
memory store, disk space and the `claude` binary. `--fix` restarts failed
services and re-bootstraps a rejected token, then re-checks. Exit code 1
when something is failing (script-friendly).

## Tests

```bash
cd cli && python -m pytest tests/ -v
```

Tests are offline — no live backend required.
