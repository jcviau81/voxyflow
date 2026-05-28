"""Integration tests: voxyflow.delegate tool across provider paths.

These tests exercise:
1. Anthropic path  — VOXYFLOW_DELEGATE_TOOL schema in input_schema format
2. OpenAI path     — VOXYFLOW_DELEGATE_TOOL_OPENAI schema in function format
3. Gemini path     — VOXYFLOW_DELEGATE_TOOL_GEMINI in Gemini schema format
4. tool_defs.py    — DELEGATE_ACTION_TOOL backward-compat alias still resolves
5. mcp_tool_defs.py— voxyflow.delegate entry exists in _TOOL_DEFINITIONS
6. tool registry   — voxyflow.delegate is in TOOLS_DISPATCHER set

They are pure import + structural tests — no LLM calls, no DB.
"""

import pytest


# ---------------------------------------------------------------------------
# 1. delegate_tool.py — schema correctness across providers
# ---------------------------------------------------------------------------


class TestAnthropicToolFormat:
    def test_schema_has_all_required_fields(self):
        from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL

        schema = VOXYFLOW_DELEGATE_TOOL["input_schema"]
        required = schema["required"]
        assert "action" in required
        assert "description" in required
        assert "complexity" not in required
        assert "card_id" not in required
        assert "context" not in required

    def test_schema_strict_no_additional(self):
        from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL

        schema = VOXYFLOW_DELEGATE_TOOL["input_schema"]
        assert schema.get("additionalProperties") is False

    def test_complexity_enum_values(self):
        from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL

        schema = VOXYFLOW_DELEGATE_TOOL["input_schema"]
        complexity_prop = schema["properties"]["complexity"]
        assert set(complexity_prop["enum"]) == {"simple", "standard", "complex"}

    def test_card_id_has_uuid_pattern(self):
        from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL

        schema = VOXYFLOW_DELEGATE_TOOL["input_schema"]
        card_id_prop = schema["properties"]["card_id"]
        assert "pattern" in card_id_prop
        # The pattern should match a UUID
        import re
        pattern = card_id_prop["pattern"]
        assert re.match(pattern, "12345678-1234-1234-1234-1234567890ab")
        assert not re.match(pattern, "not-a-uuid")


class TestOpenAIToolFormat:
    def test_type_is_function(self):
        from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL_OPENAI

        assert VOXYFLOW_DELEGATE_TOOL_OPENAI["type"] == "function"

    def test_function_name_matches(self):
        from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL_OPENAI, TOOL_NAME_SAFE

        assert VOXYFLOW_DELEGATE_TOOL_OPENAI["function"]["name"] == TOOL_NAME_SAFE

    def test_strict_schema(self):
        from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL_OPENAI

        params = VOXYFLOW_DELEGATE_TOOL_OPENAI["function"]["parameters"]
        assert params.get("additionalProperties") is False
        assert "action" in params["required"]
        assert "description" in params["required"]


class TestGeminiToolFormat:
    def test_name_matches(self):
        from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL_GEMINI, TOOL_NAME_SAFE

        assert VOXYFLOW_DELEGATE_TOOL_GEMINI["name"] == TOOL_NAME_SAFE

    def test_parameters_type_is_object(self):
        from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL_GEMINI

        params = VOXYFLOW_DELEGATE_TOOL_GEMINI["parameters"]
        assert params["type"] == "OBJECT"

    def test_required_fields_present(self):
        from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL_GEMINI

        params = VOXYFLOW_DELEGATE_TOOL_GEMINI["parameters"]
        assert "action" in params.get("required", [])
        assert "description" in params.get("required", [])


# ---------------------------------------------------------------------------
# 2. tool_defs.py — backward-compat alias
# ---------------------------------------------------------------------------


class TestToolDefsBackwardCompat:
    def test_delegate_action_tool_resolves(self):
        """DELEGATE_ACTION_TOOL must still exist and point to voxyflow_delegate."""
        from app.services.llm.tool_defs import DELEGATE_ACTION_TOOL

        assert DELEGATE_ACTION_TOOL is not None
        assert DELEGATE_ACTION_TOOL.get("name") == "voxyflow_delegate"

    def test_voxyflow_delegate_tool_importable(self):
        from app.services.llm.tool_defs import VOXYFLOW_DELEGATE_TOOL

        assert VOXYFLOW_DELEGATE_TOOL is not None


# ---------------------------------------------------------------------------
# 3. mcp_tool_defs.py — voxyflow.delegate in _TOOL_DEFINITIONS
# ---------------------------------------------------------------------------


class TestMcpToolDefs:
    def test_voxyflow_delegate_in_tool_definitions(self):
        from app.mcp_tool_defs import _TOOL_DEFINITIONS

        names = [t["name"] for t in _TOOL_DEFINITIONS]
        assert "voxyflow.delegate" in names

    def test_voxyflow_delegate_has_correct_schema(self):
        from app.mcp_tool_defs import _TOOL_DEFINITIONS

        entry = next(t for t in _TOOL_DEFINITIONS if t["name"] == "voxyflow.delegate")
        schema = entry.get("inputSchema", {})
        assert schema.get("additionalProperties") is False
        assert "action" in schema.get("required", [])
        assert "description" in schema.get("required", [])

    def test_voxyflow_delegate_role_is_all(self):
        """voxyflow.delegate should be available to all roles (dispatcher + worker)."""
        from app.mcp_tool_defs import _TOOL_DEFINITIONS

        entry = next(t for t in _TOOL_DEFINITIONS if t["name"] == "voxyflow.delegate")
        assert entry.get("_role") == "all"


# ---------------------------------------------------------------------------
# 4. tool registry — voxyflow.delegate in dispatcher sets
# ---------------------------------------------------------------------------


class TestToolRegistry:
    def test_in_tools_dispatcher(self):
        from app.tools.registry import TOOLS_DISPATCHER

        assert "voxyflow.delegate" in TOOLS_DISPATCHER

    def test_in_tools_dispatcher_codex(self):
        from app.tools.registry import TOOLS_DISPATCHER_CODEX

        assert "voxyflow.delegate" in TOOLS_DISPATCHER_CODEX


# ---------------------------------------------------------------------------
# 5. mcp_system_handlers.py — handler registered
# ---------------------------------------------------------------------------


class TestMcpSystemHandlers:
    def test_voxyflow_delegate_handler_registered(self):
        from app.mcp_system_handlers import SYSTEM_TOOL_HANDLERS

        assert "voxyflow_delegate" in SYSTEM_TOOL_HANDLERS

    def test_voxyflow_delegate_handler_is_callable(self):
        from app.mcp_system_handlers import SYSTEM_TOOL_HANDLERS
        import asyncio

        handler = SYSTEM_TOOL_HANDLERS["voxyflow_delegate"]
        assert callable(handler)
