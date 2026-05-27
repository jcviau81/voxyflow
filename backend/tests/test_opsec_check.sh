#!/usr/bin/env bash
# Unit tests for opsec-check.sh. Run with: bash backend/tests/test_opsec_check.sh
set -euo pipefail
SCRIPT="$(git rev-parse --show-toplevel)/scripts/opsec-check.sh"
PASS=0; FAIL=0
assert_exit() {
  local desc="$1"; local expected="$2"; shift 2
  set +e; "$@" >/dev/null 2>&1; local actual=$?; set -e
  if [[ "$actual" == "$expected" ]]; then
    echo "✓ $desc"; PASS=$((PASS+1))
  else
    echo "✗ $desc — expected exit $expected, got $actual"; FAIL=$((FAIL+1))
  fi
}
# Stdin mode
assert_exit 'clean commit message passes'      0 bash -c "echo 'feat: add new feature' | $SCRIPT --stdin"
assert_exit 'ROG in commit msg fails'          1 bash -c "echo 'fix: deployed on ROG' | $SCRIPT --stdin"
assert_exit 'TheThing in commit msg fails'     1 bash -c "echo 'pulled TheThing' | $SCRIPT --stdin"
assert_exit 'CGNAT IP in commit msg fails'     1 bash -c "echo 'tested at 100.67.12.87' | $SCRIPT --stdin"
assert_exit 'jcviau81 (gh username) passes'    0 bash -c "echo 'https://github.com/jcviau81/voxyflow' | $SCRIPT --stdin"
assert_exit 'PROGRESS does not trigger ROG'    0 bash -c "echo 'WORK IN PROGRESS' | $SCRIPT --stdin"
assert_exit 'bare jcviau fails'                1 bash -c "echo 'login as jcviau' | $SCRIPT --stdin"
assert_exit 'tailscale subdomain fails'        1 bash -c "echo 'ssh rog.tail6531d.ts.net' | $SCRIPT --stdin"
assert_exit '/home/jcviau path fails'          1 bash -c "echo 'cd /home/jcviau/voxyflow' | $SCRIPT --stdin"
assert_exit 'id_ed25519_rog key fails'         1 bash -c "echo 'ssh -i id_ed25519_rog' | $SCRIPT --stdin"
echo ""
echo "Result: $PASS passed, $FAIL failed."
exit $((FAIL > 0))
