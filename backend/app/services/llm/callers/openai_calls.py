"""OpenAI-compatible call paths for ApiCallerMixin (proxy fallback + delegate streaming).

Extracted verbatim from api_caller.py. See app.services.llm.callers package
docstring for the self-attribute contract required from the host class.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Callable, Optional

from app.services.llm.model_utils import (
    _is_thinking_model,
    _flatten_system,
    invoke_tool_callback,
    make_think_stream_filter,
)
from app.services.llm.tool_defs import (
    VOXYFLOW_DELEGATE_TOOL,
    _mcp_tool_name_from_claude,
    _call_mcp_tool,
    anthropic_to_openai_tools,
    get_claude_tools,
)
from app.tools.delegate_tool import (
    TOOL_NAME_SAFE as _DELEGATE_TOOL_NAME_SAFE,
    validate_delegate_input,
    make_tool_result_error,
)

from app.services.llm.callers.token_log import _log_token_usage

logger = logging.getLogger(__name__)


class OpenAICallsMixin:
    """OpenAI-compatible call paths (non-streaming, streaming, delegate streaming)."""

    async def _call_api_stream_openai_with_delegate(
        self,
        model: str,
        system: str,
        messages: list[dict],
        client,
        chat_id: str,
    ) -> AsyncIterator[str]:
        """OpenAI-compatible streaming dispatcher with native function-calling.

        Mirrors ``_call_api_stream_with_delegate`` (Anthropic) but uses the OpenAI
        chat.completions tool_calls protocol. Exposes the dispatcher tools + the
        ``delegate_action`` synthetic tool. Dispatcher tool calls are executed
        inline; ``delegate_action`` calls are collected into
        ``self._pending_delegates[chat_id]`` for the orchestrator to spawn workers.
        """
        import queue
        import threading

        clean_messages = [m for m in messages if m.get("role") != "system"]
        if not clean_messages:
            clean_messages = [{"role": "user", "content": "(empty)"}]

        api_messages: list[dict] = [{"role": "system", "content": _flatten_system(system)}]
        api_messages.extend(clean_messages)

        dispatcher_tools = get_claude_tools(role="dispatcher")
        dispatcher_tool_names = {t["name"] for t in dispatcher_tools}
        _all_oi_tools_src = [VOXYFLOW_DELEGATE_TOOL] + dispatcher_tools
        openai_tools = anthropic_to_openai_tools(_all_oi_tools_src)

        max_inline_rounds = 5

        try:
            for _ in range(max_inline_rounds + 1):
                kwargs: dict = {
                    "model": model,
                    "max_tokens": self.max_tokens,
                    "messages": api_messages,
                    "tools": openai_tools,
                    "tool_choice": "auto",
                    "stream": True,
                }
                # Sync .create() blocks on connect + TTFB — keep it off the
                # event loop (a sleeping local endpoint would freeze the backend).
                stream = await asyncio.to_thread(
                    lambda kw=kwargs: client.chat.completions.create(**kw)
                )

                token_queue: queue.Queue[str | None] = queue.Queue()
                streamed_tool_calls: list[dict] = []
                finish_reason_holder: list[str] = []
                content_text_holder: list[str] = []
                think_feed, think_flush = (
                    make_think_stream_filter() if _is_thinking_model(model) else (None, None)
                )

                def _consume_stream():
                    try:
                        for chunk in stream:
                            if not chunk.choices:
                                continue
                            delta = chunk.choices[0].delta
                            finish_reason = chunk.choices[0].finish_reason

                            if delta.content:
                                visible = think_feed(delta.content) if think_feed else delta.content
                                if visible:
                                    content_text_holder.append(visible)
                                    token_queue.put(visible)

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
                        logger.error(f"OpenAI delegate stream consumption error: {e}")
                    finally:
                        if think_flush:
                            tail = think_flush()
                            if tail:
                                content_text_holder.append(tail)
                                token_queue.put(tail)
                        token_queue.put(None)

                thread = threading.Thread(target=_consume_stream, daemon=True)
                thread.start()

                while True:
                    token = await asyncio.to_thread(token_queue.get)
                    if token is None:
                        break
                    yield token

                if not streamed_tool_calls:
                    return

                # Normalize tool_call ids
                normalized_calls: list[dict] = []
                for i, tc in enumerate(streamed_tool_calls):
                    normalized_calls.append({
                        "id": tc["id"] or f"call_{i}",
                        "type": "function",
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    })

                assistant_msg: dict = {
                    "role": "assistant",
                    "content": "".join(content_text_holder) or None,
                    "tool_calls": normalized_calls,
                }
                api_messages.append(assistant_msg)

                from app.tools.registry import get_registry
                _registry = get_registry()

                tool_results: list[dict] = []
                had_dispatcher_tool = False
                for tc in normalized_calls:
                    name = tc["function"]["name"]
                    try:
                        arguments = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        arguments = {}

                    if name in (_DELEGATE_TOOL_NAME_SAFE, "delegate_action"):
                        # Validate strict schema for the new canonical tool name
                        if name == _DELEGATE_TOOL_NAME_SAFE:
                            ok, err = validate_delegate_input(arguments)
                            if not ok:
                                logger.warning(f"[NativeDelegate-OpenAI] Schema validation failed: {err}")
                                tool_results.append({
                                    "role": "tool",
                                    "tool_call_id": tc["id"],
                                    "content": make_tool_result_error(err),
                                })
                                continue
                        self._pending_delegates.setdefault(chat_id, []).append(arguments)
                        logger.info(
                            f"[NativeDelegate-OpenAI] Collected {name}: "
                            f"action={arguments.get('action')}, desc={str(arguments.get('description', arguments.get('summary', '')))[:60]!r}"
                        )
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps({
                                "status": "delegated",
                                "message": "Action dispatched to background worker.",
                            }),
                        })
                        continue

                    if name in dispatcher_tool_names:
                        had_dispatcher_tool = True
                        mcp_name = _mcp_tool_name_from_claude(name)
                        logger.info(f"[DispatcherTool-OpenAI] Executing {name} → {mcp_name} with {arguments}")
                        tool_def = _registry.get(mcp_name)
                        if tool_def:
                            result = await tool_def.handler(arguments or {})
                        else:
                            result = {"error": f"Unknown tool: {mcp_name}"}
                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps(result, default=str, ensure_ascii=False),
                        })
                        continue

                    logger.warning(f"[NativeDelegate-OpenAI] Unexpected tool call: {name} — acknowledging")
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps({"error": f"Unknown tool: {name}"}),
                    })

                api_messages.extend(tool_results)

                # If only delegates were emitted, do one final non-tool turn so the model
                # finishes its text reply naturally — same shape as the Anthropic path.
                if not had_dispatcher_tool:
                    final_kwargs: dict = {
                        "model": model,
                        "max_tokens": self.max_tokens,
                        "messages": api_messages,
                        "stream": True,
                    }
                    # Blocking .create() runs off the event loop (connect + TTFB).
                    final_stream = await asyncio.to_thread(
                        lambda kw=final_kwargs: client.chat.completions.create(**kw)
                    )
                    final_queue: queue.Queue[str | None] = queue.Queue()
                    final_think_feed, final_think_flush = (
                        make_think_stream_filter() if _is_thinking_model(model) else (None, None)
                    )

                    def _consume_final():
                        try:
                            for chunk in final_stream:
                                if not chunk.choices:
                                    continue
                                delta = chunk.choices[0].delta
                                if delta.content:
                                    visible = final_think_feed(delta.content) if final_think_feed else delta.content
                                    if visible:
                                        final_queue.put(visible)
                        except Exception as e:
                            logger.error(f"OpenAI delegate final-turn error: {e}")
                        finally:
                            if final_think_flush:
                                tail = final_think_flush()
                                if tail:
                                    final_queue.put(tail)
                            final_queue.put(None)

                    threading.Thread(target=_consume_final, daemon=True).start()
                    while True:
                        tok = await asyncio.to_thread(final_queue.get)
                        if tok is None:
                            break
                        yield tok
                    return

                # Dispatcher tools were called — loop and let the model continue.

            logger.warning("[NativeDelegate-OpenAI] Inline tool loop exceeded max rounds")

        except Exception as e:
            logger.error(f"OpenAI delegate streaming call failed: {e}")
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
            max_tool_rounds = 20
            for _ in range(max_tool_rounds):
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

                        await invoke_tool_callback(tool_callback, mcp_name, arguments, result)

                        tool_results.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": json.dumps(result, default=str),
                        })

                    api_messages.extend(tool_results)
                    continue

                return choice.message.content or ""

            logger.warning("_call_api_openai: tool loop exceeded %d rounds", max_tool_rounds)
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

            # Sync .create() blocks on connect + TTFB — keep it off the
            # event loop (a sleeping local endpoint would freeze the backend).
            stream = await asyncio.to_thread(
                lambda kw=kwargs: client.chat.completions.create(**kw)
            )

            token_queue: queue.Queue[str | None] = queue.Queue()
            streamed_tool_calls: list[dict] = []
            finish_reason_holder: list[str] = []
            content_text_holder: list[str] = []
            think_feed, think_flush = (
                make_think_stream_filter() if _is_thinking_model(model) else (None, None)
            )

            def _consume_stream():
                try:
                    for chunk in stream:
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        finish_reason = chunk.choices[0].finish_reason

                        if delta.content:
                            visible = think_feed(delta.content) if think_feed else delta.content
                            if visible:
                                content_text_holder.append(visible)
                                token_queue.put(visible)

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
                    if think_flush:
                        tail = think_flush()
                        if tail:
                            content_text_holder.append(tail)
                            token_queue.put(tail)
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

                    await invoke_tool_callback(tool_callback, mcp_name, arguments, result)

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
