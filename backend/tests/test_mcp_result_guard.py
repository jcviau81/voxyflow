"""Size guard + list-minimizer behavior for MCP tool results.

The Claude CLI spills oversized MCP results to a file the dispatcher cannot
read — these layers exist so that never happens: minimizers shrink known-heavy
payloads, and _serialize_result truncates in-band with a recovery notice.
"""

import json

import pytest

from app.mcp_server import MAX_TOOL_RESULT_CHARS, _serialize_result
from app.mcp_tools_defs.postprocess import (
    _clip,
    _minimize_card_get,
    _minimize_card_history,
    _minimize_wiki_get,
    _minimize_workspace_get,
    _minimize_workspace_list,
)


class TestSerializeResult:
    def test_small_result_compact_json(self):
        out = _serialize_result("t", {"success": True, "items": [1, 2]})
        assert out == '{"success":true,"items":[1,2]}'

    def test_oversized_result_truncated_with_recovery_notice(self):
        big = {"data": "x" * (MAX_TOOL_RESULT_CHARS + 5000)}
        out = _serialize_result("t", big)
        assert len(out) < MAX_TOOL_RESULT_CHARS + 500
        assert "TRUNCATED" in out
        assert "Do NOT delegate" in out
        assert "narrower call" in out

    def test_at_cap_not_truncated(self):
        payload = {"d": "x" * (MAX_TOOL_RESULT_CHARS - 20)}
        out = _serialize_result("t", payload)
        assert "TRUNCATED" not in out


class TestClip:
    def test_short_untouched(self):
        assert _clip("hello", 10) == "hello"

    def test_long_clipped_with_hint(self):
        out = _clip("a" * 300, 100)
        assert out.startswith("a" * 100)
        assert "+200 chars" in out

    def test_non_string_passthrough(self):
        assert _clip(None, 10) is None
        assert _clip(42, 10) == 42


class TestWorkspaceGetMinimizer:
    def test_embedded_cards_slimmed(self):
        ws = {
            "id": "w1",
            "title": "WS",
            "context": "c" * 5000,
            "cards": [
                {"id": "c1", "title": "T", "status": "todo", "priority": 1,
                 "position": 0, "description": "d" * 50_000},
            ],
        }
        out = _minimize_workspace_get(ws)
        assert "description" not in out["cards"][0]
        assert out["cards"][0]["id"] == "c1"
        assert len(out["context"]) < 2200

    def test_non_workspace_passthrough(self):
        assert _minimize_workspace_get({"error": "x"}) == {"error": "x"}
        assert _minimize_workspace_get(None) is None


class TestCardGetMinimizer:
    def test_caps_description_and_agent_context(self):
        card = {"id": "c1", "description": "d" * 20_000, "agent_context": "a" * 9000}
        out = _minimize_card_get(card)
        assert len(out["description"]) < 8200
        assert len(out["agent_context"]) < 4200
        assert "fetch the item" in out["description"]


class TestCardHistoryMinimizer:
    def test_old_new_values_truncated(self):
        data = {"history": [{"field": "description", "old_value": "o" * 5000, "new_value": "n" * 5000}]}
        out = _minimize_card_history(data)
        e = out["history"][0]
        assert len(e["old_value"]) < 300
        assert len(e["new_value"]) < 300

    def test_bare_list_supported(self):
        out = _minimize_card_history([{"old_value": "o" * 1000, "new_value": "x"}])
        assert len(out[0]["old_value"]) < 300


class TestWikiGetMinimizer:
    def test_long_content_flagged(self):
        out = _minimize_wiki_get({"id": "p", "content": "w" * 40_000})
        assert len(out["content"]) == 15_000
        assert out["content_truncated"] is True
        assert out["content_total_chars"] == 40_000

    def test_short_content_untouched(self):
        page = {"id": "p", "content": "short"}
        out = _minimize_wiki_get(page)
        assert out["content"] == "short"
        assert "content_truncated" not in out


class TestWorkspaceListMinimizer:
    def test_falsy_fields_dropped_and_extras_removed(self):
        rows = [{"id": "w1", "title": "A", "status": "active", "emoji": "",
                 "is_favorite": False, "created_at": "2026-01-01", "context": "x" * 9000}]
        out = _minimize_workspace_list(rows)
        assert out == [{"id": "w1", "title": "A", "status": "active", "created_at": "2026-01-01"}]
