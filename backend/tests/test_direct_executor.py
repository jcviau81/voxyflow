"""Tests for DirectExecutor fast-path CRUD and orchestrator integration."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.direct_executor import (
    DirectExecutor,
    DIRECT_ACTION_MAP,
    CONFIRM_REQUIRED,
    NO_PARAMS_REQUIRED,
)


# ===================================================================
# A. DirectExecutor unit tests
# ===================================================================


class TestIsDirectEligible:
    """Tests for DirectExecutor.is_direct_eligible()."""

    @pytest.mark.parametrize("action", [
        "card.create", "card.update", "card.move", "card.delete", "card.list",
        "create_card", "update_card", "move_card", "delete_card",
        # New actions
        "card.get", "get_card", "list_cards",
        "project.list", "project.get", "project.create", "project.delete",
        "list_projects", "get_project", "create_project", "delete_project",
        "wiki.list", "wiki.get", "list_wiki", "get_wiki",
        "jobs.list", "list_jobs", "health",
    ])
    def test_whitelisted_actions_eligible(self, action):
        data = {"model": "direct", "action": action, "params": {"title": "x"}}
        assert DirectExecutor.is_direct_eligible(data) is True

    @pytest.mark.parametrize("action", [
        "web_research", "file_read", "git_commit", "system.exec", "unknown",
    ])
    def test_non_whitelisted_actions_not_eligible(self, action):
        data = {"model": "direct", "action": action, "params": {"q": "x"}}
        assert DirectExecutor.is_direct_eligible(data) is False

    @pytest.mark.parametrize("action", ["health", "project.list", "list_projects", "jobs.list", "list_jobs"])
    def test_no_param_actions_eligible_without_params(self, action):
        """Actions that need no params should be eligible even with empty/missing params."""
        data = {"model": "direct", "action": action}
        assert DirectExecutor.is_direct_eligible(data) is True

        data_empty = {"model": "direct", "action": action, "params": {}}
        assert DirectExecutor.is_direct_eligible(data_empty) is True

    def test_not_eligible_without_model_direct(self):
        data = {"model": "sonnet", "action": "card.create", "params": {"title": "x"}}
        assert DirectExecutor.is_direct_eligible(data) is False

    def test_not_eligible_without_params(self):
        data = {"model": "direct", "action": "card.create"}
        assert DirectExecutor.is_direct_eligible(data) is False

    def test_not_eligible_with_empty_params(self):
        data = {"model": "direct", "action": "card.create", "params": {}}
        assert DirectExecutor.is_direct_eligible(data) is False


class TestNeedsConfirmation:
    """Tests for DirectExecutor.needs_confirmation()."""

    @pytest.mark.parametrize("action", [
        "card.delete", "delete_card", "project.delete", "delete_project",
    ])
    def test_delete_actions_need_confirmation(self, action):
        assert DirectExecutor.needs_confirmation({"action": action}) is True

    @pytest.mark.parametrize("action", [
        "card.create", "card.update", "card.move", "card.list", "card.get",
        "create_card", "update_card", "move_card", "list_cards", "get_card",
        "project.list", "project.get", "project.create",
        "list_projects", "get_project", "create_project",
        "wiki.list", "wiki.get", "list_wiki", "get_wiki",
        "jobs.list", "list_jobs", "health",
    ])
    def test_non_delete_actions_no_confirmation(self, action):
        assert DirectExecutor.needs_confirmation({"action": action}) is False

    def test_missing_action_no_confirmation(self):
        assert DirectExecutor.needs_confirmation({}) is False


class TestExecute:
    """Tests for DirectExecutor.execute()."""

    @pytest.fixture
    def mock_mcp(self):
        """Patch _find_tool and _call_api from mcp_server."""
        tool_def = {
            "name": "voxyflow.card.create",
            "inputSchema": {
                "required": ["project_id", "title"],
                "properties": {
                    "project_id": {"type": "string"},
                    "title": {"type": "string"},
                },
            },
        }
        with patch("app.mcp_server._find_tool", return_value=tool_def) as find, \
             patch("app.mcp_server._call_api", new_callable=AsyncMock) as call:
            yield find, call, tool_def

    @pytest.mark.asyncio
    async def test_execute_calls_api_with_correct_params(self, mock_mcp):
        find_tool, call_api, tool_def = mock_mcp
        call_api.return_value = {"id": "card-123", "title": "Test"}

        data = {"action": "card.create", "params": {"title": "Test"}}
        result = await DirectExecutor.execute(data, project_id="proj-1")

        assert result["success"] is True
        assert result["action"] == "card.create"
        assert result["mcp_tool"] == "voxyflow.card.create"
        assert result["result"] == {"id": "card-123", "title": "Test"}
        assert result["duration_ms"] >= 0

        call_api.assert_called_once_with(tool_def, {"title": "Test", "project_id": "proj-1"})

    @pytest.mark.asyncio
    async def test_execute_auto_injects_project_id(self, mock_mcp):
        _, call_api, tool_def = mock_mcp
        call_api.return_value = {"ok": True}

        data = {"action": "card.create", "params": {"title": "New Card"}}
        await DirectExecutor.execute(data, project_id="my-proj")

        called_params = call_api.call_args[0][1]
        assert called_params["project_id"] == "my-proj"

    @pytest.mark.asyncio
    async def test_execute_does_not_overwrite_explicit_project_id(self, mock_mcp):
        _, call_api, tool_def = mock_mcp
        call_api.return_value = {"ok": True}

        data = {"action": "card.create", "params": {"title": "X", "project_id": "explicit"}}
        await DirectExecutor.execute(data, project_id="context-proj")

        called_params = call_api.call_args[0][1]
        assert called_params["project_id"] == "explicit"

    @pytest.mark.asyncio
    async def test_execute_error_when_api_raises(self, mock_mcp):
        _, call_api, _ = mock_mcp
        call_api.side_effect = RuntimeError("connection refused")

        data = {"action": "card.create", "params": {"title": "X"}}
        result = await DirectExecutor.execute(data, project_id="proj-1")

        assert result["success"] is False
        assert "connection refused" in result["error"]
        assert result["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_execute_unknown_action_returns_error(self):
        data = {"action": "not_a_thing", "params": {"x": 1}}
        result = await DirectExecutor.execute(data)

        assert result["success"] is False
        assert "not in direct whitelist" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_missing_project_id_returns_error(self):
        tool_def = {
            "name": "voxyflow.card.create",
            "inputSchema": {"required": ["project_id"], "properties": {}},
        }
        with patch("app.mcp_server._find_tool", return_value=tool_def), \
             patch("app.mcp_server._call_api", new_callable=AsyncMock):
            data = {"action": "card.create", "params": {"title": "X"}}
            result = await DirectExecutor.execute(data, project_id=None)

            assert result["success"] is False
            assert "project_id required" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self):
        with patch("app.mcp_server._find_tool", return_value=None):
            data = {"action": "card.create", "params": {"title": "X"}}
            result = await DirectExecutor.execute(data)

            assert result["success"] is False
            assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_execute_card_list_auto_injects_project_id(self):
        """card.list should auto-inject project_id from context."""
        tool_def = {
            "name": "voxyflow.card.list",
            "inputSchema": {
                "required": ["project_id"],
                "properties": {"project_id": {"type": "string"}},
            },
        }
        with patch("app.mcp_server._find_tool", return_value=tool_def), \
             patch("app.mcp_server._call_api", new_callable=AsyncMock, return_value=[]) as call_api:
            data = {"action": "card.list", "params": {}}
            result = await DirectExecutor.execute(data, project_id="proj-abc")

            assert result["success"] is True
            call_api.assert_called_once_with(tool_def, {"project_id": "proj-abc"})

    @pytest.mark.asyncio
    async def test_execute_project_list_no_params(self):
        """project.list needs no params at all."""
        tool_def = {
            "name": "voxyflow.project.list",
            "inputSchema": {"properties": {}},
        }
        with patch("app.mcp_server._find_tool", return_value=tool_def), \
             patch("app.mcp_server._call_api", new_callable=AsyncMock, return_value=[{"id": "p1"}]) as call_api:
            data = {"action": "project.list", "params": {}}
            result = await DirectExecutor.execute(data)

            assert result["success"] is True
            assert result["mcp_tool"] == "voxyflow.project.list"
            call_api.assert_called_once_with(tool_def, {})

    @pytest.mark.asyncio
    async def test_execute_health_no_params(self):
        """health action needs no params."""
        tool_def = {
            "name": "voxyflow.health",
            "inputSchema": {"properties": {}},
        }
        with patch("app.mcp_server._find_tool", return_value=tool_def), \
             patch("app.mcp_server._call_api", new_callable=AsyncMock, return_value={"status": "ok"}) as call_api:
            data = {"action": "health", "params": {}}
            result = await DirectExecutor.execute(data)

            assert result["success"] is True
            assert result["mcp_tool"] == "voxyflow.health"
            call_api.assert_called_once_with(tool_def, {})

    @pytest.mark.asyncio
    async def test_execute_card_get_with_card_id(self):
        """card.get passes card_id through."""
        tool_def = {
            "name": "voxyflow.card.get",
            "inputSchema": {
                "required": ["card_id"],
                "properties": {"card_id": {"type": "string"}},
            },
        }
        with patch("app.mcp_server._find_tool", return_value=tool_def), \
             patch("app.mcp_server._call_api", new_callable=AsyncMock, return_value={"id": "c1", "title": "Test"}) as call_api:
            data = {"action": "card.get", "params": {"card_id": "c1"}}
            result = await DirectExecutor.execute(data)

            assert result["success"] is True
            assert result["mcp_tool"] == "voxyflow.card.get"
            call_api.assert_called_once_with(tool_def, {"card_id": "c1"})

    @pytest.mark.asyncio
    async def test_execute_wiki_list_auto_injects_project_id(self):
        """wiki.list should auto-inject project_id from context."""
        tool_def = {
            "name": "voxyflow.wiki.list",
            "inputSchema": {
                "required": ["project_id"],
                "properties": {"project_id": {"type": "string"}},
            },
        }
        with patch("app.mcp_server._find_tool", return_value=tool_def), \
             patch("app.mcp_server._call_api", new_callable=AsyncMock, return_value=[]) as call_api:
            data = {"action": "wiki.list", "params": {}}
            result = await DirectExecutor.execute(data, project_id="proj-xyz")

            assert result["success"] is True
            call_api.assert_called_once_with(tool_def, {"project_id": "proj-xyz"})

    @pytest.mark.asyncio
    async def test_execute_project_create_with_params(self):
        """project.create passes title and optional description."""
        tool_def = {
            "name": "voxyflow.project.create",
            "inputSchema": {
                "required": ["title"],
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
            },
        }
        with patch("app.mcp_server._find_tool", return_value=tool_def), \
             patch("app.mcp_server._call_api", new_callable=AsyncMock, return_value={"id": "p-new"}) as call_api:
            data = {"action": "project.create", "params": {"title": "New Project", "description": "Desc"}}
            result = await DirectExecutor.execute(data)

            assert result["success"] is True
            assert result["mcp_tool"] == "voxyflow.project.create"
            call_api.assert_called_once_with(tool_def, {"title": "New Project", "description": "Desc"})

    @pytest.mark.asyncio
    async def test_execute_project_delete_needs_project_id(self):
        """project.delete should work with explicit project_id in params."""
        tool_def = {
            "name": "voxyflow.project.delete",
            "inputSchema": {
                "required": ["project_id"],
                "properties": {"project_id": {"type": "string"}},
            },
        }
        with patch("app.mcp_server._find_tool", return_value=tool_def), \
             patch("app.mcp_server._call_api", new_callable=AsyncMock, return_value={"success": True}) as call_api:
            data = {"action": "project.delete", "params": {"project_id": "proj-del"}}
            result = await DirectExecutor.execute(data)

            assert result["success"] is True
            call_api.assert_called_once_with(tool_def, {"project_id": "proj-del"})


# ===================================================================
# B. Integration-level tests for the orchestrator direct action flow
# ===================================================================


def _make_orchestrator():
    """Create a ChatOrchestrator with mocked dependencies."""
    from app.services.chat_orchestration import ChatOrchestrator

    claude_service = MagicMock()
    return ChatOrchestrator(claude_service)


def _mock_ws():
    """Create a mock WebSocket with async send_json."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


class TestExecuteDirectAction:
    """Tests for ChatOrchestrator._execute_direct_action()."""

    @pytest.mark.asyncio
    async def test_direct_action_sends_started_and_completed(self):
        orch = _make_orchestrator()
        ws = _mock_ws()

        mock_result = {
            "success": True,
            "action": "card.create",
            "mcp_tool": "voxyflow.card.create",
            "result": {"id": "c1", "title": "Test"},
            "duration_ms": 42,
        }

        with patch.object(DirectExecutor, "execute", new_callable=AsyncMock, return_value=mock_result), \
             patch.object(DirectExecutor, "needs_confirmation", return_value=False):
            await orch._execute_direct_action(
                data={"action": "card.create", "params": {"title": "Test"}},
                websocket=ws,
                session_id="sess-1",
                project_id="proj-1",
            )

        # Should have sent: action:started, action:completed, chat:response
        messages = [call.args[0] for call in ws.send_json.call_args_list]
        types = [m["type"] for m in messages]

        assert "action:started" in types
        assert "action:completed" in types

        completed = next(m for m in messages if m["type"] == "action:completed")
        assert completed["payload"]["success"] is True
        assert completed["payload"]["action"] == "card.create"

    @pytest.mark.asyncio
    async def test_delete_triggers_confirmation_flow(self):
        orch = _make_orchestrator()
        ws = _mock_ws()

        data = {"action": "card.delete", "params": {"card_id": "c1"}}

        await orch._execute_direct_action(
            data=data,
            websocket=ws,
            session_id="sess-1",
            project_id="proj-1",
        )

        # Should send confirm_required, NOT action:started
        messages = [call.args[0] for call in ws.send_json.call_args_list]
        types = [m["type"] for m in messages]

        assert "action:confirm_required" in types
        assert "action:started" not in types
        assert "action:completed" not in types

        # Should store in _pending_confirms
        assert len(orch._pending_confirms) == 1
        task_id = list(orch._pending_confirms.keys())[0]
        assert orch._pending_confirms[task_id]["data"] == data
        assert orch._pending_confirms[task_id]["project_id"] == "proj-1"

    @pytest.mark.asyncio
    async def test_delete_confirmation_message_content(self):
        orch = _make_orchestrator()
        ws = _mock_ws()

        await orch._execute_direct_action(
            data={"action": "card.delete", "params": {"card_id": "c1"}},
            websocket=ws,
            session_id="sess-1",
        )

        confirm_msg = ws.send_json.call_args_list[0][0][0]
        assert confirm_msg["type"] == "action:confirm_required"
        assert confirm_msg["payload"]["action"] == "card.delete"
        assert "irreversible" in confirm_msg["payload"]["message"].lower()


class TestHandleActionConfirm:
    """Tests for ChatOrchestrator.handle_action_confirm()."""

    @pytest.mark.asyncio
    async def test_confirm_true_executes_action(self):
        orch = _make_orchestrator()
        ws = _mock_ws()

        # Pre-populate pending confirmation
        task_id = "direct-abc12345"
        orch._pending_confirms[task_id] = {
            "data": {"action": "card.delete", "params": {"card_id": "c1"}},
            "project_id": "proj-1",
            "session_id": "sess-1",
        }

        mock_result = {
            "success": True,
            "action": "card.delete",
            "mcp_tool": "voxyflow.card.delete",
            "result": {"deleted": True},
            "duration_ms": 30,
        }

        with patch.object(DirectExecutor, "execute", new_callable=AsyncMock, return_value=mock_result):
            await orch.handle_action_confirm(task_id, confirmed=True, websocket=ws)

        # Should have sent action:started and action:completed
        messages = [call.args[0] for call in ws.send_json.call_args_list]
        types = [m["type"] for m in messages]
        assert "action:started" in types
        assert "action:completed" in types

        completed = next(m for m in messages if m["type"] == "action:completed")
        assert completed["payload"]["success"] is True
        assert completed["payload"]["taskId"] == task_id

        # Pending should be cleared
        assert task_id not in orch._pending_confirms

    @pytest.mark.asyncio
    async def test_confirm_false_cancels_action(self):
        orch = _make_orchestrator()
        ws = _mock_ws()

        task_id = "direct-cancel01"
        orch._pending_confirms[task_id] = {
            "data": {"action": "card.delete", "params": {"card_id": "c1"}},
            "project_id": "proj-1",
            "session_id": "sess-1",
        }

        with patch.object(DirectExecutor, "execute", new_callable=AsyncMock) as mock_exec:
            await orch.handle_action_confirm(task_id, confirmed=False, websocket=ws)

            # Should NOT execute the action
            mock_exec.assert_not_called()

        # Should send action:completed with success=False
        messages = [call.args[0] for call in ws.send_json.call_args_list]
        assert len(messages) == 1
        msg = messages[0]
        assert msg["type"] == "action:completed"
        assert msg["payload"]["success"] is False
        assert "Cancelled" in msg["payload"]["result"]["error"]

        # Pending should be cleared
        assert task_id not in orch._pending_confirms

    @pytest.mark.asyncio
    async def test_confirm_unknown_task_id_is_noop(self):
        orch = _make_orchestrator()
        ws = _mock_ws()

        await orch.handle_action_confirm("nonexistent-id", confirmed=True, websocket=ws)

        ws.send_json.assert_not_called()


# ===================================================================
# C. card.move lambda regression tests
# ===================================================================


class TestCardMoveLambda:
    """Verify the card.move MCP tool lambda accepts both 'new_status' and 'status'."""

    def test_lambda_accepts_new_status(self):
        from app.mcp_server import _find_tool
        tool = _find_tool("voxyflow.card.move")
        assert tool is not None

        _, _, transformer = tool["_http"]
        result = transformer({"new_status": "in-progress"})
        assert result == {"status": "in-progress"}

    def test_lambda_accepts_status_fallback(self):
        """Delegate JSON sends 'status' not 'new_status' — lambda must handle both."""
        from app.mcp_server import _find_tool
        tool = _find_tool("voxyflow.card.move")

        _, _, transformer = tool["_http"]
        result = transformer({"status": "done"})
        assert result == {"status": "done"}

    def test_lambda_prefers_new_status_over_status(self):
        """If both keys present, new_status wins (MCP canonical name)."""
        from app.mcp_server import _find_tool
        tool = _find_tool("voxyflow.card.move")

        _, _, transformer = tool["_http"]
        result = transformer({"new_status": "todo", "status": "done"})
        assert result == {"status": "todo"}
