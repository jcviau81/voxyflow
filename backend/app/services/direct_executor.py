"""Direct Executor — fast-path inline CRUD for whitelisted atomic operations.

Bypasses the worker pipeline entirely. No Claude API call — the dispatcher
parses structured params from the delegate JSON and calls the Voxyflow REST API
(via the same MCP HTTP layer) directly.

Latency target: <500ms instead of ~10s worker round-trip.

Usage:
    from app.services.direct_executor import DirectExecutor

    executor = DirectExecutor()
    result = await executor.execute("card.create", params, project_id)
"""

import logging
import time
from typing import Any

logger = logging.getLogger("voxyflow.direct_executor")


# ---------------------------------------------------------------------------
# Whitelist of actions eligible for direct execution (no LLM needed)
# ---------------------------------------------------------------------------

# Maps short action names (used in delegate blocks) → MCP tool names
DIRECT_ACTION_MAP: dict[str, str] = {
    "card.create": "voxyflow.card.create",
    "card.update": "voxyflow.card.update",
    "card.move": "voxyflow.card.move",
    "card.delete": "voxyflow.card.delete",
    "card.list": "voxyflow.card.list",
    # Aliases the dispatcher might use
    "create_card": "voxyflow.card.create",
    "update_card": "voxyflow.card.update",
    "move_card": "voxyflow.card.move",
    "delete_card": "voxyflow.card.delete",
}

# Actions that require user confirmation before execution (irreversible)
CONFIRM_REQUIRED = {"card.delete", "delete_card"}


class DirectExecutor:
    """Executes whitelisted CRUD operations inline without spawning a worker."""

    @staticmethod
    def is_direct_eligible(delegate_data: dict) -> bool:
        """Check if a delegate should take the fast path.

        Returns True if:
          - model == "direct"
          - action is in the whitelist
          - params dict is present (structured parameters required)
        """
        if delegate_data.get("model") != "direct":
            return False

        action = delegate_data.get("action", "")
        if action not in DIRECT_ACTION_MAP:
            logger.warning(f"[DirectExecutor] Action '{action}' not in whitelist, falling back to worker")
            return False

        if not delegate_data.get("params"):
            logger.warning(f"[DirectExecutor] No 'params' in delegate for action '{action}', falling back to worker")
            return False

        return True

    @staticmethod
    def needs_confirmation(delegate_data: dict) -> bool:
        """Check if this action requires user confirmation before execution."""
        action = delegate_data.get("action", "")
        return action in CONFIRM_REQUIRED

    @staticmethod
    async def execute(
        delegate_data: dict,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a direct CRUD action and return the result.

        Args:
            delegate_data: The full delegate dict with action, params, etc.
            project_id: The current project context (injected into params if needed).

        Returns:
            {
                "success": bool,
                "action": str,
                "mcp_tool": str,
                "result": dict,       # raw API response
                "duration_ms": int,
            }
        """
        from app.mcp_server import _find_tool, _call_api

        action = delegate_data.get("action", "")
        mcp_tool_name = DIRECT_ACTION_MAP.get(action)

        if not mcp_tool_name:
            return {
                "success": False,
                "action": action,
                "mcp_tool": None,
                "error": f"Action '{action}' not in direct whitelist",
                "duration_ms": 0,
            }

        tool_def = _find_tool(mcp_tool_name)
        if not tool_def:
            return {
                "success": False,
                "action": action,
                "mcp_tool": mcp_tool_name,
                "error": f"MCP tool '{mcp_tool_name}' not found",
                "duration_ms": 0,
            }

        # Build the params to pass to the MCP tool
        params = dict(delegate_data.get("params", {}))

        # Auto-inject project_id if the tool needs it and it's not in params
        tool_schema = tool_def.get("inputSchema", {})
        required_fields = tool_schema.get("required", [])
        if "project_id" in required_fields and "project_id" not in params:
            if project_id:
                params["project_id"] = project_id
            else:
                return {
                    "success": False,
                    "action": action,
                    "mcp_tool": mcp_tool_name,
                    "error": "project_id required but not available",
                    "duration_ms": 0,
                }

        logger.info(f"[DirectExecutor] Executing {action} → {mcp_tool_name} with params={params}")
        start = time.time()

        try:
            result = await _call_api(tool_def, params)
            duration_ms = int((time.time() - start) * 1000)

            success = result.get("success", True) if isinstance(result, dict) else True

            logger.info(f"[DirectExecutor] {action} completed in {duration_ms}ms (success={success})")

            return {
                "success": success,
                "action": action,
                "mcp_tool": mcp_tool_name,
                "result": result,
                "duration_ms": duration_ms,
            }

        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(f"[DirectExecutor] {action} failed in {duration_ms}ms: {e}", exc_info=True)
            return {
                "success": False,
                "action": action,
                "mcp_tool": mcp_tool_name,
                "error": str(e),
                "duration_ms": duration_ms,
            }
