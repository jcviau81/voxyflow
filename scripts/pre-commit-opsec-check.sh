#!/usr/bin/env bash
# Pre-commit hook: refuse commits containing identifying infra info.
# Install with: ln -s ../../scripts/pre-commit-opsec-check.sh .git/hooks/pre-commit

set -euo pipefail

FORBIDDEN_PATTERN='ROG|TheThing|snaf\.foo|snaffoo|Corsair|thething|tail6531d|jcviau\.rm|/home/jcviau|100\.67\.12\.87|100\.96\.26\.98|100\.80\.12\.91|id_ed25519_rog|id_ed25519_ember'

# Get staged files (text files only)
FILES=\$(git diff --cached --name-only --diff-filter=ACM | grep -Ev '\.(png|jpg|jpeg|gif|ico|woff|woff2|ttf|otf|pdf)\$' || true)

if [ -z "\$FILES" ]; then
  exit 0
fi

HITS=0
for file in \$FILES; do
  if [ -f "\$file" ]; then
    if grep -nE "\$FORBIDDEN_PATTERN" "\$file" 2>/dev/null; then
      echo -e "\n❌ OPSEC violation in \$file (above)" >&2
      HITS=\$((HITS+1))
    fi
  fi
done

if [ "\$HITS" -gt 0 ]; then
  echo -e "\n💥 \$HITS file(s) contain identifying infra info. Sanitize before committing." >&2
  echo "   See INFRA.md § placeholders and INFRA.local.md.example for the convention." >&2
  echo "   Bypass at your own risk: git commit --no-verify" >&2
  exit 1
fi

exit 0
