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
        # Tag the last tool with cache_control so Anthropic caches the entire
        # tool block (it's static per-role and cheap to cache). Anthropic caches
        # up-to-and-including any block tagged with ephemeral cache_control.
        if tools:
            tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
        return tools
    except Exception as e:
        logger.warning(f"Could not load tools for Claude: {e}")
        return []


def _mcp_tool_name_from_claude(claude_name: str) -> str:
    """Convert a Claude tool name (underscores) back to its MCP equivalent.

    The forward transform is ``name.replace(".", "_")``, which is NOT
    invertible by naive split — some real tool names contain underscores
    inside a single segment (``voxyflow.ai.review_code``) while others
    are deeper than 3 segments (``voxyflow.card.comment.add``). The only
    reliable inverse is a reverse lookup against the registered tool
    names; fall back to a naive 2-split for unknown names so callers get
    a reasonable guess instead of a KeyError.
    """
    try:
        from app.mcp_server import _TOOL_DEFINITIONS
        for tool in _TOOL_DEFINITIONS:
            if tool["name"].replace(".", "_") == claude_name:
                return tool["name"]
    except Exception as e:
        logger.debug(f"_mcp_tool_name_from_claude reverse lookup failed: {e}")
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
    """Load model layer overrides.  Resolves endpoint_id references.

    Reads from the SQLite ``app_settings`` table (source of truth — same row
    the /api/settings endpoint serves), with settings.json as a legacy
    fallback for pre-migration installs. Uses the sync sqlite3 driver so
    this works from ClaudeService.__init__ (sync ctor) as well as from
    reload_models() called out of async request handlers.
    """
    data = _read_settings_from_db_sync() or _read_settings_from_file_sync()
    if not data:
        return {}
    models = data.get("models", {}) or {}
    _resolve_endpoint_refs(models)
    return models


def _read_settings_from_db_sync() -> dict | None:
    """Synchronous read of the app_settings row. Returns None on any error.

    Uses sqlite3 directly (not SQLAlchemy) so the same function is callable
    from both sync construction paths and async handlers without coupling
    to the engine's event loop.
    """
    import sqlite3
    from app.config import get_settings
    try:
        # database_url looks like "sqlite+aiosqlite:///<path>" — strip scheme
        db_url = get_settings().database_url
        if "://" in db_url:
            db_path = db_url.split("://", 1)[1]
        else:
            db_path = db_url
        # SQLAlchemy uses a leading slash for absolute paths; sqlite3 takes a
        # plain filesystem path. A URL like "sqlite+aiosqlite:////abs/path"
        # yields "/abs/path" here, which is what we want.
        conn = sqlite3.connect(db_path, timeout=5.0)
        try:
            # uri=False; app_settings table may not exist on a fresh install
            cur = conn.execute(
                "SELECT value FROM app_settings WHERE key = 'app_settings'"
            )
            row = cur.fetchone()
            if not row:
                return None
            return json.loads(row[0])
        finally:
            conn.close()
    except sqlite3.OperationalError:
        # Table missing — fresh install, caller will fall back to file/defaults
        return None
    except Exception as e:
        logger.warning("Failed to read model overrides from DB: %s", e)
        return None


def _read_settings_from_file_sync() -> dict | None:
    """Legacy fallback — reads settings.json from disk (redacted, may be stale)."""
    from app.config import SETTINGS_FILE
    if not SETTINGS_FILE.exists():
        return None
    try:
        with open(SETTINGS_FILE) as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Failed to load model overrides from settings.json: %s", e)
        return None


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
