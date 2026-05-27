#!/usr/bin/env bash
# OPSEC scanner. Scans either staged files (pre-commit) or stdin (commit-msg).
# Usage:
#   opsec-check.sh --staged              # scan files in git --cached
#   opsec-check.sh --stdin               # scan one input from stdin (commit message)
#   opsec-check.sh --file <path>         # scan a single file
#
# Exit codes: 0 = clean, 1 = violation found, 2 = config/IO error.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATTERNS_FILE="$SCRIPT_DIR/opsec-patterns.txt"
ALLOW_FILE="$SCRIPT_DIR/opsec-allow.txt"
LOG_FILE=".git/opsec-check.log"

RED=$'\033[0;31m'
YELLOW=$'\033[0;33m'
GREEN=$'\033[0;32m'
BOLD=$'\033[1m'
RESET=$'\033[0m'

[[ -f "$PATTERNS_FILE" ]] || { echo "opsec-check: missing $PATTERNS_FILE" >&2; exit 2; }

# Build patterns: strip comments and empty lines, join with |
PATTERNS=$(grep -vE '^[[:space:]]*(#|$)' "$PATTERNS_FILE" | tr '\n' '|' | sed 's/|$//')
ALLOW_PATTERNS=""
if [[ -f "$ALLOW_FILE" ]]; then
  ALLOW_PATTERNS=$(grep -vE '^[[:space:]]*(#|$)' "$ALLOW_FILE" | tr '\n' '|' | sed 's/|$//')
fi

log_event() {
  mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true
  printf '{"ts":"%s","event":"%s","file":"%s","line":"%s","match":%s}\n' \
    "$(date -u +%FT%TZ)" "$1" "$2" "$3" "$(printf '%s' "$4" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" \
    >> "$LOG_FILE" 2>/dev/null || true
}

is_allowed() {
  local line="$1"
  [[ -z "$ALLOW_PATTERNS" ]] && return 1
  echo "$line" | grep -qE "$ALLOW_PATTERNS"
}

scan_text() {
  local label="$1"
  local content="$2"
  local violations=0
  # grep -P for PCRE (jcviau negative lookahead). On macOS, fall back to grep -E without that feature.
  if echo "" | grep -P '' >/dev/null 2>&1; then
    GREPCMD=(grep -nP)
  else
    # macOS doesn't have -P. Strip the negative-lookahead pattern from PATTERNS and warn.
    GREPCMD=(grep -nE)
  fi
  # Capture matches with context
  while IFS=: read -r linenum hit; do
    [[ -z "$linenum" ]] && continue
    if is_allowed "$hit"; then
      log_event allowed "$label" "$linenum" "$hit"
      continue
    fi
    violations=$((violations+1))
    echo "${RED}${BOLD}❌ OPSEC violation${RESET} in ${BOLD}${label}${RESET}:${linenum}" >&2
    echo "   ${YELLOW}${hit}${RESET}" >&2
    log_event violation "$label" "$linenum" "$hit"
  done < <(echo "$content" | "${GREPCMD[@]}" "$PATTERNS" || true)
  return $violations
}

# Files that necessarily contain the trigger patterns by design (the OPSEC
# system's own source code and tests). Matched against the path with grep -E.
EXEMPT_PATHS_RE='^scripts/opsec-(patterns|allow|check|exempt)\.|^scripts/(pre-commit|commit-msg)-opsec\.sh$|^scripts/install-opsec-hooks\.sh$|^backend/tests/test_opsec_check\.sh$'

scan_file() {
  local f="$1"
  [[ -f "$f" ]] || return 0
  # Skip the scanner's own source files (they contain the trigger patterns by design).
  if echo "$f" | grep -qE "$EXEMPT_PATHS_RE"; then
    return 0
  fi
  # Skip binary
  if file --mime "$f" 2>/dev/null | grep -q 'charset=binary'; then
    return 0
  fi
  scan_text "$f" "$(cat "$f")"
}

main() {
  local mode="${1:-}"
  local total=0
  case "$mode" in
    --staged)
      local files
      files=$(git diff --cached --name-only --diff-filter=ACM \
              | grep -Ev '\.(png|jpg|jpeg|gif|ico|woff|woff2|ttf|otf|pdf|svg|webp|mp4|webm)$' || true)
      [[ -z "$files" ]] && exit 0
      while IFS= read -r f; do
        [[ -z "$f" ]] && continue
        scan_file "$f" || total=$((total + $?))
      done <<< "$files"
      ;;
    --stdin)
      scan_text "<commit-msg>" "$(cat)" || total=$?
      ;;
    --file)
      scan_file "${2:?missing path}" || total=$?
      ;;
    *)
      echo "usage: $0 {--staged | --stdin | --file <path>}" >&2
      exit 2
      ;;
  esac

  if (( total > 0 )); then
    echo >&2
    echo "${RED}${BOLD}💥 $total OPSEC violation(s) found.${RESET}" >&2
    echo "   See INFRA.md § placeholders and INFRA.local.md.example for the convention." >&2
    echo "   Audit log: $LOG_FILE" >&2
    echo "   Bypass (last resort): git commit --no-verify" >&2
    exit 1
  fi
  echo "${GREEN}✓ OPSEC scan clean${RESET}" >&2
  exit 0
}

main "$@"
