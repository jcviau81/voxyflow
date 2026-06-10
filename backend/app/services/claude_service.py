"""Claude API integration — native Anthropic SDK (primary) with OpenAI-compatible proxy fallback.

This module is the composition root for ClaudeService. The implementation is
split into focused mixins under ``app.services.llm`` (same pattern as
ApiCallerMixin):

  - ``app.services.llm.prompt_cache``        — ``_make_cached_system``
  - ``app.services.llm.chat_history``        — ChatHistoryMixin (+ ``_is_synthetic_prompt``)
  - ``app.services.llm.chat_streams``        — ChatStreamMixin (chat_fast_stream / chat_deep_stream)
  - ``app.services.llm.worker_execution``    — WorkerExecutionMixin (execute_worker_task / execute_lightweight_task)
  - ``app.services.llm.oneshot_generators``  — OneShotMixin (generate_brief / standup / ...)

All public names that other modules import from here are re-exported below, so
existing import paths keep working unchanged.
"""

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from app.config import get_settings, VOXYFLOW_SANDBOX_DIR, workspace_workdir
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
from app.services.cli_session_registry import register_logical_chat_session
from app.services.personality_service import get_personality_service
from app.services.memory_service import get_memory_service
from app.services.agent_personas import AgentType, get_persona_prompt
from app.services.session_store import session_store
from app.services.rag_service import get_rag_service
from app.services.time_context import format_message_timestamp, utc_now_iso
from app.tools.registry import (
    TOOLS_DISPATCHER, TOOLS_WORKER, _ROLE_TOOL_SETS,
)

# Re-exports — keep these importable from app.services.claude_service
# (routes/debug.py, orchestration/tool_call_fallback.py import
# _make_cached_system; tests import _is_synthetic_prompt).
from app.services.llm.prompt_cache import _make_cached_system, make_cached_system
from app.services.llm.chat_history import (
    _SYNTHETIC_PROMPT_PREFIXES,
    _is_synthetic_prompt,
    ChatHistoryMixin,
)
from app.services.llm.chat_streams import ChatStreamMixin
from app.services.llm.worker_execution import WorkerExecutionMixin
from app.services.llm.oneshot_generators import OneShotMixin

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LRU Dict — bounded dict that evicts the oldest entry on overflow
# ---------------------------------------------------------------------------

# _LRUDict, _MODEL_MAP, _resolve_model → app.services.llm.model_utils

# DELEGATE_ACTION_TOOL, get_claude_tools, _mcp_tool_name_from_claude, _call_mcp_tool,
# _load_model_overrides, _get_api_key_from_settings → app.services.llm.tool_defs
from app.services.llm.tool_defs import (
    DELEGATE_ACTION_TOOL,
    get_claude_tools,
    _mcp_tool_name_from_claude,
    _call_mcp_tool,
    _load_model_overrides,
    _get_api_key_from_settings,
)


# ---------------------------------------------------------------------------
# ClaudeService
# ---------------------------------------------------------------------------

class ClaudeService(
    ApiCallerMixin,
    ChatHistoryMixin,
    ChatStreamMixin,
    WorkerExecutionMixin,
    OneShotMixin,
):
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
    _instance_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "ClaudeService":
        if cls._instance is None:
            with cls._instance_lock:
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
        self._codex_backend = None

        # Load overrides from settings.json
        overrides = _load_model_overrides()

        # Resolve API key (keyring/env already merged into config.claude_api_key)
        default_api_key = config.claude_api_key

        # --- Fast layer ---
        fast_cfg = overrides.get("fast", {})
        fast_model_raw = fast_cfg.get("model", "").strip()
        self.fast_model = _resolve_model(fast_model_raw or config.claude_sonnet_model)
        fast_key = _get_api_key_from_settings(fast_cfg) or default_api_key
        self.fast_context_1m = bool(fast_cfg.get("context_1m", False))
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
        self.deep_context_1m = bool(deep_cfg.get("context_1m", False))
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
        self.haiku_context_1m = bool(haiku_cfg.get("context_1m", False))
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
        # Last streaming usage stats (keyed by chat_id). Populated by streaming
        # helpers in api_caller.py; consumed by layer_runners via consume_last_chat_usage().
        self._last_stream_usage: dict[str, dict] = {}
        # Weight (in tokens) of the context WE inject into the dispatcher, broken
        # down by source (system/tools/memory/workspace/sessions/workers). Computed
        # at assembly time in chat_*_stream; surfaced via consume_last_chat_usage().
        # This is what we control — unlike the model-reported usage, which in CLI
        # mode is inflated by Claude Code's own prompt + MCP tool schemas.
        self._last_context_breakdown: dict[str, dict] = {}

        logger.info(
            f"ClaudeService initialized — cli={self.use_cli} native={self.use_native} | "
            f"fast={self.fast_model}({self.fast_client_type}) | "
            f"deep={self.deep_model}({self.deep_client_type}) | "
            f"haiku={self.haiku_model}({self.haiku_client_type})"
        )

    def reload_models(self) -> None:
        """Hot-reload model/provider config from settings.json without restarting.

        Delegates to :func:`app.services.llm.model_reload.reload_layer_models`
        which handles the multi-provider factory, native Anthropic SDK, and
        OpenAI-compat proxy paths for all three (fast/deep/haiku) layers.
        """
        from app.services.llm.model_reload import reload_layer_models
        reload_layer_models(self)

    def _infer_layer(self, model: str) -> str:
        """Map a model name to a conceptual layer for token logging."""
        if model == self.fast_model:
            return "fast"
        if model == self.deep_model:
            return "deep"
        if model == self.haiku_model:
            return "haiku"
        return "unknown"
