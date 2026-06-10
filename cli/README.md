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
voxy chat "message" [-w WS] [--deep] # one-shot chat, streams live
voxy chat [-w WS]                    # interactive REPL (/quit, /deep)

voxy ws list [--json]
voxy ws create TITLE [-d DESC]
voxy ws delete NAME_OR_ID [-y]

voxy cards list -w WS [--status S] [--json]
voxy cards add TITLE -w WS [-d DESC]
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
```

Workspace arguments (`-w`) accept either the workspace **id** or its **title**
(case-insensitive; unique prefixes work too).

All `list` commands take `--json` for scripting.

## Tests

```bash
cd cli && python -m pytest tests/ -v
```

Tests are offline — no live backend required.
