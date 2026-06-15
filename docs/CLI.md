# voxy — CLI Reference

`voxy` is the power CLI for Voxyflow: chat, kanban, workers, jobs, skills, settings, and install maintenance from the terminal. It talks to the same REST/WebSocket API as the web UI.

Source lives in [`cli/`](../cli/) (Python, Typer + Rich + httpx).

---

## Installation

`./install.sh` installs `voxy` automatically as part of the one-shot setup. To install it yourself:

**Editable into the backend venv** (dev — `git pull` updates the CLI in place):

```bash
# from the repo root:
backend/venv/bin/pip install -e ./cli
```

**Global install with pipx:**

```bash
pipx install ./cli
# or editable, so `git pull` updates the CLI in place:
pipx install --editable ./cli
```

Verify: `voxy --version`

---

## Configuration

| Setting | Source | Default |
|---------|--------|---------|
| Base URL | `VOXYFLOW_URL` env var | `http://localhost:8000` |
| Auth token | `~/.voxyflow/auth_token` | auto-bootstrapped |
| CLI state (default workspace) | `~/.voxyflow/cli.json` | empty |

- **Auth token** — read from `~/.voxyflow/auth_token`; if the file is missing or empty, the token is fetched from `GET /api/auth/bootstrap` and cached back to the file (mode `0600`).
- **WebSocket URL** — derived from the base URL (`http://` → `ws://…/ws`, `https://` → `wss://…/ws`). Used by `voxy chat`.

### Workspace arguments

Anywhere a command takes a workspace (`-w` / positional), you can pass either the workspace **id** or its **title** — matching is case-insensitive and unique prefixes work. The special refs `general`, `main`, `home`, and `none` force the general/main chat regardless of any default workspace.

### Scripting

All `list` commands (and `voxy status`) take `--json` for raw JSON output.

---

## Commands

### `voxy status`

Backend health + counts overview: overall status, per-service health (scheduler, database, RAG, …), resource usage, and counts of workspaces, active workers, and enabled jobs.

```
voxy status [--json]
```

### `voxy use` — persistent default workspace

```
voxy use [WORKSPACE] [--clear]
```

- `voxy use myproject` — persists a default workspace in `~/.voxyflow/cli.json`; `chat` and `cards` then target it when `-w` is omitted.
- `voxy use` (no argument) — shows the current default.
- `voxy use --clear` — resets to the general chat.

Explicit `-w` always wins over the default; `-w general` forces the general/main chat. Deleting the default workspace (`voxy ws delete`) also clears it.

### `voxy chat`

```
voxy chat "message" [-w WORKSPACE] [--deep] [--timeout SECONDS]   # one-shot, streams live
voxy chat [-w WORKSPACE] [--deep] [--timeout SECONDS]             # interactive REPL
```

| Option | Description |
|--------|-------------|
| `-w, --workspace` | Workspace name or id (`general` forces the general chat; default: the `voxy use` workspace, else general) |
| `--deep` | Use the deep (slow, smart) model layer |
| `--timeout` | Seconds to wait for the full response (default 120) |

REPL commands: `/quit` (also `/exit`, `/q`) exits; `/deep` toggles deep mode.

### `voxy ws` — workspaces

```
voxy ws list [--json]                 # › marks the `voxy use` workspace
voxy ws create TITLE [-d DESCRIPTION]
voxy ws delete NAME_OR_ID [-y]        # -y skips confirmation
```

### `voxy cards` — kanban cards

```
voxy cards list [-w WORKSPACE] [--status STATUS] [--json]
voxy cards add TITLE [-w WORKSPACE] [-d DESCRIPTION]
voxy cards move CARD_ID STATUS        # backlog / todo / in-progress / done
voxy cards done CARD_ID
voxy cards rm CARD_ID [-y]
```

- `list` and `add` require a workspace — pass `-w` or set one with `voxy use`.
- `rm` archives the card first, then deletes it (the API requires archive-then-delete).

### `voxy workers` — background worker monitoring

```
voxy workers [list] [--status S] [-n LIMIT] [--json]   # default subcommand: list
voxy workers watch [-i INTERVAL] [-n LIMIT]            # live table, Ctrl-C to stop
voxy workers peek TASK_ID                               # live peek (DB fallback for finished tasks)
voxy workers steer TASK_ID MESSAGE                      # inject guidance into a running worker
voxy workers cancel TASK_ID
```

| Option | Description |
|--------|-------------|
| `--status` | Filter: `pending` / `running` / `done` / `failed` / `cancelled` |
| `-n, --limit` | Max tasks to show (default 20) |
| `-i, --interval` | Poll interval for `watch` in seconds (default 2.0) |

### `voxy jobs` — scheduled jobs

```
voxy jobs list [--json]
voxy jobs run JOB_ID      # trigger a job now
```

### `voxy skills` — installed skills

```
voxy skills list [--json]   # global and per-workspace skills
voxy skills show NAME       # render the skill's full SKILL.md
```

Tries `GET /api/skills` first, falling back to reading `SKILL.md` files directly from `~/.voxyflow/skills/` (global skills at the top level, workspace skills under `workspace-<uuid>/` subdirectories). `SKILL.md` carries YAML frontmatter with `name` and `description`.

### `voxy config` — backend settings

View and edit the backend's `/api/settings` from the terminal.

```
voxy config show [--json]      # view current settings (secrets redacted)
voxy config get PATH           # read one value by dotted path
voxy config set PATH VALUE     # set one value
```

- `voxy config get models.fast.model` — dotted paths address nested keys.
- `voxy config set` performs a read-modify-write of `/api/settings`. `VALUE` is parsed as JSON when possible (`true`, `42`, `{"a":1}`), otherwise treated as a string.
- Secrets (API keys) are redacted to `***` on read; sending `***` back on write preserves the real key server-side, so a `show`-edit-`set` round-trip never clobbers stored secrets.

### `voxy update` — update the install

```
voxy update [--check] [--no-restart] [--full]
```

Updates a running install in place: `git pull --ff-only`, then reinstalls Python dependencies and/or rebuilds the frontend **only when the pulled diff touches them** (`--full` forces both), restarts the systemd services, and waits for the backend to report healthy.

| Option | Description |
|--------|-------------|
| `--check` | Only report how far behind origin the install is — no changes |
| `--no-restart` | Pull and rebuild, but do not restart services |
| `--full` | Force both the Python dep reinstall and the frontend rebuild |

### `voxy doctor` — diagnostics

```
voxy doctor [--fix]
```

Runs a full diagnostic pass over the install:

- backend reachable, `/api/health` per-service details
- auth token valid; websocket connect
- systemd unit states
- running-backend commit vs local git commit (stale-code detection via `/api/version`)
- frontend build present
- chroma data dir, disk space
- `claude` CLI on PATH

`--fix` restarts inactive services and re-bootstraps an invalid token.

---

## Examples

```bash
# Point the CLI at a remote install
export VOXYFLOW_URL=https://voxyflow.my-tailnet.ts.net

# Work in a project for a while
voxy use myproject
voxy cards add "Write release notes" -d "v0.9 highlights"
voxy chat "what should I tackle first?"
voxy cards move 3f2a… in-progress

# Watch the workers grind
voxy workers watch

# Script against the API
voxy cards list --status todo --json | jq -r '.[].title'

# Keep the install fresh
voxy update --check && voxy update
```

---

## Tests

```bash
cd cli && python -m pytest tests/ -v
```

Tests are offline — no live backend required.
