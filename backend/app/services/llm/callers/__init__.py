"""Per-backend call mixins for ApiCallerMixin (split from api_caller.py).

Each module provides one mixin covering a backend family:
  - anthropic_calls.AnthropicCallsMixin — native Anthropic SDK (tool_use loop,
    dispatcher delegate streaming, plain streaming)
  - openai_calls.OpenAICallsMixin — OpenAI-compatible proxy paths
  - server_tools_calls.ServerToolsCallsMixin — server-side XML <tool_call> loop
    for providers without native tool support (+ _should_use_server_tools,
    _load_tool_settings)
  - cli_calls.CliCallsMixin — Claude CLI subprocess paths
  - codex_calls.CodexCallsMixin — Codex CLI subprocess paths

Self-attribute contract — these mixins rely on attributes provided by the host
class (ClaudeService):
  self.deep_model, self.fast_model, self.haiku_model
  self.max_tokens, self.max_tokens_opus, self.max_tokens_sonnet, self.max_tokens_haiku
  self.fast_client, self.fast_client_type
  self.fast_context_1m, self.deep_context_1m, self.haiku_context_1m (optional flags)
  self._infer_layer()
  self._pending_delegates (dict[chat_id, list] — delegate collection)
  self._last_stream_usage (dict[chat_id, dict] — per-chat usage snapshots)
  self._cli_backend (when client_type == "cli")
  self._codex_backend (when client_type == "codex"; lazily created by CodexCallsMixin)
"""

from app.services.llm.callers.token_log import (
    TOKEN_LOG_PATH,
    _log_token_usage,
    _CONTEXT_1M_HEADER,
    _supports_1m_context,
)
from app.services.llm.callers.anthropic_calls import AnthropicCallsMixin
from app.services.llm.callers.openai_calls import OpenAICallsMixin
from app.services.llm.callers.server_tools_calls import ServerToolsCallsMixin
from app.services.llm.callers.cli_calls import CliCallsMixin
from app.services.llm.callers.codex_calls import CodexCallsMixin

__all__ = [
    "TOKEN_LOG_PATH",
    "_log_token_usage",
    "_CONTEXT_1M_HEADER",
    "_supports_1m_context",
    "AnthropicCallsMixin",
    "OpenAICallsMixin",
    "ServerToolsCallsMixin",
    "CliCallsMixin",
    "CodexCallsMixin",
]
