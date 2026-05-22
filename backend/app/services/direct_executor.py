"""Direct Executor — fast-path inline CRUD for whitelisted atomic operations.

Bypasses the worker pipeline entirely. No Claude API call — the dispatcher
parses structured params from the delegate JSON and calls the Voxyflow REST API
(via the same MCP HTTP layer) directly.

Latency target: <500ms instead of ~10s worker round-trip.

Usage:
    from app.services.direct_executor import DirectExecutor

    executor = DirectExecutor()
    result = await executor.execute("card.create", params, workspace_id)
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
    # Card CRUD
    "card.create": "voxyflow.card.create",
    "card.update": "voxyflow.card.update",
    "card.move": "voxyflow.card.move",
    "card.delete": "voxyflow.card.delete",
    "card.list": "voxyflow.card.list",
    "card.get": "voxyflow.card.get",
    # Card aliases
    "create_card": "voxyflow.card.create",
    "update_card": "voxyflow.card.update",
    "move_card": "voxyflow.card.move",
    "delete_card": "voxyflow.card.delete",
    "list_cards": "voxyflow.card.list",
    "get_card": "voxyflow.card.get",
    # Workspace CRUD
    "project.list": "voxyflow.workspace.list",
    "project.get": "voxyflow.workspace.get",
    "project.create": "voxyflow.workspace.create",
    "project.delete": "voxyflow.workspace.delete",
    "list_projects": "voxyflow.workspace.list",
    "get_project": "voxyflow.workspace.get",
    "create_project": "voxyflow.workspace.create",
    "delete_project": "voxyflow.workspace.delete",
    # Wiki read
    "wiki.list": "voxyflow.wiki.list",
    "wiki.get": "voxyflow.wiki.get",
    "list_wiki": "voxyflow.wiki.list",
    "get_wiki": "voxyflow.wiki.get",
    # Jobs & health
    "jobs.list": "voxyflow.jobs.list",
    "list_jobs": "voxyflow.jobs.list",
    "jobs.update": "voxyflow.jobs.update",
    "jobs.delete": "voxyflow.jobs.delete",
    "health": "voxyflow.health",
    # Worker Ledger
    "workers.list": "voxyflow.workers.list",
    "workers.get_result": "voxyflow.workers.get_result",
}

# CRUD-simple write intents: these use a lighter worker when they *aren't*
# direct-eligible (e.g. the LLM forgot the params dict, so the action falls
# back to the worker path). Kept here so alias renames stay co-located with
# the ``DIRECT_ACTION_MAP`` that also references them.
CRUD_SIMPLE_INTENTS = frozenset({"create_card", "move_card", "update_card"})

# Actions that require user confirmation before execution (irreversible)
CONFIRM_REQUIRED = {"card.delete", "delete_card", "project.delete", "delete_project", "jobs.delete"}

# Actions that require no params (can have empty/missing params dict)
NO_PARAMS_REQUIRED = {"project.list", "list_projects", "jobs.list", "list_jobs", "health", "workers.list", "card.list", "list_cards", "wiki.list", "list_wiki"}

# Read actions — these need LLM context injection so Voxy can use the data
# in her response.  Direct execution works for writes (fire-and-forget) but
# reads must go through a worker so the result is fed back as a tool_result.
READ_ACTIONS = {
    "card.get", "get_card",
    "card.list", "list_cards",
    "project.get", "get_project",
    "project.list", "list_projects",
    "wiki.get", "get_wiki",
    "wiki.list", "list_wiki",
    "workers.list", "workers.get_result",
}


class DirectExecutor:
    """Executes whitelisted CRUD operations inline without spawning a worker."""

    @staticmethod
    def is_direct_eligible(delegate_data: dict) -> bool:
        """Check if a delegate should take the fast path.

        Returns True if:
          - action is in the CRUD whitelist (regardless of model)
          - params dict is present (structured parameters required)

        Auto-routes CRUD intents to direct execution even if the LLM
        requested model=haiku/sonnet — saves tokens by skipping the LLM.
        """
        action = delegate_data.get("action", "")
        if action not in DIRECT_ACTION_MAP:
            logger.debug(f"[DirectExecutor] Action '{action}' not in whitelist, falling back to worker")
            return False

        # No-param actions (health, list_projects, etc.) don't need params
        if action in NO_PARAMS_REQUIRED:
            return True

        params = delegate_data.get("params")
        if not params:  # None or empty dict {}
            logger.warning(f"[DirectExecutor] No 'params' in delegate for action '{action}', falling back to worker")
            return False

        return True

    @staticmethod
    def needs_confirmation(delegate_data: dict) -> bool:
        """Check if this action requires user confirmation before execution."""
        action = delegate_data.get("action", "")
        return action in CONFIRM_REQUIRED


    @staticmethod
    async def _resolve_card_by_title(
        title: str,
        workspace_id: str,
    ) -> str | None:
        """Look up a card_id by title within a project.

        Returns the card_id if found, None otherwise.
        If multiple cards match, returns the first and logs a warning.
        """
        from app.mcp_server import _find_tool, _call_api

        list_tool = _find_tool("voxyflow.card.list")
        if not list_tool:
            logger.error("[DirectExecutor] Cannot resolve card by title: voxyflow.card.list tool not found")
            return None

        try:
            result = await _call_api(list_tool, {"workspace_id": workspace_id})
        except Exception:
            logger.exception("[DirectExecutor] card.list failed during title lookup")
            return None

        # result can be a list of cards or a dict with a cards key
        cards = result if isinstance(result, list) else result.get("cards", result.get("data", []))
        if not isinstance(cards, list):
            logger.warning(f"[DirectExecutor] Unexpected card.list response format: {type(result)}")
            return None

        # Normalize search title for fuzzy matching
        search_title = title.strip().lower()
        matches = [c for c in cards if c.get("title", "").strip().lower() == search_title]

        if not matches:
            logger.info(f"[DirectExecutor] No card found with title '{title}' in project {workspace_id}")
            return None

        if len(matches) > 1:
            logger.warning(
                f"[DirectExecutor] {len(matches)} cards match title '{title}' in project {workspace_id}, "
                f"using first: {matches[0].get('id')}"
            )

        card_id = matches[0].get("id")
        logger.info(f"[DirectExecutor] Resolved title '{title}' → card_id={card_id}")
        return card_id

    @staticmethod
    async def execute(
        delegate_data: dict,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a direct CRUD action and return the result.

        Args:
            delegate_data: The full delegate dict with action, params, etc.
            workspace_id: The current project context (injected into params if needed).

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

        # Hard-scope workspace_id to the current chat's project. Mirrors the
        # invariant enforced by `_build_url_and_payload` (via VOXYFLOW_WORKSPACE_ID
        # env) for the MCP subprocess path. DirectExecutor runs in the backend
        # process where that env is not set, so we enforce it explicitly here —
        # otherwise a stray / guessed workspace_id from the LLM leaks cards into
        # the wrong project (typically Home / system-main when the dispatcher
        # misreads its context).
        tool_schema = tool_def.get("inputSchema", {})
        required_fields = tool_schema.get("required", [])
        if "workspace_id" in tool_schema.get("properties", {}) or "workspace_id" in required_fields:
            if workspace_id:
                llm_pid = params.get("workspace_id")
                if llm_pid and llm_pid != workspace_id:
                    logger.warning(
                        f"[DirectExecutor] Ignoring LLM-supplied workspace_id={llm_pid!r}; "
                        f"forcing current chat scope {workspace_id!r}"
                    )
                params["workspace_id"] = workspace_id
            elif "workspace_id" in required_fields and "workspace_id" not in params:
                return {
                    "success": False,
                    "action": action,
                    "mcp_tool": mcp_tool_name,
                    "error": "workspace_id required but not available",
                    "duration_ms": 0,
                }

        # --- Auto-resolve card_id by title for move/update actions ---
        card_move_actions = {"card.move", "move_card", "card.update", "update_card"}
        if action in card_move_actions and "card_id" not in params:
            # Try to resolve by title, card_title, or name
            card_title = (
                params.pop("card_title", None)
                or params.pop("title", None)
                or params.pop("name", None)
            )
            if card_title and workspace_id:
                logger.info(f"[DirectExecutor] card_id missing for {action}, resolving by title: '{card_title}'")
                resolved_id = await DirectExecutor._resolve_card_by_title(card_title, workspace_id)
                if resolved_id:
                    params["card_id"] = resolved_id
                else:
                    return {
                        "success": False,
                        "action": action,
                        "mcp_tool": mcp_tool_name,
                        "error": f"No card found with title '{card_title}' in current project",
                        "duration_ms": 0,
                    }
            elif not card_title:
                return {
                    "success": False,
                    "action": action,
                    "mcp_tool": mcp_tool_name,
                    "error": f"card_id is required for {action} — provide card_id or card_title/title for auto-lookup",
                    "duration_ms": 0,
                }
            else:
                return {
                    "success": False,
                    "action": action,
                    "mcp_tool": mcp_tool_name,
                    "error": "Cannot resolve card by title: no workspace_id available",
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
