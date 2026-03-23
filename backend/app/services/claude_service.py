"""Claude API integration — native Anthropic SDK (primary) with OpenAI-compatible proxy fallback."""

import asyncio
import json
import logging
from collections import OrderedDict, defaultdict
from typing import AsyncIterator, Callable, Optional, Union

import httpx

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
    "claude-haiku-4":   "claude-haiku-4-20250514",
    "claude-sonnet-4":  "claude-sonnet-4-20250514",
    "claude-opus-4":    "claude-opus-4-20250514",
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
    """Create a native Anthropic SDK client."""
    import anthropic
    kwargs = {"api_key": api_key} if api_key else {}
    if api_base:
        kwargs["base_url"] = api_base
    return anthropic.Anthropic(**kwargs)


def _make_openai_client(provider_url: str, api_key: str):
    """Create an OpenAI-compatible client (proxy fallback)."""
    from openai import OpenAI
    return OpenAI(
        base_url=provider_url or "http://localhost:3457/v1",
        api_key=api_key if api_key else "not-needed",
    )


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
                fast_cfg.get("api_key", ""),
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
                deep_cfg.get("api_key", ""),
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
                haiku_cfg.get("api_key", ""),
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
                analyzer_cfg.get("api_key", ""),
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
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.fast_context_messages:]

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=False,
            include_daily=True,
            query=user_message,
        )
        system_prompt = self.personality.build_fast_prompt(
            memory_context=memory_context,
            chat_level=chat_level,
            project=project_context,
            card=card_context,
        )

        if project_id:
            try:
                rag_context = await get_rag_service().build_rag_context(project_id, user_message)
                if rag_context:
                    system_prompt += "\n\n## Relevant Context from Project Knowledge Base\n" + rag_context
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_fast): {e}")

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
    ) -> AsyncIterator[str]:
        """Layer 1 (streaming): Yield tokens as they arrive from the fast layer.

        Native Anthropic path: uses delegate_action tool_use for dispatching.
        Proxy path: zero tools, relies on <delegate> XML blocks in text.
        """
        use_native_delegate = self.fast_client_type == "anthropic"

        await self._append_and_persist_async(chat_id, "user", user_message, model="fast")
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.fast_context_messages:]

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=False,
            include_daily=True,
            query=user_message,
        )
        system_prompt = self.personality.build_fast_prompt(
            memory_context=memory_context,
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            project_names=project_names,
            native_tools=use_native_delegate,
        )

        if project_id:
            try:
                rag_context = await get_rag_service().build_rag_context(project_id, user_message)
                if rag_context:
                    system_prompt += "\n\n## Relevant Context from Project Knowledge Base\n" + rag_context
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_fast_stream): {e}")

        # Inject identity priming exchange at the start of conversations.
        primed_messages = list(recent)
        is_auto_greeting = "greet" in user_message.lower() and "naturally" in user_message.lower()
        if len(history) <= 4 and not is_auto_greeting:
            if use_native_delegate:
                priming_assistant = (
                    "I'm Voxy, running inside Voxyflow's chat layer. I'm a dispatcher — "
                    "I converse with you directly and delegate all actions to background workers "
                    "using the delegate_action tool. I never execute actions myself. When you ask "
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
    ) -> AsyncIterator[str]:
        """Deep layer (streaming): Yield tokens from the deep model directly to chat.

        Native Anthropic path: uses delegate_action tool_use for dispatching.
        Proxy path: zero tools, relies on <delegate> XML blocks in text.
        """
        use_native_delegate = self.deep_client_type == "anthropic"

        await self._append_and_persist_async(chat_id, "user", user_message, model="deep")
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.deep_context_messages:]

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=True,
            include_daily=True,
            query=user_message,
        )
        system_prompt = self.personality.build_deep_prompt(
            memory_context=memory_context,
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            project_names=project_names,
            is_chat_responder=True,
            native_tools=use_native_delegate,
        )

        if project_id:
            try:
                rag_context = await get_rag_service().build_rag_context(project_id, user_message)
                if rag_context:
                    system_prompt += "\n\n## Relevant Context from Project Knowledge Base\n" + rag_context
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_deep_stream): {e}")

        # Identity priming for deep chat layer (same as fast — see chat_fast_stream)
        primed_messages = list(recent)
        is_auto_greeting = "greet" in user_message.lower() and "naturally" in user_message.lower()
        if len(history) <= 4 and not is_auto_greeting:
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

        await self._append_and_persist_async(chat_id, "assistant", full_response, model="deep")

    async def chat_deep_supervisor(
        self,
        chat_id: str,
        user_message: str,
        fast_response: str = "",
        project_name: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
        project_id: Optional[str] = None,
    ) -> dict:
        """Layer 2: Deep supervisor — decides whether to enrich or correct the fast layer's response."""
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.deep_context_messages:]

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=True,
            include_daily=True,
            query=user_message,
        )

        supervisor_base = (
            "You are the deep-thinking supervisor layer of Voxyflow.\n"
            "The user sent a message, and the fast layer already responded.\n"
            "You can see the fast layer's full response below.\n"
            "Your job: decide if the fast response needs improvement.\n\n"
            "Decide one of:\n"
            '- "enrich": Add valuable context, deeper insight, or important nuance the fast layer missed\n'
            '- "correct": Fix a factual error or significant oversight in the fast layer\'s response\n'
            '- "none": The fast layer\'s response was fine, no need to add anything\n\n'
            "BIAS STRONGLY TOWARD 'none'.\n"
            "- If the conversation is casual → \"none\"\n"
            "- If the question is simple → \"none\"\n"
            "- If the fast layer answered reasonably → \"none\"\n"
            "- Simple greetings, acknowledgments, small talk → ALWAYS \"none\"\n"
            "- Only speak up if you have genuinely valuable insight the fast layer missed\n"
            "- Think: \"Would a thoughtful person interrupt to add this?\" If no → \"none\"\n\n"
            "If action is 'enrich' or 'correct', write a natural follow-up message.\n"
            "Make it sound like the same person thinking deeper:\n"
            '- "Actually, now that I think about it..."\n'
            '- "Oh wait, I should also mention..."\n'
            '- "Hmm, let me nuance that..."\n\n'
            "Respond ONLY with valid JSON (no markdown, no code blocks):\n"
            '{"action": "enrich"|"correct"|"none", "content": "..."}\n'
            'If "none", content can be empty string.\n'
            "Respond in the same language the user used."
        )

        system_prompt = self.personality.build_system_prompt(
            base_prompt=supervisor_base,
            include_memory_context=memory_context,
        )

        if project_id:
            try:
                rag_context = await get_rag_service().build_rag_context(project_id, user_message)
                if rag_context:
                    system_prompt += "\n\n## Relevant Context from Project Knowledge Base\n" + rag_context
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_deep_supervisor): {e}")

        eval_messages = [*recent, {"role": "user", "content": user_message}]
        if fast_response:
            eval_messages.append(
                {"role": "assistant", "content": f"[Fast layer's response]: {fast_response}"}
            )
            eval_messages.append(
                {"role": "user", "content": "Evaluate the fast layer's response above. Should you enrich, correct, or stay silent?"}
            )

        try:
            response_text = await self._call_api(
                model=self.deep_model,
                system=system_prompt,
                messages=eval_messages,
                client=self.deep_client,
                client_type=self.deep_client_type,
                use_tools=True,
                layer="deep",
                chat_level=chat_level,
            )
            result = json.loads(response_text.strip())
            if result.get("action") in ("enrich", "correct", "none"):
                return result
            return {"action": "none", "content": ""}
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Deep supervisor failed to parse response: {e}")
            return {"action": "none", "content": ""}

    async def chat_deep_executor(
        self,
        chat_id: str,
        user_message: str,
        project_name: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
        project_id: Optional[str] = None,
    ) -> str:
        """Execute a delegated action from the Fast layer using tools.

        Unlike chat_deep_supervisor (which evaluates), this method is designed
        to carry out concrete actions (create cards, update cards, etc.) via MCP tools.
        Returns a plain-text summary of what was done.
        """
        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=False,
            include_daily=False,
            query=user_message,
        )

        executor_base = (
            "You are the action executor layer of Voxyflow.\n"
            "The fast layer identified an action that needs to be performed.\n"
            "Your job: execute it using your available tools, then confirm what you did.\n\n"
            "Rules:\n"
            "- Execute the requested action immediately using the appropriate tool\n"
            "- Do NOT ask for confirmation — the user already confirmed via the fast layer\n"
            "- After executing, respond with a brief summary of what you did\n"
            "- If the action fails, explain why\n"
            "- Respond in the same language the user used\n\n"
            "## Research & Content Quality Rules (CRITICAL)\n"
            "When filling cards with researched content (deals, lists, recommendations, etc.):\n"
            "- ALWAYS include source URLs for every fact, price, deal, or recommendation\n"
            "- ALWAYS include exact prices (not ranges) when found\n"
            "- ALWAYS name the specific site/store where the deal was found\n"
            "- Format: 'Item name — $X.XX at StoreName (url)'\n"
            "- If you cannot find a real source URL, explicitly say 'Source not verified'\n"
            "- Never fabricate URLs or prices — if uncertain, state it clearly\n"
            "- Include the date/time of research so the user knows how fresh the info is\n"
        )

        system_prompt = self.personality.build_system_prompt(
            base_prompt=executor_base,
            include_memory_context=memory_context,
        )

        if project_id:
            try:
                rag_context = await get_rag_service().build_rag_context(project_id, user_message)
                if rag_context:
                    system_prompt += "\n\n## Relevant Context from Project Knowledge Base\n" + rag_context
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_deep_executor): {e}")

        messages = [{"role": "user", "content": user_message}]

        response_text = await self._call_api(
            model=self.deep_model,
            system=system_prompt,
            messages=messages,
            client=self.deep_client,
            client_type=self.deep_client_type,
            use_tools=True,
            layer="deep",
            chat_level=chat_level,
        )

        return response_text or ""

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

        # Build worker-specific prompt
        system_prompt = self.personality.build_worker_prompt(
            model=model,
            chat_level=chat_level,
            project=project_context,
            card=card_context,
        )

        if project_id:
            try:
                rag_context = await get_rag_service().build_rag_context(project_id, prompt)
                if rag_context:
                    system_prompt += "\n\n## Relevant Context from Project Knowledge Base\n" + rag_context
            except Exception as e:
                logger.warning(f"RAG context injection failed (execute_worker_task): {e}")

        return await self._call_api(
            model=model_name,
            system=system_prompt,
            messages=[{"role": "user", "content": prompt}],
            client=client,
            client_type=client_type,
            use_tools=True,
            tool_callback=tool_callback,
            layer=layer,
            chat_level=chat_level,
        )

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
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.deep_context_messages:]

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=True,
            include_daily=True,
            query=user_message,
        )
        system_prompt = self.personality.build_deep_prompt(memory_context=memory_context)

        if project_id:
            try:
                rag_context = await get_rag_service().build_rag_context(project_id, user_message)
                if rag_context:
                    system_prompt += "\n\n## Relevant Context from Project Knowledge Base\n" + rag_context
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_deep): {e}")

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

    async def chat_with_agent(
        self,
        chat_id: str,
        user_message: str,
        agent_type: AgentType,
        task_context: str = "",
        project_name: Optional[str] = None,
    ) -> str:
        """Call Claude with a specialized agent persona."""
        await self._append_and_persist_async(chat_id, "user", user_message, model="deep")
        history = self._get_history(chat_id)

        settings = get_settings()
        recent = history[-settings.deep_context_messages:]

        agent_persona_prompt = get_persona_prompt(agent_type)
        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            include_long_term=True,
            include_daily=True,
            query=user_message,
        )
        system_prompt = self.personality.build_agent_prompt(
            agent_persona=agent_persona_prompt,
            task_context=task_context or "Complete the task described in the conversation.",
            memory_context=memory_context,
        )

        response_text = await self._call_api(
            model=self.deep_model,
            system=system_prompt,
            messages=recent,
            client=self.deep_client,
            client_type=self.deep_client_type,
            layer="deep",
        )

        await self._append_and_persist_async(chat_id, "assistant", response_text, model="deep")
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
        system: str,
        messages: list[dict],
        client,
        use_tools: bool = True,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
        layer: str = "fast",
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

        kwargs = {
            "model": model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": clean_messages,
        }
        if claude_tools:
            kwargs["tools"] = claude_tools

        try:
            # Agentic tool-use loop (max 10 rounds)
            for _ in range(10):
                response = await asyncio.to_thread(
                    lambda kw=kwargs: client.messages.create(**kw)
                )

                stop_reason = response.stop_reason  # "end_turn" | "tool_use" | "max_tokens"

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
                                tool_callback(mcp_name, arguments, result)
                            except Exception:
                                pass

                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result, default=str),
                        })

                    # Append tool results as a user message
                    kwargs["messages"] = list(kwargs["messages"]) + [
                        {"role": "user", "content": tool_results}
                    ]
                    continue  # Loop back for Claude's next response

                # No tool calls — collect text from content blocks
                text_parts = [b.text for b in response.content if b.type == "text"]
                return "".join(text_parts)

            logger.warning("_call_api_anthropic: tool loop exceeded 10 rounds")
            return ""

        except Exception as e:
            logger.error(f"Anthropic native API call failed: {e}")
            raise

    async def _call_api_stream_with_delegate(
        self,
        model: str,
        system: str,
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
            "tools": [DELEGATE_ACTION_TOOL],
        }

        try:
            # Collect streamed content and tool_use blocks
            streamed_text_parts: list[str] = []
            tool_use_blocks: list = []

            def _do_stream():
                events = []
                with client.messages.stream(**kwargs) as stream:
                    for text in stream.text_stream:
                        events.append(("text", text))
                    final_msg = stream.get_final_message()
                    for block in final_msg.content:
                        if block.type == "tool_use":
                            events.append(("tool_use", block))
                    events.append(("stop_reason", final_msg.stop_reason))
                return events

            events = await asyncio.to_thread(_do_stream)

            stop_reason = "end_turn"
            for event_type, data in events:
                if event_type == "text":
                    streamed_text_parts.append(data)
                    yield data
                elif event_type == "tool_use":
                    tool_use_blocks.append(data)
                elif event_type == "stop_reason":
                    stop_reason = data

            if not tool_use_blocks:
                # No delegates — done
                return

            # Collect delegate tool_use blocks (don't execute — orchestrator handles them)
            delegates = []
            for block in tool_use_blocks:
                if block.name == "delegate_action":
                    delegates.append(block.input or {})
                    logger.info(
                        f"[NativeDelegate] Collected delegate_action: "
                        f"action={block.input.get('action')}, summary={block.input.get('summary', '')!r}"
                    )
                else:
                    logger.warning(f"[NativeDelegate] Unexpected tool_use: {block.name} — ignoring")

            if delegates:
                self._pending_delegates[chat_id] = delegates

            # If Claude stopped for tool_use, we need to send back a synthetic result
            # so it can finish its response (it may want to say something after delegating).
            if stop_reason == "tool_use":
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

        except Exception as e:
            logger.error(f"Anthropic delegate streaming call failed: {e}")
            raise

    async def _call_api_stream_anthropic(
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
                return events

            events = await asyncio.to_thread(_do_stream)

            stop_reason = "end_turn"
            for event_type, data in events:
                if event_type == "text":
                    streamed_text_parts.append(data)
                    yield data
                elif event_type == "tool_use":
                    tool_use_blocks.append(data)
                elif event_type == "stop_reason":
                    stop_reason = data

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

            response = await asyncio.to_thread(
                lambda msgs=list(api_messages): client.chat.completions.create(
                    model=model,
                    max_tokens=self.max_tokens,
                    messages=msgs,
                )
            )

            response_text = response.choices[0].message.content or ""

            # Parse tool calls
            text_content, tool_calls = parser.parse(response_text)

            logger.info(f"[ServerTools] Round {round_num + 1}: response_len={len(response_text)}, tool_calls={len(tool_calls)}, has_tool_call_tag={'<tool_call>' in response_text}")
            if not tool_calls and '<tool_call>' not in response_text:
                logger.info(f"[ServerTools] No tool calls found. Response tail: {response_text[-200:]!r}")

            if not tool_calls:
                return response_text

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
        system: str,
        messages: list[dict],
        client=None,
        client_type: str = "anthropic",
        use_tools: bool = True,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
        layer: str = "fast",
    ) -> str:
        """Dispatch to native Anthropic SDK, OpenAI-compat, or server-side tools."""
        api_client = client or self.fast_client
        ct = client_type if client is not None else self.fast_client_type

        if ct == "anthropic":
            return await self._call_api_anthropic(
                model=model, system=system, messages=messages, client=api_client,
                use_tools=use_tools, tool_callback=tool_callback, chat_level=chat_level,
                layer=layer,
            )
        elif use_tools and self._should_use_server_tools(ct):
            return await self._call_api_server_tools(
                model=model, system=system, messages=messages, client=api_client,
                layer=layer, chat_level=chat_level, tool_callback=tool_callback,
            )
        else:
            return await self._call_api_openai(
                model=model, system=system, messages=messages, client=api_client,
                use_tools=use_tools, tool_callback=tool_callback, chat_level=chat_level,
                layer=layer,
            )

    async def _call_api_stream(
        self,
        model: str,
        system: str,
        messages: list[dict],
        client=None,
        client_type: str = "anthropic",
        use_tools: bool = True,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        chat_level: str = "general",
        layer: str = "fast",
    ) -> AsyncIterator[str]:
        """Dispatch streaming to native Anthropic SDK, OpenAI-compat, or server-side tools."""
        api_client = client or self.fast_client
        ct = client_type if client is not None else self.fast_client_type

        if ct == "anthropic":
            async for token in self._call_api_stream_anthropic(
                model=model, system=system, messages=messages, client=api_client,
                use_tools=use_tools, tool_callback=tool_callback, chat_level=chat_level,
                layer=layer,
            ):
                yield token
        elif use_tools and self._should_use_server_tools(ct):
            async for token in self._call_api_stream_server_tools(
                model=model, system=system, messages=messages, client=api_client,
                layer=layer, chat_level=chat_level, tool_callback=tool_callback,
            ):
                yield token
        else:
            async for token in self._call_api_stream_openai(
                model=model, system=system, messages=messages, client=api_client,
                use_tools=use_tools, tool_callback=tool_callback, chat_level=chat_level,
                layer=layer,
            ):
                yield token
