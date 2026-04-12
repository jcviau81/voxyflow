"""Claude API integration — native Anthropic SDK (primary) with OpenAI-compatible proxy fallback."""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from app.config import get_settings, VOXYFLOW_WORKSPACE_DIR
from app.services.llm.client_factory import (
    _make_anthropic_client,
    _make_async_anthropic_client,
    _make_openai_client,
)
from app.services.llm.cli_backend import ClaudeCliBackend
from app.services.llm.model_utils import (
    _LRUDict,
    _MODEL_MAP,
    _resolve_model,
    _strip_think_tags,
    _is_thinking_model,
    _inject_no_think,
)
from app.services.llm.api_caller import ApiCallerMixin
from app.services.personality_service import get_personality_service
from app.services.memory_service import get_memory_service
from app.services.agent_personas import AgentType, get_persona_prompt
from app.services.session_store import session_store
from app.services.rag_service import get_rag_service
from app.tools.registry import (
    TOOLS_READ_ONLY, TOOLS_VOXYFLOW_CRUD, TOOLS_FULL, _LAYER_TOOL_SETS,
)

logger = logging.getLogger(__name__)


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

# _LRUDict, _MODEL_MAP, _resolve_model → app.services.llm.model_utils

# DELEGATE_ACTION_TOOL, INLINE_TOOLS, _INLINE_TOOL_NAMES, _execute_inline_tool,
# get_claude_tools, _mcp_tool_name_from_claude, _call_mcp_tool,
# _load_model_overrides, _get_api_key_from_settings → app.services.llm.tool_defs
from app.services.llm.tool_defs import (
    DELEGATE_ACTION_TOOL,
    INLINE_TOOLS,
    _INLINE_TOOL_NAMES,
    _execute_inline_tool,
    get_claude_tools,
    _mcp_tool_name_from_claude,
    _call_mcp_tool,
    _load_model_overrides,
    _get_api_key_from_settings,
)


# ---------------------------------------------------------------------------
# ClaudeService
# ---------------------------------------------------------------------------

class ClaudeService(ApiCallerMixin):
    """
    Handles Claude API calls for both conversation layers.

    Three backend paths (in precedence order):
      1. CLI subprocess: claude_use_cli=True  → spawns `claude -p` (Max subscription)
      2. Native Anthropic SDK: claude_use_native=True → direct API calls
      3. OpenAI-compatible proxy: fallback at localhost:3457

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
        self.use_cli = config.claude_use_cli

        # CLI backend (shared across all layers when use_cli=True)
        self._cli_backend = ClaudeCliBackend(config.claude_cli_path) if self.use_cli else None

        # Load overrides from settings.json
        overrides = _load_model_overrides()

        # Resolve API key (keyring/env already merged into config.claude_api_key)
        default_api_key = config.claude_api_key

        # --- Fast layer ---
        fast_cfg = overrides.get("fast", {})
        fast_model_raw = fast_cfg.get("model", "").strip()
        self.fast_model = _resolve_model(fast_model_raw or config.claude_sonnet_model)
        fast_key = _get_api_key_from_settings(fast_cfg) or default_api_key
        if self.use_cli:
            self.fast_client = None
            self.fast_client_type = "cli"
        elif self.use_native and fast_key:
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
        if self.use_cli:
            self.deep_client = None
            self.deep_client_type = "cli"
        elif self.use_native and deep_key:
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
        if self.use_cli:
            self.haiku_client = None
            self.haiku_client_type = "cli"
        elif self.use_native and haiku_key:
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
        if self.use_cli:
            self.analyzer_client = None
            self.analyzer_client_type = "cli"
        elif self.use_native and analyzer_key:
            self.analyzer_client = _make_anthropic_client(analyzer_key, analyzer_cfg.get("provider_url", config.claude_api_base))
            self.analyzer_client_type = "anthropic"
        else:
            self.analyzer_client = _make_openai_client(
                analyzer_cfg.get("provider_url", config.claude_proxy_url),
                analyzer_cfg.get("api_key") or default_api_key,
            )
            self.analyzer_client_type = "openai"

        # Legacy single client (backward compat, always OpenAI-compat proxy)
        if not self.use_cli:
            from openai import OpenAI as _OAI
            self.client = _OAI(base_url=config.claude_proxy_url, api_key=config.claude_api_key or "not-needed")
        else:
            self.client = None

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
            f"ClaudeService initialized — cli={self.use_cli} native={self.use_native} | "
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

            if self.use_cli:
                client = None
                client_type = "cli"
            elif self.use_native and key and ("claude" in model.lower() or "anthropic" in purl.lower()):
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
        card_id = card_context.get("id", "") if card_context else ""
        await self._append_and_persist_async(chat_id, "user", user_message, model="fast")

        recent = await self._get_windowed_history(chat_id)

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            project_id=project_id,
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
            project_id=project_id or "", card_id=card_id,
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
        session_id: str = "",
    ) -> AsyncIterator[str]:
        """Layer 1 (streaming): Yield tokens as they arrive from the fast layer.

        Native Anthropic path: uses delegate_action tool_use for dispatching.
        Proxy path: zero tools, relies on <delegate> XML blocks in text.
        CLI+MCP path: inline tools via MCP + <delegate> XML blocks for complex tasks.
        """
        use_native_delegate = self.fast_client_type == "anthropic"
        use_cli_mcp = self.fast_client_type == "cli"
        card_id = card_context.get("id", "") if card_context else ""

        await self._append_and_persist_async(chat_id, "user", user_message, model="fast")
        full_history = self._get_history(chat_id)  # full history for conversation-age checks
        recent = await self._get_windowed_history(chat_id)  # windowed messages for the API

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            project_id=project_id,
            include_long_term=False,
            include_daily=True,
            query=user_message,
        )
        # Determine tool mode for personality prompt
        native_tools_mode = "cli_mcp" if use_cli_mcp else use_native_delegate
        # Static base prompt — personality + dispatcher + tools only (cacheable)
        base_prompt = self.personality.build_fast_prompt(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            native_tools=native_tools_mode,
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

        # Tell the model what it actually is
        dynamic_parts.append(
            f"IMPORTANT: You are running on model '{self.fast_model}'. "
            f"This is your actual model — not Haiku, not what the .env says. "
            f"If asked, say you are {self.fast_model}."
        )

        if project_id:
            try:
                pass  # RAG disabled — use knowledge.search tool instead
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_fast_stream): {e}")

        if active_workers_context:
            dynamic_parts.append("## Background Workers Status\n" + active_workers_context)

        # Build system param with prompt caching for Anthropic native path
        system_prompt = _make_cached_system(
            base_prompt, dynamic_parts,
            is_anthropic=(use_native_delegate or use_cli_mcp),
        )
        # Inject /no_think for thinking models (Qwen3, DeepSeek-R1, etc.)
        system_prompt = _inject_no_think(system_prompt, self.fast_model)

        # Inject identity priming exchange at the start of conversations.
        primed_messages = list(recent)
        is_auto_greeting = "greet" in user_message.lower() and "naturally" in user_message.lower()
        if len(full_history) <= 4 and not is_auto_greeting:
            if use_native_delegate:
                priming_assistant = (
                    "I'm Voxy, running inside Voxyflow's chat layer. I'm a dispatcher — "
                    "I converse with you directly and use inline tools for fast operations. "
                    "My inline tools: memory_search, memory_save, knowledge_search, "
                    "card_list, card_get, card_create, card_update, card_move, "
                    "workers_list, workers_get_result, workers_read_artifact. For complex tasks (research, code, "
                    "multi-step ops), I delegate to background workers via delegate_action."
                )
            elif use_cli_mcp:
                priming_assistant = (
                    "I'm Voxy, running inside Voxyflow's chat layer. I'm a dispatcher — "
                    "I converse with you directly and use MCP tools for fast operations "
                    "(card CRUD, memory search, project/wiki lookups). For complex tasks "
                    "(research, code, multi-step ops), I include <delegate> blocks in my "
                    "response to trigger background workers."
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
        elif use_cli_mcp:
            # CLI+MCP: inline tools via MCP, <delegate> XML for complex tasks
            # For persistent sessions: if process exists, send only the new message
            # with dynamic context as prefix (saves tokens)
            is_persistent = (
                self._cli_backend
                and self._cli_backend.has_persistent_chat(chat_id)
            )
            if is_persistent:
                # Build compact dynamic context for subsequent turns
                dynamic_ctx = dynamic_context.strip() if dynamic_context else ""
                user_msg = user_message
                if dynamic_ctx:
                    user_msg = f"[Context update]\n{dynamic_ctx}\n\n{user_message}"
                stream_messages = [{"role": "user", "content": user_msg}]
            else:
                stream_messages = primed_messages

            full_response = ""
            async for token in self._call_api_stream(
                model=self.fast_model,
                system=system_prompt,
                messages=stream_messages,
                client=self.fast_client,
                client_type=self.fast_client_type,
                use_tools=True,
                mcp_role="dispatcher",
                chat_level=chat_level,
                chat_id=chat_id,
                session_id=session_id, project_id=project_id or "", card_id=card_id,
                session_type="chat",
                cwd=str(VOXYFLOW_WORKSPACE_DIR),
            ):
                full_response += token
                yield token
            logger.info(
                f"[chat_fast_stream] CLI+MCP path — "
                f"{'persistent' if is_persistent else 'new session'}, "
                f"inline tools via MCP, XML delegates"
            )
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
                chat_id=chat_id,
                session_id=session_id, project_id=project_id or "", card_id=card_id,
                session_type="chat",
                cwd=str(VOXYFLOW_WORKSPACE_DIR),
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
        session_id: str = "",
    ) -> AsyncIterator[str]:
        """Deep layer (streaming): Yield tokens from the deep model directly to chat.

        Native Anthropic path: uses delegate_action tool_use for dispatching.
        Proxy path: zero tools, relies on <delegate> XML blocks in text.
        CLI+MCP path: inline tools via MCP + <delegate> XML blocks for complex tasks.
        """
        use_native_delegate = self.deep_client_type == "anthropic"
        use_cli_mcp = self.deep_client_type == "cli"
        card_id = card_context.get("id", "") if card_context else ""

        await self._append_and_persist_async(chat_id, "user", user_message, model="deep")
        full_history = self._get_history(chat_id)  # full history for conversation-age checks
        recent = await self._get_windowed_history(chat_id)  # windowed messages for the API

        memory_context = self.memory.build_memory_context(
            project_name=project_name,
            project_id=project_id,
            include_long_term=True,
            include_daily=True,
            query=user_message,
        )
        # Determine tool mode for personality prompt
        native_tools_mode = "cli_mcp" if use_cli_mcp else use_native_delegate
        # Static base prompt — personality + dispatcher + tools only (cacheable)
        base_prompt = self.personality.build_deep_prompt(
            chat_level=chat_level,
            project=project_context,
            card=card_context,
            is_chat_responder=True,
            native_tools=native_tools_mode,
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

        dynamic_parts.append(
            f"IMPORTANT: You are running on model '{self.deep_model}'. "
            f"This is your actual model. If asked, say you are {self.deep_model}."
        )

        if project_id:
            try:
                pass  # RAG disabled — use knowledge.search tool instead
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_deep_stream): {e}")

        if active_workers_context:
            dynamic_parts.append("## Background Workers Status\n" + active_workers_context)

        # Build system param with prompt caching for Anthropic native path
        system_prompt = _make_cached_system(
            base_prompt, dynamic_parts,
            is_anthropic=(use_native_delegate or use_cli_mcp),
        )
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
            elif use_cli_mcp:
                priming_assistant = (
                    "I'm Voxy, running inside Voxyflow's chat layer as the Deep model. I'm a dispatcher — "
                    "I converse with you directly and use MCP tools for fast operations "
                    "(card CRUD, memory search, project/wiki lookups). For complex tasks "
                    "(research, code, multi-step ops), I include <delegate> blocks in my "
                    "response to trigger background workers."
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
        elif use_cli_mcp:
            # CLI+MCP: persistent session optimization
            is_persistent = (
                self._cli_backend
                and self._cli_backend.has_persistent_chat(chat_id)
            )
            if is_persistent:
                dynamic_ctx = dynamic_context.strip() if dynamic_context else ""
                user_msg = user_message
                if dynamic_ctx:
                    user_msg = f"[Context update]\n{dynamic_ctx}\n\n{user_message}"
                stream_messages = [{"role": "user", "content": user_msg}]
            else:
                stream_messages = primed_messages

            full_response = ""
            async for token in self._call_api_stream(
                model=self.deep_model,
                system=system_prompt,
                messages=stream_messages,
                client=self.deep_client,
                client_type=self.deep_client_type,
                use_tools=True,
                mcp_role="dispatcher",
                chat_level=chat_level,
                chat_id=chat_id,
                session_id=session_id, project_id=project_id or "", card_id=card_id,
                session_type="chat",
                cwd=str(VOXYFLOW_WORKSPACE_DIR),
            ):
                full_response += token
                yield token
            logger.info(f"[chat_deep_stream] CLI+MCP path — inline tools via MCP, XML delegates")
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
                chat_id=chat_id,
                session_id=session_id, project_id=project_id or "", card_id=card_id,
                session_type="chat",
                cwd=str(VOXYFLOW_WORKSPACE_DIR),
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
        session_id: str = "",
        task_id: str = "",
    ) -> str:
        """Execute a delegated task with the specified worker model (haiku/sonnet/opus)."""
        card_id = card_context.get("id", "") if card_context else ""
        # Select client/model based on model param — all workers get full tools
        if model == "haiku":
            client, client_type, model_name = (
                self.haiku_client, self.haiku_client_type, self.haiku_model
            )
        elif model == "opus":
            client, client_type, model_name = (
                self.deep_client, self.deep_client_type, self.deep_model
            )
        else:  # sonnet (default)
            client, client_type, model_name = (
                self.fast_client, self.fast_client_type, self.fast_model
            )
        layer = "deep"  # All workers get TOOLS_FULL regardless of model

        # Workers always use the native Anthropic async SDK (tool_use blocks) to avoid
        # XML <tool_call> truncation issues with the OpenAI-compat proxy path.
        # Using AsyncAnthropic avoids "Streaming required for long requests" errors.
        # The client is pointed at CLIProxyAPI which supports /v1/messages.
        # CLI path: no upgrade needed — Claude CLI handles tools via MCP.
        if client_type == "openai":
            _cfg = get_settings()
            worker_api_url = _cfg.claude_proxy_url  # e.g. http://localhost:3457/v1
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
            "with a status (success/partial/failed) and the FULL RAW OUTPUT in the summary field. "
            "Put the COMPLETE, VERBATIM content — full file contents, full stdout/stderr, all data. "
            "Do NOT summarize, paraphrase, or truncate. Never write generic 'Done' or 'Task complete'. "
            "The dispatcher needs the exact raw content, not a description of what you found. "
            "This is mandatory — never finish without calling task.complete."
        )

        if project_id:
            try:
                pass  # RAG disabled — use knowledge.search tool instead
            except Exception as e:
                logger.warning(f"RAG context injection failed (execute_worker_task): {e}")

        system_prompt = _make_cached_system(
            base_prompt, dynamic_parts, is_anthropic=(client_type in ("anthropic", "cli"))
        )
        system_prompt = _inject_no_think(system_prompt, model_name)

        # Resolve workspace cwd for the worker subprocess
        worker_cwd = ""
        if project_context and project_context.get("local_path"):
            worker_cwd = project_context["local_path"]
        elif not worker_cwd:
            worker_cwd = str(VOXYFLOW_WORKSPACE_DIR)

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
            chat_id=chat_id,
            cancel_event=cancel_event,
            message_queue=message_queue,
            session_id=session_id, project_id=project_id or "", card_id=card_id,
            session_type="worker",
            task_id=task_id,
            cwd=worker_cwd,
        )
        return (_strip_think_tags(result) if _is_thinking_model(model_name) else result) if result else result

    async def execute_lightweight_task(
        self,
        chat_id: str,
        prompt: str,
        model: str = "haiku",
        project_id: Optional[str] = None,
        card_context: Optional[dict] = None,
        tool_callback: Optional[Callable[[str, dict, dict], None]] = None,
        cancel_event: Optional[asyncio.Event] = None,
        message_queue: Optional[asyncio.Queue] = None,
        session_id: str = "",
        task_id: str = "",
    ) -> str:
        """Lightweight worker — minimal prompt, no personality, no project context.

        For tasks that need LLM judgment but not full context (enrich, summarize,
        research). Saves ~80% tokens vs execute_worker_task.
        """
        card_id = card_context.get("id", "") if card_context else ""
        if model == "haiku":
            client, client_type, model_name = (
                self.haiku_client, self.haiku_client_type, self.haiku_model
            )
        elif model == "opus":
            client, client_type, model_name = (
                self.deep_client, self.deep_client_type, self.deep_model
            )
        else:
            client, client_type, model_name = (
                self.fast_client, self.fast_client_type, self.fast_model
            )

        system_prompt = (
            "You are a task worker. Execute the task below using the available MCP tools. "
            "Be precise and concise. When done, call task.complete with the FULL RAW OUTPUT "
            "in the summary field (not just 'Done'). Do NOT summarize or truncate — include "
            "the complete verbatim content: file contents, command stdout/stderr, data values."
        )

        if client_type in ("anthropic", "cli"):
            system_prompt_final: str | list[dict] = [{"type": "text", "text": system_prompt}]
        else:
            system_prompt_final = system_prompt

        logger.info(f"[LightWorker] Executing lightweight task: model={model_name} prompt_len={len(prompt)}")

        result = await self._call_api(
            model=model_name,
            system=system_prompt_final,
            messages=[{"role": "user", "content": prompt}],
            client=client,
            client_type=client_type,
            use_tools=True,
            tool_callback=tool_callback,
            layer="analyzer",
            chat_id=chat_id,
            cancel_event=cancel_event,
            message_queue=message_queue,
            session_id=session_id, project_id=project_id or "", card_id=card_id,
            session_type="worker",
            task_id=task_id,
            cwd=str(VOXYFLOW_WORKSPACE_DIR),
        )
        return result or ""

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

