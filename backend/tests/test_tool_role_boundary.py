"""Tool Role Boundary — regression tests

Dispatcher chats must stay lightweight and non-blocking, regardless of which
model tier (fast/deep) is driving them. Dangerous tools — shell exec, filesystem
writes, git mutation, web fetch, destructive ops — are worker-only. This test
fails if someone widens TOOLS_DISPATCHER to include anything on the forbidden
list, or if fast/deep ever creep back into the role map as if they were tool
tiers (they are not — they are pure model selection).

Invariant from CLAUDE.md §"Tool Access Architecture":
    When adding new tools: add to TOOLS_WORKER. Only add to TOOLS_DISPATCHER
    if the tool is instant, non-blocking, and safe for inline chat.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.tools.registry import TOOLS_DISPATCHER, TOOLS_WORKER, _ROLE_TOOL_SETS


# Any of these in TOOLS_DISPATCHER is a regression. Add to this list if you
# coin new dangerous tool names.
FORBIDDEN_DISPATCHER_TOOLS = {
    # OS / dev-environment access — never inline.
    "system.exec",
    "file.write", "file.patch",
    "git.commit",
    "web.fetch", "web.search",
    "tmux.run", "tmux.send", "tmux.new", "tmux.kill",
    # Heavy AI — synchronous LLM call, blocks inline chat (CLAUDE.md lists it
    # as worker-only alongside voxyflow.ai.*).
    "voxyflow.card.enrich",
    # Programmatic tool calling — runs arbitrary Python in the MCP subprocess.
    # Same boundary as system.exec: worker-only forever.
    "voxyflow.script",
    # NOTE: the following are intentionally NOT forbidden — Voxyflow is
    # single-user local and these are instant DB / queue ops the dispatcher
    # needs inline:
    #   * whole-entity *.delete and *.export (workspace/card/doc/wiki) —
    #     reversible via the undo journal (voxyflow.undo.*)
    #   * memory.delete — local Chroma op, scope-enforced via env var
    #   * task.steer — pairs with task.peek/cancel for worker control
    #   * kg.* including kg.invalidate — temporal model (sets valid_to,
    #     doesn't hard-delete), and KG is local single-user state
    # Don't re-add any of these here without re-checking the policy.
}


def test_dispatcher_is_subset_of_worker():
    """TOOLS_DISPATCHER must be a strict subset of TOOLS_WORKER.

    The worker role sees everything the dispatcher sees (plus more).
    If this fails, someone added a dispatcher-only tool that workers can't use.
    """
    extras = TOOLS_DISPATCHER - TOOLS_WORKER
    assert not extras, (
        f"TOOLS_DISPATCHER has tools not in TOOLS_WORKER: {extras}. "
        "Add them to TOOLS_WORKER or move them out of TOOLS_DISPATCHER."
    )


def test_dispatcher_excludes_dangerous_tools():
    """TOOLS_DISPATCHER must not contain any forbidden (heavy/destructive) tool."""
    leaked = TOOLS_DISPATCHER & FORBIDDEN_DISPATCHER_TOOLS
    assert not leaked, (
        f"Dispatcher role exposes forbidden tools: {leaked}. "
        "These must be worker-only (inline chat cannot block on them)."
    )


def test_dispatcher_tools_are_all_known():
    """Every tool in TOOLS_DISPATCHER must resolve against mcp_server definitions.

    Catches typos — a renamed tool silently falling out of the dispatcher set.
    """
    from app.mcp_server import _TOOL_DEFINITIONS
    known = {t["name"] for t in _TOOL_DEFINITIONS}
    unknown = TOOLS_DISPATCHER - known
    assert not unknown, (
        f"TOOLS_DISPATCHER references tool names not in _TOOL_DEFINITIONS: {unknown}"
    )


def test_role_sets_only_define_real_roles():
    """Only "dispatcher" and "worker" are real roles — the same for any model
    or provider. There is no provider-specific role: a Codex dispatcher uses the
    standard "dispatcher" set (tool lists live in registry.py per role, not per
    provider). fast/deep are model tiers, NOT tool tiers. Any unknown role string
    (incl. a legacy "dispatcher_codex") falls back to dispatcher via
    get_by_role()'s default.
    """
    assert _ROLE_TOOL_SETS == {
        "dispatcher": TOOLS_DISPATCHER,
        "worker": TOOLS_WORKER,
    }


def test_worker_gets_dangerous_tools():
    """Sanity check: workers DO get the heavy tools (otherwise the boundary is moot)."""
    expected_worker_only = {"system.exec", "file.write", "git.commit", "web.fetch"}
    missing = expected_worker_only - TOOLS_WORKER
    assert not missing, (
        f"Worker role is missing expected tools: {missing}. "
        "If you removed these, update the regression test."
    )


def test_memory_save_schema_has_no_workspace_id():
    """STRICT ISOLATION: memory.save must not expose workspace_id in its schema.

    Scope is enforced server-side via VOXYFLOW_WORKSPACE_ID env var. A schema
    that exposes workspace_id lets the LLM write cross-workspace — violates
    CLAUDE.md §"Workspace Isolation" §3.
    """
    from app.mcp_server import _TOOL_DEFINITIONS
    mem_save = next((t for t in _TOOL_DEFINITIONS if t["name"] == "memory.save"), None)
    assert mem_save is not None, "memory.save tool definition missing"
    props = mem_save["inputSchema"].get("properties", {})
    assert "workspace_id" not in props, (
        "memory.save schema exposes workspace_id — the LLM must not override "
        "workspace scope. Scope is enforced via VOXYFLOW_WORKSPACE_ID env var."
    )


def test_knowledge_search_schema_has_no_workspace_id():
    """STRICT ISOLATION: knowledge.search must not expose workspace_id."""
    from app.mcp_server import _TOOL_DEFINITIONS
    ks = next((t for t in _TOOL_DEFINITIONS if t["name"] == "knowledge.search"), None)
    assert ks is not None, "knowledge.search tool definition missing"
    props = ks["inputSchema"].get("properties", {})
    required = ks["inputSchema"].get("required", [])
    assert "workspace_id" not in props, (
        "knowledge.search schema exposes workspace_id — scope must come from "
        "VOXYFLOW_WORKSPACE_ID env var only."
    )
    assert "workspace_id" not in required
