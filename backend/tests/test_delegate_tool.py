"""Unit tests for app.tools.delegate_tool.

Tests cover:
- validate_delegate_input: happy paths, required-field errors, enum validation,
  UUID regex, additionalProperties=false, type checks.
- make_tool_result_error: JSON structure returned on validation failure.
- Provider format dicts: Anthropic / OpenAI / Gemini fields presence.
- TOOL_NAME / TOOL_NAME_SAFE constants.
"""

import json
import pytest

from app.tools.delegate_tool import (
    TOOL_NAME,
    TOOL_NAME_SAFE,
    VOXYFLOW_DELEGATE_TOOL,
    VOXYFLOW_DELEGATE_TOOL_OPENAI,
    VOXYFLOW_DELEGATE_TOOL_GEMINI,
    validate_delegate_input,
    make_tool_result_error,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_tool_name(self):
        assert TOOL_NAME == "voxyflow.delegate"

    def test_tool_name_safe(self):
        # Dots are not valid in Anthropic/OpenAI tool names → underscored version
        assert TOOL_NAME_SAFE == "voxyflow_delegate"
        assert "." not in TOOL_NAME_SAFE


# ---------------------------------------------------------------------------
# validate_delegate_input — happy paths
# ---------------------------------------------------------------------------


class TestValidateDelegateInputHappy:
    def test_minimal_valid(self):
        ok, err = validate_delegate_input({"action": "create_card", "description": "Do something"})
        assert ok is True, f"Expected success, got error: {err}"
        assert err == ""

    def test_all_optional_fields(self):
        ok, err = validate_delegate_input({
            "action": "migrate_schema",
            "description": "Run DB migration",
            "complexity": "complex",
            "card_id": "12345678-1234-1234-1234-1234567890ab",
            "context": "additional context here",
        })
        assert ok is True, f"Expected success, got error: {err}"

    def test_complexity_simple(self):
        ok, err = validate_delegate_input({"action": "x", "description": "y", "complexity": "simple"})
        assert ok is True

    def test_complexity_standard(self):
        ok, err = validate_delegate_input({"action": "x", "description": "y", "complexity": "standard"})
        assert ok is True

    def test_complexity_complex(self):
        ok, err = validate_delegate_input({"action": "x", "description": "y", "complexity": "complex"})
        assert ok is True


# ---------------------------------------------------------------------------
# validate_delegate_input — error paths
# ---------------------------------------------------------------------------


class TestValidateDelegateInputErrors:
    def test_not_a_dict(self):
        ok, err = validate_delegate_input("not a dict")  # type: ignore[arg-type]
        assert ok is False
        assert "object" in err.lower() or "dict" in err.lower()

    def test_missing_action(self):
        ok, err = validate_delegate_input({"description": "something"})
        assert ok is False
        assert "action" in err

    def test_missing_description(self):
        ok, err = validate_delegate_input({"action": "do_stuff"})
        assert ok is False
        assert "description" in err

    def test_empty_action(self):
        ok, err = validate_delegate_input({"action": "", "description": "y"})
        assert ok is False
        assert "action" in err

    def test_empty_description(self):
        ok, err = validate_delegate_input({"action": "x", "description": ""})
        assert ok is False
        assert "description" in err

    def test_unknown_field_rejected(self):
        ok, err = validate_delegate_input({"action": "x", "description": "y", "rogue_field": "bad"})
        assert ok is False
        assert "rogue_field" in err

    def test_invalid_complexity_enum(self):
        ok, err = validate_delegate_input({"action": "x", "description": "y", "complexity": "ultra"})
        assert ok is False
        assert "complexity" in err

    def test_invalid_card_id_format(self):
        ok, err = validate_delegate_input({
            "action": "x", "description": "y",
            "card_id": "not-a-uuid",
        })
        assert ok is False
        assert "card_id" in err

    def test_valid_card_id_all_zeros(self):
        ok, err = validate_delegate_input({
            "action": "x", "description": "y",
            "card_id": "00000000-0000-0000-0000-000000000000",
        })
        assert ok is True

    def test_context_wrong_type(self):
        ok, err = validate_delegate_input({"action": "x", "description": "y", "context": 42})
        assert ok is False
        assert "context" in err

    def test_action_wrong_type(self):
        ok, err = validate_delegate_input({"action": 123, "description": "y"})
        assert ok is False
        assert "action" in err


# ---------------------------------------------------------------------------
# make_tool_result_error
# ---------------------------------------------------------------------------


class TestMakeToolResultError:
    def test_returns_valid_json(self):
        raw = make_tool_result_error("some validation failed")
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_contains_error_key(self):
        parsed = json.loads(make_tool_result_error("boom"))
        assert parsed.get("error") == "VALIDATION_FAILED"

    def test_contains_message(self):
        parsed = json.loads(make_tool_result_error("field X is required"))
        assert "field X is required" in parsed.get("message", "")

    def test_contains_hint(self):
        parsed = json.loads(make_tool_result_error("bad"))
        assert "hint" in parsed


# ---------------------------------------------------------------------------
# Provider format dicts
# ---------------------------------------------------------------------------


class TestProviderDicts:
    def test_anthropic_format(self):
        tool = VOXYFLOW_DELEGATE_TOOL
        assert tool["name"] == "voxyflow_delegate"
        assert "input_schema" in tool
        schema = tool["input_schema"]
        assert schema.get("additionalProperties") is False
        assert "action" in schema["required"]
        assert "description" in schema["required"]

    def test_openai_format(self):
        tool = VOXYFLOW_DELEGATE_TOOL_OPENAI
        assert tool["type"] == "function"
        fn = tool["function"]
        assert fn["name"] == "voxyflow_delegate"
        assert "parameters" in fn
        params = fn["parameters"]
        assert params.get("additionalProperties") is False
        assert "action" in params["required"]
        assert "description" in params["required"]

    def test_gemini_format(self):
        tool = VOXYFLOW_DELEGATE_TOOL_GEMINI
        assert tool["name"] == "voxyflow_delegate"
        assert "parameters" in tool
        params = tool["parameters"]
        # Gemini uses OBJECT type string
        assert params.get("type") == "OBJECT"
        props = params["properties"]
        assert "action" in props
        assert "description" in props
