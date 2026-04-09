"""Tool definitions and inline tool executor for the LLM layer.

- DELEGATE_ACTION_TOOL: native tool_use schema for dispatching to background workers
- INLINE_TOOLS: tools executed directly by the fast layer (memory, RAG, workers)
- get_claude_tools(): builds the tool list for a given layer/context
- _execute_inline_tool(): executes inline tools without delegation
"""

import json
import logging
from typing import Optional

from app.tools.registry import TOOLS_READ_ONLY, _LAYER_TOOL_SETS

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
                    "create_sprint, web_research"
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
# Inline tools — executed directly by the fast layer (no delegation)
# ---------------------------------------------------------------------------

INLINE_TOOLS = [
    {
        "name": "memory_search",
        "description": (
            "Search Voxy's long-term memory for relevant context. Use this to recall "
            "prior conversations, decisions, user preferences, or stored facts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query — describe what you're trying to remember",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 5)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "knowledge_search",
        "description": (
            "Search the project knowledge base (RAG) for relevant context. Use when you "
            "need background information about the project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project ID to search within (default: system-main)",
                },
                "query": {
                    "type": "string",
                    "description": "Search query — describe what you're looking for",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_save",
        "description": (
            "Save something to Voxy's long-term memory. Use this to remember user preferences, "
            "decisions, facts, or lessons learned for future conversations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The information to remember",
                },
                "type": {
                    "type": "string",
                    "enum": ["decision", "preference", "fact", "lesson"],
                    "description": "Category of memory: decision, preference, fact, or lesson",
                },
                "importance": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "Importance level (default: medium)",
                },
            },
            "required": ["content", "type"],
        },
    },
    # --- Card CRUD (inline — instant, no worker needed) ---
    {
        "name": "card_list",
        "description": (
            "List cards in the current project. Returns card titles, statuses, and IDs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "Project ID (uses current project if omitted)",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by status (card, todo, in-progress, done, archived)",
                },
            },
        },
    },
    {
        "name": "card_get",
        "description": (
            "Get full details of a specific card by ID."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {
                    "type": "string",
                    "description": "Card ID to look up",
                },
            },
            "required": ["card_id"],
        },
    },
    {
        "name": "card_create",
        "description": (
            "Create a new card in the current project. Returns the created card."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Card title (required)",
                },
                "description": {
                    "type": "string",
                    "description": "Card description/body",
                },
                "status": {
                    "type": "string",
                    "description": "Initial status (default: todo)",
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority 0-4 (default: 0)",
                },
                "project_id": {
                    "type": "string",
                    "description": "Target project ID (uses current project if omitted)",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "card_update",
        "description": (
            "Update an existing card's title, description, or priority."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {
                    "type": "string",
                    "description": "Card ID to update (required if card_title not given)",
                },
                "card_title": {
                    "type": "string",
                    "description": "Card title to find (required if card_id not given)",
                },
                "title": {
                    "type": "string",
                    "description": "New title",
                },
                "description": {
                    "type": "string",
                    "description": "New description",
                },
                "priority": {
                    "type": "integer",
                    "description": "New priority 0-4",
                },
                "project_id": {
                    "type": "string",
                    "description": "Project ID for card_title lookup",
                },
            },
        },
    },
    {
        "name": "card_move",
        "description": (
            "Move a card to a different status column."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {
                    "type": "string",
                    "description": "Card ID to move (required if card_title not given)",
                },
                "card_title": {
                    "type": "string",
                    "description": "Card title to find (required if card_id not given)",
                },
                "status": {
                    "type": "string",
                    "description": "Target status: card, todo, in-progress, done, archived",
                },
                "project_id": {
                    "type": "string",
                    "description": "Project ID for card_title lookup",
                },
            },
            "required": ["status"],
        },
    },
    {
        "name": "card_archive",
        "description": (
            "Archive a card (soft-delete). The card is hidden from the board but NOT deleted. "
            "Use this instead of card.delete — cards must be archived before they can be permanently deleted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {
                    "type": "string",
                    "description": "Card ID to archive",
                },
            },
            "required": ["card_id"],
        },
    },
    # --- Worker management (inline) ---
    {
        "name": "workers_list",
        "description": (
            "List active and recent worker tasks for the current session. Use this BEFORE "
            "dispatching a new task to check if a similar worker is already running."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "Filter by session ID (uses current session if omitted)",
                },
                "status": {
                    "type": "string",
                    "enum": ["running", "done", "failed", "timed_out", "cancelled"],
                    "description": "Filter by status (default: show all)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 10)",
                },
            },
        },
    },
    {
        "name": "workers_get_result",
        "description": (
            "Get the full details and result of a specific worker task by task_id. "
            "Use to retrieve the outcome of a completed worker."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "Worker task ID to look up",
                },
            },
            "required": ["task_id"],
        },
    },
]

# Names of tools that execute inline (not delegated)
_INLINE_TOOL_NAMES = {t["name"] for t in INLINE_TOOLS}


async def _execute_inline_tool(name: str, params: dict) -> dict:
    """Execute an inline tool and return the result."""
    if name == "memory_search":
        from app.services.memory_service import get_memory_service
        query = params.get("query", "")
        if not query:
            return {"error": "query is required"}
        limit = params.get("limit", 5)
        try:
            ms = get_memory_service()
            results = ms.search_memory(query, limit=limit)
            if not results:
                return {"result": "No matching memories found."}
            formatted = [
                {"text": r.get("text", ""), "score": round(r.get("score", 0), 3),
                 "collection": r.get("collection", "")}
                for r in results
            ]
            return {"results": formatted}
        except Exception as e:
            return {"error": str(e)}
    elif name == "knowledge_search":
        from app.services.rag_service import get_rag_service
        project_id = params.get("project_id", "system-main")
        query = params.get("query", "")
        if not query:
            return {"error": "query is required"}
        try:
            result = await get_rag_service().build_rag_context(project_id, query)
            return {"result": result or "No relevant knowledge found."}
        except Exception as e:
            return {"error": str(e)}
    elif name == "memory_save":
        from app.services.memory_service import get_memory_service
        mem_content = params.get("content", "")
        if not mem_content:
            return {"error": "content is required"}
        memory_type = params.get("type", "fact")
        importance = params.get("importance", "medium")
        try:
            ms = get_memory_service()
            doc_id = ms.store_memory(
                text=mem_content,
                metadata={
                    "type": memory_type,
                    "importance": importance,
                    "source": "manual",
                },
            )
            return {"saved": True, "id": doc_id or ""}
        except Exception as e:
            logger.error(f"[InlineTool] memory_save failed: {e}")
            return {"error": str(e)}
    elif name == "card_archive":
        card_id = params.get("card_id", "")
        if not card_id:
            return {"error": "card_id is required"}
        try:
            result = await _call_mcp_tool("voxyflow.card.archive", {"card_id": card_id})
            return result
        except Exception as e:
            logger.error(f"[InlineTool] card_archive failed: {e}")
            return {"error": str(e)}
    elif name in ("card_list", "card_get", "card_create", "card_update", "card_move"):
        mcp_name = "voxyflow." + name.replace("_", ".", 1)
        try:
            result = await _call_mcp_tool(mcp_name, params)
            return result
        except Exception as e:
            logger.error(f"[InlineTool] {name} failed: {e}")
            return {"error": str(e)}
    elif name == "workers_list":
        from app.services.worker_session_store import get_worker_session_store
        try:
            store = get_worker_session_store()
            session_id = params.get("session_id")
            sessions = store.get_sessions(session_id=session_id)
            status_filter = params.get("status")
            if status_filter:
                sessions = [s for s in sessions if s.get("status") == status_filter]
            limit = params.get("limit", 10)
            sessions = sessions[:limit]
            if not sessions:
                return {"result": "No active or recent workers found."}
            return {"workers": sessions, "count": len(sessions)}
        except Exception as e:
            logger.error(f"[InlineTool] workers_list failed: {e}")
            return {"error": str(e)}
    elif name == "workers_get_result":
        from app.services.worker_session_store import get_worker_session_store
        task_id = params.get("task_id", "")
        if not task_id:
            return {"error": "task_id is required"}
        try:
            store = get_worker_session_store()
            session = store.get_session(task_id)
            if session is None:
                return {"error": f"Worker task not found: {task_id}"}
            return session
        except Exception as e:
            logger.error(f"[InlineTool] workers_get_result failed: {e}")
            return {"error": str(e)}
    return {"error": f"Unknown inline tool: {name}"}


# ---------------------------------------------------------------------------
# MCP Tool bridge — converts Voxyflow MCP tools to Claude native tool_use
# ---------------------------------------------------------------------------

def get_claude_tools(
    chat_level: str = "general",
    layer: str = "fast",
    project_id: Optional[str] = None,
) -> list[dict]:
    """Convert Voxyflow MCP tool definitions to Claude API tool_use format."""
    try:
        from app.mcp_server import get_tool_list
        all_tools = get_tool_list()

        layer_allowed = _LAYER_TOOL_SETS.get(layer, TOOLS_READ_ONLY)

        if chat_level == "general":
            context_allowed = {
                "voxyflow.card.create_unassigned", "voxyflow.card.list_unassigned",
                "voxyflow.card.create", "voxyflow.card.list", "voxyflow.card.get",
                "voxyflow.card.update", "voxyflow.card.move",
                "voxyflow.project.create", "voxyflow.project.list", "voxyflow.project.get",
                "voxyflow.health",
            } | {
                "system.exec", "web.search", "web.fetch",
                "file.read", "file.write", "file.list",
                "git.status", "git.log", "git.diff", "git.branches", "git.commit",
                "tmux.list", "tmux.capture", "tmux.run", "tmux.send", "tmux.new", "tmux.kill",
                "voxyflow.jobs.list", "voxyflow.jobs.create",
                "voxyflow.doc.list", "voxyflow.doc.delete",
                "task.complete",
            }
        elif chat_level == "project":
            context_allowed = {t["name"] for t in all_tools}
        else:
            context_allowed = {t["name"] for t in all_tools}

        allowed = layer_allowed & context_allowed

        tools = []
        for tool in all_tools:
            if tool["name"] in allowed:
                tools.append({
                    "name": tool["name"].replace(".", "_"),
                    "description": tool["description"],
                    "input_schema": tool["inputSchema"],
                })
        return tools
    except Exception as e:
        logger.warning(f"Could not load MCP tools for Claude: {e}")
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
    """Load model layer overrides from settings.json if it exists."""
    from app.config import SETTINGS_FILE
    if not SETTINGS_FILE.exists():
        return {}
    try:
        with open(SETTINGS_FILE) as f:
            data = json.load(f)
        return data.get("models", {})
    except Exception as e:
        logger.warning(f"Failed to load model overrides from settings.json: {e}")
        return {}


def _get_api_key_from_settings(layer_cfg: dict) -> str:
    """Extract api_key from a settings.json layer config block."""
    return (layer_cfg.get("api_key") or "").strip()
