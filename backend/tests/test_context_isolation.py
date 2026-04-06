"""Voxyflow — Context Isolation & Tool Scoping Tests

Comprehensive test suite verifying:
1. Tool scoping per chat level (general / project / card)
2. Chat Init content correctness per level
3. Context isolation — no data leaks between levels
4. Tool call fallback parsing (regex extraction)
5. Analyzer output format expectations
6. Deep layer prompt (chat responder mode)
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

    Post-refactor: "general" is now the system-main project and gets both
    unassigned aliases AND project card tools. Project level gets all tools.
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
            "voxyflow.project.create",
            "voxyflow.project.list",
            "voxyflow.project.get",
            "voxyflow.health",
        }
    elif chat_level == "project":
        # Project level: all tools (unassigned aliases are still valid)
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
    """Replicate the name conversion from claude_service.py."""
    parts = claude_name.split("_", 2)
    return ".".join(parts)


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

    def test_general_has_project_tools(self):
        names = self._tool_names("general")
        assert "voxyflow_project_create" in names, "General chat should have project_create"
        assert "voxyflow_project_list" in names, "General chat should have project_list"

    def test_general_has_health(self):
        names = self._tool_names("general")
        assert "voxyflow_health" in names, "General chat should have health check"

    def test_general_has_card_tools(self):
        """Post-refactor: general (Main project) has card tools since Main is a real project."""
        names = self._tool_names("general")
        assert "voxyflow_card_create" in names, "General/Main should have card_create"
        assert "voxyflow_card_update" in names, "General/Main should have card_update"
        assert "voxyflow_card_move" in names, "General/Main should have card_move"

    def test_general_excludes_wiki_tools(self):
        names = self._tool_names("general")
        assert "voxyflow_wiki_create" not in names, "General/Main chat should NOT have wiki_create"
        assert "voxyflow_wiki_list" not in names, "General/Main chat should NOT have wiki_list"

    def test_general_excludes_ai_project_tools(self):
        names = self._tool_names("general")
        assert "voxyflow_ai_standup" not in names, "General/Main chat should NOT have standup"
        assert "voxyflow_ai_brief" not in names, "General/Main chat should NOT have brief"

    def test_general_tool_count(self):
        """General/Main chat should have exactly 11 tools (unassigned aliases + card CRUD + project/health)."""
        tools = _get_claude_tools("general")
        assert len(tools) == 11, f"Expected 11 general tools, got {len(tools)}: {[t['name'] for t in tools]}"

    # -- Project chat tools --

    def test_project_has_card_tools(self):
        names = self._tool_names("project")
        assert "voxyflow_card_create" in names, "Project chat should have card_create"
        assert "voxyflow_card_update" in names, "Project chat should have card_update"
        assert "voxyflow_card_list" in names, "Project chat should have card_list"

    def test_project_has_wiki_tools(self):
        names = self._tool_names("project")
        assert "voxyflow_wiki_create" in names, "Project chat should have wiki_create"
        assert "voxyflow_wiki_list" in names, "Project chat should have wiki_list"

    def test_project_has_ai_tools(self):
        names = self._tool_names("project")
        assert "voxyflow_ai_standup" in names, "Project chat should have standup"
        assert "voxyflow_ai_brief" in names, "Project chat should have brief"
        assert "voxyflow_ai_health" in names, "Project chat should have health"

    def test_project_has_unassigned_tools(self):
        """Post-refactor: unassigned tools are aliases, available everywhere."""
        names = self._tool_names("project")
        assert "voxyflow_card_create_unassigned" in names, "Project chat should have card_create_unassigned (alias)"
        assert "voxyflow_card_list_unassigned" in names, "Project chat should have card_list_unassigned (alias)"

    def test_project_has_more_tools_than_general(self):
        general = _get_claude_tools("general")
        project = _get_claude_tools("project")
        assert len(project) > len(general), "Project should have more tools than general"

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
        for level in ("general", "project", "card"):
            tools = _get_claude_tools(level)
            for t in tools:
                assert "." not in t["name"], f"Tool name has dots: {t['name']} (level={level})"

    def test_tools_have_required_fields(self):
        """Each tool must have name, description, and input_schema."""
        for level in ("general", "project", "card"):
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

    def test_general_chat_init_has_mode(self):
        ps = self._ps()
        prompt = ps.build_general_chat_init(project_names=["Voxyflow", "Dictoral"])
        assert "Main project" in prompt

    def test_general_chat_init_lists_projects(self):
        ps = self._ps()
        prompt = ps.build_general_chat_init(project_names=["Voxyflow", "Dictoral"])
        assert "Voxyflow" in prompt
        assert "Dictoral" in prompt

    def test_general_chat_init_main_project_context(self):
        ps = self._ps()
        prompt = ps.build_general_chat_init(project_names=["Voxyflow"])
        assert "Main project" in prompt

    def test_general_chat_init_mentions_notes(self):
        ps = self._ps()
        prompt = ps.build_general_chat_init()
        assert "card" in prompt.lower() or "Card" in prompt

    def test_general_chat_init_empty_projects(self):
        ps = self._ps()
        prompt = ps.build_general_chat_init(project_names=[])
        assert "no projects yet" in prompt

    def test_general_chat_init_none_projects(self):
        ps = self._ps()
        prompt = ps.build_general_chat_init(project_names=None)
        assert "no projects yet" in prompt

    # -- Project Chat Init --

    def test_project_chat_init_has_project_name(self):
        ps = self._ps()
        project = {"title": "TestProject", "description": "A test", "tech_stack": "Python"}
        prompt = ps.build_project_chat_init(project)
        assert "TestProject" in prompt

    def test_project_chat_init_has_mode(self):
        ps = self._ps()
        project = {"title": "TestProject"}
        prompt = ps.build_project_chat_init(project)
        assert "## Project:" in prompt

    def test_project_chat_init_has_tech_stack(self):
        ps = self._ps()
        project = {"title": "TestProject", "tech_stack": "Python, FastAPI"}
        prompt = ps.build_project_chat_init(project)
        assert "Python, FastAPI" in prompt

    def test_project_chat_init_has_stay_focused(self):
        ps = self._ps()
        project = {"title": "TestProject"}
        prompt = ps.build_project_chat_init(project)
        assert "Stay focused here" in prompt

    def test_project_chat_init_has_card_counts(self):
        ps = self._ps()
        project = {
            "title": "TestProject",
            "cards": [
                {"status": "done", "title": "Card1", "updated_at": "2026-01-01"},
                {"status": "todo", "title": "Card2", "updated_at": "2026-01-02"},
                {"status": "in_progress", "title": "Card3", "updated_at": "2026-01-03"},
            ],
        }
        prompt = ps.build_project_chat_init(project)
        assert "3 cards" in prompt
        assert "1 done" in prompt
        assert "1 in progress" in prompt
        assert "1 todo" in prompt

    # -- Card Chat Init --

    def test_card_chat_init_has_card_title(self):
        ps = self._ps()
        project = {"title": "TestProject"}
        card = {"title": "Fix bug", "status": "todo", "priority": "high", "agent_type": "coder"}
        prompt = ps.build_card_chat_init(project, card)
        assert "Fix bug" in prompt

    def test_card_chat_init_has_mode(self):
        ps = self._ps()
        project = {"title": "TestProject"}
        card = {"title": "Fix bug", "status": "todo"}
        prompt = ps.build_card_chat_init(project, card)
        assert "Card Chat" in prompt

    def test_card_chat_init_has_project_name(self):
        ps = self._ps()
        project = {"title": "TestProject"}
        card = {"title": "Fix bug"}
        prompt = ps.build_card_chat_init(project, card)
        assert "TestProject" in prompt

    def test_card_chat_init_has_status_and_priority(self):
        ps = self._ps()
        project = {"title": "TestProject"}
        card = {"title": "Fix bug", "status": "in_progress", "priority": "high"}
        prompt = ps.build_card_chat_init(project, card)
        assert "in_progress" in prompt
        assert "high" in prompt

    def test_card_chat_init_has_checklist_count(self):
        ps = self._ps()
        project = {"title": "TestProject"}
        card = {
            "title": "Fix bug",
            "checklist_items": [
                {"text": "Step 1", "done": True},
                {"text": "Step 2", "done": False},
                {"text": "Step 3", "done": True},
            ],
        }
        prompt = ps.build_card_chat_init(project, card)
        assert "2/3" in prompt  # 2 completed out of 3


class TestContextIsolation:
    """Test 3: Verify no data leaks between chat levels."""

    def _ps(self):
        from app.services.personality_service import PersonalityService
        return PersonalityService()

    def test_general_prompt_has_no_card_references(self):
        """General prompt should not mention kanban or sprint in general chat init."""
        ps = self._ps()
        prompt = ps.build_general_chat_init(project_names=["Voxyflow"])
        assert "kanban" not in prompt.lower()
        assert "sprint" not in prompt.lower()

    def test_general_prompt_mentions_main_project(self):
        ps = self._ps()
        prompt = ps.build_general_chat_init(project_names=["Voxyflow"])
        assert "Main project" in prompt

    def test_project_prompt_scoped_to_one_project(self):
        ps = self._ps()
        project = {"title": "ProjectA", "description": "AAA"}
        prompt = ps.build_project_chat_init(project)
        assert "ProjectA" in prompt
        assert "Stay focused here" in prompt

    def test_general_full_prompt_includes_chat_init_first(self):
        """Chat Init block should appear BEFORE personality files in the full prompt."""
        ps = self._ps()
        prompt = ps.build_general_prompt(project_names=["Voxyflow"])
        assert prompt.startswith("## Who You Are")

    def test_project_full_prompt_includes_chat_init_first(self):
        ps = self._ps()
        project = {"title": "TestProject"}
        prompt = ps.build_project_prompt(project)
        assert prompt.startswith("## Project:")

    def test_card_full_prompt_includes_chat_init_first(self):
        ps = self._ps()
        project = {"title": "TestProject"}
        card = {"title": "Fix bug"}
        prompt = ps.build_card_prompt(project, card)
        assert prompt.startswith("## Chat Init")

    def test_general_and_project_tools_overlap_post_refactor(self):
        """Post-refactor: both general (Main project) and project have card tools.
        Unassigned aliases are available everywhere."""
        general_names = {t["name"] for t in _get_claude_tools("general")}
        project_names_set = {t["name"] for t in _get_claude_tools("project")}

        # Unassigned aliases available in both
        assert "voxyflow_card_create_unassigned" in general_names
        assert "voxyflow_card_create_unassigned" in project_names_set

        # Card tools available in both
        assert "voxyflow_card_create" in general_names
        assert "voxyflow_card_create" in project_names_set


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
            '<tool_call>{"name": "voxyflow.project.create", "arguments": {"title": "New Project"}}</tool_call>'
        )
        matches = self.PATTERN.findall(text)
        assert len(matches) == 2
        assert json.loads(matches[0])["name"] == "voxyflow.card.create_unassigned"
        assert json.loads(matches[1])["name"] == "voxyflow.project.create"

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
    "project_id": "abc123",
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


class TestAnalyzerPrompt:
    """Test 6: Verify the analyzer prompt structure and content."""

    def _ps(self):
        from app.services.personality_service import PersonalityService
        return PersonalityService()

    def test_analyzer_requests_json(self):
        ps = self._ps()
        prompt = ps.build_analyzer_prompt(chat_level="general", project_names=["Test"])
        assert "JSON" in prompt

    def test_analyzer_has_suggestion_types(self):
        ps = self._ps()
        prompt = ps.build_analyzer_prompt(chat_level="general", project_names=["Test"])
        assert "card-mainboard|card|project" in prompt

    def test_analyzer_requires_verb_titles(self):
        ps = self._ps()
        prompt = ps.build_analyzer_prompt(chat_level="general")
        assert "Verb" in prompt or "VERB" in prompt
        assert "Fix" in prompt or "Add" in prompt or "Create" in prompt

    def test_analyzer_general_context_mentions_main_project(self):
        ps = self._ps()
        prompt = ps.build_analyzer_prompt(chat_level="general", project_names=["Voxyflow"])
        assert "Main" in prompt
        assert "MAIN PROJECT" in prompt or "Main Project" in prompt or "main project" in prompt.lower()

    def test_analyzer_project_context(self):
        ps = self._ps()
        prompt = ps.build_analyzer_prompt(chat_level="project")
        assert "PROJECT CHAT" in prompt or "Project Chat" in prompt

    def test_analyzer_has_bad_examples(self):
        ps = self._ps()
        prompt = ps.build_analyzer_prompt(chat_level="general")
        assert "BAD Example" in prompt or "too vague" in prompt or "too broad" in prompt, \
            "Analyzer prompt should have bad examples"

    def test_analyzer_has_good_examples(self):
        ps = self._ps()
        prompt = ps.build_analyzer_prompt(chat_level="general")
        assert "✅" in prompt, "Analyzer prompt should have good examples"


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
        project = {"title": "TestProject"}
        project_prompt = ps.build_deep_prompt(chat_level="project", project=project, is_chat_responder=True)
        assert "Main" in general_prompt
        assert "TestProject" in project_prompt


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
    """Verify the fast prompt includes tool instructions filtered by level."""

    def _ps(self):
        from app.services.personality_service import PersonalityService
        return PersonalityService()

    def test_fast_prompt_general_has_card_tools_text(self):
        """Post-refactor: general (Main project) has both unassigned aliases and card tools."""
        ps = self._ps()
        prompt = ps.build_fast_prompt(chat_level="general", project_names=["Test"])
        assert "voxyflow.card.create_unassigned" in prompt or "voxyflow.card.create" in prompt

    def test_fast_prompt_project_has_card_tools_text(self):
        ps = self._ps()
        project = {"title": "TestProject"}
        prompt = ps.build_fast_prompt(chat_level="project", project=project)
        assert "voxyflow.card.create" in prompt

    def test_fast_prompt_card_has_all_tools_text(self):
        ps = self._ps()
        project = {"title": "TestProject"}
        card = {"title": "Fix bug"}
        prompt = ps.build_fast_prompt(chat_level="card", project=project, card=card)
        assert "voxyflow.card.create" in prompt
        assert "voxyflow.card.create_unassigned" in prompt

    def test_fast_prompt_has_tool_call_xml_instruction(self):
        ps = self._ps()
        prompt = ps.build_fast_prompt(chat_level="general")
        assert "<delegate>" in prompt, "Fast prompt should instruct on <delegate> XML format"


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
class TestIntegrationProjectCRUD:
    """Test 4a: Integration test — project CRUD via REST API."""

    @pytest.mark.asyncio
    async def test_list_projects(self, backend_url):
        import httpx
        async with httpx.AsyncClient(base_url=backend_url, timeout=10) as client:
            response = await client.get("/api/projects")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_create_project(self, backend_url):
        import httpx
        import time
        title = f"TestProject_Integration_Isolation_{int(time.time())}"
        async with httpx.AsyncClient(base_url=backend_url, timeout=10) as client:
            response = await client.post("/api/projects", json={
                "title": title,
                "description": "Created by integration test",
            })
            assert response.status_code in (200, 201), f"Create failed: {response.text}"
            data = response.json()
            assert "id" in data
            project_id = data["id"]

            # Verify it exists
            get_resp = await client.get(f"/api/projects/{project_id}")
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
    """Test 4d: Integration test — card CRUD within a project."""

    @pytest.mark.asyncio
    async def test_create_card_in_project(self, backend_url):
        import httpx
        import time
        async with httpx.AsyncClient(base_url=backend_url, timeout=10) as client:
            # Create a temporary project with unique name to avoid conflicts
            proj_resp = await client.post("/api/projects", json={
                "title": f"TestProject_CardCRUD_{int(time.time())}",
                "description": "Temporary for card test",
            })
            assert proj_resp.status_code in (200, 201)
            project_id = proj_resp.json()["id"]

            # Create a card
            card_resp = await client.post(f"/api/projects/{project_id}/cards", json={
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
            list_resp = await client.get(f"/api/projects/{project_id}/cards")
            assert list_resp.status_code == 200
            cards = list_resp.json()
            assert any(c["id"] == card_data["id"] for c in cards)
