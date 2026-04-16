"""Tool Role Boundary — regression tests

Dispatcher chats (fast + deep) must stay lightweight and non-blocking. Dangerous
tools — shell exec, filesystem writes, git mutation, web fetch, destructive ops —
are worker-only. This test fails if someone widens TOOLS_DISPATCHER to include
anything on the forbidden list.

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
    "system.exec",
    "file.write", "file.patch",
    "git.commit",
    "web.fetch", "web.search",
    "tmux.run", "tmux.send", "tmux.new", "tmux.kill",
    "voxyflow.project.delete", "voxyflow.card.delete", "voxyflow.doc.delete",
    "voxyflow.project.export",
    "memory.delete",
    "kg.invalidate",
    "task.steer",
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


def test_role_sets_map_legacy_layer_names():
    """fast/deep legacy names must still resolve to dispatcher tools."""
    assert _ROLE_TOOL_SETS["fast"] is TOOLS_DISPATCHER
    assert _ROLE_TOOL_SETS["deep"] is TOOLS_DISPATCHER
    assert _ROLE_TOOL_SETS["dispatcher"] is TOOLS_DISPATCHER
    assert _ROLE_TOOL_SETS["worker"] is TOOLS_WORKER


def test_worker_gets_dangerous_tools():
    """Sanity check: workers DO get the heavy tools (otherwise the boundary is moot)."""
    expected_worker_only = {"system.exec", "file.write", "git.commit", "web.fetch"}
    missing = expected_worker_only - TOOLS_WORKER
    assert not missing, (
        f"Worker role is missing expected tools: {missing}. "
        "If you removed these, update the regression test."
    )


def test_memory_save_schema_has_no_project_id():
    """STRICT ISOLATION: memory.save must not expose project_id in its schema.

    Scope is enforced server-side via VOXYFLOW_PROJECT_ID env var. A schema
    that exposes project_id lets the LLM write cross-project — violates
    CLAUDE.md §"Project Isolation" §3.
    """
    from app.mcp_server import _TOOL_DEFINITIONS
    mem_save = next((t for t in _TOOL_DEFINITIONS if t["name"] == "memory.save"), None)
    assert mem_save is not None, "memory.save tool definition missing"
    props = mem_save["inputSchema"].get("properties", {})
    assert "project_id" not in props, (
        "memory.save schema exposes project_id — the LLM must not override "
        "project scope. Scope is enforced via VOXYFLOW_PROJECT_ID env var."
    )


def test_knowledge_search_schema_has_no_project_id():
    """STRICT ISOLATION: knowledge.search must not expose project_id."""
    from app.mcp_server import _TOOL_DEFINITIONS
    ks = next((t for t in _TOOL_DEFINITIONS if t["name"] == "knowledge.search"), None)
    assert ks is not None, "knowledge.search tool definition missing"
    props = ks["inputSchema"].get("properties", {})
    required = ks["inputSchema"].get("required", [])
    assert "project_id" not in props, (
        "knowledge.search schema exposes project_id — scope must come from "
        "VOXYFLOW_PROJECT_ID env var only."
    )
    assert "project_id" not in required
