"""API caller mixin for ClaudeService — Anthropic, OpenAI-compat, and server-tools paths.

Extracted from claude_service.py. Relies on self attributes from ClaudeService:
  self.deep_model, self.fast_model, self.haiku_model
  self.max_tokens, self.max_tokens_opus, self.max_tokens_sonnet, self.max_tokens_haiku
  self.fast_client, self.fast_client_type
  self._infer_layer(), self._load_tool_settings(), self._should_use_server_tools()
  self._pending_delegates
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from app.services.llm.model_utils import (
    _strip_think_tags,
    _is_thinking_model,
    _inject_no_think,
)
from app.services.llm.tool_defs import (
    DELEGATE_ACTION_TOOL,
    INLINE_TOOLS,
    _INLINE_TOOL_NAMES,
    _execute_inline_tool,
    _mcp_tool_name_from_claude,
    _call_mcp_tool,
    get_claude_tools,
)

logger = logging.getLogger(__name__)

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


def _flatten_system(system: str | list[dict]) -> str:
    """Convert system content blocks back to a plain string (for non-Anthropic paths)."""
    if isinstance(system, str):
        return system
    return "\n\n".join(block["text"] for block in system if block.get("text"))


class ApiCallerMixin:
    """Mixin providing all _call_api_* methods for ClaudeService."""

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
                            except Exception as e:
                                logger.debug("tool_callback raised (non-fatal): %s", e)

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
                        except Exception as e:
                            logger.debug("tool_callback raised (non-fatal): %s", e)

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
            for _ in range(20):
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
                            except Exception as e:
                                logger.debug("tool_callback raised (non-fatal): %s", e)

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
                        except Exception as e:
                            logger.debug("tool_callback raised (non-fatal): %s", e)

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
        except Exception as e:
            logger.warning("Failed to load tool settings: %s", e)
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
                except Exception as e:
                    logger.debug("tool_callback raised (non-fatal): %s", e)

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
                    except Exception as e:
                        logger.debug("tool_callback raised (non-fatal): %s", e)

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
