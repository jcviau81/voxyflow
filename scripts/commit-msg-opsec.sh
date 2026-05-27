#!/usr/bin/env bash
# Called by git as: commit-msg-opsec.sh <path-to-COMMIT_EDITMSG>
exec "$(dirname "${BASH_SOURCE[0]}")/opsec-check.sh" --file "$1"
