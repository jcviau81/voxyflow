"""Voxyflow — Context Isolation & Tool Scoping Tests

Comprehensive test suite verifying:
1. Tool scoping per chat level (general / workspace / card)
2. Chat Init content correctness per level
3. Context isolation — no data leaks between levels
4. Tool call fallback parsing (regex extraction)
5. Deep layer prompt (chat responder mode)
7. Integration tests against the running backend API

Unit tests run standalone (no server needed).
Integration tests require the backend at http://localhost:8000.

NOTE: claude_service.py has heavy import dependencies (pydantic_settings, etc.)
that may not be installed in the test environment. Tests that validate tool scoping
and name conversion replicate the filtering logic locally to avoid the import chain.
"""

import json
import re
import sys
import os

import pytest

# Ensure the backend app is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ============================================================================
# Helpers — replicate claude_service logic to avoid heavy import chain
# ============================================================================

def _get_tool_list():
    """Import get_tool_list from mcp_server (lightweight, no pydantic deps)."""
    from app.mcp_server import get_tool_list
    return get_tool_list()


def _get_claude_tools(chat_level: str = "general") -> list[dict]:
    """Replicate get_claude_tools logic from claude_service.py.

    This avoids importing claude_service which pulls in pydantic_settings, etc.
    The logic is identical to the production code.

    Post-refactor: "general" is now the system-main workspace and gets both
    unassigned aliases AND workspace card tools. Workspace level gets all tools.
    """
    all_tools = _get_tool_list()

    if chat_level == "general":
        allowed = {
            "voxyflow.card.create_unassigned",
            "voxyflow.card.list_unassigned",
            "voxyflow.card.create",
            "voxyflow.card.list",
            "voxyflow.card.get",
            "voxyflow.card.update",
            "voxyflow.card.move",
            "voxyflow.workspace.create",
            "voxyflow.workspace.list",
            "voxyflow.workspace.get",
            "voxyflow.health",
        }
    elif chat_level == "workspace":
        # Workspace level: all tools (unassigned aliases are still valid)
        allowed = {t["name"] for t in all_tools}
    else:
        allowed = {t["name"] for t in all_tools}

    tools = []
    for tool in all_tools:
        if tool["name"] in allowed:
            tools.append({
                "name": tool["name"].replace(".", "_"),
                "description": tool["description"],
                "input_schema": tool["inputSchema"],
            })
    return tools


def _mcp_tool_name_from_claude(claude_name: str) -> str:
    """Replicate the production reverse lookup in tool_defs.py."""
    from app.services.llm.tool_defs import _mcp_tool_name_from_claude as real
    return real(claude_name)


# ============================================================================
# UNIT TESTS — No server required
# ============================================================================


class TestToolScoping:
    """Test 1: Verify correct tools are available per chat level."""

    def _tool_names(self, level: str) -> set[str]:
        return {t["name"] for t in _get_claude_tools(level)}

    # -- General chat tools --

    def test_general_has_card_unassigned_tools(self):
        names = self._tool_names("general")
        assert "voxyflow_card_create_unassigned" in names, "General chat should have card_create_unassigned"
        assert "voxyflow_card_list_unassigned" in names, "General chat should have card_list_unassigned"

    def test_general_has_workspace_tools(self):
        names = self._tool_names("general")
        assert "voxyflow_workspace_create" in names, "General chat should have workspace_create"
        assert "voxyflow_workspace_list" in names, "General chat should have workspace_list"

    def test_general_has_health(self):
        names = self._tool_names("general")
        assert "voxyflow_health" in names, "General chat should have health check"

    def test_general_has_card_tools(self):
        """Post-refactor: general (Main workspace) has card tools since Main is a real workspace."""
        names = self._tool_names("general")
        assert "voxyflow_card_create" in names, "General/Main should have card_create"
        assert "voxyflow_card_update" in names, "General/Main should have card_update"
        assert "voxyflow_card_move" in names, "General/Main should have card_move"

    def test_general_excludes_wiki_tools(self):
        names = self._tool_names("general")
        assert "voxyflow_wiki_create" not in names, "General/Main chat should NOT have wiki_create"
        assert "voxyflow_wiki_list" not in names, "General/Main chat should NOT have wiki_list"

    def test_general_excludes_ai_workspace_tools(self):
        names = self._tool_names("general")
        assert "voxyflow_ai_standup" not in names, "General/Main chat should NOT have standup"
        assert "voxyflow_ai_brief" not in names, "General/Main chat should NOT have brief"

    def test_general_tool_count(self):
        """General/Main chat should have exactly 11 tools (unassigned aliases + card CRUD + workspace/health)."""
        tools = _get_claude_tools("general")
        assert len(tools) == 11, f"Expected 11 general tools, got {len(tools)}: {[t['name'] for t in tools]}"

    # -- Workspace chat tools --

    def test_workspace_has_card_tools(self):
        names = self._tool_names("workspace")
        assert "voxyflow_card_create" in names, "Workspace chat should have card_create"
        assert "voxyflow_card_update" in names, "Workspace chat should have card_update"
        assert "voxyflow_card_list" in names, "Workspace chat should have card_list"

    def test_workspace_has_wiki_tools(self):
        names = self._tool_names("workspace")
        assert "voxyflow_wiki_create" in names, "Workspace chat should have wiki_create"
        assert "voxyflow_wiki_list" in names, "Workspace chat should have wiki_list"

    def test_workspace_has_ai_tools(self):
        names = self._tool_names("workspace")
        assert "voxyflow_ai_standup" in names, "Workspace chat should have standup"
        assert "voxyflow_ai_brief" in names, "Workspace chat should have brief"
        assert "voxyflow_ai_health" in names, "Workspace chat should have health"

    def test_workspace_has_unassigned_tools(self):
        """Post-refactor: unassigned tools are aliases, available everywhere."""
        names = self._tool_names("workspace")
        assert "voxyflow_card_create_unassigned" in names, "Workspace chat should have card_create_unassigned (alias)"
        assert "voxyflow_card_list_unassigned" in names, "Workspace chat should have card_list_unassigned (alias)"

    def test_workspace_has_more_tools_than_general(self):
        general = _get_claude_tools("general")
        workspace = _get_claude_tools("workspace")
        assert len(workspace) > len(general), "Workspace should have more tools than general"

    # -- Card chat tools --

    def test_card_has_all_tools(self):
        all_mcp = _get_tool_list()
        card_tools = _get_claude_tools("card")
        assert len(card_tools) == len(all_mcp), (
            f"Card chat should have ALL tools ({len(all_mcp)}), got {len(card_tools)}"
        )

    def test_card_has_unassigned_and_card_tools(self):
        names = self._tool_names("card")
        assert "voxyflow_card_create_unassigned" in names, "Card chat should have card_create_unassigned (full access)"
        assert "voxyflow_card_create" in names, "Card chat should have card_create"
        assert "voxyflow_wiki_create" in names, "Card chat should have wiki_create"

    # -- Tool format validation --

    def test_tool_names_have_no_dots(self):
        """Claude API forbids dots in tool names — they should be underscores."""
        for level in ("general", "workspace", "card"):
            tools = _get_claude_tools(level)
            for t in tools:
                assert "." not in t["name"], f"Tool name has dots: {t['name']} (level={level})"

    def test_tools_have_required_fields(self):
        """Each tool must have name, description, and input_schema."""
        for level in ("general", "workspace", "card"):
            tools = _get_claude_tools(level)
            for t in tools:
                assert "name" in t, f"Tool missing 'name' (level={level})"
                assert "description" in t, f"Tool missing 'description': {t['name']}"
                assert "input_schema" in t, f"Tool missing 'input_schema': {t['name']}"


class TestChatInitContent:
    """Test 2: Verify Chat Init blocks contain correct content per level."""

    def _ps(self):
        from app.services.personality_service import PersonalityService
        return PersonalityService()

    # -- General Chat Init --
    # Post-refactor: the static general chat init no longer embeds dynamic
    # content (workspace names, etc). It advertises the Home workspace only.
    # Dynamic workspace/memory data lives in build_dynamic_context_block().

    def test_general_chat_init_has_home_workspace(self):
        ps = self._ps()
        prompt = ps.build_general_chat_init()
        assert "Home workspace" in prompt

    def test_general_chat_init_mentions_cards(self):
        ps = self._ps()
        prompt = ps.build_general_chat_init()
        assert "card" in prompt.lower() or "Card" in prompt

    # -- Workspace Chat Init --

    def test_workspace_chat_init_has_workspace_name(self):
        ps = self._ps()
        workspace = {"title": "TestWorkspace", "description": "A test", "tech_stack": "Python"}
        prompt = ps.build_workspace_chat_init(workspace)
        assert "TestWorkspace" in prompt

    def test_workspace_chat_init_has_mode(self):
        ps = self._ps()
        workspace = {"title": "TestWorkspace"}
        prompt = ps.build_workspace_chat_init(workspace)
        assert "## Workspace:" in prompt

    def test_workspace_chat_init_has_stay_focused(self):
        ps = self._ps()
        workspace = {"title": "TestWorkspace"}
        prompt = ps.build_workspace_chat_init(workspace)
        assert "Stay focused here" in prompt

    # Dynamic workspace fields (tech_stack, card counts) moved to
    # build_dynamic_context_block — covered by TestDynamicContextBlock below.

    # -- Card Chat Init --

    def test_card_chat_init_has_card_title(self):
        ps = self._ps()
        workspace = {"title": "TestWorkspace"}
        card = {"title": "Fix bug", "status": "todo", "priority": "high", "agent_type": "coder"}
        prompt = ps.build_card_chat_init(workspace, card)
        assert "Fix bug" in prompt

    def test_card_chat_init_has_mode(self):
        ps = self._ps()
        workspace = {"title": "TestWorkspace"}
        card = {"title": "Fix bug", "status": "todo"}
        prompt = ps.build_card_chat_init(workspace, card)
        assert "Card Chat" in prompt

    def test_card_chat_init_has_workspace_name(self):
        ps = self._ps()
        workspace = {"title": "TestWorkspace"}
        card = {"title": "Fix bug"}
        prompt = ps.build_card_chat_init(workspace, card)
        assert "TestWorkspace" in prompt

    # Status / priority / checklist moved out of the static card chat init
    # into build_dynamic_context_block — covered by TestDynamicContextBlock.


class TestDynamicContextBlock:
    """Verify dynamic workspace / card data ends up in build_dynamic_context_block.

    The static chat-init builders are intentionally cache-friendly and omit
    everything that changes call-to-call. The dynamic block is where the
    per-call state (tech stack, card counts, checklist, etc.) lives.
    """

    def _ps(self):
        from app.services.personality_service import PersonalityService
        return PersonalityService()

    def test_workspace_dynamic_has_tech_stack(self):
        ps = self._ps()
        workspace = {"title": "TestWorkspace", "tech_stack": "Python, FastAPI"}
        block = ps.build_dynamic_context_block(chat_level="workspace", workspace=workspace)
        assert "Python, FastAPI" in block

    def test_workspace_dynamic_has_card_counts(self):
        # NOTE: the canonical DB status is "in-progress" (hyphen) — see
        # app.models.enums.CardStatus. The underscore form was a bug.
        ps = self._ps()
        workspace = {
            "title": "TestWorkspace",
            "cards": [
                {"status": "done", "title": "Card1"},
                {"status": "todo", "title": "Card2"},
                {"status": "in-progress", "title": "Card3"},
            ],
        }
        block = ps.build_dynamic_context_block(chat_level="workspace", workspace=workspace)
        assert "3 cards" in block
        assert "1 done" in block
        assert "1 in progress" in block
        assert "1 todo" in block

    def test_workspace_dynamic_lists_in_progress_titles(self):
        """Regression: in-progress cards (canonical hyphen status) must show
        in the 'In progress:' block, not '(none)'."""
        ps = self._ps()
        workspace = {
            "title": "TestWorkspace",
            "cards": [{"status": "in-progress", "title": "ActiveCard"}],
        }
        block = ps.build_dynamic_context_block(chat_level="workspace", workspace=workspace)
        assert "ActiveCard" in block
        assert "In progress: (none)" not in block

    def test_card_dynamic_has_status_and_priority(self):
        ps = self._ps()
        card = {"title": "Fix bug", "status": "in-progress", "priority": "high"}
        block = ps.build_dynamic_context_block(chat_level="card", card=card)
        assert "in-progress" in block
        assert "high" in block

    def test_card_dynamic_has_checklist_count(self):
        ps = self._ps()
        card = {
            "title": "Fix bug",
            "checklist_items": [
                {"text": "Step 1", "done": True},
                {"text": "Step 2", "done": False},
                {"text": "Step 3", "done": True},
            ],
        }
        block = ps.build_dynamic_context_block(chat_level="card", card=card)
        assert "2/3" in block  # 2 completed out of 3


class TestContextIsolation:
    """Test 3: Verify no data leaks between chat levels."""

    def _ps(self):
        from app.services.personality_service import PersonalityService
        return PersonalityService()

    def test_general_prompt_has_no_card_references(self):
        """General prompt should not mention kanban or sprint in general chat init."""
        ps = self._ps()
        prompt = ps.build_general_chat_init(workspace_names=["Voxyflow"])
        assert "kanban" not in prompt.lower()
        assert "sprint" not in prompt.lower()

    def test_general_prompt_mentions_home_workspace(self):
        ps = self._ps()
        prompt = ps.build_general_chat_init()
        assert "Home workspace" in prompt

    def test_workspace_prompt_scoped_to_one_workspace(self):
        ps = self._ps()
        workspace = {"title": "WorkspaceA", "description": "AAA"}
        prompt = ps.build_workspace_chat_init(workspace)
        assert "WorkspaceA" in prompt
        assert "Stay focused here" in prompt

    def test_general_full_prompt_includes_chat_init_first(self):
        """Chat Init block should appear BEFORE personality files in the full prompt."""
        ps = self._ps()
        prompt = ps.build_general_prompt(workspace_names=["Voxyflow"])
        assert prompt.startswith("## Who You Are")

    def test_general_full_prompt_includes_custom_instructions(self, monkeypatch):
        ps = self._ps()
        monkeypatch.setattr(
            ps,
            "get_personality_settings",
            lambda: {"custom_instructions": "CUSTOM_MARKER", "tone": "casual", "warmth": "warm", "preferred_language": "auto"},
        )
        prompt = ps.build_general_prompt()
        assert "## Custom Instructions" in prompt
        assert "CUSTOM_MARKER" in prompt

    def test_workspace_full_prompt_includes_chat_init_first(self):
        ps = self._ps()
        workspace = {"title": "TestWorkspace"}
        prompt = ps.build_workspace_prompt(workspace)
        assert prompt.startswith("## Workspace:")

    def test_workspace_full_prompt_includes_identity(self, monkeypatch):
        ps = self._ps()
        monkeypatch.setattr(ps, "load_identity", lambda: "IDENTITY_MARKER")
        prompt = ps.build_workspace_prompt({"title": "TestWorkspace"})
        assert "IDENTITY_MARKER" in prompt

    def test_workspace_full_prompt_includes_custom_instructions(self, monkeypatch):
        ps = self._ps()
        monkeypatch.setattr(
            ps,
            "get_personality_settings",
            lambda: {"custom_instructions": "CUSTOM_MARKER", "tone": "casual", "warmth": "warm", "preferred_language": "auto"},
        )
        prompt = ps.build_workspace_prompt({"title": "TestWorkspace"})
        assert "CUSTOM_MARKER" in prompt

    def test_card_full_prompt_includes_chat_init_first(self):
        ps = self._ps()
        workspace = {"title": "TestWorkspace"}
        card = {"title": "Fix bug"}
        prompt = ps.build_card_prompt(workspace, card)
        assert prompt.startswith("## Chat Init")

    def test_card_full_prompt_includes_identity(self, monkeypatch):
        ps = self._ps()
        monkeypatch.setattr(ps, "load_identity", lambda: "IDENTITY_MARKER")
        prompt = ps.build_card_prompt({"title": "TestWorkspace"}, {"title": "Fix bug"})
        assert "IDENTITY_MARKER" in prompt

    def test_card_agent_prompt_includes_user_profile(self, monkeypatch):
        ps = self._ps()
        monkeypatch.setattr(ps, "load_user", lambda: "USER_MARKER")
        prompt = ps.build_card_prompt(
            {"title": "TestWorkspace"},
            {"title": "Fix bug"},
            agent_persona={"system_prompt": "AGENT_MARKER"},
        )
        assert "AGENT_MARKER" in prompt
        assert "USER_MARKER" in prompt

    def test_card_agent_prompt_includes_custom_instructions(self, monkeypatch):
        ps = self._ps()
        monkeypatch.setattr(
            ps,
            "get_personality_settings",
            lambda: {"custom_instructions": "CUSTOM_MARKER", "tone": "casual", "warmth": "warm", "preferred_language": "auto"},
        )
        prompt = ps.build_card_prompt(
            {"title": "TestWorkspace"},
            {"title": "Fix bug"},
            agent_persona={"system_prompt": "AGENT_MARKER"},
        )
        assert "AGENT_MARKER" in prompt
        assert "CUSTOM_MARKER" in prompt

    def test_general_and_workspace_tools_overlap_post_refactor(self):
        """Post-refactor: both general (Main workspace) and workspace have card tools.
        Unassigned aliases are available everywhere."""
        general_names = {t["name"] for t in _get_claude_tools("general")}
        workspace_names_set = {t["name"] for t in _get_claude_tools("workspace")}

        # Unassigned aliases available in both
        assert "voxyflow_card_create_unassigned" in general_names
        assert "voxyflow_card_create_unassigned" in workspace_names_set

        # Card tools available in both
        assert "voxyflow_card_create" in general_names
        assert "voxyflow_card_create" in workspace_names_set


class TestToolCallFallbackParsing:
    """Test 5: Verify the regex-based tool call fallback parser."""

    PATTERN = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)

    def test_single_tool_call(self):
        text = 'Sure! <tool_call>{"name": "voxyflow.card.create_unassigned", "arguments": {"content": "Test note"}}</tool_call> Done!'
        matches = self.PATTERN.findall(text)
        assert len(matches) == 1
        call = json.loads(matches[0])
        assert call["name"] == "voxyflow.card.create_unassigned"
        assert call["arguments"]["content"] == "Test note"

    def test_multiple_tool_calls(self):
        text = (
            '<tool_call>{"name": "voxyflow.card.create_unassigned", "arguments": {"content": "Note 1"}}</tool_call>\n'
            'Then also:\n'
            '<tool_call>{"name": "voxyflow.workspace.create", "arguments": {"title": "New Workspace"}}</tool_call>'
        )
        matches = self.PATTERN.findall(text)
        assert len(matches) == 2
        assert json.loads(matches[0])["name"] == "voxyflow.card.create_unassigned"
        assert json.loads(matches[1])["name"] == "voxyflow.workspace.create"

    def test_no_tool_call(self):
        text = "Just a regular response with no tool calls."
        matches = self.PATTERN.findall(text)
        assert len(matches) == 0

    def test_multiline_tool_call(self):
        text = """Here:
<tool_call>
{
  "name": "voxyflow.card.create",
  "arguments": {
    "workspace_id": "abc123",
    "title": "Fix login bug"
  }
}
</tool_call>"""
        matches = self.PATTERN.findall(text)
        assert len(matches) == 1
        call = json.loads(matches[0])
        assert call["name"] == "voxyflow.card.create"
        assert call["arguments"]["title"] == "Fix login bug"

    def test_tool_call_with_params_key(self):
        """Some LLMs use 'params' instead of 'arguments'."""
        text = '<tool_call>{"name": "voxyflow.health", "params": {}}</tool_call>'
        matches = self.PATTERN.findall(text)
        assert len(matches) == 1
        call = json.loads(matches[0])
        assert call["name"] == "voxyflow.health"


class TestToolNameConversion:
    """Test tool name conversion between Claude and MCP formats."""

    def test_claude_to_mcp_simple(self):
        assert _mcp_tool_name_from_claude("voxyflow_card_create") == "voxyflow.card.create"

    def test_claude_to_mcp_note(self):
        assert _mcp_tool_name_from_claude("voxyflow_card_create_unassigned") == "voxyflow.card.create_unassigned"

    def test_claude_to_mcp_health(self):
        # "voxyflow_health" splits into only 2 parts
        assert _mcp_tool_name_from_claude("voxyflow_health") == "voxyflow.health"

    def test_claude_to_mcp_ai_tool(self):
        assert _mcp_tool_name_from_claude("voxyflow_ai_standup") == "voxyflow.ai.standup"

    def test_claude_to_mcp_review_code(self):
        # "voxyflow_ai_review_code" → split(_, 2) → ["voxyflow", "ai", "review_code"]
        assert _mcp_tool_name_from_claude("voxyflow_ai_review_code") == "voxyflow.ai.review_code"

    def test_roundtrip_all_tools(self):
        """Every MCP tool name should survive the dot→underscore→dot roundtrip."""
        for tool in _get_tool_list():
            mcp_name = tool["name"]
            claude_name = mcp_name.replace(".", "_")
            roundtripped = _mcp_tool_name_from_claude(claude_name)
            assert roundtripped == mcp_name, (
                f"Roundtrip failed: {mcp_name} → {claude_name} → {roundtripped}"
            )


class TestDeepPrompt:
    """Test 7: Verify the deep layer prompt (chat responder mode)."""

    def _ps(self):
        from app.services.personality_service import PersonalityService
        return PersonalityService()

    def test_deep_chat_responder_has_dispatcher_rule(self):
        ps = self._ps()
        prompt = ps.build_deep_prompt(chat_level="general", is_chat_responder=True)
        assert "Dispatcher" in prompt or "DISPATCHER" in prompt or "dispatcher" in prompt

    def test_deep_prompt_changes_with_chat_level(self):
        ps = self._ps()
        general_prompt = ps.build_deep_prompt(chat_level="general", is_chat_responder=True)
        workspace = {"title": "TestWorkspace"}
        workspace_prompt = ps.build_deep_prompt(chat_level="workspace", workspace=workspace, is_chat_responder=True)
        assert "Home" in general_prompt
        assert "TestWorkspace" in workspace_prompt


class TestMCPToolDefinitions:
    """Validate the MCP tool definitions are well-formed."""

    def test_all_tools_have_http_method(self):
        from app.mcp_server import _TOOL_DEFINITIONS
        for tool in _TOOL_DEFINITIONS:
            assert "_http" in tool or "_handler" in tool, \
                f"Tool {tool['name']} missing _http or _handler"
            if "_http" in tool:
                method, path, _ = tool["_http"]
                assert method in ("GET", "POST", "PUT", "PATCH", "DELETE"), (
                    f"Tool {tool['name']} has invalid HTTP method: {method}"
                )

    def test_all_tools_have_input_schema(self):
        from app.mcp_server import _TOOL_DEFINITIONS
        for tool in _TOOL_DEFINITIONS:
            assert "inputSchema" in tool, f"Tool {tool['name']} missing inputSchema"
            assert tool["inputSchema"]["type"] == "object"

    def test_public_tool_defs_exclude_http(self):
        for tool in _get_tool_list():
            assert "_http" not in tool, f"Public tool {tool['name']} leaks _http"

    def test_find_tool_returns_correct(self):
        from app.mcp_server import _find_tool
        tool = _find_tool("voxyflow.card.create")
        assert tool is not None
        assert tool["name"] == "voxyflow.card.create"

    def test_find_tool_returns_none_for_unknown(self):
        from app.mcp_server import _find_tool
        assert _find_tool("voxyflow.nonexistent.tool") is None

    def test_tool_count(self):
        tools = _get_tool_list()
        assert len(tools) >= 25, f"Expected at least 25 tools, got {len(tools)}"


class TestFastPromptToolInjection:
    """Verify the fast prompt wires up the dispatcher delegation mechanism.

    Post-refactor, tool names are exposed to the LLM via the native tool API
    (Anthropic ``tools`` / OpenAI ``functions``), not as plain text inside the
    system prompt — so asserting that a specific ``voxyflow.card.create``
    substring appears no longer matches production behaviour. What does stay
    stable is the delegate-block contract the dispatcher ends with.
    """

    def _ps(self):
        from app.services.personality_service import PersonalityService
        return PersonalityService()

    def test_fast_prompt_has_delegate_instruction(self):
        ps = self._ps()
        prompt = ps.build_fast_prompt(chat_level="general")
        assert "voxyflow.delegate" in prompt, "Fast prompt should instruct on voxyflow.delegate MCP tool"
        assert "<delegate>" not in prompt, "Fast prompt must NOT contain legacy <delegate> XML markup"


class TestWorkerPromptIdentity:
    def _ps(self):
        from app.services.personality_service import PersonalityService
        return PersonalityService()

    def test_worker_prompt_includes_identity(self, monkeypatch):
        ps = self._ps()
        monkeypatch.setattr(ps, "load_identity", lambda: "IDENTITY_MARKER")
        monkeypatch.setattr(ps, "load_soul", lambda: "")
        monkeypatch.setattr(ps, "load_user", lambda: "")
        monkeypatch.setattr(ps, "load_worker", lambda: "WORKER_MARKER")
        monkeypatch.setattr(ps, "_build_tool_section", lambda *args, **kwargs: "TOOLS_MARKER")

        prompt = ps.build_worker_prompt(chat_level="general")

        assert "IDENTITY_MARKER" in prompt
        assert prompt.index("IDENTITY_MARKER") < prompt.index("WORKER_MARKER")

    def test_worker_prompt_includes_user_profile(self, monkeypatch):
        ps = self._ps()
        monkeypatch.setattr(ps, "load_identity", lambda: "")
        monkeypatch.setattr(ps, "load_soul", lambda: "")
        monkeypatch.setattr(ps, "load_user", lambda: "USER_MARKER")
        monkeypatch.setattr(ps, "load_worker", lambda: "WORKER_MARKER")
        monkeypatch.setattr(ps, "_build_tool_section", lambda *args, **kwargs: "TOOLS_MARKER")

        prompt = ps.build_worker_prompt(chat_level="general")

        assert "USER_MARKER" in prompt
        assert prompt.index("USER_MARKER") < prompt.index("WORKER_MARKER")

    def test_worker_prompt_includes_custom_instructions(self, monkeypatch):
        ps = self._ps()
        monkeypatch.setattr(ps, "load_identity", lambda: "")
        monkeypatch.setattr(ps, "load_soul", lambda: "")
        monkeypatch.setattr(ps, "load_user", lambda: "")
        monkeypatch.setattr(ps, "load_worker", lambda: "WORKER_MARKER")
        monkeypatch.setattr(ps, "_build_tool_section", lambda *args, **kwargs: "TOOLS_MARKER")
        monkeypatch.setattr(
            ps,
            "get_personality_settings",
            lambda: {"custom_instructions": "CUSTOM_MARKER", "tone": "casual", "warmth": "warm", "preferred_language": "auto"},
        )

        prompt = ps.build_worker_prompt(chat_level="general")

        assert "CUSTOM_MARKER" in prompt
        assert prompt.index("CUSTOM_MARKER") < prompt.index("WORKER_MARKER")


class TestAgentPromptBuilder:
    def _ps(self):
        from app.services.personality_service import PersonalityService
        return PersonalityService()

    def test_legacy_system_prompt_builder_removed(self):
        ps = self._ps()
        assert not hasattr(ps, "build_system_prompt")

    def test_agent_prompt_uses_active_settings_overrides(self, monkeypatch):
        ps = self._ps()
        monkeypatch.setattr(ps, "load_identity", lambda: "")
        monkeypatch.setattr(ps, "load_soul", lambda: "")
        monkeypatch.setattr(ps, "load_agents", lambda: "")
        monkeypatch.setattr(ps, "load_user", lambda: "USER_MARKER")
        monkeypatch.setattr(
            ps,
            "get_personality_settings",
            lambda: {"custom_instructions": "CUSTOM_MARKER", "tone": "casual", "warmth": "warm", "preferred_language": "auto"},
        )

        prompt = ps.build_agent_prompt("AGENT_MARKER", "TASK_MARKER", memory_context="MEMORY_MARKER")

        assert "USER_MARKER" in prompt
        assert "CUSTOM_MARKER" in prompt
        assert "MEMORY_MARKER" in prompt
        assert "AGENT_MARKER" in prompt
        assert "TASK_MARKER" in prompt


class TestMemoryFallbackIsolation:
    """Workspace chats must never fall back to global file memory.

    The file-based fallback (MEMORY.md + daily logs) is general-chat-only
    context. A fresh workspace (no ChromaDB hits) or a ChromaDB failure must
    not inject those global files into a workspace chat — 'a clean workspace
    must show zero knowledge from other contexts'.
    """

    def _make_service(self, calls):
        from app.services.memory_service import MemoryService

        class FakeMs(MemoryService):
            def __init__(self):
                self._chromadb_enabled = True
                self.daily_lookback_days = 3

            def search_memory(self, query, collections=None, limit=10, offset=0, **kwargs):
                return []  # fresh workspace — no memories anywhere

            def _build_l0_identity(self, workspace_id, budget=100):
                return None  # no KG service in unit tests

            def _load_long_term_memory(self):
                calls.append("long_term")
                return "GLOBAL MEMORY"

            def _load_daily_logs(self, days=None):
                calls.append("daily")
                return "GLOBAL DAILY"

            def _load_project_memory(self, workspace_name):
                calls.append(f"workspace:{workspace_name}")
                return ""

        return FakeMs()

    def test_workspace_empty_chromadb_never_reads_global_files(self):
        calls: list[str] = []
        ms = self._make_service(calls)
        ms._build_chromadb_context(
            query="test", workspace_id="proj-xyz", workspace_name="Proj",
            include_long_term=True,
        )
        assert "long_term" not in calls, "workspace chat read global MEMORY.md"
        assert "daily" not in calls, "workspace chat read global daily logs"

    def test_workspace_chromadb_exception_never_reads_global_files(self):
        calls: list[str] = []
        ms = self._make_service(calls)

        def _boom(*a, **k):
            raise RuntimeError("chromadb down")

        ms._build_l2_ondemand = _boom  # force the exception fallback path
        ms._build_chromadb_context(
            query="test", workspace_id="proj-xyz", workspace_name="Proj",
            include_long_term=True,
        )
        assert "long_term" not in calls, "exception fallback read global MEMORY.md"
        assert "daily" not in calls, "exception fallback read global daily logs"

    def test_workspace_queryless_never_reads_global_files(self):
        """build_memory_context without a query (e.g. tool-call follow-up)."""
        calls: list[str] = []
        ms = self._make_service(calls)
        ms.build_memory_context(
            workspace_name="Proj", workspace_id="proj-xyz",
            include_long_term=True, include_daily=True, layers=(0,),
        )
        assert "long_term" not in calls, "query-less workspace call read global MEMORY.md"
        assert "daily" not in calls, "query-less workspace call read global daily logs"

    def test_general_chat_still_gets_global_file_fallback(self):
        calls: list[str] = []
        ms = self._make_service(calls)
        ctx = ms.build_memory_context(include_long_term=True, include_daily=True)
        assert "long_term" in calls, "general chat lost MEMORY.md fallback"
        assert "daily" in calls, "general chat lost daily-log fallback"
        assert ctx and "GLOBAL MEMORY" in ctx


# ============================================================================
# INTEGRATION TESTS — Require running backend at http://localhost:8000
# ============================================================================


@pytest.fixture
def backend_url():
    return os.environ.get("VOXYFLOW_URL", "http://localhost:8000")


def _backend_available(url: str = "http://localhost:8000") -> bool:
    """Check if the backend is reachable."""
    import httpx
    try:
        r = httpx.get(f"{url}/api/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


pytestmark_integration = pytest.mark.skipif(
    not _backend_available(),
    reason="Backend not available at http://localhost:8000",
)


@pytestmark_integration
class TestIntegrationWorkspaceCRUD:
    """Test 4a: Integration test — workspace CRUD via REST API."""

    @pytest.mark.asyncio
    async def test_list_workspaces(self, backend_url):
        import httpx
        async with httpx.AsyncClient(base_url=backend_url, timeout=10) as client:
            response = await client.get("/api/workspaces")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_create_workspace(self, backend_url):
        import httpx
        import time
        title = f"TestWorkspace_Integration_Isolation_{int(time.time())}"
        async with httpx.AsyncClient(base_url=backend_url, timeout=10) as client:
            response = await client.post("/api/workspaces", json={
                "title": title,
                "description": "Created by integration test",
            })
            assert response.status_code in (200, 201), f"Create failed: {response.text}"
            data = response.json()
            assert "id" in data
            workspace_id = data["id"]

            # Verify it exists
            get_resp = await client.get(f"/api/workspaces/{workspace_id}")
            assert get_resp.status_code == 200
            assert get_resp.json()["title"] == title


@pytestmark_integration
class TestIntegrationHealthEndpoint:
    """Test 4b: Integration test — health endpoint."""

    @pytest.mark.asyncio
    async def test_health_returns_ok(self, backend_url):
        import httpx
        async with httpx.AsyncClient(base_url=backend_url, timeout=10) as client:
            response = await client.get("/api/health")
            assert response.status_code == 200
            data = response.json()
            assert "status" in data or isinstance(data, dict)


@pytestmark_integration
class TestIntegrationMCPToolEndpoints:
    """Test 4c: Integration test — MCP tool definitions endpoint."""

    @pytest.mark.asyncio
    async def test_tool_definitions_endpoint(self, backend_url):
        import httpx
        async with httpx.AsyncClient(base_url=backend_url, timeout=10) as client:
            response = await client.get("/mcp/tools")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, (list, dict))


@pytestmark_integration
class TestIntegrationCardCRUD:
    """Test 4d: Integration test — card CRUD within a workspace."""

    @pytest.mark.asyncio
    async def test_create_card_in_workspace(self, backend_url):
        import httpx
        import time
        async with httpx.AsyncClient(base_url=backend_url, timeout=10) as client:
            # Create a temporary workspace with unique name to avoid conflicts
            proj_resp = await client.post("/api/workspaces", json={
                "title": f"TestWorkspace_CardCRUD_{int(time.time())}",
                "description": "Temporary for card test",
            })
            assert proj_resp.status_code in (200, 201)
            workspace_id = proj_resp.json()["id"]

            # Create a card
            card_resp = await client.post(f"/api/workspaces/{workspace_id}/cards", json={
                "title": "Test Card Isolation",
                "description": "Integration test card",
                "status": "todo",
                "priority": 2,
            })
            assert card_resp.status_code in (200, 201), f"Card create failed: {card_resp.text}"
            card_data = card_resp.json()
            assert "id" in card_data
            assert card_data["title"] == "Test Card Isolation"

            # List cards
            list_resp = await client.get(f"/api/workspaces/{workspace_id}/cards")
            assert list_resp.status_code == 200
            cards = list_resp.json()
            assert any(c["id"] == card_data["id"] for c in cards)
