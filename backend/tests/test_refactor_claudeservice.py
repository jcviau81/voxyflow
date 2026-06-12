"""Refactor guards for the claude_service.py → llm/ mixin split.

Checks that:
  1. Every public/private name other modules import from
     app.services.claude_service still resolves (re-export facade).
  2. The _get_history alias and _histories attribute survive (worker_pool
     reaches in today), and the new cleanup_chat() contract works.
  3. chat_fast_stream / chat_deep_stream public signatures are unchanged
     after the dedup into _chat_stream(layer=...).
  4. Priming texts honour the dispatcher-redesign invariants (neutral
     identity, inline-CRUD policy incl. Codex) and worker-lifecycle prompt
     text is byte-identical to the pre-refactor literals.
  5. Prompt assembly (system blocks + priming injection) of the deduped
     _chat_stream matches the original fast/deep algorithms.
"""

import asyncio
import inspect

import pytest


# ---------------------------------------------------------------------------
# 1. Re-exports
# ---------------------------------------------------------------------------

def test_facade_reexports_resolve():
    import app.services.claude_service as cs
    from app.services.llm import prompt_cache, chat_history

    # routes/debug.py + orchestration/tool_call_fallback.py import this:
    assert cs._make_cached_system is prompt_cache._make_cached_system
    assert cs.make_cached_system is prompt_cache._make_cached_system
    # tests/test_worker_callback_pipeline.py imports this:
    assert cs._is_synthetic_prompt is chat_history._is_synthetic_prompt
    assert cs._SYNTHETIC_PROMPT_PREFIXES == ("[worker-callback]", "[SYSTEM: Direct action")
    # the test in test_worker_callback_pipeline monkeypatches cs.session_store:
    assert hasattr(cs, "session_store")
    # tool_defs pass-throughs that historically lived here:
    for name in ("DELEGATE_ACTION_TOOL", "get_claude_tools", "_load_model_overrides",
                 "_get_api_key_from_settings", "_LRUDict", "_resolve_model"):
        assert hasattr(cs, name), name


def test_claude_service_composes_all_mixins():
    from app.services.claude_service import ClaudeService
    from app.services.llm.api_caller import ApiCallerMixin
    from app.services.llm.chat_history import ChatHistoryMixin
    from app.services.llm.chat_streams import ChatStreamMixin
    from app.services.llm.worker_execution import WorkerExecutionMixin
    from app.services.llm.oneshot_generators import OneShotMixin

    for mixin in (ApiCallerMixin, ChatHistoryMixin, ChatStreamMixin,
                  WorkerExecutionMixin, OneShotMixin):
        assert issubclass(ClaudeService, mixin), mixin.__name__


# ---------------------------------------------------------------------------
# 2. _get_history alias, _histories attribute, cleanup_chat contract
# ---------------------------------------------------------------------------

def test_get_history_alias_survives():
    from app.services.claude_service import ClaudeService
    from app.services.llm.chat_history import ChatHistoryMixin

    assert ChatHistoryMixin.__dict__["_get_history"] is ChatHistoryMixin.__dict__["get_history"]
    assert ClaudeService._get_history is ClaudeService.get_history


def test_cleanup_chat_pops_history():
    from app.services.claude_service import ClaudeService

    svc = ClaudeService.__new__(ClaudeService)
    svc._histories = {"chat-a": [{"role": "user", "content": "hi"}], "chat-b": []}
    svc.cleanup_chat("chat-a")
    assert "chat-a" not in svc._histories
    assert "chat-b" in svc._histories
    # No-op on missing key:
    svc.cleanup_chat("chat-a")


# ---------------------------------------------------------------------------
# 3. Public signatures unchanged after the fast/deep dedup
# ---------------------------------------------------------------------------

def test_chat_stream_signatures_preserved():
    from app.services.claude_service import ClaudeService

    fast = inspect.signature(ClaudeService.chat_fast_stream)
    assert list(fast.parameters) == [
        "self", "chat_id", "user_message", "workspace_name", "chat_level",
        "project_context", "card_context", "workspace_id", "project_names",
        "active_workers_context", "session_id", "live_state_block",
        "worker_events_block", "session_handoff_block", "role",
        "autonomy_directive_path",
    ]
    assert fast.parameters["role"].default == "dispatcher"
    assert fast.parameters["autonomy_directive_path"].default == ""

    deep = inspect.signature(ClaudeService.chat_deep_stream)
    assert list(deep.parameters) == [
        "self", "chat_id", "user_message", "workspace_name", "chat_level",
        "project_context", "card_context", "workspace_id", "project_names",
        "active_workers_context", "session_id", "live_state_block",
        "worker_events_block", "session_handoff_block",
    ]


# ---------------------------------------------------------------------------
# 4. Prompt text byte-identity (literals copied from the pre-refactor source)
# ---------------------------------------------------------------------------

def test_priming_texts_pinned():
    """Pin priming invariants (2026-06 dispatcher ruleset redesign).

    All branches must state the same inline-CRUD policy as the DISPATCHER.md
    decision table (Codex included — it is no longer read-only), and identity
    must stay neutral (bot name is configurable; no hardcoded 'Voxy').
    """
    from app.services.llm.chat_streams import _PRIMING_ASSISTANT, _PRIMING_USER

    assert _PRIMING_USER == (
        "[SYSTEM INIT] Confirm your identity and operating mode. "
        "Who are you, where are you running, and how do you handle action requests?"
    )

    # Structural invariants of the redesigned priming table.
    assert set(_PRIMING_ASSISTANT) == {
        (layer, branch)
        for layer in ("fast", "deep")
        for branch in ("native", "codex", "cli_mcp", "proxy")
    }
    for (layer, branch), text in _PRIMING_ASSISTANT.items():
        # Neutral identity — never hardcode the configurable bot name.
        assert "Voxy," not in text and "I'm Voxy" not in text, (layer, branch)
        assert "dispatcher" in text, (layer, branch)
        # No provider model names — complexity/tier language only.
        for forbidden in ("haiku", "sonnet", "opus", "gpt"):
            assert forbidden not in text.lower(), (layer, branch)
        # Every branch delegates subprocess work via the delegate tool.
        assert "voxyflow_delegate" in text or "voxyflow.delegate" in text, (layer, branch)

    # Codex branches must claim the SAME inline capabilities as other
    # dispatchers — the read-only-era wording was a regression.
    for layer in ("fast", "deep"):
        codex_text = _PRIMING_ASSISTANT[(layer, "codex")]
        assert "read-only" not in codex_text, layer
        assert "same inline MCP tools" in codex_text, layer
        assert "including deletes" in codex_text, layer
    # Tool-bearing branches act inline on instant local operations.
    for branch in ("native", "cli_mcp"):
        for layer in ("fast", "deep"):
            assert "instant local operations" in _PRIMING_ASSISTANT[(layer, branch)], (layer, branch)


def test_worker_lifecycle_prompts_byte_identical_to_original():
    from app.services.llm.worker_execution import (
        WORKER_LIFECYCLE_PROMPT,
        CODEX_WORKER_LIFECYCLE_PROMPT,
        CODEX_LIGHTWEIGHT_LIFECYCLE_PROMPT,
    )

    assert WORKER_LIFECYCLE_PROMPT == (
        "## Worker Lifecycle (MANDATORY)\n"
        "You operate under a strict 3-phase protocol. The orchestrator enforces it.\n\n"
        "**Phase 1 — Claim.** As your FIRST action, call voxyflow.worker.claim with "
        "your task_id and a one-sentence plan describing what you intend to do. "
        "Do NOT run any other tool before claim.\n\n"
        "**Phase 2 — Work.** Use any tools needed to complete the task. "
        "Save full raw output (file contents, stdout/stderr, data) — it will be persisted "
        "to an artifact that the dispatcher can read on demand.\n\n"
        "**Phase 3 — Complete.** As your LAST action, call voxyflow.worker.complete "
        "with: task_id, status (success/partial/failed), summary (2–4 sentences of what you "
        "did and why it matters — NOT the raw output), findings (3–7 short bullets of the "
        "key results), pointers (labelled offsets into the artifact for important detail), "
        "and next_step (optional). Stop immediately after.\n\n"
        "The summary is the ONLY thing the dispatcher sees directly — write it for a reader "
        "who has NOT seen the raw output. Do not truncate the artifact itself; the "
        "dispatcher will fetch specific sections via read_artifact using your pointers."
    )
    assert CODEX_WORKER_LIFECYCLE_PROMPT == (
        "## Codex Voxyflow lifecycle\n"
        "You have Voxyflow MCP tools through Codex. Use the real tools when they are available: "
        "first call voxyflow.worker.claim, then do the work, and as your last action call "
        "voxyflow.worker.complete. Do not merely print lifecycle JSON when the MCP tools are available.\n\n"
        "Only if the lifecycle MCP tools are unavailable, include fallback fenced JSON blocks "
        "named voxyflow_worker_claim and voxyflow_worker_complete in your final answer with the "
        "same fields. The complete block must include task_id, status, summary, findings, "
        "pointers, and next_step."
    )
    assert CODEX_LIGHTWEIGHT_LIFECYCLE_PROMPT == (
        "\n\nCodex lifecycle: use the real Voxyflow MCP lifecycle tools when available: "
        "first voxyflow.worker.claim, last voxyflow.worker.complete. Only if those tools "
        "are unavailable, include fallback fenced JSON blocks named voxyflow_worker_claim "
        "and voxyflow_worker_complete in your final answer. The complete block must include "
        "task_id, status, summary, findings, pointers, and next_step."
    )


# ---------------------------------------------------------------------------
# 5. Prompt-assembly equivalence of the deduped _chat_stream
# ---------------------------------------------------------------------------

class _FakeMemory:
    def _has_extractable_signal(self, msgs):
        return False

    def build_memory_context(self, **kwargs):
        # Record the kwargs so the test can assert per-layer memory params.
        self.last_kwargs = kwargs
        return "MEMCTX"


class _FakePersonality:
    def build_fast_prompt(self, **kwargs):
        self.fast_kwargs = kwargs
        return "BASEFAST"

    def build_deep_prompt(self, **kwargs):
        self.deep_kwargs = kwargs
        return "BASEDEEP"

    def build_autonomy_prompt(self, **kwargs):
        return "BASEAUTO"

    def build_dynamic_context_block(self, **kwargs):
        return "DYNBLOCK"


class _FakeCliBackend:
    def has_persistent_chat(self, chat_id):
        return False


def _make_stub_service(monkeypatch):
    """Bare ClaudeService with everything around _chat_stream stubbed out."""
    import app.services.claude_service as cs
    from app.services.llm import chat_history

    svc = cs.ClaudeService.__new__(cs.ClaudeService)
    svc.fast_model, svc.fast_client, svc.fast_client_type = "fast-model-x", None, "cli"
    svc.deep_model, svc.deep_client, svc.deep_client_type = "deep-model-x", None, "cli"
    svc._cli_backend = _FakeCliBackend()
    svc.memory = _FakeMemory()
    svc.personality = _FakePersonality()
    svc._histories = {}
    svc._history_locks = type(
        "LD", (dict,), {"__missing__": lambda s, k: s.setdefault(k, asyncio.Lock())}
    )()
    svc._pending_delegates = {}
    svc._last_stream_usage = {}
    svc._last_context_breakdown = {}

    # Session store: empty history, no summary, no-op persistence.
    monkeypatch.setattr(chat_history.session_store, "get_history_for_claude",
                        lambda chat_id, limit=40: [])
    monkeypatch.setattr(chat_history.session_store, "save_message",
                        lambda chat_id, msg: None)
    monkeypatch.setattr(chat_history.session_store, "load_summary",
                        lambda chat_id: None)

    # Worker classes: empty.
    async def _no_wc(self):
        return []
    monkeypatch.setattr(cs.ClaudeService, "_load_worker_classes_context", _no_wc)

    # Capture the stream call.
    captured = {}

    async def _fake_stream(self, **kwargs):
        captured.update(kwargs)
        yield "ok"
    monkeypatch.setattr(cs.ClaudeService, "_call_api_stream", _fake_stream)
    return svc, captured


def _expected_system(base: str, model: str, identity_tail: str) -> list[dict]:
    """Mirror of the original assembly: cached base block + dynamic block."""
    dynamic_text = "DYNBLOCK\n\n" + (
        f"IMPORTANT: You are running on model '{model}'. " + identity_tail
    )
    return [
        {"type": "text", "text": base, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_text},
    ]


def test_fast_stream_prompt_assembly_matches_original(monkeypatch):
    from app.services.llm.chat_streams import _PRIMING_ASSISTANT, _PRIMING_USER

    svc, captured = _make_stub_service(monkeypatch)

    async def run():
        return [t async for t in svc.chat_fast_stream("chat-eq-fast", "hello there")]
    tokens = asyncio.run(run())

    assert tokens == ["ok"]
    assert captured["model"] == "fast-model-x"
    assert captured["client_type"] == "cli"
    assert captured["use_tools"] is True
    assert captured["mcp_role"] == "dispatcher"
    assert captured["system"] == _expected_system(
        "BASEFAST", "fast-model-x",
        "This is your actual model — not Haiku, not what the .env says. "
        "If asked, say you are fast-model-x.",
    )
    # Identity priming injected for young conversations (CLI+MCP branch).
    msgs = captured["messages"]
    assert msgs[0] == {"role": "user", "content": _PRIMING_USER}
    assert msgs[1] == {"role": "assistant", "content": _PRIMING_ASSISTANT[("fast", "cli_mcp")]}
    assert msgs[-1]["role"] == "user"
    assert msgs[-1]["content"].endswith("hello there")
    # Fast-layer memory params (budget 600, no long-term, adaptive layers).
    assert svc.memory.last_kwargs["budget"] == 600
    assert svc.memory.last_kwargs["include_long_term"] is False
    assert svc.memory.last_kwargs["layers"] == (0, 1)
    # Assistant reply persisted into shared history.
    history = svc._histories["chat-eq-fast"]
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == "ok"


def test_deep_stream_prompt_assembly_matches_original(monkeypatch):
    from app.services.llm.chat_streams import _PRIMING_ASSISTANT, _PRIMING_USER

    svc, captured = _make_stub_service(monkeypatch)

    async def run():
        return [t async for t in svc.chat_deep_stream("chat-eq-deep", "hello there")]
    tokens = asyncio.run(run())

    assert tokens == ["ok"]
    assert captured["model"] == "deep-model-x"
    assert captured["system"] == _expected_system(
        "BASEDEEP", "deep-model-x",
        "This is your actual model. If asked, say you are deep-model-x.",
    )
    msgs = captured["messages"]
    assert msgs[0] == {"role": "user", "content": _PRIMING_USER}
    assert msgs[1] == {"role": "assistant", "content": _PRIMING_ASSISTANT[("deep", "cli_mcp")]}
    # Deep prompt builder got is_chat_responder=True (original behavior).
    assert svc.personality.deep_kwargs["is_chat_responder"] is True
    # Deep-layer memory params (budget 1500, long-term on, full layers).
    assert svc.memory.last_kwargs["budget"] == 1500
    assert svc.memory.last_kwargs["include_long_term"] is True
    assert svc.memory.last_kwargs["layers"] == (0, 1, 2)


def test_fast_stream_autonomy_skips_priming(monkeypatch):
    svc, captured = _make_stub_service(monkeypatch)

    async def run():
        return [t async for t in svc.chat_fast_stream(
            "chat-eq-auto", "tick", role="autonomy", autonomy_directive_path="/tmp/d.md",
        )]
    asyncio.run(run())

    assert captured["system"][0]["text"] == "BASEAUTO"
    # No [SYSTEM INIT] priming pair for autonomy ticks.
    assert all("[SYSTEM INIT]" not in (m.get("content") or "") for m in captured["messages"])
