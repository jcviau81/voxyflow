"""Server-side tool-handling call paths for ApiCallerMixin (XML <tool_call> loop).

Extracted verbatim from api_caller.py. See app.services.llm.callers package
docstring for the self-attribute contract required from the host class.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator, Callable, Optional

from app.services.llm.model_utils import (
    _strip_think_tags,
    _is_thinking_model,
    _inject_no_think,
    invoke_tool_callback,
    make_think_stream_filter,
)

from app.services.llm.callers.token_log import _log_token_usage

logger = logging.getLogger(__name__)


class ServerToolsCallsMixin:
    """Server-side tool execution loop for providers without native tool support."""

    # ------------------------------------------------------------------
    # Internal: Server-side tool handling (for proxy / generic providers)
    # ------------------------------------------------------------------

    def _load_tool_settings(self) -> dict:
        """Load tool settings from settings.json."""
        import os
        from pathlib import Path
        settings_path = Path(os.environ.get("VOXYFLOW_DATA_DIR", str(Path.home() / ".voxyflow"))) / "settings.json"
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
                    for _tc, _result in zip(tool_calls, results):
                        await invoke_tool_callback(tool_callback, _tc.name, _tc.arguments, _result)
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
            for tc, result in zip(tool_calls, results):
                await invoke_tool_callback(tool_callback, tc.name, tc.arguments, result)

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
        think_feed, think_flush = (
            make_think_stream_filter() if _is_thinking_model(model) else (None, None)
        )

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
                        visible = think_feed(delta.content) if think_feed else delta.content
                        if visible:
                            content_parts.append(visible)
                            token_queue.put(visible)
            except Exception as e:
                logger.error(f"Server-tools stream error: {e}")
            finally:
                if think_flush:
                    tail = think_flush()
                    if tail:
                        content_parts.append(tail)
                        token_queue.put(tail)
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

        for tc, result in zip(tool_calls, results):
            await invoke_tool_callback(tool_callback, tc.name, tc.arguments, result)

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
                # Final text response — yield it (strip <think> reasoning for
                # thinking models, mirroring the non-streaming sibling)
                final_text = _strip_think_tags(response_text) if _is_thinking_model(model) else response_text
                if final_text:
                    yield "\n\n" + final_text
                return

            results = await executor.execute_batch(tool_calls, timeout=timeout_per_tool)

            for tc, result in zip(tool_calls, results):
                await invoke_tool_callback(tool_callback, tc.name, tc.arguments, result)

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
