"""Dispatcher chat streaming mixin for ClaudeService (fast + deep layers).

Extracted from app.services.claude_service. ``chat_fast_stream`` and
``chat_deep_stream`` were ~90% identical; they are now thin wrappers over a
single parameterized ``_chat_stream(layer=...)``. All prompt strings, priming
texts, and streaming semantics are preserved verbatim — the per-layer
differences live in the ``_LAYER_*`` tables and a few explicit
``if layer == ...`` branches below.

ChatStreamMixin expects the composing class to provide (created in
ClaudeService.__init__):
  - fast/deep layer config: ``fast_model``/``deep_model``, ``fast_client``/
    ``deep_client``, ``fast_client_type``/``deep_client_type``
  - ``self._cli_backend``, ``self.personality``, ``self.memory``
  - ``self._pending_delegates``, ``self._last_stream_usage``,
    ``self._last_context_breakdown``
  - history helpers from ChatHistoryMixin, ``_call_api_stream*`` from
    ApiCallerMixin
"""

import asyncio
import logging
from typing import AsyncIterator, Optional

from app.config import VOXYFLOW_SANDBOX_DIR
from app.services.cli_session_registry import register_logical_chat_session
from app.services.llm.chat_history import _is_synthetic_prompt
from app.services.llm.model_utils import (
    _strip_think_tags,
    _is_thinking_model,
    _inject_no_think,
)
from app.services.llm.prompt_cache import _make_cached_system

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Identity priming — injected at the start of young conversations.
# One table for the 4 backend branches × 2 layers (texts moved VERBATIM from
# the original chat_fast_stream / chat_deep_stream bodies — do not reword).
# Branch keys: "native" (Anthropic native OR OpenAI-compat delegate),
# "codex", "cli_mcp", "proxy" (fallback).
# ---------------------------------------------------------------------------

_PRIMING_USER = (
    "[SYSTEM INIT] Confirm your identity and operating mode. "
    "Who are you, where are you running, and how do you handle action requests?"
)

_PRIMING_ASSISTANT: dict[tuple[str, str], str] = {
    ("fast", "native"): (
        "I'm Voxy, running inside Voxyflow's chat layer. I'm a dispatcher — "
        "I converse with you directly and use inline tools for fast operations. "
        "My inline tools: memory_search, memory_save, knowledge_search, "
        "card_list, card_get, card_create, card_update, card_move, "
        "workers_list, workers_get_result, workers_read_artifact. For complex tasks (research, code, "
        "multi-step ops), I delegate to background workers via the `voxyflow.delegate` MCP tool."
    ),
    ("fast", "codex"): (
        "I'm Voxy, running inside Voxyflow's chat layer. I'm a dispatcher — "
        "I converse briefly, use read-only MCP tools only to inspect state, "
        "and delegate action work to background workers by calling the "
        "`voxyflow.delegate` MCP tool. I do not perform implementation, "
        "research, filesystem, shell, card writes, or multi-step work inline."
    ),
    ("fast", "cli_mcp"): (
        "I'm Voxy, running inside Voxyflow's chat layer. I'm a dispatcher — "
        "I converse with you directly and use MCP tools for fast operations "
        "(card CRUD, memory search, workspace/wiki lookups). For complex tasks "
        "(research, code, multi-step ops), I call the `voxyflow.delegate` MCP "
        "tool to trigger background workers."
    ),
    ("fast", "proxy"): (
        "I'm Voxy, running inside Voxyflow's chat layer. I'm a dispatcher — "
        "I converse with you directly and delegate complex actions to background "
        "workers via the `voxyflow.delegate` tool. When you ask me to do "
        "something like a web search or run code, I respond briefly and call "
        "`voxyflow.delegate` to trigger the worker. "
        "The worker handles it in the background and the result appears in the chat."
    ),
    ("deep", "native"): (
        "I'm Voxy, running inside Voxyflow's chat layer as the Deep model. I'm a dispatcher — "
        "I converse with you directly and delegate all actions to background workers "
        "using the `voxyflow.delegate` MCP tool. I never execute actions myself. When you ask "
        "me to do something, I respond briefly and call `voxyflow.delegate` to trigger the worker."
    ),
    ("deep", "codex"): (
        "I'm Voxy, running inside Voxyflow's chat layer as the Deep model. "
        "I'm a dispatcher — I converse briefly, use read-only MCP tools only "
        "to inspect state, and delegate action work to background workers by "
        "calling the `voxyflow.delegate` MCP tool. I do not perform implementation, "
        "research, filesystem, shell, card writes, or multi-step work inline."
    ),
    ("deep", "cli_mcp"): (
        "I'm Voxy, running inside Voxyflow's chat layer as the Deep model. I'm a dispatcher — "
        "I converse with you directly and use MCP tools for fast operations "
        "(card CRUD, memory search, workspace/wiki lookups). For complex tasks "
        "(research, code, multi-step ops), I call the `voxyflow.delegate` MCP "
        "tool to trigger background workers."
    ),
    ("deep", "proxy"): (
        "I'm Voxy, running inside Voxyflow's chat layer. I'm a dispatcher — "
        "I converse with you directly and delegate complex actions to background "
        "workers via the `voxyflow.delegate` tool. When you ask me to do "
        "something like a web search or run code, I respond briefly and call "
        "`voxyflow.delegate` to trigger the worker. "
        "The worker handles it in the background and the result appears in the chat."
    ),
}


class ChatStreamMixin:
    """Streaming dispatcher chat (fast/deep) + per-chat delegate/usage bookkeeping."""

    # ------------------------------------------------------------------
    # Native delegate helpers
    # ------------------------------------------------------------------

    def pop_pending_delegates(self, chat_id: str) -> list[dict]:
        """Return and clear any native delegate_action tool_use blocks
        collected during the last streaming call for this chat_id."""
        return self._pending_delegates.pop(chat_id, [])

    def _record_context_breakdown(
        self,
        chat_id: str,
        *,
        base_prompt,
        dynamic_context: str | None,
        memory_context: str | None,
        live_state_block: str | None,
        worker_events_block: str | None,
        session_handoff_block: str | None,
        active_workers_context: str | None,
        messages: list[dict] | None,
        mcp_role: str,
    ) -> None:
        """Measure the token weight of the context WE inject, by source.

        Buckets sum to ``total``: system (base prompt) + tools (MCP/tool schemas)
        + the dynamic context block (which already contains memory + workers +
        workspace/cards) + sessions (conversation history). memory/workers are
        reported as subsets of the dynamic block; workspace is the remainder.
        """
        try:
            import json
            from app.services.token_counter import count_tokens, using_exact_tokenizer
            from app.services.llm.tool_defs import get_claude_tools

            base_text = base_prompt if isinstance(base_prompt, str) else (
                "".join(b.get("text", "") for b in base_prompt if isinstance(b, dict))
                if isinstance(base_prompt, list) else ""
            )
            system_tok = count_tokens(base_text)
            try:
                tools_tok = count_tokens(json.dumps(get_claude_tools(role=mcp_role)))
            except Exception:
                tools_tok = 0
            dyn_tok = count_tokens(dynamic_context or "")
            memory_tok = count_tokens(memory_context or "")
            workers_tok = sum(count_tokens(x or "") for x in (
                live_state_block, worker_events_block, session_handoff_block, active_workers_context,
            ))
            # Workspace/cards = whatever's left of the dynamic block after the
            # memory + ambient/worker sub-blocks (also covers time/worker-classes/misc).
            workspace_tok = max(0, dyn_tok - memory_tok - workers_tok)

            def _msg_text(m: dict) -> str:
                c = m.get("content")
                return c if isinstance(c, str) else json.dumps(c)
            sessions_tok = sum(count_tokens(_msg_text(m)) for m in (messages or []))

            total = system_tok + tools_tok + dyn_tok + sessions_tok
            self._last_context_breakdown[chat_id] = {
                "system": system_tok,
                "tools": tools_tok,
                "memory": memory_tok,
                "workspace": workspace_tok,
                "workers": workers_tok,
                "sessions": sessions_tok,
                "total": total,
                "exact": using_exact_tokenizer(),
            }
        except Exception as e:  # pragma: no cover — never break a chat over a metric
            logger.debug("context breakdown failed for %s: %s", chat_id, e)

    def consume_last_chat_usage(self, chat_id: str, layer: str) -> dict | None:
        """Return and clear usage stats from the most recent chat stream.

        The returned dict is shaped for the WebSocket payload (camelCase) and
        augmented with the model's static context window and the per-source
        weight of the context WE inject (``contextBreakdown``). Returns None
        only if neither model usage nor a context breakdown was recorded.
        """
        raw = self._last_stream_usage.pop(chat_id, None)
        breakdown = self._last_context_breakdown.pop(chat_id, None)
        if not raw and not breakdown:
            return None
        raw = raw or {}
        model = self.deep_model if layer == "deep" else self.fast_model
        from app.services.llm.capability_registry import lookup as _caps_lookup
        caps = _caps_lookup(model)
        return {
            "inputTokens": int(raw.get("input_tokens", 0) or 0),
            "outputTokens": int(raw.get("output_tokens", 0) or 0),
            "cacheReadTokens": int(raw.get("cache_read_input_tokens", 0) or 0),
            "cacheCreationTokens": int(raw.get("cache_creation_input_tokens", 0) or 0),
            "contextWindow": int(caps.context_window),
            "model": model,
            "contextBreakdown": breakdown,
        }

    # ------------------------------------------------------------------
    # Worker class context for dispatcher
    # ------------------------------------------------------------------

    async def _load_worker_classes_context(self) -> list[dict]:
        """Load worker classes for injection into dispatcher context."""
        from app.services.llm.worker_class_resolver import _load_worker_classes
        try:
            return await _load_worker_classes()
        except Exception as e:
            logger.warning(f"Failed to load worker classes for context: {e}")
            return []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def chat_fast_stream(
        self,
        chat_id: str,
        user_message: str,
        workspace_name: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
        workspace_id: Optional[str] = None,
        project_names: Optional[list] = None,
        active_workers_context: str = "",
        session_id: str = "",
        live_state_block: str = "",
        worker_events_block: str = "",
        session_handoff_block: str = "",
        role: str = "dispatcher",
        autonomy_directive_path: str = "",
    ) -> AsyncIterator[str]:
        """Layer 1 (streaming): Yield tokens as they arrive from the fast layer.

        Native Anthropic path: uses voxyflow.delegate tool_use for dispatching.
        Proxy path: no native tool support — worker delegation not available.
        CLI+MCP path: inline tools via MCP + voxyflow.delegate tool for complex tasks.
        """
        async for token in self._chat_stream(
            "fast",
            chat_id=chat_id,
            user_message=user_message,
            workspace_name=workspace_name,
            chat_level=chat_level,
            project_context=project_context,
            card_context=card_context,
            workspace_id=workspace_id,
            project_names=project_names,
            active_workers_context=active_workers_context,
            session_id=session_id,
            live_state_block=live_state_block,
            worker_events_block=worker_events_block,
            session_handoff_block=session_handoff_block,
            role=role,
            autonomy_directive_path=autonomy_directive_path,
        ):
            yield token

    async def chat_deep_stream(
        self,
        chat_id: str,
        user_message: str,
        workspace_name: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
        workspace_id: Optional[str] = None,
        project_names: Optional[list] = None,
        active_workers_context: str = "",
        session_id: str = "",
        live_state_block: str = "",
        worker_events_block: str = "",
        session_handoff_block: str = "",
    ) -> AsyncIterator[str]:
        """Deep layer (streaming): Yield tokens from the deep model directly to chat.

        Native Anthropic path: uses voxyflow.delegate tool_use for dispatching.
        Proxy path: no native tool support — worker delegation not available.
        CLI+MCP path: inline tools via MCP + voxyflow.delegate tool for complex tasks.
        """
        async for token in self._chat_stream(
            "deep",
            chat_id=chat_id,
            user_message=user_message,
            workspace_name=workspace_name,
            chat_level=chat_level,
            project_context=project_context,
            card_context=card_context,
            workspace_id=workspace_id,
            project_names=project_names,
            active_workers_context=active_workers_context,
            session_id=session_id,
            live_state_block=live_state_block,
            worker_events_block=worker_events_block,
            session_handoff_block=session_handoff_block,
        ):
            yield token

    # ------------------------------------------------------------------
    # Shared implementation (fast + deep)
    # ------------------------------------------------------------------

    async def _chat_stream(
        self,
        layer: str,
        *,
        chat_id: str,
        user_message: str,
        workspace_name: Optional[str] = None,
        chat_level: str = "general",
        project_context: Optional[dict] = None,
        card_context: Optional[dict] = None,
        workspace_id: Optional[str] = None,
        project_names: Optional[list] = None,
        active_workers_context: str = "",
        session_id: str = "",
        live_state_block: str = "",
        worker_events_block: str = "",
        session_handoff_block: str = "",
        role: str = "dispatcher",
        autonomy_directive_path: str = "",
    ) -> AsyncIterator[str]:
        """Single parameterized dispatcher stream — ``layer`` is "fast" or "deep".

        The fast/deep differences are: model/client/client_type, memory budget
        and layers, base prompt builder (fast/autonomy vs deep), the model
        identity line, the priming texts (table above), the persistent-CLI
        check, and log labels. Everything else is shared verbatim.
        """
        if layer == "fast":
            model = self.fast_model
            client = self.fast_client
            client_type = self.fast_client_type
        else:
            model = self.deep_model
            client = self.deep_client
            client_type = self.deep_client_type

        use_native_delegate = client_type == "anthropic"
        use_openai_delegate = client_type == "openai"
        use_cli_mcp = client_type in ("cli", "codex")
        card_id = card_context.get("id", "") if card_context else ""

        await self._append_and_persist_async(
            chat_id, "user", user_message, model=model,
            msg_type="system" if _is_synthetic_prompt(user_message) else None,
        )
        full_history = self._get_history(chat_id)  # full history for conversation-age checks
        recent = await self._get_windowed_history(chat_id)  # windowed messages for the API

        if layer == "fast":
            # Adaptive layers: if message has extractable signal, load full context
            fast_layers: tuple[int, ...] = (0, 1)
            if self.memory._has_extractable_signal([{"content": user_message, "role": "user"}]):
                fast_layers = (0, 1, 2)
            mem_include_long_term = False
            mem_budget = 600
            mem_layers = fast_layers
        else:
            mem_include_long_term = True
            mem_budget = 1500
            mem_layers = (0, 1, 2)

        # Kick the (blocking) embedding + ChromaDB memory query onto a worker
        # thread so it doesn't stall the event loop, and overlaps with the base
        # prompt build + worker-classes load below. Awaited just before use.
        memory_task = asyncio.create_task(asyncio.to_thread(
            self.memory.build_memory_context,
            workspace_name=workspace_name,
            workspace_id=workspace_id,
            include_long_term=mem_include_long_term,
            include_daily=True,
            query=user_message,
            budget=mem_budget,
            layers=mem_layers,
        ))
        # Determine tool mode for personality prompt.
        # OpenAI-compat dispatchers (Qwen via Ollama, Groq, etc.) use the same
        # native delegate_action tool-call protocol as Anthropic — XML delegates
        # are unreliable on small open-weight models.
        native_tools_mode = (
            "codex_mcp" if client_type == "codex"
            else ("claude_cli_mcp" if use_cli_mcp else (use_native_delegate or use_openai_delegate))
        )
        # Static base prompt — personality + dispatcher (or autonomy) + tools (cacheable)
        if layer == "fast":
            if role == "autonomy":
                base_prompt = self.personality.build_autonomy_prompt(
                    workspace=project_context,
                    directive_path=autonomy_directive_path,
                    native_tools=native_tools_mode,
                )
            else:
                base_prompt = self.personality.build_fast_prompt(
                    chat_level=chat_level,
                    workspace=project_context,
                    card=card_context,
                    native_tools=native_tools_mode,
                )
        else:
            base_prompt = self.personality.build_deep_prompt(
                chat_level=chat_level,
                workspace=project_context,
                card=card_context,
                is_chat_responder=True,
                native_tools=native_tools_mode,
            )

        # Collect dynamic context (changes per-call — injected OUTSIDE the cached block)
        dynamic_parts: list[str] = []
        wc_list = await self._load_worker_classes_context()
        # Resolve the memory context now (kicked off on a thread above) — its
        # blocking work overlapped with the base prompt + worker-classes load.
        memory_context = await memory_task

        # Workspace/card context + memory — dynamic, must NOT be in base_prompt
        dynamic_context = self.personality.build_dynamic_context_block(
            chat_level=chat_level,
            workspace=project_context,
            card=card_context,
            workspace_names=project_names,
            memory_context=memory_context,
            worker_classes=wc_list,
            live_state=live_state_block or None,
            worker_events=worker_events_block or None,
            session_handoff=session_handoff_block or None,
        )
        if dynamic_context:
            dynamic_parts.append(dynamic_context)

        # Tell the model what it actually is
        if layer == "fast":
            dynamic_parts.append(
                f"IMPORTANT: You are running on model '{model}'. "
                f"This is your actual model — not Haiku, not what the .env says. "
                f"If asked, say you are {model}."
            )
        else:
            dynamic_parts.append(
                f"IMPORTANT: You are running on model '{model}'. "
                f"This is your actual model. If asked, say you are {model}."
            )

        if workspace_id:
            try:
                pass  # RAG disabled — use knowledge.search tool instead
            except Exception as e:
                logger.warning(f"RAG context injection failed (chat_{layer}_stream): {e}")

        if active_workers_context:
            dynamic_parts.append("## Background Workers Status\n" + active_workers_context)

        # Build system param with prompt caching for Anthropic native path
        system_prompt = _make_cached_system(
            base_prompt, dynamic_parts,
            is_anthropic=(use_native_delegate or use_cli_mcp),
        )
        # Inject /no_think for thinking models (Qwen3, DeepSeek-R1, etc.)
        system_prompt = _inject_no_think(system_prompt, model)

        # Inject identity priming exchange at the start of conversations.
        # Autonomy ticks skip priming — no user is present to prime to.
        primed_messages = list(recent)
        is_auto_greeting = "greet" in user_message.lower() and "naturally" in user_message.lower()
        if role != "autonomy" and len(full_history) <= 4 and not is_auto_greeting:
            if use_native_delegate or use_openai_delegate:
                priming_branch = "native"
            elif client_type == "codex":
                priming_branch = "codex"
            elif use_cli_mcp:
                priming_branch = "cli_mcp"
            else:
                priming_branch = "proxy"
            priming_assistant = _PRIMING_ASSISTANT[(layer, priming_branch)]
            priming = [
                {"role": "user", "content": _PRIMING_USER},
                {"role": "assistant", "content": priming_assistant},
            ]
            primed_messages = priming + primed_messages

        # Measure the weight of the context we inject (system/tools/memory/
        # workspace/sessions/workers) for the context-usage indicator.
        self._record_context_breakdown(
            chat_id,
            base_prompt=base_prompt,
            dynamic_context=dynamic_context,
            memory_context=memory_context,
            live_state_block=live_state_block,
            worker_events_block=worker_events_block,
            session_handoff_block=session_handoff_block,
            active_workers_context=active_workers_context,
            messages=primed_messages,
            mcp_role="dispatcher",
        )

        # Clear any previous pending delegates for this chat
        self._pending_delegates.pop(chat_id, None)

        if use_native_delegate:
            # Native Anthropic: stream with delegate_action tool
            full_response = ""
            async with register_logical_chat_session(
                chat_id=chat_id, workspace_id=workspace_id,
                model=model, session_type="chat",
            ):
                async for token in self._call_api_stream_with_delegate(
                    model=model,
                    system=system_prompt,
                    messages=primed_messages,
                    client=client,
                    chat_id=chat_id,
                ):
                    full_response += token
                    yield token
            logger.info(f"[chat_{layer}_stream] Native delegate path — collected {len(self._pending_delegates.get(chat_id, []))} delegates")
        elif use_openai_delegate:
            # OpenAI-compat (Qwen via Ollama, Groq, Mistral, etc.):
            # native delegate_action tool-call — small open-weight models follow
            # function-call schemas far more reliably than embedded XML.
            full_response = ""
            async with register_logical_chat_session(
                chat_id=chat_id, workspace_id=workspace_id,
                model=model, session_type="chat",
            ):
                async for token in self._call_api_stream_openai_with_delegate(
                    model=model,
                    system=system_prompt,
                    messages=primed_messages,
                    client=client,
                    chat_id=chat_id,
                ):
                    full_response += token
                    yield token
            logger.info(
                f"[chat_{layer}_stream] OpenAI native delegate path — collected "
                f"{len(self._pending_delegates.get(chat_id, []))} delegates"
            )
        elif use_cli_mcp:
            # CLI+MCP: inline tools via MCP, voxyflow.delegate tool for complex tasks
            # For persistent sessions: if process exists, send only the new message
            # with dynamic context as prefix (saves tokens)
            if layer == "fast":
                is_persistent = (
                    self.fast_client_type == "cli"
                    and self.deep_client_type == "cli"
                    and self._cli_backend
                    and self._cli_backend.has_persistent_chat(chat_id)
                )
            else:
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
                model=model,
                system=system_prompt,
                messages=stream_messages,
                client=client,
                client_type=client_type,
                use_tools=True,
                mcp_role="dispatcher",
                chat_level=chat_level,
                chat_id=chat_id,
                session_id=session_id, workspace_id=workspace_id or "", card_id=card_id,
                session_type="chat",
                cwd=str(VOXYFLOW_SANDBOX_DIR),
            ):
                full_response += token
                yield token
            if layer == "fast":
                logger.info(
                    f"[chat_fast_stream] Local CLI+MCP path — "
                    f"{'persistent' if is_persistent else 'new session'}, "
                    f"inline tools via MCP, voxyflow.delegate tool"
                )
            else:
                logger.info(f"[chat_deep_stream] Local CLI+MCP path — inline tools via MCP, voxyflow.delegate tool")
        else:
            # Proxy fallback: no tools, XML delegate blocks
            full_response = ""
            async for token in self._call_api_stream(
                model=model,
                system=system_prompt,
                messages=primed_messages,
                client=client,
                client_type=client_type,
                use_tools=False,
                chat_level=chat_level,
                chat_id=chat_id,
                session_id=session_id, workspace_id=workspace_id or "", card_id=card_id,
                session_type="chat",
                cwd=str(VOXYFLOW_SANDBOX_DIR),
            ):
                full_response += token
                yield token

        # Strip <think> blocks only for thinking models (Qwen3, DeepSeek-R1, etc.)
        if _is_thinking_model(model):
            full_response = _strip_think_tags(full_response)
        if full_response:
            await self._append_and_persist_async(chat_id, "assistant", full_response, model=model)
