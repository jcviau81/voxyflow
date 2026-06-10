"""Anthropic SDK call paths for ApiCallerMixin (native tool_use loop + delegate streaming).

Extracted verbatim from api_caller.py. See app.services.llm.callers package
docstring for the self-attribute contract required from the host class.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Callable, Optional

from app.services.llm.model_utils import invoke_tool_callback
from app.services.llm.tool_defs import (
    VOXYFLOW_DELEGATE_TOOL,
    _mcp_tool_name_from_claude,
    _call_mcp_tool,
    get_claude_tools,
)
from app.tools.delegate_tool import (
    TOOL_NAME_SAFE as _DELEGATE_TOOL_NAME_SAFE,
    validate_delegate_input,
    make_tool_result_error,
)

from app.services.llm.callers.token_log import (
    _CONTEXT_1M_HEADER,
    _log_token_usage,
    _supports_1m_context,
)

logger = logging.getLogger(__name__)


class AnthropicCallsMixin:
    """Native Anthropic SDK call paths (non-streaming, streaming, delegate streaming)."""

    def _anthropic_extra_headers(self, model: str) -> dict:
        """Return extra headers for an Anthropic SDK call for *model*.

        Picks the per-layer ``context_1m`` flag (fast/deep/haiku) by matching
        *model* against the layer's configured model name. Returns an empty
        dict when the flag is off or the model doesn't support the beta.
        """
        if not _supports_1m_context(model):
            return {}
        flag = False
        if model == getattr(self, "fast_model", None):
            flag = bool(getattr(self, "fast_context_1m", False))
        elif model == getattr(self, "deep_model", None):
            flag = bool(getattr(self, "deep_context_1m", False))
        elif model == getattr(self, "haiku_model", None):
            flag = bool(getattr(self, "haiku_context_1m", False))
        return dict(_CONTEXT_1M_HEADER) if flag else {}

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
            # Agentic tool-use loop — no round limit, bounded by task timeout + cancel_event
            _round = 0
            while True:
                _round += 1
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
                extra_headers = self._anthropic_extra_headers(model)
                call_kwargs = {**kwargs, "extra_headers": extra_headers} if extra_headers else kwargs
                if isinstance(client, _anthropic.AsyncAnthropic):
                    async with client.messages.stream(**call_kwargs) as stream:
                        response = await stream.get_final_message()
                else:
                    response = await asyncio.to_thread(
                        lambda kw=call_kwargs: client.messages.create(**kw)
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
                        f"[Anthropic] max_tokens reached on round {_round} for {chat_id!r} "
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

                        await invoke_tool_callback(tool_callback, mcp_name, arguments, result)

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

            logger.info(f"[Anthropic] tool loop ended after {_round} rounds for {chat_id!r}")
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
        import queue
        import threading

        clean_messages = [m for m in messages if m.get("role") != "system"]
        if not clean_messages:
            clean_messages = [{"role": "user", "content": "(empty)"}]

        # Build dispatcher tool schemas from the registry (single source of truth)
        dispatcher_tools = get_claude_tools(role="dispatcher")
        all_tools = [VOXYFLOW_DELEGATE_TOOL] + dispatcher_tools

        kwargs = {
            "model": model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": clean_messages,
            "tools": all_tools,
        }
        extra_headers = self._anthropic_extra_headers(model)
        if extra_headers:
            kwargs["extra_headers"] = extra_headers

        # Build set of dispatcher tool names for routing (underscore format from get_claude_tools)
        dispatcher_tool_names = {t["name"] for t in dispatcher_tools}

        max_inline_rounds = 3  # Prevent infinite inline tool loops

        try:
            for inline_round in range(max_inline_rounds + 1):
                # Collect streamed content and tool_use blocks
                streamed_text_parts: list[str] = []
                tool_use_blocks: list = []

                # Thread + queue bridge so text tokens reach the user as they
                # arrive (same pattern as the OpenAI variant) instead of
                # buffering the entire response before yielding anything.
                event_queue: queue.Queue = queue.Queue()

                def _do_stream(_kw=kwargs):
                    try:
                        with client.messages.stream(**_kw) as stream:
                            for text in stream.text_stream:
                                event_queue.put(("text", text))
                            final_msg = stream.get_final_message()
                            for block in final_msg.content:
                                if block.type == "tool_use":
                                    event_queue.put(("tool_use", block))
                            event_queue.put(("stop_reason", final_msg.stop_reason))
                            event_queue.put(("usage", final_msg.usage))
                    except Exception as e:
                        event_queue.put(("error", e))
                    finally:
                        event_queue.put(None)

                threading.Thread(target=_do_stream, daemon=True).start()

                stop_reason = "end_turn"
                stream_usage = None
                while True:
                    item = await asyncio.to_thread(event_queue.get)
                    if item is None:
                        break
                    event_type, data = item
                    if event_type == "text":
                        streamed_text_parts.append(data)
                        yield data
                    elif event_type == "tool_use":
                        tool_use_blocks.append(data)
                    elif event_type == "stop_reason":
                        stop_reason = data
                    elif event_type == "usage":
                        stream_usage = data
                    elif event_type == "error":
                        raise data

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
                    if chat_id:
                        self._last_stream_usage[chat_id] = {
                            "input_tokens": stream_usage.input_tokens,
                            "output_tokens": stream_usage.output_tokens,
                            "cache_creation_input_tokens": getattr(stream_usage, "cache_creation_input_tokens", 0) or 0,
                            "cache_read_input_tokens": getattr(stream_usage, "cache_read_input_tokens", 0) or 0,
                        }

                if not tool_use_blocks:
                    # No tool calls — done
                    return

                # Separate dispatcher tools from delegate tool calls
                # Accept both the new canonical name and the legacy name for backward compat.
                _is_delegate = lambda b: b.name in (_DELEGATE_TOOL_NAME_SAFE, "delegate_action")
                tool_blocks = [b for b in tool_use_blocks if b.name in dispatcher_tool_names]
                delegate_blocks = [b for b in tool_use_blocks if _is_delegate(b)]
                unknown_blocks = [b for b in tool_use_blocks if b.name not in dispatcher_tool_names and not _is_delegate(b)]

                for b in unknown_blocks:
                    logger.warning(f"[NativeDelegate] Unexpected tool_use: {b.name} — ignoring")

                # Collect delegates (validate strict schema for new tool name)
                # Track per-block validation errors so we can surface them as
                # tool_result errors to the LLM for self-correction.
                _delegate_validation_errors: dict[str, str] = {}
                for block in delegate_blocks:
                    payload = block.input or {}
                    if block.name == _DELEGATE_TOOL_NAME_SAFE:
                        ok, err = validate_delegate_input(payload)
                        if not ok:
                            logger.warning(f"[NativeDelegate] Schema validation failed: {err}")
                            _delegate_validation_errors[block.id] = err
                            # Don't collect invalid payloads — force self-correction
                            continue
                    self._pending_delegates.setdefault(chat_id, []).append(payload)
                    logger.info(
                        f"[NativeDelegate] Collected {block.name}: "
                        f"action={payload.get('action')}, desc={str(payload.get('description', payload.get('summary', '')))[:60]!r}"
                    )

                # Execute dispatcher tools via the registry
                from app.tools.registry import get_registry
                _registry = get_registry()
                tool_results_map: dict[str, str] = {}
                for block in tool_blocks:
                    # Convert underscore name back to dot notation for registry lookup
                    mcp_name = _mcp_tool_name_from_claude(block.name)
                    logger.info(f"[DispatcherTool] Executing {block.name} → {mcp_name} with {block.input}")
                    tool_def = _registry.get(mcp_name)
                    if tool_def:
                        result = await tool_def.handler(block.input or {})
                    else:
                        result = {"error": f"Unknown tool: {mcp_name}"}
                    tool_results_map[block.id] = json.dumps(result, default=str, ensure_ascii=False)
                    logger.info(f"[DispatcherTool] {mcp_name} result: {len(tool_results_map[block.id])} chars")

                # If we have dispatcher tools that need results fed back, continue the loop
                if tool_blocks and stop_reason == "tool_use":
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
                        if block.id in tool_results_map:
                            tool_results_content.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": tool_results_map[block.id],
                            })
                        elif block.id in _delegate_validation_errors:
                            # Schema validation failed — send error so LLM can self-correct
                            tool_results_content.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": make_tool_result_error(_delegate_validation_errors[block.id]),
                            })
                        else:
                            # Delegate or unknown — acknowledge
                            tool_results_content.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({"status": "delegated", "message": "Action dispatched to background worker."}),
                            })

                    # Accumulate onto the messages used for THIS round (not the
                    # original clean_messages) so earlier rounds' tool results
                    # stay visible to the model on round 2+.
                    kwargs["messages"] = list(kwargs["messages"]) + [
                        {"role": "assistant", "content": assistant_content},
                        {"role": "user", "content": tool_results_content},
                    ]
                    # Reset streamed text for next round
                    streamed_text_parts = []
                    continue  # Next round of the tool loop

                # No dispatcher tools or not stopped for tool_use — handle delegate continuation
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

                    # Build per-block tool_result (success or validation error)
                    _cont_results = []
                    for block in tool_use_blocks:
                        if block.id in _delegate_validation_errors:
                            _cont_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "is_error": True,
                                "content": make_tool_result_error(_delegate_validation_errors[block.id]),
                            })
                        else:
                            _cont_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": json.dumps({"status": "delegated", "message": "Action dispatched to background worker."}),
                            })

                    # Continue from this round's running message list so tool
                    # results from earlier inline rounds are preserved.
                    continuation_messages = list(kwargs["messages"]) + [
                        {"role": "assistant", "content": assistant_content},
                        {"role": "user", "content": _cont_results},
                    ]

                    # Get the final response (no tools this time — just let Claude finish talking)
                    final_kwargs = {
                        "model": model,
                        "max_tokens": self.max_tokens,
                        "system": system,
                        "messages": continuation_messages,
                    }
                    if extra_headers:
                        final_kwargs["extra_headers"] = extra_headers
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
        import queue
        import threading

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
        extra_headers = self._anthropic_extra_headers(model)
        if extra_headers:
            kwargs["extra_headers"] = extra_headers

        try:
            # Collect streamed content and tool_use blocks
            streamed_text_parts: list[str] = []
            tool_use_blocks: list = []

            # Thread + queue bridge so text tokens reach the user as they
            # arrive instead of buffering the entire response first.
            event_queue: queue.Queue = queue.Queue()

            def _do_stream():
                """Run in thread — pushes (type, data) tuples as they arrive."""
                try:
                    with client.messages.stream(**kwargs) as stream:
                        for text in stream.text_stream:
                            event_queue.put(("text", text))
                        # After stream, inspect final message for tool_use blocks
                        final_msg = stream.get_final_message()
                        for block in final_msg.content:
                            if block.type == "tool_use":
                                event_queue.put(("tool_use", block))
                        event_queue.put(("stop_reason", final_msg.stop_reason))
                        event_queue.put(("usage", final_msg.usage))
                except Exception as e:
                    event_queue.put(("error", e))
                finally:
                    event_queue.put(None)

            threading.Thread(target=_do_stream, daemon=True).start()

            stop_reason = "end_turn"
            stream_usage = None
            while True:
                item = await asyncio.to_thread(event_queue.get)
                if item is None:
                    break
                event_type, data = item
                if event_type == "text":
                    streamed_text_parts.append(data)
                    yield data
                elif event_type == "tool_use":
                    tool_use_blocks.append(data)
                elif event_type == "stop_reason":
                    stop_reason = data
                elif event_type == "usage":
                    stream_usage = data
                elif event_type == "error":
                    raise data

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
                if chat_id:
                    self._last_stream_usage[chat_id] = {
                        "input_tokens": stream_usage.input_tokens,
                        "output_tokens": stream_usage.output_tokens,
                        "cache_creation_input_tokens": getattr(stream_usage, "cache_creation_input_tokens", 0) or 0,
                        "cache_read_input_tokens": getattr(stream_usage, "cache_read_input_tokens", 0) or 0,
                    }

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

                    await invoke_tool_callback(tool_callback, mcp_name, arguments, result)

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
