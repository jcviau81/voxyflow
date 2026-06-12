"""Refactor guard: app.mcp_tool_defs split into the app.mcp_tools_defs package.

Asserts the aggregated ``_TOOL_DEFINITIONS`` list is IDENTICAL to the
pre-split monolith: same tool names in the same order, same structure
(deep hash), and the ``_post_process`` values are the SAME function objects
as the helpers in ``app.mcp_tools_defs.postprocess``.

The snapshot below was taken from the monolithic ``app/mcp_tool_defs.py``
at commit 1ebc093, immediately before the split.
"""

import hashlib
import json

# Importing app.mcp_server is load-bearing for the hash check below:
# _build_consolidated_tools() runs at module load and auto-assigns
# `_scope = "voxyflow"` to ungrouped voxyflow.* tools that lack one (a
# deterministic, env-independent mutation that predates the split). Forcing
# the import here makes the structural hash stable regardless of which other
# tests ran first.
import app.mcp_server  # noqa: F401
from app.mcp_tool_defs import _TOOL_DEFINITIONS
from app.mcp_tools_defs import (
    DELEGATE_TOOLS,
    ENDPOINT_TOOLS,
    KANBAN_TOOLS,
    MEMORY_KG_TOOLS,
    OPS_JOBS_TOOLS,
    SCRIPT_TOOLS,
    SKILL_TOOLS,
    SYSTEM_TOOLS,
    TASK_STEER_TOOLS,
    WIKI_DOCS_AI_TOOLS,
    WORKER_LIFECYCLE_TOOLS,
    WORKERS_MONITOR_TOOLS,
    postprocess,
)

# ---------------------------------------------------------------------------
# Pre-split snapshot (names in original order + deep structural hash)
# ---------------------------------------------------------------------------

# Hash of the monolithic list AFTER app.mcp_server's import-time _scope
# auto-assign (see import note above). The raw pre-import hash of the same
# monolith was 485855c6ca20f3f613b8673efe90984da4ffaf6548ec3bd6289c9998f1dba261;
# the split list reproduced it exactly before the mutation as well.
# 2026-06: re-pinned after adding SKILL_TOOLS + SCRIPT_TOOLS (105 → 110 tools);
# the previous snapshot was d00bfd752f44180443318df7c60cb69059fd195313b3e1206e695de915ed90d1.
# 2026-06-10: re-pinned after adding voxyflow.jobs.schedule_nl to OPS_JOBS_TOOLS
# (110 → 111 tools); the previous snapshot was
# 058e08a36e03fe94475a890396143c4934f9295f612527b5eb2d86e4a7af76a6.
# 2026-06-11: re-pinned after slimming voxyflow.workspace.list (new
# _post_process + description — large lists spilled to unreadable files in
# dispatcher chats); the previous snapshot was
# 484f131153e9264e29d2b243b677c253f4bb03a1e2fa54c7cb07e49e70093c49.
# 2026-06-11 (2): re-pinned for the dispatcher-rules overhaul: minimizers on
# workspace.get/card.get/card.history/wiki.get, status filters on
# workspace.list/card.list, get_result+read_artifact pagination params,
# delegate description rewrite, memory.delete bulk ids; previous snapshot was
# dc0154e2e784ed273f3b451398d57e7fb65f416b101a5e0dd6fabc8ed7c3d25c.
SNAPSHOT_SHA256 = "5f75da0110705316e73e97d457dc2c4575ae7dace85ebde0b81866f78e508ead"

SNAPSHOT_NAMES = [
    "voxyflow.card.create_unassigned",
    "voxyflow.card.list_unassigned",
    "voxyflow.workspace.create",
    "voxyflow.workspace.list",
    "voxyflow.workspace.get",
    "voxyflow.workspace.delete",
    "voxyflow.workspace.update",
    "voxyflow.workspace.export",
    "voxyflow.workspace.archive",
    "voxyflow.workspace.restore",
    "voxyflow.card.create",
    "voxyflow.card.list",
    "voxyflow.card.get",
    "voxyflow.card.update",
    "voxyflow.card.move",
    "voxyflow.card.archive",
    "voxyflow.card.delete",
    "voxyflow.card.duplicate",
    "voxyflow.card.enrich",
    "voxyflow.card.restore",
    "voxyflow.card.list_archived",
    "voxyflow.card.history",
    "voxyflow.card.relation.add",
    "voxyflow.card.relation.list",
    "voxyflow.card.relation.delete",
    "voxyflow.card.time.log",
    "voxyflow.card.time.list",
    "voxyflow.card.time.delete",
    "voxyflow.card.checklist.add",
    "voxyflow.card.checklist.add_bulk",
    "voxyflow.card.checklist.list",
    "voxyflow.card.checklist.update",
    "voxyflow.card.checklist.delete",
    "voxyflow.wiki.list",
    "voxyflow.wiki.create",
    "voxyflow.wiki.get",
    "voxyflow.wiki.update",
    "voxyflow.wiki.delete",
    "voxyflow.ai.standup",
    "voxyflow.ai.brief",
    "voxyflow.ai.health",
    "voxyflow.ai.prioritize",
    "voxyflow.ai.review_code",
    "voxyflow.doc.list",
    "voxyflow.doc.delete",
    "voxyflow.focus.log",
    "voxyflow.focus.analytics",
    "voxyflow.sessions.list",
    "voxyflow.workers.list",
    "voxyflow.workers.get_result",
    "voxyflow.workers.read_artifact",
    "voxyflow.workers.ack_artifact",
    "voxyflow.workers.list_unread",
    "voxyflow.task.peek",
    "voxyflow.task.cancel",
    "voxyflow.session.read",
    "voxyflow.health",
    "voxyflow.jobs.list",
    "voxyflow.jobs.create",
    "voxyflow.jobs.update",
    "voxyflow.jobs.delete",
    "voxyflow.jobs.schedule_nl",
    "voxyflow.heartbeat.read",
    "voxyflow.heartbeat.write",
    "voxyflow.autonomy.status",
    "voxyflow.autonomy.enable",
    "voxyflow.autonomy.disable",
    "voxyflow.autonomy.run_now",
    "system.exec",
    "web.search",
    "web.fetch",
    "file.read",
    "file.write",
    "file.patch",
    "file.list",
    "git.status",
    "git.log",
    "git.diff",
    "git.branches",
    "git.commit",
    "tmux.list",
    "tmux.run",
    "tmux.send",
    "tmux.capture",
    "tmux.new",
    "tmux.kill",
    "voxyflow.worker.claim",
    "voxyflow.worker.complete",
    "tools.load",
    "memory.search",
    "memory.save",
    "knowledge.search",
    "memory.delete",
    "voxyflow.undo.list",
    "voxyflow.undo.apply",
    "memory.get",
    "kg.add",
    "kg.query",
    "kg.timeline",
    "kg.invalidate",
    "kg.stats",
    "task.steer",
    "voxyflow.endpoint.list",
    "voxyflow.endpoint.add",
    "voxyflow.endpoint.remove",
    "voxyflow.delegate",
    "voxyflow.skill.list",
    "voxyflow.skill.get",
    "voxyflow.skill.save",
    "voxyflow.skill.delete",
    "voxyflow.script",
]


def _normalize(obj):
    """Canonical JSON-able form; callables become their qualname marker."""
    if isinstance(obj, dict):
        return {k: _normalize(v) for k, v in sorted(obj.items())}
    if isinstance(obj, (list, tuple)):
        return [_normalize(x) for x in obj]
    if callable(obj):
        return f"<callable:{getattr(obj, '__qualname__', repr(obj))}>"
    return obj


def _structure_hash(defs):
    blob = json.dumps(_normalize(defs), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


class TestToolDefsSplitEquivalence:
    def test_tool_count(self):
        assert len(_TOOL_DEFINITIONS) == len(SNAPSHOT_NAMES) == 111

    def test_names_in_original_order(self):
        assert [t["name"] for t in _TOOL_DEFINITIONS] == SNAPSHOT_NAMES

    def test_full_structure_hash(self):
        assert _structure_hash(_TOOL_DEFINITIONS) == SNAPSHOT_SHA256

    def test_post_process_same_function_objects(self):
        by_name = {t["name"]: t for t in _TOOL_DEFINITIONS}
        assert by_name["voxyflow.card.list"]["_post_process"] is postprocess._minimize_card_list
        assert by_name["voxyflow.card.list_unassigned"]["_post_process"] is postprocess._minimize_card_list
        assert (
            by_name["voxyflow.card.list_archived"]["_post_process"]
            is postprocess._minimize_card_list_archived
        )
        assert (
            by_name["voxyflow.workspace.list"]["_post_process"]
            is postprocess._minimize_workspace_list
        )
        assert (
            by_name["voxyflow.workspace.get"]["_post_process"]
            is postprocess._minimize_workspace_get
        )
        assert by_name["voxyflow.card.get"]["_post_process"] is postprocess._minimize_card_get
        assert (
            by_name["voxyflow.card.history"]["_post_process"]
            is postprocess._minimize_card_history
        )
        assert by_name["voxyflow.wiki.get"]["_post_process"] is postprocess._minimize_wiki_get
        # No other tool carries a _post_process
        assert sum(1 for t in _TOOL_DEFINITIONS if "_post_process" in t) == 8

    def test_aggregator_is_exact_concatenation(self):
        expected = [
            *KANBAN_TOOLS,
            *WIKI_DOCS_AI_TOOLS,
            *WORKERS_MONITOR_TOOLS,
            *OPS_JOBS_TOOLS,
            *SYSTEM_TOOLS,
            *WORKER_LIFECYCLE_TOOLS,
            *MEMORY_KG_TOOLS,
            *TASK_STEER_TOOLS,
            *ENDPOINT_TOOLS,
            *DELEGATE_TOOLS,
            *SKILL_TOOLS,
            *SCRIPT_TOOLS,
        ]
        assert len(_TOOL_DEFINITIONS) == len(expected)
        for got, want in zip(_TOOL_DEFINITIONS, expected):
            assert got is want  # same dict objects, not copies

    def test_facade_reexports_helpers(self):
        from app import mcp_tool_defs

        assert mcp_tool_defs._minimal_card is postprocess._minimal_card
        assert mcp_tool_defs._minimize_card_list is postprocess._minimize_card_list
        assert (
            mcp_tool_defs._minimize_card_list_archived
            is postprocess._minimize_card_list_archived
        )
        assert mcp_tool_defs._CARD_LIST_KEEP == postprocess._CARD_LIST_KEEP
