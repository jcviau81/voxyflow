"""Post-processing helpers for list tool results.

Extracted verbatim from ``app/mcp_tool_defs.py`` (H8 monolith split).
Pure data — every entry follows the schema documented in ``app.mcp_tool_defs``.
"""

from __future__ import annotations


_CARD_LIST_KEEP = ("id", "title", "status", "priority", "position", "assignee", "agent_type")

_WORKSPACE_LIST_KEEP = ("id", "title", "status", "emoji", "is_favorite", "created_at")


def _minimize_workspace_list(data):
    """Workspace list responses to the minimal fields an LLM actually needs.

    Full workspace rows (description, context, flags, timestamps) × 100+
    workspaces exceed the CLI's tool-result size limit, which spills the
    result to a file the dispatcher has no tools to read — turning trivial
    inline ops ("delete my test workspaces") into forced worker delegations.
    Falsy fields are dropped per row (emoji/'' , is_favorite/False…).
    """
    if not isinstance(data, list):
        return data
    return [
        {k: w[k] for k in _WORKSPACE_LIST_KEEP if w.get(k)}
        for w in data
        if isinstance(w, dict)
    ]


def _minimal_card(card: dict) -> dict:
    return {k: card[k] for k in _CARD_LIST_KEEP if k in card}


def _minimize_card_list(data):
    """Workspace card list responses to the minimal fields an LLM actually needs.

    Full ``CardResponse`` carries description, files, time sums, checklist
    progress, watchers, etc. — a workspace with ~200 cards balloons the tool
    result to >1 MB of tokens per call.

    Also drops archived cards (``status == 'archived'`` or ``archived_at`` set).
    The REST endpoint already filters ``archived_at IS NULL``, but cards whose
    ``status`` column was flipped to ``'archived'`` via ``card.update`` /
    ``card.move`` slip through — the LLM should use ``card.list_archived``
    explicitly when it wants those.
    """
    if not isinstance(data, list):
        return data
    out = []
    for c in data:
        if not isinstance(c, dict):
            continue
        if c.get("status") == "archived" or c.get("archived_at"):
            continue
        out.append(_minimal_card(c))
    return out


def _minimize_card_list_archived(data):
    """Same shape as ``_minimize_card_list`` but keeps archived rows.

    Used for ``voxyflow.card.list_archived`` where archived cards ARE the point.
    """
    if not isinstance(data, list):
        return data
    return [_minimal_card(c) for c in data if isinstance(c, dict)]
