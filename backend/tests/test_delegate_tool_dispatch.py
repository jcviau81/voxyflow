"""Tests for delegate dispatch post-markup-parser-removal (2026-05-27).

Covers:
  1. <delegate>...</delegate> XML markup in assistant text is NOT parsed/executed.
  2. voxyflow.delegate is present in all 4 provider tool lists.
  3. Dispatcher system prompt does NOT contain the string '<delegate>'.
"""

import pytest
import re


# ---------------------------------------------------------------------------
# 1. Legacy <delegate> XML markup is rendered as prose, not executed
# ---------------------------------------------------------------------------


class TestLegacyMarkupNotParsed:
    """After removing the XML parser, any <delegate> text in a response
    must be treated as plain prose — never parsed, never executed."""

    def test_delegate_dispatch_mixin_has_no_xml_parser(self):
        """DelegateDispatchMixin must NOT have _parse_and_emit_delegates."""
        from app.services.orchestration.delegate_dispatch import DelegateDispatchMixin
        assert not hasattr(DelegateDispatchMixin, "_parse_and_emit_delegates"), (
            "_parse_and_emit_delegates must be removed — XML markup parser was dropped on 2026-05-27"
        )

    def test_delegate_dispatch_mixin_has_no_parse_safe(self):
        """DelegateDispatchMixin must NOT have _parse_and_emit_delegates_safe."""
        from app.services.orchestration.delegate_dispatch import DelegateDispatchMixin
        assert not hasattr(DelegateDispatchMixin, "_parse_and_emit_delegates_safe"), (
            "_parse_and_emit_delegates_safe must be removed alongside the XML parser"
        )

    def test_delegate_dispatch_mixin_has_no_delegate_pattern(self):
        """DelegateDispatchMixin must NOT have _DELEGATE_PATTERN regex."""
        from app.services.orchestration.delegate_dispatch import DelegateDispatchMixin
        assert not hasattr(DelegateDispatchMixin, "_DELEGATE_PATTERN"), (
            "_DELEGATE_PATTERN must be removed — no XML parsing anymore"
        )

    def test_chat_orchestrator_has_no_xml_parser(self):
        """ChatOrchestrator must NOT have its own _parse_and_emit_delegates override."""
        from app.services.chat_orchestration import ChatOrchestrator
        # Check that the method doesn't exist on the class directly
        # (it should not be defined in chat_orchestration.py)
        assert "_parse_and_emit_delegates" not in ChatOrchestrator.__dict__, (
            "ChatOrchestrator.__dict__ must not have _parse_and_emit_delegates "
            "(legacy override was removed on 2026-05-27)"
        )

    def test_markup_parser_env_var_not_referenced(self):
        """DELEGATE_MARKUP_PARSER_ENABLED must not appear in delegate_dispatch.py."""
        import pathlib
        content = pathlib.Path(
            "app/services/orchestration/delegate_dispatch.py"
        ).read_text()
        assert "DELEGATE_MARKUP_PARSER_ENABLED" not in content, (
            "DELEGATE_MARKUP_PARSER_ENABLED env var must be fully removed from delegate_dispatch.py"
        )


# ---------------------------------------------------------------------------
# 2. voxyflow.delegate is in all 4 provider tool lists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider", [
    "anthropic",
    "codex",
    "openai",
    "gemini",
])
class TestDelegateToolInAllProviders:
    """voxyflow.delegate must be present in tool definitions for all 4 providers."""

    def test_provider_has_delegate_tool(self, provider: str):
        if provider == "anthropic":
            from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL
            assert VOXYFLOW_DELEGATE_TOOL["name"] == "voxyflow_delegate", (
                "Anthropic tool name must be voxyflow_delegate"
            )
            assert "input_schema" in VOXYFLOW_DELEGATE_TOOL

        elif provider == "codex":
            # Codex uses same MCP tool list as Claude CLI dispatcher
            from app.tools.registry import TOOLS_DISPATCHER_CODEX
            assert "voxyflow.delegate" in TOOLS_DISPATCHER_CODEX, (
                "voxyflow.delegate must be in TOOLS_DISPATCHER_CODEX for Codex CLI path"
            )

        elif provider == "openai":
            from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL_OPENAI
            assert VOXYFLOW_DELEGATE_TOOL_OPENAI["type"] == "function"
            assert VOXYFLOW_DELEGATE_TOOL_OPENAI["function"]["name"] == "voxyflow_delegate"
            assert "action" in VOXYFLOW_DELEGATE_TOOL_OPENAI["function"]["parameters"]["required"]

        elif provider == "gemini":
            from app.tools.delegate_tool import VOXYFLOW_DELEGATE_TOOL_GEMINI
            assert VOXYFLOW_DELEGATE_TOOL_GEMINI["name"] == "voxyflow_delegate"
            assert "action" in VOXYFLOW_DELEGATE_TOOL_GEMINI["parameters"].get("required", [])

    def test_cli_dispatcher_has_delegate(self, provider: str):
        """CLI dispatcher tool registry must contain voxyflow.delegate."""
        if provider in ("anthropic", "codex"):
            from app.tools.registry import TOOLS_DISPATCHER, TOOLS_DISPATCHER_CODEX
            registry = TOOLS_DISPATCHER_CODEX if provider == "codex" else TOOLS_DISPATCHER
            assert "voxyflow.delegate" in registry, (
                f"voxyflow.delegate must be in tool registry for {provider} CLI path"
            )
        else:
            pytest.skip(f"Registry check not applicable for HTTP provider: {provider}")


# ---------------------------------------------------------------------------
# 3. Dispatcher system prompt does NOT contain '<delegate>'
# ---------------------------------------------------------------------------


class TestDispatcherPromptNoXml:
    """The system prompt sent to the dispatcher LLM must NOT contain
    the legacy <delegate> XML markup — it must use voxyflow.delegate tool instead."""

    def _get_personality_service(self):
        from app.services.personality_service import PersonalityService
        return PersonalityService()

    @pytest.mark.parametrize("native_tools,label", [
        ("claude_cli_mcp", "Claude CLI MCP"),
        ("codex_mcp", "Codex MCP"),
        (True, "Native Anthropic/OpenAI"),
        (False, "Proxy/fallback"),
    ])
    def test_fast_prompt_no_delegate_xml(self, native_tools, label):
        """Fast dispatcher prompt must not contain '<delegate>' XML markup."""
        ps = self._get_personality_service()
        prompt = ps.build_fast_prompt(chat_level="general", native_tools=native_tools)
        assert "<delegate>" not in prompt, (
            f"[{label}] Fast dispatcher prompt must NOT contain '<delegate>' XML markup. "
            "Use voxyflow.delegate tool instructions instead."
        )

    @pytest.mark.parametrize("native_tools,label", [
        ("claude_cli_mcp", "Claude CLI MCP"),
        ("codex_mcp", "Codex MCP"),
        (True, "Native Anthropic/OpenAI"),
        (False, "Proxy/fallback"),
    ])
    def test_fast_prompt_has_voxyflow_delegate(self, native_tools, label):
        """Fast dispatcher prompt must reference voxyflow.delegate (the correct mechanism)."""
        ps = self._get_personality_service()
        prompt = ps.build_fast_prompt(chat_level="general", native_tools=native_tools)
        assert "voxyflow.delegate" in prompt or "voxyflow_delegate" in prompt, (
            f"[{label}] Fast dispatcher prompt must reference voxyflow.delegate tool."
        )

    def test_dispatcher_md_no_delegate_xml(self):
        """personality/DISPATCHER.md must not contain '<delegate>' XML markup."""
        import pathlib
        dispatcher_path = pathlib.Path("personality/DISPATCHER.md")
        if not dispatcher_path.exists():
            pytest.skip("DISPATCHER.md not found at expected path")
        content = dispatcher_path.read_text()
        assert "<delegate>" not in content, (
            "personality/DISPATCHER.md must not contain '<delegate>' XML markup "
            "(removed 2026-05-27). Update to use voxyflow.delegate tool instructions."
        )
