"""Refactor insurance for the api_caller.py → callers/ package split.

Verifies the facade keeps its public surface, the five mixins compose without
method-name collisions, and async generator vs coroutine semantics are intact.
"""

import inspect

from app.services.llm.api_caller import ApiCallerMixin
from app.services.llm.callers import (
    AnthropicCallsMixin,
    OpenAICallsMixin,
    ServerToolsCallsMixin,
    CliCallsMixin,
    CodexCallsMixin,
)

MIXINS = [
    AnthropicCallsMixin,
    OpenAICallsMixin,
    ServerToolsCallsMixin,
    CliCallsMixin,
    CodexCallsMixin,
]


class TestMixinComposition:
    def test_apicallermixin_bases(self):
        """ApiCallerMixin composes exactly the five backend mixins, in order."""
        assert list(ApiCallerMixin.__bases__) == MIXINS

    def test_no_overlapping_method_names_between_mixins(self):
        """No two mixins may define the same attribute (MRO order must not matter)."""
        seen: dict[str, str] = {}
        for mixin in MIXINS:
            for name in vars(mixin):
                if name.startswith("__"):
                    continue
                assert name not in seen, (
                    f"{name!r} defined in both {seen[name]} and {mixin.__name__}"
                )
                seen[name] = mixin.__name__

    def test_facade_does_not_shadow_mixin_methods(self):
        """The facade only adds the dispatch hub — it must not override mixin methods."""
        mixin_attrs = {n for m in MIXINS for n in vars(m) if not n.startswith("__")}
        facade_attrs = {n for n in vars(ApiCallerMixin) if not n.startswith("__")}
        overlap = mixin_attrs & facade_attrs
        assert not overlap, f"Facade shadows mixin attributes: {overlap}"

    def test_mro_resolution(self):
        """Every expected method resolves through the MRO from the expected module."""
        expected = {
            "_anthropic_extra_headers": "anthropic_calls",
            "_call_api_anthropic": "anthropic_calls",
            "_call_api_stream_with_delegate": "anthropic_calls",
            "_call_api_stream_anthropic": "anthropic_calls",
            "_call_api_stream_openai_with_delegate": "openai_calls",
            "_call_api_openai": "openai_calls",
            "_call_api_stream_openai": "openai_calls",
            "_load_tool_settings": "server_tools_calls",
            "_call_api_server_tools": "server_tools_calls",
            "_call_api_stream_server_tools": "server_tools_calls",
            "_should_use_server_tools": "server_tools_calls",
            "_call_api_cli": "cli_calls",
            "_call_api_stream_cli": "cli_calls",
            "_call_api_codex": "codex_calls",
            "_call_api_stream_codex": "codex_calls",
            "_call_api": "api_caller",
            "_call_api_stream": "api_caller",
        }
        for name, module_tail in expected.items():
            fn = getattr(ApiCallerMixin, name, None)
            assert fn is not None, f"ApiCallerMixin lost method {name}"
            assert fn.__module__.endswith(module_tail), (
                f"{name} resolves from {fn.__module__}, expected *.{module_tail}"
            )


class TestAsyncSemantics:
    """Streaming methods must stay async generators; call methods stay coroutines."""

    ASYNC_GENERATORS = [
        "_call_api_stream",
        "_call_api_stream_anthropic",
        "_call_api_stream_with_delegate",
        "_call_api_stream_openai",
        "_call_api_stream_openai_with_delegate",
        "_call_api_stream_server_tools",
        "_call_api_stream_cli",
        "_call_api_stream_codex",
    ]

    COROUTINES = [
        "_call_api",
        "_call_api_anthropic",
        "_call_api_openai",
        "_call_api_server_tools",
        "_call_api_cli",
        "_call_api_codex",
    ]

    def test_async_generator_functions(self):
        for name in self.ASYNC_GENERATORS:
            fn = getattr(ApiCallerMixin, name)
            assert inspect.isasyncgenfunction(fn), f"{name} must be an async generator"

    def test_coroutine_functions(self):
        for name in self.COROUTINES:
            fn = getattr(ApiCallerMixin, name)
            assert inspect.iscoroutinefunction(fn), f"{name} must be a coroutine function"


class TestFacadeReExports:
    def test_token_log_reexports(self):
        from app.services.llm import api_caller

        assert hasattr(api_caller, "TOKEN_LOG_PATH")
        assert hasattr(api_caller, "_log_token_usage")
        assert hasattr(api_caller, "_CONTEXT_1M_HEADER")
        assert hasattr(api_caller, "_supports_1m_context")

        from app.services.llm.callers import token_log

        assert api_caller.TOKEN_LOG_PATH is token_log.TOKEN_LOG_PATH
        assert api_caller._log_token_usage is token_log._log_token_usage

    def test_claude_service_still_inherits(self):
        from app.services.claude_service import ClaudeService

        assert issubclass(ClaudeService, ApiCallerMixin)

    def test_supports_1m_context_behavior(self):
        from app.services.llm.api_caller import _supports_1m_context

        assert _supports_1m_context("claude-sonnet-4-6")
        assert not _supports_1m_context("claude-opus-4-7")
        assert not _supports_1m_context("")
        assert not _supports_1m_context(None)
