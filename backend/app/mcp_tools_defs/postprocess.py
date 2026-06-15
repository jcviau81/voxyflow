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


def _clip(value, limit: int):
    """Truncate a string field, flagging the cut so the model knows to .get."""
    if not isinstance(value, str) or len(value) <= limit:
        return value
    return value[:limit] + f"…[+{len(value) - limit} chars — fetch the item for full text]"


def _minimize_workspace_get(data):
    """Slim ``workspace.get``: workspace fields + minimal embedded cards.

    The raw response embeds every card's full description — 200 cards of
    worker-appended content reaches 200k-1M chars. Card detail is one
    ``card.get`` away.
    """
    if not isinstance(data, dict) or "cards" not in data:
        return data
    out = dict(data)
    out["context"] = _clip(out.get("context"), 2000)
    out["description"] = _clip(out.get("description"), 2000)
    cards = out.get("cards")
    if isinstance(cards, list):
        out["cards"] = [_minimal_card(c) for c in cards if isinstance(c, dict)]
    return out


def _minimize_card_get(data):
    """Cap the unbounded text fields of a single card (worker-appended)."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    out["description"] = _clip(out.get("description"), 8000)
    out["agent_context"] = _clip(out.get("agent_context"), 4000)
    return out


def _minimize_card_history(data):
    """Card history journals full old/new values (incl. whole descriptions)."""
    entries = data.get("history") if isinstance(data, dict) else data
    if not isinstance(entries, list):
        return data
    slim = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        e = dict(e)
        for k in ("old_value", "new_value"):
            e[k] = _clip(e.get(k), 200)
        slim.append(e)
    if isinstance(data, dict):
        return {**data, "history": slim}
    return slim


def _minimize_wiki_get(data):
    """Cap wiki page content (worker reports can be 50-200k chars)."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    content = out.get("content")
    if isinstance(content, str) and len(content) > 15_000:
        out["content"] = content[:15_000]
        out["content_truncated"] = True
        out["content_total_chars"] = len(content)
    return out
