"""Tool definitions for the LLM dispatch layer.

- DELEGATE_ACTION_TOOL: native tool_use schema for dispatching to background workers
- get_claude_tools(): builds tool schemas from the registry for a given role
- _call_mcp_tool(): executes a tool via the MCP/REST API bridge
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Delegate tool — native tool_use for dispatching actions to workers
# ---------------------------------------------------------------------------

DELEGATE_ACTION_TOOL = {
    "name": "delegate_action",
    "description": (
        "Dispatch an action to a background worker for execution. "
        "Use this whenever the user asks you to DO something (create cards, search the web, "
        "run commands, write files, etc.). You CANNOT execute actions yourself — you MUST "
        "delegate them. The worker will execute the action and report results back to the user."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": (
                    "The action to perform. Examples: create_card, move_card, update_card, "
                    "create_project, search_web, run_command, write_file, analyze_code, "
                    "web_research"
                ),
            },
            "summary": {
                "type": "string",
                "description": "Brief human-readable description of what the worker should do",
            },
            "model": {
                "type": "string",
                "enum": ["haiku", "sonnet", "opus"],
                "description": (
                    "Which worker model to use. haiku=simple CRUD, "
                    "sonnet=research/web/balanced, opus=complex multi-step"
                ),
                "default": "sonnet",
            },
            "complexity": {
                "type": "string",
                "enum": ["simple", "complex"],
                "description": "simple=single-step CRUD, complex=multi-step or destructive",
                "default": "simple",
            },
            "project_name": {
                "type": "string",
                "description": "Target project name (if applicable)",
            },
            "card_title": {
                "type": "string",
                "description": "Target card title (if applicable)",
            },
            "description": {
                "type": "string",
                "description": "Detailed description or content for the action",
            },
        },
        "required": ["action", "summary"],
    },
}


# ---------------------------------------------------------------------------
# Tool bridge — builds Claude native tool_use schemas from the registry
# ---------------------------------------------------------------------------

def get_claude_tools(
    chat_level: str = "general",
    role: str = "dispatcher",
    project_id: Optional[str] = None,
    # Deprecated — ignored, kept for call-site compat during transition
    layer: str = "fast",
) -> list[dict]:
    """Build Claude API tool_use schemas from the tool registry.

    The ``role`` parameter controls tool access:
    - "dispatcher" (default) — lightweight read + basic CRUD, same for fast/deep
    - "worker" — full tool access

    The old ``layer`` parameter is ignored; fast vs deep is model selection only.
    """
    try:
        from app.tools.registry import get_registry
        registry = get_registry()
        role_tools = registry.get_by_role(role)

        tools = []
        for tool_def in role_tools:
            tools.append({
                "name": tool_def.name.replace(".", "_"),
                "description": tool_def.description,
                "input_schema": tool_def.parameters,
            })
        return tools
    except Exception as e:
        logger.warning(f"Could not load tools for Claude: {e}")
        return []


def _mcp_tool_name_from_claude(claude_name: str) -> str:
    """Convert Claude tool name back to MCP equivalent.
    voxyflow_card_create → voxyflow.card.create
    """
    parts = claude_name.split("_", 2)
    return ".".join(parts)


async def _call_mcp_tool(tool_mcp_name: str, arguments: dict) -> dict:
    """Call the Voxyflow REST API via the MCP _call_api helper."""
    try:
        from app.mcp_server import _find_tool, _call_api as mcp_call_api
        tool_def = _find_tool(tool_mcp_name)
        if tool_def is None:
            return {"success": False, "error": f"Unknown MCP tool: {tool_mcp_name}"}
        result = await mcp_call_api(tool_def, arguments or {})
        return result
    except Exception as e:
        logger.error(f"MCP tool call failed: {tool_mcp_name} → {e}")
        return {"success": False, "error": str(e)}


def _load_model_overrides() -> dict:
    """Load model layer overrides from settings.json.  Resolves endpoint_id references."""
    from app.config import SETTINGS_FILE
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
        models = data.get("models", {})
        _resolve_endpoint_refs(models)
        return models
    except Exception as e:
        logger.warning(f"Failed to load model overrides from settings.json: {e}")
        return {}


def _resolve_endpoint_refs(models: dict) -> None:
    """In-place: for any layer that has an endpoint_id, overwrite provider_url/
    provider_type/api_key with the values from the saved endpoints list.
    This ensures the layer always uses the current endpoint config, even if
    the endpoint was edited after the layer was assigned."""
    endpoints = {ep.get("id"): ep for ep in models.get("endpoints", []) if ep.get("id")}
    for layer_key in ("fast", "deep", "haiku"):
        layer = models.get(layer_key)
        if not isinstance(layer, dict):
            continue
        ep_id = layer.get("endpoint_id", "").strip()
        if not ep_id:
            continue
        ep = endpoints.get(ep_id)
        if ep:
            layer["provider_url"] = ep.get("url", layer.get("provider_url", ""))
            layer["provider_type"] = ep.get("provider_type", layer.get("provider_type", ""))
            # Only copy api_key if the endpoint has one — don't overwrite with empty
            if ep.get("api_key"):
                layer["api_key"] = ep["api_key"]
        else:
            logger.warning(
                "[model_overrides] endpoint_id '%s' in layer '%s' not found in endpoints list",
                ep_id, layer_key,
            )


def _get_api_key_from_settings(layer_cfg: dict) -> str:
    """Extract api_key from a settings.json layer config block."""
    key = (layer_cfg.get("api_key") or "").strip()
    return key if key != "***" else ""  # never use the redacted sentinel
