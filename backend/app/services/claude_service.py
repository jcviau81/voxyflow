"""Claude API integration — native Anthropic SDK (primary) with OpenAI-compatible proxy fallback."""

import asyncio
import json
import logging
import os
from collections import OrderedDict, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from app.config import get_settings
from app.services.personality_service import get_personality_service
from app.services.memory_service import get_memory_service
from app.services.agent_personas import AgentType, get_persona_prompt
from app.services.session_store import session_store
from app.services.rag_service import get_rag_service
from app.tools.registry import (
    TOOLS_READ_ONLY, TOOLS_VOXYFLOW_CRUD, TOOLS_FULL, _LAYER_TOOL_SETS,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token usage JSONL logging
# ---------------------------------------------------------------------------

TOKEN_LOG_PATH = Path(os.path.expanduser("~/.voxyflow/logs/token_usage.jsonl"))


def _log_token_usage(
    *,
    layer: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    chat_id: str = "",
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> None:
    """Append a JSONL entry to the token usage log file."""
    try:
        TOKEN_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "layer": layer,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "chat_id": chat_id,
            "cache_creation_tokens": cache_creation_tokens,
            "cache_read_tokens": cache_read_tokens,
        }
        with open(TOKEN_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.debug(f"Token usage logging failed: {e}")


# ---------------------------------------------------------------------------
# Prompt caching — Anthropic cache_control on system content blocks
# ---------------------------------------------------------------------------

def _flatten_system(system: str | list[dict]) -> str:
    """Convert system content blocks back to a plain string (for non-Anthropic paths)."""
    if isinstance(system, str):
        return system
    return "\n\n".join(block["text"] for block in system if block.get("text"))


def _make_cached_system(
    base_prompt: str,
    dynamic_parts: list[str] | None = None,
    is_anthropic: bool = True,
) -> str | list[dict]:
    """Build the system parameter for Claude API calls with prompt caching.

    For Anthropic native SDK: returns a list of content blocks where the static
    base prompt is marked with cache_control={'type': 'ephemeral'} so Anthropic
    caches it across calls in the same session (~5 min TTL).

    For OpenAI-compatible proxy: returns a plain concatenated string (no caching).

    Args:
        base_prompt: The static personality/instruction prompt (cacheable).
        dynamic_parts: Optional list of dynamic context strings (RAG, workers, etc.)
                       that change per-call and should NOT be cached.
        is_anthropic: Whether we're using the native Anthropic SDK.
    """
    dynamic_text = ""
    if dynamic_parts:
        dynamic_text = "\n\n".join(p for p in dynamic_parts if p)

    if not is_anthropic:
        # Proxy path — plain string, no caching support
        if dynamic_text:
            return base_prompt + "\n\n" + dynamic_text
        return base_prompt

    # Anthropic native path — use content blocks with cache_control
    blocks = [
        {
            "type": "text",
            "text": base_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]
    if dynamic_text:
        blocks.append({"type": "text", "text": dynamic_text})
    return blocks


# ---------------------------------------------------------------------------
# LRU Dict — bounded dict that evicts the oldest entry on overflow
# ---------------------------------------------------------------------------

class _LRUDict(OrderedDict):
    """An OrderedDict subclass that enforces a maximum size by evicting the
    least-recently-used (oldest) entry whenever the limit is exceeded.

    Usage: drop-in replacement for plain dict / defaultdict in cases where
    the key space is theoretically unbounded (e.g. chat_id per user session).
    """

    def __init__(self, maxsize: int = 500, default_factory=None):
        super().__init__()
        self._maxsize = maxsize
        self._default_factory = default_factory

    def __getitem__(self, key):
        value = super().__getitem__(key)
        # Move to end so it is treated as most-recently-used
        self.move_to_end(key)
        return value

    def __setitem__(self, key, value):
        if key in self:
            self.move_to_end(key)
        super().__setitem__(key, value)
        # Evict oldest entries until we are within the size limit
        while len(self) > self._maxsize:
            oldest_key, _ = next(iter(self.items()))
            logger.debug(f"[LRUDict] Evicting key: {oldest_key!r} (maxsize={self._maxsize})")
            super().__delitem__(oldest_key)

    def __missing__(self, key):
        """Support defaultdict-style default_factory."""
        if self._default_factory is None:
            raise KeyError(key)
        value = self._default_factory()
        self[key] = value
        return value

# ---------------------------------------------------------------------------
# Model name mapping: short names → Anthropic full names
# ---------------------------------------------------------------------------
_MODEL_MAP = {
    "claude-haiku-4":   "claude-haiku-4-5-20251001",
    "claude-sonnet-4":  "claude-sonnet-4-6",
    "claude-opus-4":    "claude-opus-4-6",
    "claude-haiku-3":   "claude-3-haiku-20240307",
    "claude-sonnet-3":  "claude-3-5-sonnet-20241022",
    "claude-opus-3":    "claude-3-opus-20240229",
}


def _resolve_model(name: str, native: bool = True) -> str:
    """Return the full Anthropic model name for a short alias, or the name unchanged.
    When using the proxy (native=False), keep short names as-is."""
    if not native:
        return name
    return _MODEL_MAP.get(name, name)


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
    {
        "name": "workers.list",
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
        "name": "workers.get_result",
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
            # store_memory is sync; accepts text= and metadata= dict
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
    elif name == "workers.list":
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
            logger.error(f"[InlineTool] workers.list failed: {e}")
            return {"error": str(e)}
    elif name == "workers.get_result":
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
            logger.error(f"[InlineTool] workers.get_result failed: {e}")
            return {"error": str(e)}
    return {"error": f"Unknown inline tool: {name}"}


# ---------------------------------------------------------------------------
# MCP Tool bridge — converts Voxyflow MCP tools to Claude native tool_use
# ---------------------------------------------------------------------------

# Tool sets are now in app.tools.registry — imported above


def get_claude_tools(
    chat_level: str = "general",
    layer: str = "fast",
    project_id: Optional[str] = None,
) -> list[dict]:
    """Convert Voxyflow MCP tool definitions to Claude API tool_use format.

    Filters tools by layer (fast=read-only, analyzer=CRUD, deep=full)
    and by chat_level (general/project/card context).
    """
    try:
        from app.mcp_server import get_tool_list
        all_tools = get_tool_list()

        # Layer-based filtering (primary gate)
        layer_allowed = _LAYER_TOOL_SETS.get(layer, TOOLS_READ_ONLY)

        # Context-based filtering (secondary gate)
        # "general" is now the system-main project — gets both aliases and project tools
        if chat_level == "general":
            context_allowed = {
                "voxyflow.card.create_unassigned", "voxyflow.card.list_unassigned",
                "voxyflow.card.create", "voxyflow.card.list", "voxyflow.card.get",
                "voxyflow.card.update", "voxyflow.card.move",
                "voxyflow.project.create", "voxyflow.project.list", "voxyflow.project.get",
                "voxyflow.health",
            } | {
                # System/infra tools pass through context filter
                "system.exec", "web.search", "web.fetch",
                "file.read", "file.write", "file.list",
                "git.status", "git.log", "git.diff", "git.branches", "git.commit",
                "tmux.list", "tmux.capture", "tmux.run", "tmux.send", "tmux.new", "tmux.kill",
                "voxyflow.jobs.list", "voxyflow.jobs.create",
                "voxyflow.doc.list", "voxyflow.doc.delete",
                "task.complete",  # Worker supervision
            }
        elif chat_level == "project":
            # Project level: all tools (unassigned aliases are still valid)
            context_allowed = {t["name"] for t in all_tools}
        else:
            context_allowed = {t["name"] for t in all_tools}

        # Tool must pass BOTH layer and context gates
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
    """Convert a Claude tool name back to its MCP equivalent.

    voxyflow_card_create → voxyflow.card.create
    """
    parts = claude_name.split("_", 2)  # ['voxyflow', 'card', 'create']
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
    import os
    from pathlib import Path

    settings_path = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/voxyflow"))) / "settings.json"
    if not settings_path.exists():
        return {}
    try:
        with open(settings_path) as f:
            data = json.load(f)
        return data.get("models", {})
    except Exception as e:
        logger.warning(f"Failed to load model overrides from settings.json: {e}")
        return {}


# ---------------------------------------------------------------------------
# Client factories
# ---------------------------------------------------------------------------

def _make_anthropic_client(api_key: str, api_base: str = ""):
    """Create a native Anthropic SDK client (sync)."""
    import anthropic
    kwargs = {"api_key": api_key} if api_key else {}
    if api_base:
        kwargs["base_url"] = api_base
    return anthropic.Anthropic(**kwargs)


def _make_async_anthropic_client(api_key: str, api_base: str = ""):
    """Create a native async Anthropic SDK client (for worker tasks)."""
    import anthropic
    kwargs = {"api_key": api_key} if api_key else {}
    if api_base:
        kwargs["base_url"] = api_base
    return anthropic.AsyncAnthropic(**kwargs)


def _make_openai_client(provider_url: str, api_key: str):
    """Create an OpenAI-compatible client (proxy fallback)."""
    from openai import OpenAI
    return OpenAI(
        base_url=provider_url or "http://localhost:3457/v1",
        api_key=api_key if api_key else "not-needed",
    )


import re as _re

def _strip_think_tags(text: str) -> str:
    """Strip <think>...</think> blocks from model output (Qwen3, DeepSeek-R1, etc.)."""
    return _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL).strip()


def _is_thinking_model(model_name: str) -> bool:
    """Detect models that emit <think> tokens (Qwen3, DeepSeek-R1, etc.)."""
    if not model_name:
        return False
    lower = model_name.lower()
    return any(x in lower for x in ("qwen3", "qwen2.5-think", "deepseek-r1", "deepseek-r2", "qwq"))


def _inject_no_think(system: str | list, model_name: str) -> str | list:
    """Prepend /no_think to system prompt for thinking models to disable chain-of-thought."""
    if not _is_thinking_model(model_name):
        return system
    prefix = "/no_think\n\n"
    if isinstance(system, str):
        return prefix + system
    if isinstance(system, list):
        # List of content blocks — prepend to first text block
        result = list(system)
        for i, block in enumerate(result):
            if isinstance(block, dict) and block.get("text"):
                result[i] = {**block, "text": prefix + block["text"]}
                return result
        # No text block found — prepend a new one
        return [{"type": "text", "text": prefix}] + result
    return system


def _get_api_key_from_settings(layer_cfg: dict) -> str:
    """Extract api_key from a settings.json layer config block."""
    return (layer_cfg.get("api_key") or "").strip()


# ---------------------------------------------------------------------------
# ClaudeService
# ---------------------------------------------------------------------------

class ClaudeService:
    """
    Handles Claude API calls for both conversation layers.

    Primary path: native Anthropic Python SDK (claude_use_native=True).
    Fallback path: OpenAI-compatible proxy at localhost:3457 (claude_use_native=False).

    Model/provider overrides can be configured via the Settings UI (settings.json).
    All calls are personality-infused via PersonalityService.
    """

    _instance: "ClaudeService | None" = None

    def __new__(cls) -> "ClaudeService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        config = get_settings()
        self.max_tokens = config.claude_max_tokens
        # Per-model max_tokens (haiku=8192, sonnet=16000, opus=32000)
        self.max_tokens_haiku = config.claude_max_tokens_haiku
        self.max_tokens_sonnet = config.claude_max_tokens_sonnet
        self.max_tokens_opus = config.claude_max_tokens_opus
        self.use_native = config.claude_use_native

        # Load overrides from settings.json
        overrides = _load_model_overrides()

        # Resolve API key (keyring/env already merged into config.claude_api_key)
        default_api_key = config.claude_api_key

        # --- Fast layer ---
        fast_cfg = overrides.get("fast", {})
        fast_model_raw = fast_cfg.get("model", "").strip()
        self.fast_model = _resolve_model(fast_model_raw or config.claude_sonnet_model)
        fast_key = _get_api_key_from_settings(fast_cfg) or default_api_key
        if self.use_native and fast_key:
            self.fast_client = _make_anthropic_client(fast_key, fast_cfg.get("provider_url", config.claude_api_base))
            self.fast_client_type = "anthropic"
        else:
            self.fast_client = _make_openai_client(
                fast_cfg.get("provider_url", config.claude_proxy_url),
                fast_cfg.get("api_key") or default_api_key,
            )
            self.fast_client_type = "openai"

        # --- Deep layer ---
        deep_cfg = overrides.get("deep", {})
        deep_model_raw = deep_cfg.get("model", "").strip()
        self.deep_model = _resolve_model(deep_model_raw or config.claude_deep_model)
        deep_key = _get_api_key_from_settings(deep_cfg) or default_api_key
        if self.use_native and deep_key:
            self.deep_client = _make_anthropic_client(deep_key, deep_cfg.get("provider_url", config.claude_api_base))
            self.deep_client_type = "anthropic"
        else:
            self.deep_client = _make_openai_client(
                deep_cfg.get("provider_url", config.claude_proxy_url),
                deep_cfg.get("api_key") or default_api_key,
            )
            self.deep_client_type = "openai"

        # --- Haiku worker layer ---
        haiku_cfg = overrides.get("haiku", {})
        haiku_model_raw = haiku_cfg.get("model", "").strip()
        self.haiku_model = _resolve_model(haiku_model_raw or "claude-haiku-4")
        haiku_key = _get_api_key_from_settings(haiku_cfg) or default_api_key
        if self.use_native and haiku_key:
            self.haiku_client = _make_anthropic_client(haiku_key, haiku_cfg.get("provider_url", config.claude_api_base))
            self.haiku_client_type = "anthropic"
        else:
            self.haiku_client = _make_openai_client(
                haiku_cfg.get("provider_url", config.claude_proxy_url),
                haiku_cfg.get("api_key") or default_api_key,
            )
            self.haiku_client_type = "openai"

        # --- Analyzer layer ---
        analyzer_cfg = overrides.get("analyzer", {})
        analyzer_model_raw = analyzer_cfg.get("model", "").strip()
        self.analyzer_model = _resolve_model(analyzer_model_raw or config.claude_analyzer_model)
        analyzer_key = _get_api_key_from_settings(analyzer_cfg) or default_api_key
        if self.use_native and analyzer_key:
            self.analyzer_client = _make_anthropic_client(analyzer_key, analyzer_cfg.get("provider_url", config.claude_api_base))
            self.analyzer_client_type = "anthropic"
        else:
            self.analyzer_client = _make_openai_client(
                analyzer_cfg.get("provider_url", config.claude_proxy_url),
                analyzer_cfg.get("api_key") or default_api_key,
            )
            self.analyzer_client_type = "openai"

        # Legacy single client (backward compat, always OpenAI-compat proxy)
        from openai import OpenAI as _OAI
        self.client = _OAI(base_url=config.claude_proxy_url, api_key=config.claude_api_key or "not-needed")

        self.personality = get_personality_service()
        self.memory = get_memory_service()
        # LRU-bounded dicts: max 500 entries to prevent unbounded RAM growth.
        # Oldest chat_ids are evicted automatically when the limit is exceeded.
        self._histories: _LRUDict = _LRUDict(maxsize=500)
        # Per-chat_id async locks — also LRU-bounded so orphaned locks get evicted too.
        self._history_locks: _LRUDict = _LRUDict(maxsize=500, default_factory=asyncio.Lock)
        # Native delegate tool_use blocks collected during streaming (keyed by chat_id)
        # Populated by chat_fast_stream / chat_deep_stream, consumed by orchestrator
        self._pending_delegates: dict[str, list[dict]] = {}

        logger.info(
            f"ClaudeService initialized — native={self.use_native} | "
            f"fast={self.fast_model}({self.fast_client_type}) | "
            f"deep={self.deep_model}({self.deep_client_type}) | "
            f"haiku={self.haiku_model}({self.haiku_client_type})"
        )

    def reload_models(self) -> None:
        """Hot-reload model/provider config from settings.json without restarting."""
        config = get_settings()
        overrides = _load_model_overrides()
        default_api_key = config.claude_api_key

        for layer, attr_prefix, default_model in [
            ("fast", "fast", config.claude_sonnet_model),
            ("deep", "deep", config.claude_deep_model),
            ("haiku", "haiku", "claude-haiku-4"),
            ("analyzer", "analyzer", config.claude_analyzer_model),
        ]:
            cfg = overrides.get(layer, {})
            model_raw = cfg.get("model", "").strip()
            model = _resolve_model(model_raw or default_model)
            key = _get_api_key_from_settings(cfg) or default_api_key
            purl = cfg.get("provider_url", "")

            if self.use_native and key and ("claude" in model.lower() or "anthropic" in purl.lower()):
                client = _make_anthropic_client(key, purl or config.claude_api_base)
                client_type = "anthropic"
            else:
                client = _make_openai_client(
                    purl or config.claude_proxy_url,
                    cfg.get("api_key") or default_api_key,
                )
                client_type = "openai"

            setattr(self, f"{attr_prefix}_model", model)
            setattr(self, f"{attr_prefix}_client", client)
            setattr(self, f"{attr_prefix}_client_type", client_type)

        logger.info(
            f"ClaudeService reloaded — "
            f"fast={self.fast_model}({self.fast_client_type}) | "
            f"deep={self.deep_model}({self.deep_client_type}) | "
            f"haiku={self.haiku_model}({self.haiku_client_type}) | "
            f"analyzer={self.analyzer_model}({self.analyzer_client_type})"
        )

    def _infer_layer(self, model: str) -> str:
        """Map a model name to a conceptual layer for token logging."""
        if model == self.fast_model:
            return "fast"
        if model == self.deep_model:
            return "deep"
        if model == self.haiku_model:
            return "haiku"
        if model == self.analyzer_model:
            return "analyzer"
        return "unknown"

    # ------------------------------------------------------------------
    # History helpers (accessible across layers via the singleton)
    # ------------------------------------------------------------------

    def get_history(self, chat_id: str) -> list[dict]:
        """Return conversation history for *chat_id*, loading from the session
        store on first access.  Because ClaudeService is a singleton, this
        history is shared across all layers (fast, deep, analyzer).

        NOTE: Callers that mutate the history (append) should use
        _append_and_persist() under the per-chat lock instead of
        manipulating the list directly.
        """
        if chat_id not in self._histories:
            self._histories[chat_id] = session_store.get_history_for_claude(chat_id, limit=40)
        return self._histories[chat_id]

    # Keep the underscore alias so existing internal callers don't break.
    _get_history = get_history

    def _get_lock(self, chat_id: str) -> asyncio.Lock:
        """Return the per-chat_id asyncio.Lock (created on first access)."""
        return self._history_locks[chat_id]

    async def _append_and_persist_async(self, chat_id: str, role: str, content: str,
                                        model: str | None = None, msg_type: str | None = None,
                                        session_id: str | None = None):
        """Locked, dedup-guarded append + persist.  Prefer this over the sync version."""
        async with self._get_lock(chat_id):
            history = self._get_history(chat_id)

            # Dedup guard: skip if last message has same role+content
            if history and history[-1].get("role") == role and history[-1].get("content") == content:
                logger.debug(f"[dedup] Skipping duplicate {role} message for {chat_id}")
                return

            history.append({"role": role, "content": content})
            msg = {"role": role, "content": content}
            if model:
                msg["model"] = model
            if msg_type:
                msg["type"] = msg_type
            if session_id:
                msg["session_id"] = session_id
            session_store.save_message(chat_id, msg)

    def _append_and_persist(self, chat_id: str, role: str, content: str,
                            model: str | None = None, msg_type: str | None = None,
                            session_id: str | None = None):
        """Sync version with dedup guard (no async lock).
        Kept for backward compat — prefer _append_and_persist_async in async code."""
        history = self._get_history(chat_id)
        # Dedup guard: skip if last message has same role+content
        if history and history[-1].get("role") == role and history[-1].get("content") == content:
            logger.debug(f"[dedup] Skipping duplicate {role} message for {chat_id}")
            return
        history.append({"role": role, "content": content})
        msg = {"role": role, "content": content}
        if model:
            msg["model"] = model
        if msg_type:
            msg["type"] = msg_type
        if session_id:
            msg["session_id"] = session_id
        session_store.save_message(chat_id, msg)

    # ------------------------------------------------------------------
    # Sliding window with summarization
    # ------------------------------------------------------------------

    async def _summarize_evicted_messages(self, chat_id: str, messages: list[dict], existing_text: str = "") -> str:
        """Use Haiku to summarize evicted messages, appending to any existing summary."""
        if not messages:
            return existing_text

        # Build the content to summarize
        convo_lines = []
        for m in messages:
            role = m.get("role", "unknown").upper()
            convo_lines.append(f"{role}: {m.get('content', '')}")
        new_convo = "\n".join(convo_lines)

        prompt_parts = []
        if existing_text:
            prompt_parts.append(f"Previous conversation summary:\n{existing_text}\n\n---\n")
        prompt_parts.append(f"New messages to incorporate:\n{new_convo}")
        prompt_parts.append(
            "\n\nWrite a concise summary (1-3 paragraphs) capturing: key decisions made, "
            "topics discussed, important context, and any pending actions or requests. "
            "Merge with the previous summary if one exists. Be factual and brief."
        )

        try:
            summary = await self._call_api(
                model=self.haiku_model,
                system="You are a conversation summarizer. Output only the summary, nothing else.",
                messages=[{"role": "user", "content": "".join(prompt_parts)}],
                client=self.haiku_client,
                client_type=self.haiku_client_type,
                use_tools=False,
                layer="analyzer",
                chat_level="general",
            )
            return (summary or "").strip()
        except Exception as e:
            logger.warning(f"[sliding_window] Haiku summarization failed: {e}")
            # Fallback: keep existing summary unchanged
            return existing_text

    async def _get_windowed_history(self, chat_id: str) -> list[dict]:
        """Return messages for Claude API with sliding window summarization.

        If history exceeds chat_window_size, older messages are summarized
        via Haiku and injected as a context block before the recent messages.
        """
        settings = get_settings()
        window = settings.chat_window_size
        history = self._get_history(chat_id)

        if len(history) <= window:
            return list(history)

        # Determine what needs summarizing
        existing = session_store.load_summary(chat_id)
        already_summarized = existing["summarized_count"] if existing else 0
        cutoff = len(history) - window  # everything before this index gets summarized

        if cutoff > already_summarized:
            # New messages to evict — summarize them incrementally
            existing_text = existing["summary_text"] if existing else ""
            newly_evicted = history[already_summarized:cutoff]
            summary_text = await self._summarize_evicted_messages(chat_id, newly_evicted, existing_text)
            if summary_text:
                session_store.save_summary(chat_id, summary_text, cutoff)
        else:
            summary_text = existing["summary_text"] if existing else ""

        recent = history[-window:]

        if summary_text:
            summary_msg = {
                "role": "user",
                "content": (
                    f"[CONVERSATION CONTEXT — Summary of earlier messages]\n\n"
                    f"{summary_text}\n\n"
                    f"[END OF SUMMARY — The conversation continues below]"
                ),
            }
            return [summary_msg, {"role": "assistant", "content": "Understood, I have the context from our earlier conversation."}, *recent]

        return list(recent)

    # ------------------------------------------------------------------
    # Native delegate helpers
    # ------------------------------------------------------------------

    def pop_pending_delegates(self, chat_id: str) -> list[dict]:
        """Return and clear any native delegate_action tool_use blocks
        collected during the last streaming call for this chat_id."""
        return self._pending_delegates.pop(chat_id, [])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat_fast(
        self,
        chat_id: str,
        user_message: str,
        project_name: Optional[str] = None,
        project_id: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
    ) -> str:
        """Layer 1: Fast conversational response, personality-infused."""
        await self._append_and_persist_async(chat_id, "user", user_message, model="fast")

        recent = await self._get_windowed_history(chat_id)

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=False,
            include_daily=True,
            query=user_message,
        )
        # Static base prompt (cacheable)
        base_prompt = self.personality.build_fast_prompt(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
        )

        # Dynamic context (per-call, not cached)
        dynamic_parts: list[str] = []
        dynamic_context = self.personality.build_dynamic_context_block(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            memory_context=memory_context,
        )
        if dynamic_context:
            dynamic_parts.append(dynamic_context)

        if project_id:
            try:
                pass  # RAG disabled — use knowledge.search tool instead
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_fast): {e}")

        system_prompt = _make_cached_system(
            base_prompt, dynamic_parts, is_anthropic=(self.fast_client_type == "anthropic")
        )

        response_text = await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=recent,
            client=self.fast_client,
            client_type=self.fast_client_type,
            chat_level=chat_level,
        )

        await self._append_and_persist_async(chat_id, "assistant", response_text, model="fast")
        return response_text

    async def chat_fast_stream(
        self,
        chat_id: str,
        user_message: str,
        project_name: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
        project_id: Optional[str] = None,
        project_names: Optional[list] = None,
        active_workers_context: str = "",
    ) -> AsyncIterator[str]:
        """Layer 1 (streaming): Yield tokens as they arrive from the fast layer.

        Native Anthropic path: uses delegate_action tool_use for dispatching.
        Proxy path: zero tools, relies on <delegate> XML blocks in text.
        """
        use_native_delegate = self.fast_client_type == "anthropic"

        await self._append_and_persist_async(chat_id, "user", user_message, model="fast")
        full_history = self._get_history(chat_id)  # full history for conversation-age checks
        recent = await self._get_windowed_history(chat_id)  # windowed messages for the API

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=False,
            include_daily=True,
            query=user_message,
        )
        # Static base prompt — personality + dispatcher + tools only (cacheable)
        base_prompt = self.personality.build_fast_prompt(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            native_tools=use_native_delegate,
        )

        # Collect dynamic context (changes per-call — injected OUTSIDE the cached block)
        dynamic_parts: list[str] = []

        # Project/card context + memory — dynamic, must NOT be in base_prompt
        dynamic_context = self.personality.build_dynamic_context_block(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            project_names=project_names,
            memory_context=memory_context,
        )
        if dynamic_context:
            dynamic_parts.append(dynamic_context)

        if project_id:
            try:
                pass  # RAG disabled — use knowledge.search tool instead
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_fast_stream): {e}")

        if active_workers_context:
            dynamic_parts.append("## Background Workers Status\n" + active_workers_context)

        # Build system param with prompt caching for Anthropic native path
        system_prompt = _make_cached_system(base_prompt, dynamic_parts, is_anthropic=use_native_delegate)
        # Inject /no_think for thinking models (Qwen3, DeepSeek-R1, etc.)
        system_prompt = _inject_no_think(system_prompt, self.fast_model)

        # Inject identity priming exchange at the start of conversations.
        primed_messages = list(recent)
        is_auto_greeting = "greet" in user_message.lower() and "naturally" in user_message.lower()
        if len(full_history) <= 4 and not is_auto_greeting:
            if use_native_delegate:
                priming_assistant = (
                    "I'm Voxy, running inside Voxyflow's chat layer. I'm a dispatcher — "
                    "I converse with you directly and delegate most actions to background workers "
                    "using the delegate_action tool. I also have inline tools (memory_search, "
                    "knowledge_search, memory_save) that I execute directly to recall and save context. When you ask "
                    "me to do something like a web search or create a card, I respond briefly and "
                    "call delegate_action to trigger the worker. The worker handles it in the "
                    "background and the result appears in the chat."
                )
            else:
                priming_assistant = (
                    "I'm Voxy, running inside Voxyflow's chat layer. I'm a dispatcher — "
                    "I converse with you directly and delegate all actions to background workers "
                    "via <delegate> blocks. I never execute tools myself. When you ask me to do "
                    "something like a web search or create a card, I respond briefly and include "
                    "a <delegate> block at the end of my message to trigger the worker. "
                    "The worker handles it in the background and the result appears in the chat."
                )
            priming = [
                {"role": "user", "content": (
                    "[SYSTEM INIT] Confirm your identity and operating mode. "
                    "Who are you, where are you running, and how do you handle action requests?"
                )},
                {"role": "assistant", "content": priming_assistant},
            ]
            primed_messages = priming + primed_messages

        # Clear any previous pending delegates for this chat
        self._pending_delegates.pop(chat_id, None)

        if use_native_delegate:
            # Native Anthropic: stream with delegate_action tool
            full_response = ""
            async for token in self._call_api_stream_with_delegate(
                model=self.fast_model,
                system=system_prompt,
                messages=primed_messages,
                client=self.fast_client,
                chat_id=chat_id,
            ):
                full_response += token
                yield token
            logger.info(f"[chat_fast_stream] Native delegate path — collected {len(self._pending_delegates.get(chat_id, []))} delegates")
        else:
            # Proxy fallback: no tools, XML delegate blocks
            full_response = ""
            async for token in self._call_api_stream(
                model=self.fast_model,
                system=system_prompt,
                messages=primed_messages,
                client=self.fast_client,
                client_type=self.fast_client_type,
                use_tools=False,
                chat_level=chat_level,
            ):
                full_response += token
                yield token

        # Strip <think> blocks only for thinking models (Qwen3, DeepSeek-R1, etc.)
        if _is_thinking_model(self.fast_model):
            full_response = _strip_think_tags(full_response)
        if full_response:
            await self._append_and_persist_async(chat_id, "assistant", full_response, model="fast")

    async def chat_deep_stream(
        self,
        chat_id: str,
        user_message: str,
        project_name: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
        project_id: Optional[str] = None,
        project_names: Optional[list] = None,
        active_workers_context: str = "",
    ) -> AsyncIterator[str]:
        """Deep layer (streaming): Yield tokens from the deep model directly to chat.

        Native Anthropic path: uses delegate_action tool_use for dispatching.
        Proxy path: zero tools, relies on <delegate> XML blocks in text.
        """
        use_native_delegate = self.deep_client_type == "anthropic"

        await self._append_and_persist_async(chat_id, "user", user_message, model="deep")
        full_history = self._get_history(chat_id)  # full history for conversation-age checks
        recent = await self._get_windowed_history(chat_id)  # windowed messages for the API

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=True,
            include_daily=True,
            query=user_message,
        )
        # Static base prompt — personality + dispatcher + tools only (cacheable)
        base_prompt = self.personality.build_deep_prompt(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            is_chat_responder=True,
            native_tools=use_native_delegate,
        )

        # Collect dynamic context (changes per-call — injected OUTSIDE the cached block)
        dynamic_parts: list[str] = []

        # Project/card context + memory — dynamic, must NOT be in base_prompt
        dynamic_context = self.personality.build_dynamic_context_block(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            project_names=project_names,
            memory_context=memory_context,
        )
        if dynamic_context:
            dynamic_parts.append(dynamic_context)

        if project_id:
            try:
                pass  # RAG disabled — use knowledge.search tool instead
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_deep_stream): {e}")

        if active_workers_context:
            dynamic_parts.append("## Background Workers Status\n" + active_workers_context)

        # Build system param with prompt caching for Anthropic native path
        system_prompt = _make_cached_system(base_prompt, dynamic_parts, is_anthropic=use_native_delegate)
        # Inject /no_think for thinking models (Qwen3, DeepSeek-R1, etc.)
        system_prompt = _inject_no_think(system_prompt, self.deep_model)

        # Identity priming for deep chat layer (same as fast — see chat_fast_stream)
        primed_messages = list(recent)
        is_auto_greeting = "greet" in user_message.lower() and "naturally" in user_message.lower()
        if len(full_history) <= 4 and not is_auto_greeting:
            if use_native_delegate:
                priming_assistant = (
                    "I'm Voxy, running inside Voxyflow's chat layer as the Deep model. I'm a dispatcher — "
                    "I converse with you directly and delegate all actions to background workers "
                    "using the delegate_action tool. I never execute actions myself. When you ask "
                    "me to do something, I respond briefly and call delegate_action to trigger the worker."
                )
            else:
                priming_assistant = (
                    "I'm Voxy, running inside Voxyflow's chat layer. I'm a dispatcher — "
                    "I converse with you directly and delegate all actions to background workers "
                    "via <delegate> blocks. I never execute tools myself. When you ask me to do "
                    "something like a web search or create a card, I respond briefly and include "
                    "a <delegate> block at the end of my message to trigger the worker. "
                    "The worker handles it in the background and the result appears in the chat."
                )
            priming = [
                {"role": "user", "content": (
                    "[SYSTEM INIT] Confirm your identity and operating mode. "
                    "Who are you, where are you running, and how do you handle action requests?"
                )},
                {"role": "assistant", "content": priming_assistant},
            ]
            primed_messages = priming + primed_messages

        # Clear any previous pending delegates for this chat
        self._pending_delegates.pop(chat_id, None)

        if use_native_delegate:
            full_response = ""
            async for token in self._call_api_stream_with_delegate(
                model=self.deep_model,
                system=system_prompt,
                messages=primed_messages,
                client=self.deep_client,
                chat_id=chat_id,
            ):
                full_response += token
                yield token
            logger.info(f"[chat_deep_stream] Native delegate path — collected {len(self._pending_delegates.get(chat_id, []))} delegates")
        else:
            full_response = ""
            async for token in self._call_api_stream(
                model=self.deep_model,
                system=system_prompt,
                messages=primed_messages,
                client=self.deep_client,
                client_type=self.deep_client_type,
                use_tools=False,
                chat_level=chat_level,
            ):
                full_response += token
                yield token

        # Strip <think> blocks only for thinking models (Qwen3, DeepSeek-R1, etc.)
        if _is_thinking_model(self.deep_model):
            full_response = _strip_think_tags(full_response)
        if full_response:
            await self._append_and_persist_async(chat_id, "assistant", full_response, model="deep")


    async def execute_worker_task(
        self,
        chat_id: str,
        prompt: str,
        model: str = "sonnet",
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
        project_id: Optional[str] = None,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        cancel_event: Optional[asyncio.Event] = None,
        message_queue: Optional[asyncio.Queue] = None,
    ) -> str:
        """Execute a delegated task with the specified worker model (haiku/sonnet/opus)."""
        # Select client/model based on model param
        if model == "haiku":
            client, client_type, model_name = (
                self.haiku_client, self.haiku_client_type, self.haiku_model
            )
            layer = "analyzer"  # Uses TOOLS_VOXYFLOW_CRUD
        elif model == "opus":
            client, client_type, model_name = (
                self.deep_client, self.deep_client_type, self.deep_model
            )
            layer = "deep"  # Uses TOOLS_FULL
        else:  # sonnet (default)
            client, client_type, model_name = (
                self.fast_client, self.fast_client_type, self.fast_model
            )
            layer = "deep"  # Sonnet worker gets full tools for research

        # Workers always use the native Anthropic async SDK (tool_use blocks) to avoid
        # XML <tool_call> truncation issues with the OpenAI-compat proxy path.
        # Using AsyncAnthropic avoids "Streaming required for long requests" errors.
        # The client is pointed at CLIProxyAPI which supports /v1/messages.
        if client_type == "openai":
            _cfg = get_settings()
            worker_api_url = _cfg.claude_proxy_url  # e.g. http://100.96.26.98:3457/v1
            worker_api_key = _cfg.claude_api_key or "not-needed"
            # CLIProxyAPI /v1/messages expects base_url without /v1 suffix
            anthropic_base = worker_api_url.rstrip("/")
            if anthropic_base.endswith("/v1"):
                anthropic_base = anthropic_base[:-3]
            client = _make_async_anthropic_client(worker_api_key, anthropic_base)
            client_type = "anthropic"  # Same path as sync anthropic; async detected via isinstance
            logger.info(f"[execute_worker_task] Upgraded worker client to AsyncAnthropic → {anthropic_base}")

        # Build worker-specific prompt
        base_prompt = self.personality.build_worker_prompt(
            model=model,
            chat_level=chat_level,
            project=project_context,
            card=card_context,
        )

        dynamic_parts: list[str] = []

        # Mandatory task.complete instruction for workers
        dynamic_parts.append(
            "IMPORTANT: When your task is complete, you MUST call the task.complete tool "
            "with a summary of what you did and a status (success/partial/failed). "
            "This is mandatory — never finish without calling task.complete."
        )

        if project_id:
            try:
                pass  # RAG disabled — use knowledge.search tool instead
            except Exception as e:
                logger.warning(f"RAG context injection failed (execute_worker_task): {e}")

        system_prompt = _make_cached_system(
            base_prompt, dynamic_parts, is_anthropic=(client_type == "anthropic")
        )
        system_prompt = _inject_no_think(system_prompt, model_name)

        result = await self._call_api(
            model=model_name,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=client,
            client_type=client_type,
            use_tools=True,
            tool_callback=tool_callback,
            layer=layer,
            chat_level=chat_level,
            cancel_event=cancel_event,
            message_queue=message_queue,
        )
        return (_strip_think_tags(result) if _is_thinking_model(model_name) else result) if result else result

    async def safety_net_generate_delegate(self, assistant_message: str) -> Optional[str]:
        """Quick Haiku call to extract a missing delegate from an action-promising message.

        Returns raw JSON string for the delegate, or None if extraction fails.
        """
        prompt = (
            "The following assistant message promised an action but didn't include a "
            "<delegate> block. Generate ONLY the JSON for the delegate.\n"
            "Response must be a single JSON object with these fields:\n"
            '  - "intent": action name (e.g. "create_card", "web_search", "run_command")\n'
            '  - "model": "haiku" | "sonnet" | "opus" (pick the cheapest that fits)\n'
            '  - "summary": one-line description of the action\n'
            '  - "complexity": "simple" | "complex"\n'
            "Include any extra fields relevant to the action (title, query, etc).\n"
            "Output ONLY valid JSON, no markdown, no explanation.\n\n"
            f"Message:\n{assistant_message}"
        )
        try:
            result = await self._call_api(
                model=self.haiku_model,
                system="You are a JSON extraction tool. Output only valid JSON.",
                messages=[{"role": "user", "content": prompt}],
                client=self.haiku_client,
                client_type=self.haiku_client_type,
                use_tools=False,
                layer="analyzer",
                chat_level="general",
            )
            return result.strip() if result else None
        except Exception as e:
            logger.warning(f"[SafetyNet] Haiku delegate generation failed: {e}")
            return None

    async def chat_deep(
        self,
        chat_id: str,
        user_message: str,
        project_name: Optional[str] = None,
        project_id: Optional[str] = None,
    ) -> Optional[str]:
        """Layer 2: Deep analysis, personality-infused. Returns None or enrichment text."""

        recent = await self._get_windowed_history(chat_id)

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=True,
            include_daily=True,
            query=user_message,
        )
        # Static base prompt (cacheable)
        base_prompt = self.personality.build_deep_prompt()

        # Dynamic context (per-call, not cached)
        dynamic_parts: list[str] = []
        if memory_context:
            dynamic_parts.append(f"## Relevant Memory\n{memory_context}")

        if project_id:
            try:
                pass  # RAG disabled — use knowledge.search tool instead
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_deep): {e}")

        system_prompt = _make_cached_system(
            base_prompt, dynamic_parts, is_anthropic=(self.deep_client_type == "anthropic")
        )

        response_text = await self._call_api(
            model=self.deep_model,
            system=system_prompt,
            messages=recent,
            client=self.deep_client,
            client_type=self.deep_client_type,
            layer="deep",
        )

        if not response_text or response_text.strip().upper() == "EMPTY":
            return None
        return response_text

    async def generate_brief(self, prompt: str) -> str:
        """One-shot project brief generation using the deep model. No history, no persistence."""
        system_prompt = (
            "You are a senior product manager and technical architect generating a comprehensive "
            "project brief / PRD. Produce well-structured, professional markdown. "
            "Be thorough, specific, and actionable. Use clear headings, bullet points, and "
            "tables where appropriate. Infer technical details from context when not explicitly provided."
        )
        return await self._call_api(
            model=self.deep_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.deep_client,
            client_type=self.deep_client_type,
            use_tools=False,
        )

    async def generate_health_summary(self, prompt: str) -> str:
        """One-shot health check summary using the fast model."""
        system_prompt = (
            "You are a project health analyst. Given a project's stats and issues, "
            "write a concise, honest 2-3 sentence summary of the project's health. "
            "Be direct, specific, and actionable. No filler. Use plain text only."
        )
        return await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.fast_client,
            client_type=self.fast_client_type,
            use_tools=False,
        )

    async def generate_standup(self, prompt: str) -> str:
        """One-shot standup generation using the fast model."""
        system_prompt = (
            "You are a project assistant generating a concise daily standup summary. "
            "Be direct and brief. Use markdown bullet points. No filler words.\n"
            "Format:\n"
            "**✅ Done**\n- ...\n\n**🔨 In Progress**\n- ...\n\n**🚧 Blocked / Risks**\n- ...\n\n**📌 Today's Goals**\n- ..."
        )
        return await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.fast_client,
            client_type=self.fast_client_type,
            use_tools=False,
        )

    async def generate_meeting_notes(self, notes: str) -> dict:
        """One-shot meeting notes extraction. Returns cards + summary."""
        system_prompt = (
            "You are a project assistant that extracts action items from meeting notes. "
            "Respond ONLY with valid JSON — no markdown, no code blocks, no commentary.\n"
            "The JSON must have two keys:\n"
            '  "cards": an array of objects with keys: title (str), description (str), priority (int 0-3), agent_type (str)\n'
            '  "summary": a brief 1-2 sentence summary of the meeting.\n'
            "Priority scale: 0=low, 1=medium, 2=high, 3=critical.\n"
            "agent_type must be one of: ember, researcher, coder, designer, architect, writer, qa.\n"
            "Auto-detect the most appropriate agent_type based on the action item content."
        )
        prompt = (
            "Extract action items from these meeting notes as structured tasks. "
            "Return JSON with cards array and a brief summary.\n\n"
            f"Meeting notes:\n{notes}"
        )
        response = await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.fast_client,
            client_type=self.fast_client_type,
            use_tools=False,
        )
        text = response.strip()
        if text.startswith("```"):
            text = text.split("```", 2)[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.rsplit("```", 1)[0].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"cards": [], "summary": "Could not parse meeting notes."}

    async def generate_priority_reasoning(self, prompt: str) -> str:
        """One-shot priority reasoning for top-3 cards. Returns JSON string."""
        system_prompt = (
            "You are a project prioritization assistant. "
            "Given the top prioritized cards with their scores and attributes, "
            "write a short, specific one-sentence reasoning for why each card is ranked where it is. "
            "Respond ONLY with valid JSON array — no markdown, no code blocks, no commentary."
        )
        return await self._call_api(
            model=self.fast_model,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=self.fast_client,
            client_type=self.fast_client_type,
            use_tools=False,
        )

    # ------------------------------------------------------------------
    # Internal: Anthropic native SDK
    # ------------------------------------------------------------------

    async def _call_api_anthropic(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        client,
        use_tools: bool = True,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
        layer: str = "fast",
        chat_id: str = "",
        cancel_event: Optional[asyncio.Event] = None,
        message_queue: Optional[asyncio.Queue] = None,
        client_type: str = "anthropic",
    ) -> str:
        """Native Anthropic SDK call with tool_use loop.

        - Strips system messages from the messages array (system goes in `system` param).
        - Converts OpenAI tool format (parameters) to Anthropic (input_schema) — already done
          by get_claude_tools() which always uses input_schema.
        - Loops on tool_use blocks until Claude returns a final text response.
        """
        # Strip system-role messages; system prompt is passed separately
        clean_messages = [m for m in messages if m.get("role") != "system"]

        claude_tools = get_claude_tools(chat_level=chat_level, layer=layer) if use_tools else []

        # Ensure messages list is not empty (Anthropic requires at least one)
        if not clean_messages:
            clean_messages = [{"role": "user", "content": "(empty)"}]

        # Per-model max_tokens: haiku→4096, sonnet→16000, opus→32000
        if model == self.deep_model or "opus" in model.lower():
            resolved_max_tokens = self.max_tokens_opus
        elif model == self.haiku_model or "haiku" in model.lower():
            resolved_max_tokens = self.max_tokens_haiku
        elif model == self.fast_model or "sonnet" in model.lower():
            resolved_max_tokens = self.max_tokens_sonnet
        else:
            resolved_max_tokens = self.max_tokens

        kwargs = {
            "model": model,
            "max_tokens": resolved_max_tokens,
            "system": system,
            "messages": clean_messages,
        }
        _first_turn = True  # tool_choice='any' only on first turn to avoid infinite loops
        if claude_tools:
            kwargs["tools"] = claude_tools
            # Only force tool_choice='any' on the FIRST turn (iteration 0)
            # to avoid trapping Opus in an infinite tool loop on synthesis turns.
            if layer in ("deep", "worker") and _first_turn:
                kwargs["tool_choice"] = {"type": "any"}
        try:
            # Agentic tool-use loop (max 20 rounds for complex worker tasks)
            for _ in range(20):
                # Check cancel_event before each API round
                if cancel_event and cancel_event.is_set():
                    logger.info(f"[Anthropic] Cancel event set — breaking tool loop for {chat_id}")
                    return "[Task cancelled by supervisor]"

                # Drain injected messages from external code (supervisor warnings, etc.)
                if message_queue:
                    injected: list[str] = []
                    while not message_queue.empty():
                        try:
                            msg = message_queue.get_nowait()
                            injected.append(msg)
                        except asyncio.QueueEmpty:
                            break
                    if injected:
                        combined = "\n".join(injected)
                        logger.info(f"[Anthropic] Injecting {len(injected)} message(s) into worker conversation")
                        # Ensure last message is from user (Anthropic requires alternating roles)
                        last_role = kwargs["messages"][-1].get("role") if kwargs["messages"] else None
                        if last_role == "user":
                            # Merge into the last user message
                            last_msg = kwargs["messages"][-1]
                            if isinstance(last_msg["content"], str):
                                last_msg["content"] += f"\n\n[Supervisor] {combined}"
                            else:
                                kwargs["messages"] = list(kwargs["messages"]) + [
                                    {"role": "assistant", "content": "(acknowledged)"},
                                    {"role": "user", "content": f"[Supervisor] {combined}"},
                                ]
                        else:
                            kwargs["messages"] = list(kwargs["messages"]) + [
                                {"role": "user", "content": f"[Supervisor] {combined}"},
                            ]

                # Use async streaming for AsyncAnthropic clients (detected by isinstance).
                # Sync Anthropic clients fall back to asyncio.to_thread.
                import anthropic as _anthropic
                if isinstance(client, _anthropic.AsyncAnthropic):
                    async with client.messages.stream(**kwargs) as stream:
                        response = await stream.get_final_message()
                else:
                    response = await asyncio.to_thread(
                        lambda kw=kwargs: client.messages.create(**kw)
                    )

                # After first turn: remove tool_choice so model can freely emit text
                if _first_turn:
                    _first_turn = False
                    kwargs.pop("tool_choice", None)

                # Log prompt caching stats if available
                usage = response.usage
                cache_created = getattr(usage, "cache_creation_input_tokens", 0) or 0
                cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
                if cache_created or cache_read:
                    logger.info(
                        f"[PromptCache] model={model} input={usage.input_tokens} "
                        f"cache_created={cache_created} cache_read={cache_read} "
                        f"output={usage.output_tokens}"
                    )

                # Log token usage to JSONL
                _log_token_usage(
                    layer=self._infer_layer(model),
                    model=model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    chat_id=chat_id,
                    cache_creation_tokens=cache_created,
                    cache_read_tokens=cache_read,
                )

                stop_reason = response.stop_reason  # "end_turn" | "tool_use" | "max_tokens"

                # Handle max_tokens gracefully — don't silently drop partial result
                if stop_reason == "max_tokens":
                    text_parts = [b.text for b in response.content if b.type == "text"]
                    partial = "".join(text_parts)
                    logger.warning(
                        f"[Anthropic] max_tokens reached on round {_+1} for {chat_id!r} "
                        f"(partial text length={len(partial)})"
                    )
                    return partial + "\n[Truncated: max tokens reached]"

                # Collect tool_use blocks
                tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

                if stop_reason == "tool_use" or tool_use_blocks:
                    # Append assistant's response (with tool_use blocks) to messages
                    kwargs["messages"] = list(kwargs["messages"]) + [
                        {"role": "assistant", "content": response.content}
                    ]

                    # Execute each tool and collect results
                    tool_results = []
                    for block in tool_use_blocks:
                        claude_tool_name = block.name
                        arguments = block.input or {}
                        mcp_name = _mcp_tool_name_from_claude(claude_tool_name)
                        logger.info(f"[MCP] tool_use: {claude_tool_name} → {mcp_name}({arguments})")

                        result = await _call_mcp_tool(mcp_name, arguments)

                        if tool_callback:
                            try:
                                ret = tool_callback(mcp_name, arguments, result)
                                if asyncio.iscoroutine(ret):
                                    await ret
                            except Exception:
                                pass

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })

                    # Check cancel after tool execution (repetition may have triggered it)
                    if cancel_event and cancel_event.is_set():
                        logger.info(f"[Anthropic] Cancel event set after tools — breaking loop for {chat_id}")
                        return "[Task cancelled by supervisor — repetitive loop detected]"

                    # Append tool results as a user message
                    kwargs["messages"] = list(kwargs["messages"]) + [
                        {"role": "user", "content": tool_results}
                    ]
                    continue  # Loop back for Claude's next response

                # No tool calls — collect text from content blocks
                text_parts = [b.text for b in response.content if b.type == "text"]
                return "".join(text_parts)

            logger.warning("_call_api_anthropic: tool loop exceeded 20 rounds")
            return ""

        except Exception as e:
            logger.error(f"Anthropic native API call failed: {e}")
            raise

    async def _call_api_stream_with_delegate(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        client,
        chat_id: str,
    ) -> AsyncIterator[str]:
        """Anthropic streaming with ONLY the delegate_action tool.

        Streams text tokens normally. When Claude emits a delegate_action tool_use,
        it is NOT executed — instead it's collected into self._pending_delegates[chat_id]
        for the orchestrator to process. Claude receives a synthetic "acknowledged" result
        so it can finish its text response naturally.
        """
        clean_messages = [m for m in messages if m.get("role") != "system"]
        if not clean_messages:
            clean_messages = [{"role": "user", "content": "(empty)"}]

        kwargs = {
            "model": model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": clean_messages,
            "tools": [DELEGATE_ACTION_TOOL] + INLINE_TOOLS,
        }

        max_inline_rounds = 3  # Prevent infinite inline tool loops

        try:
            for inline_round in range(max_inline_rounds + 1):
                # Collect streamed content and tool_use blocks
                streamed_text_parts: list[str] = []
                tool_use_blocks: list = []

                def _do_stream(_kw=kwargs):
                    events = []
                    with client.messages.stream(**_kw) as stream:
                        for text in stream.text_stream:
                            events.append(("text", text))
                        final_msg = stream.get_final_message()
                        for block in final_msg.content:
                            if block.type == "tool_use":
                                events.append(("tool_use", block))
                        events.append(("stop_reason", final_msg.stop_reason))
                        events.append(("usage", final_msg.usage))
                    return events

                events = await asyncio.to_thread(_do_stream)

                stop_reason = "end_turn"
                stream_usage = None
                for event_type, data in events:
                    if event_type == "text":
                        streamed_text_parts.append(data)
                        yield data
                    elif event_type == "tool_use":
                        tool_use_blocks.append(data)
                    elif event_type == "stop_reason":
                        stop_reason = data
                    elif event_type == "usage":
                        stream_usage = data

                # Log token usage from the delegate stream
                if stream_usage:
                    _log_token_usage(
                        layer=self._infer_layer(model),
                        model=model,
                        input_tokens=stream_usage.input_tokens,
                        output_tokens=stream_usage.output_tokens,
                        chat_id=chat_id,
                        cache_creation_tokens=getattr(stream_usage, "cache_creation_input_tokens", 0) or 0,
                        cache_read_tokens=getattr(stream_usage, "cache_read_input_tokens", 0) or 0,
                    )

                if not tool_use_blocks:
                    # No tool calls — done
                    return

                # Separate inline tools from delegate tool calls
                inline_blocks = [b for b in tool_use_blocks if b.name in _INLINE_TOOL_NAMES]
                delegate_blocks = [b for b in tool_use_blocks if b.name == "delegate_action"]
                unknown_blocks = [b for b in tool_use_blocks if b.name not in _INLINE_TOOL_NAMES and b.name != "delegate_action"]

                for b in unknown_blocks:
                    logger.warning(f"[NativeDelegate] Unexpected tool_use: {b.name} — ignoring")

                # Collect delegates
                for block in delegate_blocks:
                    self._pending_delegates.setdefault(chat_id, []).append(block.input or {})
                    logger.info(
                        f"[NativeDelegate] Collected delegate_action: "
                        f"action={block.input.get('action')}, summary={block.input.get('summary', '')!r}"
                    )

                # Execute inline tools
                inline_results: dict[str, str] = {}
                for block in inline_blocks:
                    logger.info(f"[InlineTool] Executing {block.name} with {block.input}")
                    result = await _execute_inline_tool(block.name, block.input or {})
                    inline_results[block.id] = json.dumps(result, default=str, ensure_ascii=False)
                    logger.info(f"[InlineTool] {block.name} result: {len(inline_results[block.id])} chars")

                # If we have inline tools that need results fed back, continue the loop
                if inline_blocks and stop_reason == "tool_use":
                    # Build continuation with tool results
                    assistant_content = []
                    if streamed_text_parts:
                        assistant_content.append({"type": "text", "text": "".join(streamed_text_parts)})
                    for block in tool_use_blocks:
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })

                    tool_results_content = []
                    for block in tool_use_blocks:
                        if block.id in inline_results:
                            tool_results_content.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": inline_results[block.id],
                            })
                        else:
                            # Delegate or unknown — acknowledge
                            tool_results_content.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({"status": "delegated", "message": "Action dispatched to background worker."}),
                            })

                    kwargs["messages"] = list(clean_messages) + [
                        {"role": "assistant", "content": assistant_content},
                        {"role": "user", "content": tool_results_content},
                    ]
                    # Reset streamed text for next round
                    streamed_text_parts = []
                    continue  # Next round of the inline loop

                # No inline tools or not stopped for tool_use — handle delegate continuation
                if stop_reason == "tool_use" and delegate_blocks:
                    # Build the continuation: acknowledge the delegate(s)
                    assistant_content = []
                    if streamed_text_parts:
                        assistant_content.append({"type": "text", "text": "".join(streamed_text_parts)})
                    for block in tool_use_blocks:
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })

                    continuation_messages = list(clean_messages) + [
                        {"role": "assistant", "content": assistant_content},
                        {"role": "user", "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({"status": "delegated", "message": "Action dispatched to background worker."}),
                            }
                            for block in tool_use_blocks
                        ]},
                    ]

                    # Get the final response (no tools this time — just let Claude finish talking)
                    final_kwargs = {
                        "model": model,
                        "max_tokens": self.max_tokens,
                        "system": system,
                        "messages": continuation_messages,
                    }
                    final_response = await asyncio.to_thread(
                        lambda kw=final_kwargs: client.messages.create(**kw)
                    )
                    for block in final_response.content:
                        if block.type == "text" and block.text:
                            yield block.text

                # Done — exit the loop
                return

            logger.warning("[NativeDelegate] Inline tool loop exceeded max rounds")

        except Exception as e:
            logger.error(f"Anthropic delegate streaming call failed: {e}")
            raise

    async def _call_api_stream_anthropic(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        client,
        use_tools: bool = True,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
        layer: str = "fast",
        chat_id: str = "",
    ) -> AsyncIterator[str]:
        """Native Anthropic SDK streaming call with tool_use handling.

        Streams text tokens on first pass. If Claude requests tool_use,
        buffers them, executes them, then makes a second non-streaming call
        for the final response and yields it as tokens.
        """
        clean_messages = [m for m in messages if m.get("role") != "system"]
        if not clean_messages:
            clean_messages = [{"role": "user", "content": "(empty)"}]

        claude_tools = get_claude_tools(chat_level=chat_level, layer=layer) if use_tools else []

        kwargs = {
            "model": model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": clean_messages,
        }
        if claude_tools:
            kwargs["tools"] = claude_tools

        try:
            # Collect streamed content and tool_use blocks
            streamed_text_parts: list[str] = []
            tool_use_blocks: list = []

            def _do_stream():
                """Run in thread — yields (type, data) tuples via a list."""
                events = []
                with client.messages.stream(**kwargs) as stream:
                    for text in stream.text_stream:
                        events.append(("text", text))
                    # After stream, inspect final message for tool_use blocks
                    final_msg = stream.get_final_message()
                    for block in final_msg.content:
                        if block.type == "tool_use":
                            events.append(("tool_use", block))
                    events.append(("stop_reason", final_msg.stop_reason))
                    events.append(("usage", final_msg.usage))
                return events

            events = await asyncio.to_thread(_do_stream)

            stop_reason = "end_turn"
            stream_usage = None
            for event_type, data in events:
                if event_type == "text":
                    streamed_text_parts.append(data)
                    yield data
                elif event_type == "tool_use":
                    tool_use_blocks.append(data)
                elif event_type == "stop_reason":
                    stop_reason = data
                elif event_type == "usage":
                    stream_usage = data

            # Log token usage from the stream
            if stream_usage:
                _log_token_usage(
                    layer=self._infer_layer(model),
                    model=model,
                    input_tokens=stream_usage.input_tokens,
                    output_tokens=stream_usage.output_tokens,
                    chat_id=chat_id,
                    cache_creation_tokens=getattr(stream_usage, "cache_creation_input_tokens", 0) or 0,
                    cache_read_tokens=getattr(stream_usage, "cache_read_input_tokens", 0) or 0,
                )

            # If tool calls present, execute them and get final response
            if tool_use_blocks or stop_reason == "tool_use":
                # Build assistant message with full content (text + tool_use blocks)
                # We need to reconstruct content blocks from streamed data
                # Use the tool_use blocks we captured from the final message
                assistant_content = []
                if streamed_text_parts:
                    assistant_content.append({"type": "text", "text": "".join(streamed_text_parts)})
                for block in tool_use_blocks:
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

                updated_messages = list(clean_messages) + [
                    {"role": "assistant", "content": assistant_content}
                ]

                # Execute tools
                tool_results = []
                for block in tool_use_blocks:
                    claude_tool_name = block.name
                    arguments = block.input or {}
                    mcp_name = _mcp_tool_name_from_claude(claude_tool_name)
                    logger.info(f"[MCP stream] tool_use: {claude_tool_name} → {mcp_name}({arguments})")

                    result = await _call_mcp_tool(mcp_name, arguments)

                    if tool_callback:
                        try:
                            tool_callback(mcp_name, arguments, result)
                        except Exception:
                            pass

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })

                updated_messages.append({"role": "user", "content": tool_results})

                # Second call — non-streaming final response
                final_text = await self._call_api_anthropic(
                    model=model,
                    system=system,
                    messages=updated_messages,
                    client=client,
                    use_tools=False,
                    chat_id=chat_id,
                )
                if final_text:
                    yield final_text

        except Exception as e:
            logger.error(f"Anthropic native streaming API call failed: {e}")
            raise

    # ------------------------------------------------------------------
    # Internal: OpenAI-compatible proxy (fallback)
    # ------------------------------------------------------------------

    async def _call_api_openai(
        self,
        model: str,
        system: str,
        messages: list[dict],
        client,
        use_tools: bool = True,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
        layer: str = "fast",
        chat_id: str = "",
    ) -> str:
        """OpenAI-compatible proxy call (fallback path)."""
        from openai import OpenAI

        api_messages = [{"role": "system", "content": system}]
        api_messages.extend(messages)

        claude_tools = get_claude_tools(chat_level=chat_level, layer=layer) if use_tools else []

        try:
            for _ in range(10):
                kwargs: dict = {
                    "model": model,
                    "max_tokens": self.max_tokens,
                    "messages": api_messages,
                }
                if claude_tools:
                    kwargs["tools"] = claude_tools

                # Tell the proxy to disable CLI tools for chat layers
                if not use_tools:
                    kwargs["extra_body"] = {"disable_tools": True}

                response = await asyncio.to_thread(
                    lambda kw=kwargs: client.chat.completions.create(**kw)
                )

                # Log token usage if available
                if hasattr(response, "usage") and response.usage:
                    u = response.usage
                    _log_token_usage(
                        layer=self._infer_layer(model),
                        model=model,
                        input_tokens=getattr(u, "prompt_tokens", 0) or 0,
                        output_tokens=getattr(u, "completion_tokens", 0) or 0,
                        chat_id=chat_id,
                    )

                choice = response.choices[0]
                finish_reason = choice.finish_reason
                tool_calls = getattr(choice.message, "tool_calls", None) or []

                if finish_reason == "tool_calls" or (tool_calls and finish_reason in ("stop", "tool_calls", None)):
                    api_messages.append(choice.message.model_dump(exclude_unset=True))

                    tool_results = []
                    for tc in tool_calls:
                        claude_tool_name = tc.function.name
                        try:
                            arguments = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError:
                            arguments = {}

                        mcp_name = _mcp_tool_name_from_claude(claude_tool_name)
                        logger.info(f"[MCP] tool_use: {claude_tool_name} → {mcp_name}({arguments})")

                        result = await _call_mcp_tool(mcp_name, arguments)

                        if tool_callback:
                            try:
                                tool_callback(mcp_name, arguments, result)
                            except Exception:
                                pass

                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result, default=str),
                        })

                    api_messages.extend(tool_results)
                    continue

                return choice.message.content or ""

            logger.warning("_call_api_openai: tool loop exceeded 10 rounds")
            return ""

        except Exception as e:
            logger.error(f"Claude proxy API call failed: {e}")
            raise

    async def _call_api_stream_openai(
        self,
        model: str,
        system: str,
        messages: list[dict],
        client,
        use_tools: bool = True,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
        layer: str = "fast",
    ) -> AsyncIterator[str]:
        """OpenAI-compatible streaming (fallback path)."""
        import asyncio
        import queue
        import threading

        api_messages = [{"role": "system", "content": system}]
        api_messages.extend(messages)

        claude_tools = get_claude_tools(chat_level=chat_level, layer=layer) if use_tools else []

        try:
            kwargs: dict = {
                "model": model,
                "max_tokens": self.max_tokens,
                "messages": api_messages,
                "stream": True,
            }
            if claude_tools:
                kwargs["tools"] = claude_tools

            # Tell the proxy to disable CLI tools for chat layers (no tools = converse only)
            if not use_tools:
                kwargs["extra_body"] = {"disable_tools": True}

            stream = client.chat.completions.create(**kwargs)

            token_queue: queue.Queue[str | None] = queue.Queue()
            streamed_tool_calls: list[dict] = []
            finish_reason_holder: list[str] = []
            content_text_holder: list[str] = []

            def _consume_stream():
                try:
                    for chunk in stream:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        finish_reason = chunk.choices[0].finish_reason

                        if delta.content:
                            content_text_holder.append(delta.content)
                            token_queue.put(delta.content)

                        if delta.tool_calls:
                            for tc_delta in delta.tool_calls:
                                idx = tc_delta.index
                                while len(streamed_tool_calls) <= idx:
                                    streamed_tool_calls.append({
                                        "id": None,
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    })
                                if tc_delta.id:
                                    streamed_tool_calls[idx]["id"] = tc_delta.id
                                if tc_delta.function:
                                    if tc_delta.function.name:
                                        streamed_tool_calls[idx]["function"]["name"] += tc_delta.function.name
                                    if tc_delta.function.arguments:
                                        streamed_tool_calls[idx]["function"]["arguments"] += tc_delta.function.arguments

                        if finish_reason:
                            finish_reason_holder.append(finish_reason)
                except Exception as e:
                    logger.error(f"Stream consumption error: {e}")
                finally:
                    token_queue.put(None)

            thread = threading.Thread(target=_consume_stream, daemon=True)
            thread.start()

            while True:
                token = await asyncio.to_thread(token_queue.get)
                if token is None:
                    break
                yield token

            finish_reason = finish_reason_holder[0] if finish_reason_holder else "stop"

            if finish_reason == "tool_calls" or streamed_tool_calls:
                assistant_msg: dict = {"role": "assistant", "content": "".join(content_text_holder) or None}
                if streamed_tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "id": tc["id"] or f"call_{i}",
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            },
                        }
                        for i, tc in enumerate(streamed_tool_calls)
                    ]
                api_messages.append(assistant_msg)

                tool_results = []
                for tc in streamed_tool_calls:
                    claude_tool_name = tc["function"]["name"]
                    try:
                        arguments = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        arguments = {}

                    mcp_name = _mcp_tool_name_from_claude(claude_tool_name)
                    logger.info(f"[MCP stream] tool_use: {claude_tool_name} → {mcp_name}({arguments})")

                    result = await _call_mcp_tool(mcp_name, arguments)

                    if tool_callback:
                        try:
                            tool_callback(mcp_name, arguments, result)
                        except Exception:
                            pass

                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"] or "call_0",
                        "content": json.dumps(result, default=str),
                    })

                api_messages.extend(tool_results)

                final_text = await self._call_api_openai(
                    model=model,
                    system=system,
                    messages=api_messages[1:],  # drop system (re-added inside)
                    client=client,
                    use_tools=False,
                )
                if final_text:
                    yield final_text

        except Exception as e:
            logger.error(f"Claude proxy streaming API call failed: {e}")
            raise

    # ------------------------------------------------------------------
    # Internal: Server-side tool handling (for proxy / generic providers)
    # ------------------------------------------------------------------

    def _load_tool_settings(self) -> dict:
        """Load tool settings from settings.json."""
        import os
        from pathlib import Path
        settings_path = Path(os.environ.get("VOXYFLOW_DIR", os.path.expanduser("~/voxyflow"))) / "settings.json"
        if not settings_path.exists():
            return {}
        try:
            with open(settings_path) as f:
                data = json.load(f)
            return data.get("tools", {})
        except Exception:
            return {}

    async def _call_api_server_tools(
        self,
        model: str,
        system: str,
        messages: list[dict],
        client,
        layer: str = "fast",
        chat_level: str = "general",
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_id: str = "",
    ) -> str:
        """Server-side tool execution loop for providers without native tool support.

        1. Inject tool definitions into system prompt
        2. Call LLM
        3. Parse <tool_call> blocks from response
        4. Execute tools
        5. Inject <tool_result> blocks as next user message
        6. Loop until no more tool calls or max_rounds reached
        """
        from app.tools.prompt_builder import get_prompt_builder
        from app.tools.response_parser import ToolResponseParser
        from app.tools.executor import get_executor

        parser = ToolResponseParser()
        executor = get_executor()

        tool_settings = self._load_tool_settings()
        max_rounds = tool_settings.get("max_rounds", 10)
        timeout_per_tool = tool_settings.get("timeout_per_tool_seconds", 30)
        warn_at_round = tool_settings.get("warn_at_round", max_rounds - 2)

        # Inject tool definitions into system prompt
        tool_prompt = get_prompt_builder().build_tool_prompt(layer, chat_level)
        augmented_system = system + "\n\n" + tool_prompt if tool_prompt else system
        # Inject /no_think for thinking models in worker layer too
        augmented_system = _inject_no_think(augmented_system, model)

        logger.info(f"[ServerTools] layer={layer}, chat_level={chat_level}, tool_prompt_len={len(tool_prompt) if tool_prompt else 0}")

        api_messages = [{"role": "system", "content": augmented_system}]
        api_messages.extend(messages)

        response_text = ""

        for round_num in range(max_rounds):
            # Inject warning near the end
            if round_num == warn_at_round:
                api_messages.append({
                    "role": "user",
                    "content": "[SYSTEM] You are running low on tool rounds. Wrap up now.",
                })

            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        lambda msgs=list(api_messages): client.chat.completions.create(
                            model=model,
                            max_tokens=self.max_tokens,
                            messages=msgs,
                        )
                    ),
                    timeout=90.0,  # 90s max per LLM call in worker
                )
            except asyncio.TimeoutError:
                logger.warning(f"[ServerTools] Round {round_num + 1}: LLM call timed out after 90s")
                return response_text or ""

            msg = response.choices[0].message
            response_text = msg.content or ""
            finish_reason = response.choices[0].finish_reason

            # Log token usage if available
            if hasattr(response, "usage") and response.usage:
                u = response.usage
                _log_token_usage(
                    layer=self._infer_layer(model),
                    model=model,
                    input_tokens=getattr(u, "prompt_tokens", 0) or 0,
                    output_tokens=getattr(u, "completion_tokens", 0) or 0,
                    chat_id=chat_id,
                )

            # Handle native OpenAI tool_calls (Ollama/Qwen3 emit these instead of XML)
            native_tool_calls = getattr(msg, "tool_calls", None) or []
            if native_tool_calls and (finish_reason in ("tool_calls", "stop") or not response_text):
                logger.info(f"[ServerTools] Round {round_num + 1}: native OpenAI tool_calls={len(native_tool_calls)}")
                # Convert native tool calls → ToolCall objects via XML round-trip so executor can handle them
                xml_blocks = []
                for tc in native_tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    args_xml = "\n".join(f"<{k}>{v}</{k}>" for k, v in args.items())
                    xml_blocks.append(f'<tool_call>\n<name>{tc.function.name}</name>\n<parameters>\n{args_xml}\n</parameters>\n</tool_call>')
                synthetic_text = "\n\n".join(xml_blocks)
                text_content, tool_calls = parser.parse(synthetic_text)
                if tool_calls:
                    results = await executor.execute_batch(tool_calls, timeout=timeout_per_tool)
                    if tool_callback:
                        for _tc, _result in zip(tool_calls, results):
                            try:
                                ret = tool_callback(_tc.name, _tc.arguments, _result)
                                if asyncio.iscoroutine(ret) or asyncio.isfuture(ret):
                                    await ret
                            except Exception as e:
                                logger.warning(f"[ServerTools] tool_callback error: {e}")
                    # Build tool result messages in OpenAI format for native tool_calls path
                    api_messages.append(msg.model_dump(exclude_unset=True))
                    for tc, result in zip(native_tool_calls, results):
                        api_messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result, default=str, ensure_ascii=False),
                        })
                    logger.info(f"[ServerTools] Round {round_num + 1}: {len(tool_calls)} native tool calls executed")
                    continue

            # Parse XML tool calls from text content (Claude/proxy path)
            text_content, tool_calls = parser.parse(response_text)

            logger.info(f"[ServerTools] Round {round_num + 1}: response_len={len(response_text)}, tool_calls={len(tool_calls)}, has_tool_call_tag={'<tool_call>' in response_text}")
            if not tool_calls and '<tool_call>' in response_text:
                logger.warning(f"[ServerTools] has_tool_call but parse failed. Full response: {response_text!r}")
                # NOTE: This path is only reachable via the OpenAI-compat proxy fallback.
                # Workers now always use native Anthropic SDK (tool_use blocks), so this
                # guard is mainly for the fast layer's <tool_call> XML fallback path.
                # The <tool_call> block was likely truncated mid-JSON by token limit.
                # Do NOT return the raw response (it contains a malformed JSON blob).
                # Return a clean error message instead so it doesn't pollute the chat.
                return "[Worker: tool call was truncated by token limit and could not be executed. Please retry with a shorter output.]"
            if not tool_calls and '<tool_call>' not in response_text:
                logger.info(f"[ServerTools] No tool calls found. Response tail: {response_text[-200:]!r}")

            if not tool_calls:
                return _strip_think_tags(response_text) if _is_thinking_model(model) else response_text

            # Execute tools
            results = await executor.execute_batch(tool_calls, timeout=timeout_per_tool)

            # Fire callbacks (supports both sync and async callbacks)
            if tool_callback:
                for tc, result in zip(tool_calls, results):
                    try:
                        ret = tool_callback(tc.name, tc.arguments, result)
                        if asyncio.iscoroutine(ret) or asyncio.isfuture(ret):
                            await ret
                    except Exception as e:
                        logger.warning(f"[ServerTools] tool_callback error: {e}")

            # Build result injection
            result_blocks = []
            for tc, result in zip(tool_calls, results):
                result_json = json.dumps(result, default=str, ensure_ascii=False)
                result_blocks.append(
                    f'<tool_result name="{tc.name}">\n{result_json}\n</tool_result>'
                )

            # Append assistant response + tool results to conversation
            api_messages.append({"role": "assistant", "content": response_text})
            api_messages.append({"role": "user", "content": "\n\n".join(result_blocks)})

            logger.info(f"[ServerTools] Round {round_num + 1}: {len(tool_calls)} tool calls executed")

        logger.warning("_call_api_server_tools: tool loop exceeded max rounds")
        return response_text

    async def _call_api_stream_server_tools(
        self,
        model: str,
        system: str,
        messages: list[dict],
        client,
        layer: str = "fast",
        chat_level: str = "general",
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
    ) -> AsyncIterator[str]:
        """Server-side tool handling with streaming.

        Streams the first response, then if tool calls are detected,
        executes them and does a non-streaming continuation loop.
        """
        import queue
        import threading

        from app.tools.prompt_builder import get_prompt_builder
        from app.tools.response_parser import ToolResponseParser
        from app.tools.executor import get_executor

        parser = ToolResponseParser()
        executor = get_executor()

        tool_settings = self._load_tool_settings()
        max_rounds = tool_settings.get("max_rounds", 10)
        timeout_per_tool = tool_settings.get("timeout_per_tool_seconds", 30)
        warn_at_round = tool_settings.get("warn_at_round", max_rounds - 2)

        # Inject tool definitions into system prompt
        tool_prompt = get_prompt_builder().build_tool_prompt(layer, chat_level)
        augmented_system = system + "\n\n" + tool_prompt if tool_prompt else system

        api_messages = [{"role": "system", "content": augmented_system}]
        api_messages.extend(messages)

        # Stream the first response
        token_queue: queue.Queue[str | None] = queue.Queue()
        content_parts: list[str] = []

        def _consume_stream():
            try:
                stream = client.chat.completions.create(
                    model=model,
                    max_tokens=self.max_tokens,
                    messages=list(api_messages),
                    stream=True,
                )
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    if delta.content:
                        content_parts.append(delta.content)
                        token_queue.put(delta.content)
            except Exception as e:
                logger.error(f"Server-tools stream error: {e}")
            finally:
                token_queue.put(None)

        thread = threading.Thread(target=_consume_stream, daemon=True)
        thread.start()

        while True:
            token = await asyncio.to_thread(token_queue.get)
            if token is None:
                break
            yield token

        # Check streamed response for tool calls
        full_response = "".join(content_parts)
        text_content, tool_calls = parser.parse(full_response)

        if not tool_calls:
            return  # No tools, streaming is complete

        # Execute tool calls from the streamed response
        results = await executor.execute_batch(tool_calls, timeout=timeout_per_tool)

        if tool_callback:
            for tc, result in zip(tool_calls, results):
                try:
                    tool_callback(tc.name, tc.arguments, result)
                except Exception:
                    pass

        # Build result injection
        result_blocks = []
        for tc, result in zip(tool_calls, results):
            result_json = json.dumps(result, default=str, ensure_ascii=False)
            result_blocks.append(
                f'<tool_result name="{tc.name}">\n{result_json}\n</tool_result>'
            )

        api_messages.append({"role": "assistant", "content": full_response})
        api_messages.append({"role": "user", "content": "\n\n".join(result_blocks)})
        logger.info(f"[ServerTools stream] Round 1: {len(tool_calls)} tool calls executed")

        # Continue with non-streaming tool loop for remaining rounds
        for round_num in range(1, max_rounds):
            if round_num == warn_at_round:
                api_messages.append({
                    "role": "user",
                    "content": "[SYSTEM] You are running low on tool rounds. Wrap up now.",
                })

            response = await asyncio.to_thread(
                lambda msgs=list(api_messages): client.chat.completions.create(
                    model=model,
                    max_tokens=self.max_tokens,
                    messages=msgs,
                )
            )

            response_text = response.choices[0].message.content or ""
            text_content, tool_calls = parser.parse(response_text)

            if not tool_calls:
                # Final text response — yield it
                if response_text:
                    yield "\n\n" + response_text
                return

            results = await executor.execute_batch(tool_calls, timeout=timeout_per_tool)

            if tool_callback:
                for tc, result in zip(tool_calls, results):
                    try:
                        tool_callback(tc.name, tc.arguments, result)
                    except Exception:
                        pass

            result_blocks = []
            for tc, result in zip(tool_calls, results):
                result_json = json.dumps(result, default=str, ensure_ascii=False)
                result_blocks.append(
                    f'<tool_result name="{tc.name}">\n{result_json}\n</tool_result>'
                )

            api_messages.append({"role": "assistant", "content": response_text})
            api_messages.append({"role": "user", "content": "\n\n".join(result_blocks)})
            logger.info(f"[ServerTools stream] Round {round_num + 1}: {len(tool_calls)} tool calls executed")

        logger.warning("_call_api_stream_server_tools: tool loop exceeded max rounds")

    # ------------------------------------------------------------------
    # Dispatcher: routes to native or fallback based on client_type
    # ------------------------------------------------------------------

    def _should_use_server_tools(self, client_type: str) -> bool:
        """Determine if server-side tool handling should be used.

        Returns True for OpenAI-compatible clients (proxy), False for native Anthropic.
        Can be overridden via settings.json tool_mode.
        """
        tool_settings = self._load_tool_settings()
        tool_mode = tool_settings.get("tool_mode", "auto")

        if tool_mode == "native":
            return False
        elif tool_mode == "server":
            return True
        else:  # "auto"
            return client_type == "openai"

    async def _call_api(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        client=None,
        client_type: str = "anthropic",
        use_tools: bool = True,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
        layer: str = "fast",
        chat_id: str = "",
        cancel_event: Optional[asyncio.Event] = None,
        message_queue: Optional[asyncio.Queue] = None,
    ) -> str:
        """Dispatch to native Anthropic SDK, OpenAI-compat, or server-side tools."""
        api_client = client or self.fast_client
        ct = client_type if client is not None else self.fast_client_type

        if ct == "anthropic":
            return await self._call_api_anthropic(
                model=model, system=system, messages=messages, client=api_client,
                use_tools=use_tools, tool_callback=tool_callback, chat_level=chat_level,
                layer=layer, chat_id=chat_id, cancel_event=cancel_event,
                message_queue=message_queue, client_type=ct,
            )
        # Non-Anthropic paths need a plain string for system
        flat_system = _flatten_system(system)
        if use_tools and self._should_use_server_tools(ct):
            return await self._call_api_server_tools(
                model=model, system=flat_system, messages=messages, client=api_client,
                layer=layer, chat_level=chat_level, tool_callback=tool_callback,
                chat_id=chat_id,
            )
        else:
            return await self._call_api_openai(
                model=model, system=flat_system, messages=messages, client=api_client,
                use_tools=use_tools, tool_callback=tool_callback, chat_level=chat_level,
                layer=layer, chat_id=chat_id,
            )

    async def _call_api_stream(
        self,
        model: str,
        system: str | list[dict],
        messages: list[dict],
        client=None,
        client_type: str = "anthropic",
        use_tools: bool = True,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
        layer: str = "fast",
        chat_id: str = "",
    ) -> AsyncIterator[str]:
        """Dispatch streaming to native Anthropic SDK, OpenAI-compat, or server-side tools."""
        api_client = client or self.fast_client
        ct = client_type if client is not None else self.fast_client_type

        if ct == "anthropic":
            async for token in self._call_api_stream_anthropic(
                model=model, system=system, messages=messages, client=api_client,
                use_tools=use_tools, tool_callback=tool_callback, chat_level=chat_level,
                layer=layer, chat_id=chat_id,
            ):
                yield token
        else:
            # Non-Anthropic paths need a plain string for system
            flat_system = _flatten_system(system)
            if use_tools and self._should_use_server_tools(ct):
                async for token in self._call_api_stream_server_tools(
                    model=model, system=flat_system, messages=messages, client=api_client,
                    layer=layer, chat_level=chat_level, tool_callback=tool_callback,
                ):
                    yield token
            else:
                async for token in self._call_api_stream_openai(
                    model=model, system=flat_system, messages=messages, client=api_client,
                    use_tools=use_tools, tool_callback=tool_callback, chat_level=chat_level,
                    layer=layer,
                ):
                    yield token
