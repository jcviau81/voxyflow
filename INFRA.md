# Voxyflow Infrastructure

_Last updated: 2026-05-26_

> 📝 This file contains the generic infrastructure topology and runbooks for Voxyflow.
> Maintainers: for the actual hostnames, IPs, SSH config, and credentials, see your local \`INFRA.local.md\` (gitignored).

This document is the source of truth for Voxyflow infrastructure: machines, branches, deploy loop, CI, and operational runbooks. Update it whenever the topology changes.

## Machines

| Role | Host | Tailscale | Description |
|------|------|-----------|-------------|
| **prod** | \`<PROD_HOST>\` | \`<TAILSCALE_IP>\` on \`<TAILSCALE_DOMAIN>\` | Live Voxyflow instance serving the dispatcher. Pull manually after merge to \`main\`. Reserved ports: 8000 (FastAPI), 18789 (Caddy). |
| **dev-primary** | \`<DEV_HOST>\` | \`<DEV_HOST_URL>\` on \`<TAILSCALE_DOMAIN>\` | Auto-deploys \`dev\` branch every 5 min via systemd timer. GPU-equipped, Caddy HTTPS reverse proxy, user-mode systemd. |
| **site host** | \`<SITE_HOST>\` | \`<TAILSCALE_IP>\` on \`<TAILSCALE_DOMAIN>\` | Hosts ONLY the static promotional site \`<SITE_PUBLIC_URL>\` (rsync target from local \`voxyflow-site\` repo). Has nothing to do with Voxyflow runtime. |

## Branching strategy

- **\`main\`** = production. Protected: PR required, force-push disabled, deletions disabled, conversation resolution required, enforce_admins=false (sole maintainer bypass for emergencies).
- **\`dev\`** = active development. Auto-deploys to dev-primary host. Open to direct push from maintainer.
- **\`feature/*\`** = feature branches. Workflow: branch from dev -> PR to dev -> validate on dev-primary host -> PR dev -> main -> manual pull on prod host.

Full workflow doc: see \`CONTRIBUTING.md\` § Branching Strategy.

## dev-primary host

### SSH access
\`\`\`bash
ssh <DEV_HOST>   # via stanza in ~/.ssh/config
# manual equivalent:
ssh -i ~/.ssh/<DEV_SSH_KEY> <USER>@<DEV_HOST_URL>
\`\`\`
The dev SSH key may be a symlink to the site host SSH key (same physical key, different intent label). It also authorises git push from dev-primary host to \`github.com/jcviau81\`.

### Services (user-mode systemd)
- \`voxyflow-backend.service\` — FastAPI backend (port from \`backend/.env\`)
- \`voxyflow-frontend.service\` — Vite-built frontend served
- \`xtts.service\` — XTTS voice synthesis (:5500)
- All three: \`systemctl --user enable\`d on boot, \`loginctl enable-linger <USER>\` set so they survive logout.

### Repo + venv layout
- \`~/voxyflow/\` — code (git, branch \`dev\`)
- \`~/voxyflow/backend/.venv/\` — Python 3.13 venv (created with \`uv venv --seed\` because system python lacks ensurepip)
- \`~/voxyflow/frontend-react/\` — Node 24 + vite
- \`~/.voxyflow/\` — runtime data (DB, sessions, chroma, attachments, settings)
- \`~/.voxyflow.backup-2026-05-26/\` — pre-wipe snapshot (102 MB), delete after ~1 month if stable
- \`~/voxyflow.old-2026-05-26/\` — pre-wipe code snapshot (6.6 GB), delete after ~1 month if stable

### Auto-deploy loop (pull-based, no GH secrets)
- Script: \`~/voxyflow-deploy/deploy-dev.sh\` — fetches origin/dev, fast-forwards, conditionally reinstalls backend deps (if requirements.txt changed) / rebuilds frontend (if package.json or sources changed), restarts services.
- Timer: \`~/.config/systemd/user/voxyflow-deploy-dev.{service,timer}\` — cadence 5 min, fires \`OnBootSec=2min\` + \`OnUnitActiveSec=5min\`.
- Log: \`~/voxyflow-deploy/deploy.log\` (rolling).
- Smoke-tested 2026-05-26 (commit 0323983): push to dev -> 5 min later detected, pulled, restarted, backend curl 200.

## CI (GitHub Actions)

\`.github/workflows/ci.yml\` runs on push + PR to [dev, main]:
- **backend** — pytest (excluding tests/e2e) + ruff F821 + isolation smoke test (\`scripts/smoke_test_isolation.py\`), python 3.13
- **frontend** — \`npx tsc --noEmit\` + \`npm run build\`, node 24, \`npm ci\` from lockfile
- \`concurrency: cancel-in-progress\` to drop superseded runs

Future ratchet: once first green run on dev is observed, add \`ci.yml / backend\` and \`ci.yml / frontend\` to required_status_checks on main protection.

## Runbooks

### Promote dev -> main (release to prod)
1. From local: \`gh pr create --base main --head dev --title "release: <date>"\`
2. Wait CI green on PR
3. Merge PR via GitHub UI
4. SSH prod host and: \`cd ~/voxyflow && git pull origin main && systemctl restart voxyflow-backend\` (or whatever the prod restart procedure is)

### Wipe + reinstall dev-primary host (full reset)
See \`docs/runbooks/dev-host-reinstall.md\` (or this section as fallback):
1. \`systemctl --user stop voxyflow-backend voxyflow-frontend xtts\`
2. \`mv ~/.voxyflow ~/.voxyflow.backup-YYYY-MM-DD && mv ~/voxyflow ~/voxyflow.old-YYYY-MM-DD\`
3. \`git clone https://github.com/jcviau81/voxyflow.git ~/voxyflow && cd ~/voxyflow && git checkout dev\`
4. **CRITICAL**: \`cp ~/voxyflow.old-YYYY-MM-DD/backend/.env ~/voxyflow/backend/.env\` (config, not data — needed for systemd EnvironmentFile)
5. \`cd ~/voxyflow/backend && uv venv --seed .venv && source .venv/bin/activate && pip install -r requirements.txt\`
6. \`cd ~/voxyflow/frontend-react && rm -rf node_modules package-lock.json && npm install && npm run build\` (clean reinstall to avoid missing .d.ts files)
7. \`systemctl --user start voxyflow-backend voxyflow-frontend xtts\`
8. Verify: \`curl https://<DEV_HOST_URL>/api/workspaces\` -> 200 (NOT /health — that's currently a SPA catch-all, see backlog card 55156055)

### Demo environment
The dev-primary host is dev-exclusive. If a demo env is needed for a recording, spin up a separate temporary instance (e.g. Docker container or other Tailscale node). Do NOT cohabit demo with dev on the dev-primary host.

### Codex CLI on dev-primary host
- Installed by JC 2026-05-26, authenticated via \`~/.codex/\`
- Symlink: \`~/.local/bin/codex -> ~/.codex/packages/standalone/current/bin/codex\`
- NEVER touched by reinstall procedure (config lives outside \`~/voxyflow/\` and \`~/.voxyflow/\`)

## Known limitations / backlog
- Backend has no real \`/health\` route — currently a SPA catch-all returns 200 (false positive). Tracked in card \`55156055\`.
- Main branch protection has no required_status_checks yet (waiting for first green CI run on dev).
- No automated test for the auto-deploy loop beyond manual smoke test.
