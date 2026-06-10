#!/usr/bin/env bash
# Voxyflow installer — idempotent setup for a single-user local install.
#
# Usage: ./install.sh [--no-frontend] [--no-services] [-h|--help]
#
# Re-running this script is safe and doubles as the manual update path:
#   git pull && ./install.sh

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Pretty printing
# ---------------------------------------------------------------------------
if [[ -t 1 ]]; then
  BOLD=$'\033[1m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[0;33m'; RED=$'\033[0;31m'; RESET=$'\033[0m'
else
  BOLD=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

info() { echo "${GREEN}==>${RESET} ${BOLD}$*${RESET}"; }
warn() { echo "${YELLOW}warning:${RESET} $*" >&2; }
err()  { echo "${RED}error:${RESET} $*" >&2; }

# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
DO_FRONTEND=1
DO_SERVICES=1

usage() {
  cat <<EOF
Voxyflow installer

Usage: ./install.sh [options]

Options:
  --no-frontend   Skip npm install + production build of the React frontend
  --no-services   Skip systemd user service installation
  -h, --help      Show this help

The script is idempotent — re-run it after 'git pull' to update an
existing install (or use 'voxy update' once the CLI is installed).
EOF
}

for arg in "$@"; do
  case "$arg" in
    --no-frontend) DO_FRONTEND=0 ;;
    --no-services) DO_SERVICES=0 ;;
    -h|--help) usage; exit 0 ;;
    *) err "unknown option: $arg"; usage; exit 2 ;;
  esac
done

# ---------------------------------------------------------------------------
# 1. Prerequisites
# ---------------------------------------------------------------------------
info "Checking prerequisites"
MISSING=()

if ! command -v git >/dev/null 2>&1; then
  MISSING+=("git — install with your package manager (e.g. apt install git)")
fi

if command -v python3 >/dev/null 2>&1; then
  if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
    MISSING+=("python3 >= 3.10 — found $(python3 --version 2>&1)")
  fi
else
  MISSING+=("python3 (>= 3.10)")
fi

if command -v node >/dev/null 2>&1; then
  NODE_MAJOR="$(node --version | sed 's/^v//' | cut -d. -f1)"
  if [[ "${NODE_MAJOR:-0}" -lt 20 ]]; then
    MISSING+=("node >= 20 — found $(node --version)")
  fi
else
  MISSING+=("node (>= 20) + npm — see https://nodejs.org or use nvm")
fi

if ! command -v npm >/dev/null 2>&1; then
  MISSING+=("npm — usually ships with node")
fi

if [[ ${#MISSING[@]} -gt 0 ]]; then
  err "missing prerequisites:"
  for m in "${MISSING[@]}"; do
    echo "  - $m" >&2
  done
  exit 1
fi
echo "    git, python3, node, npm all OK"

# ---------------------------------------------------------------------------
# 2. Backend — venv + dependencies
# ---------------------------------------------------------------------------
VENV="$REPO_DIR/backend/venv"
if [[ ! -d "$VENV" ]]; then
  info "Creating Python virtualenv at backend/venv"
  python3 -m venv "$VENV"
else
  info "Reusing existing virtualenv at backend/venv"
fi

info "Installing backend dependencies (this can take a few minutes on first run)"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$REPO_DIR/backend/requirements.txt"
echo "    backend dependencies installed"

# ---------------------------------------------------------------------------
# 3. Config — backend/.env
# ---------------------------------------------------------------------------
if [[ ! -f "$REPO_DIR/backend/.env" ]]; then
  info "Creating backend/.env from .env.example"
  cp "$REPO_DIR/backend/.env.example" "$REPO_DIR/backend/.env"
  echo "    review backend/.env to pick your LLM provider (defaults to Claude CLI)"
else
  info "backend/.env already exists — leaving it untouched"
fi

# ---------------------------------------------------------------------------
# 4. CLI — voxy
# ---------------------------------------------------------------------------
info "Installing the voxy CLI into the venv"
"$VENV/bin/pip" install --quiet -e "$REPO_DIR/cli"
mkdir -p "$HOME/.local/bin"
ln -sf "$VENV/bin/voxy" "$HOME/.local/bin/voxy"
echo "    symlinked ~/.local/bin/voxy -> backend/venv/bin/voxy"
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) warn "~/.local/bin is not on your PATH — add 'export PATH=\"\$HOME/.local/bin:\$PATH\"' to your shell profile to use 'voxy'" ;;
esac

# ---------------------------------------------------------------------------
# 5. Frontend — build
# ---------------------------------------------------------------------------
if [[ "$DO_FRONTEND" -eq 1 ]]; then
  info "Installing frontend dependencies"
  (cd "$REPO_DIR/frontend-react" && npm install --no-audit --no-fund)
  info "Building frontend (production)"
  (cd "$REPO_DIR/frontend-react" && npm run build)
else
  info "Skipping frontend build (--no-frontend)"
fi

# ---------------------------------------------------------------------------
# 6. systemd user services
# ---------------------------------------------------------------------------
SERVICES_INSTALLED=0
if [[ "$DO_SERVICES" -eq 1 ]]; then
  if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    info "Installing systemd user services"
    UNIT_DIR="$HOME/.config/systemd/user"
    mkdir -p "$UNIT_DIR"
    # The backend spawns node-based CLIs (claude, codex); nvm installs live
    # outside the default PATH, so bake the detected node bin dir into the unit.
    NODE_BIN_DIR="$(dirname "$(command -v node)")"
    for name in voxyflow-backend voxyflow-frontend; do
      template="$REPO_DIR/scripts/systemd/${name}.service.template"
      target="$UNIT_DIR/${name}.service"
      rendered="$(sed -e "s|@REPO_DIR@|$REPO_DIR|g" -e "s|@NODE_BIN@|$NODE_BIN_DIR|g" "$template")"
      if [[ -f "$target" ]] && ! diff -q <(printf '%s\n' "$rendered") "$target" >/dev/null 2>&1; then
        cp "$target" "${target}.bak"
        echo "    existing ${name}.service differs — backed up to ${name}.service.bak"
      fi
      printf '%s\n' "$rendered" > "$target"
      echo "    installed ${name}.service"
    done
    systemctl --user daemon-reload
    systemctl --user enable --now voxyflow-backend voxyflow-frontend
    SERVICES_INSTALLED=1

    # Linger lets user services start at boot without an interactive login.
    if command -v loginctl >/dev/null 2>&1; then
      LINGER="$(loginctl show-user "$USER" --property=Linger --value 2>/dev/null || echo unknown)"
      if [[ "$LINGER" == "no" ]]; then
        info "Enabling linger so services start at boot (loginctl enable-linger)"
        loginctl enable-linger "$USER" || warn "could not enable linger — run 'loginctl enable-linger $USER' manually"
      fi
    else
      echo "    note: run 'loginctl enable-linger $USER' so services start at boot without login"
    fi
  else
    warn "systemctl --user is unavailable — skipping service installation"
    echo "    start the backend manually with:" >&2
    echo "      cd backend && venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000" >&2
  fi
else
  info "Skipping systemd services (--no-services)"
fi

# ---------------------------------------------------------------------------
# 7. Verification
# ---------------------------------------------------------------------------
health_ok=0
if [[ "$SERVICES_INSTALLED" -eq 1 ]]; then
  info "Waiting for backend health check (up to 30s)"
  for _ in $(seq 1 30); do
    if curl -fsS "http://localhost:8000/health" >/dev/null 2>&1; then
      health_ok=1
      break
    fi
    sleep 1
  done
  if [[ "$health_ok" -eq 1 ]]; then
    echo
    info "Voxyflow is up!"
    echo "    Backend:  http://localhost:8000  (health: http://localhost:8000/health)"
    echo "    Frontend: http://localhost:3000"
    echo "    CLI:      try 'voxy status'"
    echo
    echo "    To update later: 'voxy update', or 'git pull && ./install.sh'"
  else
    err "backend did not respond on http://localhost:8000/health within 30s"
    echo "    check the logs:" >&2
    echo "      tail -n 100 /tmp/voxyflow-backend.log" >&2
    echo "      systemctl --user status voxyflow-backend" >&2
    exit 1
  fi
else
  echo
  info "Install finished (services not started)"
  echo "    Start the backend:  cd backend && venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000"
  [[ "$DO_FRONTEND" -eq 1 ]] && echo "    Serve the frontend: frontend-react/dist (any static server, port 3000)"
  echo "    Then check:         curl http://localhost:8000/health"
fi
