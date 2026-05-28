"""Tool definitions for the LLM dispatch layer.

- VOXYFLOW_DELEGATE_TOOL: canonical tool_use schema for voxyflow.delegate (all providers)
- DELEGATE_ACTION_TOOL: deprecated alias — points to VOXYFLOW_DELEGATE_TOOL
- get_claude_tools(): builds tool schemas from the registry for a given role
- _call_mcp_tool(): executes a tool via the MCP/REST API bridge
"""

import json
import logging
from typing import Optional

from app.tools.delegate_tool import (
    VOXYFLOW_DELEGATE_TOOL,
    VOXYFLOW_DELEGATE_TOOL_OPENAI,
    VOXYFLOW_DELEGATE_TOOL_GEMINI,
    TOOL_NAME_SAFE as _DELEGATE_TOOL_NAME_SAFE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Delegate tool — canonical voxyflow.delegate (all provider paths)
# ---------------------------------------------------------------------------

# Backward-compat alias: code that imported DELEGATE_ACTION_TOOL still works.
# Will be removed after the 2-week transition (see cleanup card).
DELEGATE_ACTION_TOOL = VOXYFLOW_DELEGATE_TOOL


# ---------------------------------------------------------------------------
# Gemini functionDeclarations helper
# ---------------------------------------------------------------------------

def anthropic_to_gemini_tools(tools: list[dict]) -> list[dict]:
    """Convert Anthropic-format tool defs to Gemini functionDeclarations format.

    Handles the special case of VOXYFLOW_DELEGATE_TOOL which has a pre-built
    Gemini representation.  Generic tools are converted by uppercasing the
    JSON Schema type tokens (Gemini uses STRING/INTEGER/… instead of string/integer/…).
    """
    out: list[dict] = []
    for t in tools or []:
        # Special case: delegate tool already has Gemini format ready
        if t.get("name") == _DELEGATE_TOOL_NAME_SAFE:
            out.append(VOXYFLOW_DELEGATE_TOOL_GEMINI)
            continue
        # Generic conversion: Anthropic → Gemini
        schema = t.get("input_schema") or t.get("parameters") or {}
        out.append({
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": _schema_to_gemini(schema),
        })
    return out


def _schema_to_gemini(schema: dict) -> dict:
    """Recursively convert JSON Schema to Gemini parameter format (type names uppercased)."""
    if not isinstance(schema, dict):
        return schema
    out = {}
    for k, v in schema.items():
        if k == "type" and isinstance(v, str):
            out[k] = v.upper()
        elif isinstance(v, dict):
            out[k] = _schema_to_gemini(v)
        elif isinstance(v, list) and k == "properties":
            # shouldn't happen (properties is always a dict) but guard anyway
            out[k] = v
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Tool bridge — builds Claude native tool_use schemas from the registry
# ---------------------------------------------------------------------------

def get_claude_tools(
    chat_level: str = "general",
    role: str = "dispatcher",
    workspace_id: Optional[str] = None,
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


def anthropic_to_openai_tools(tools: list[dict]) -> list[dict]:
    """Convert Anthropic-format tool defs (name/description/input_schema) to OpenAI format
    ([{"type": "function", "function": {name, description, parameters}}])."""
    out: list[dict] = []
    for t in tools or []:
        if "type" in t and "function" in t:
            out.append(t)
            continue
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema") or t.get("parameters") or {"type": "object", "properties": {}},
            },
        })
    return out


def _mcp_tool_name_from_claude(claude_name: str) -> str:
    """Convert a Claude tool name (underscores) back to its MCP equivalent.

    The forward transform is ``name.replace(".", "_")``, which is NOT
    invertible by naive split — some real tool names contain underscores
    inside a single segment (``voxyflow.ai.review_code``) while others
    are deeper than 3 segments (``voxyflow.card.checklist.add``). The only
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
