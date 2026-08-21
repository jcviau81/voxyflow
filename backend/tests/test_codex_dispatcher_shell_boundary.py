"""The Codex dispatcher must have no shell tool — and workers must keep theirs.

The dispatcher boundary was originally enforced with `-s read-only` alone. That
relies on bubblewrap, which cannot start on Ubuntu 24.04+ with
``kernel.apparmor_restrict_unprivileged_userns=1``: the shell does not come back
read-only, it comes back as a raw ``bwrap: loopback: Failed RTM_NEWADDR`` at call
time, which the dispatcher then reports to the user ("I couldn't run npm run
validate") instead of delegating to a worker.

Dropping the tool makes the boundary legible to the model rather than a runtime
failure. `-s read-only` stays for apply_patch, which this flag does not cover.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.llm.codex_backend import (  # noqa: E402
    _CODEX_SANDBOX_MODE,
    _DISPATCHER_DISABLED_TOOL,
    _DISPATCHER_ROLES,
    _DISPATCHER_SANDBOX_MODE,
    CodexCliBackend,
)


def _args(role: str, sandbox: str = _CODEX_SANDBOX_MODE) -> list[str]:
    return CodexCliBackend()._build_args("gpt-5.4", mcp_role=role, sandbox=sandbox)


def _disabled(args: list[str]) -> list[str]:
    return [args[i + 1] for i, a in enumerate(args) if a == "--disable" and i + 1 < len(args)]


@pytest.mark.parametrize("role", sorted(_DISPATCHER_ROLES))
def test_dispatcher_has_no_shell_tool(role):
    args = _args(role)
    assert _DISPATCHER_DISABLED_TOOL in _disabled(args), (
        f"{role} kept Codex's built-in shell tool; the read-only sandbox alone "
        "cannot block it on a host where bwrap will not start"
    )


@pytest.mark.parametrize("role", sorted(_DISPATCHER_ROLES))
def test_dispatcher_keeps_read_only_sandbox_for_apply_patch(role):
    args = _args(role)
    assert "-s" in args
    assert args[args.index("-s") + 1] == _DISPATCHER_SANDBOX_MODE


def test_dispatcher_sandbox_cannot_be_widened_by_caller():
    args = _args("dispatcher_codex", sandbox="danger-full-access")
    assert args[args.index("-s") + 1] == _DISPATCHER_SANDBOX_MODE
    assert _DISPATCHER_DISABLED_TOOL in _disabled(args)


def test_worker_keeps_its_shell_and_full_access():
    args = _args("worker")
    assert _DISPATCHER_DISABLED_TOOL not in _disabled(args), (
        "workers lost the shell tool — they need it to run builds and tests"
    )
    assert args[args.index("-s") + 1] == _CODEX_SANDBOX_MODE


def test_worker_default_sandbox_avoids_bwrap():
    """danger-full-access is what keeps workers off the broken bwrap path."""
    assert _CODEX_SANDBOX_MODE == "danger-full-access"
