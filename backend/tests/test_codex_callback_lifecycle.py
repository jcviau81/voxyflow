"""Tests for the Codex backend's ``tool_callback`` dispatch path.

Codex emits two flavours of "tool" events:

1. ``item.completed`` with ``item.type == "mcp_tool_call"`` — first-class
   MCP invocations. The raw tool name (``mcp__voxyflow__file_read``) must be
   mapped back to the Voxyflow dotted form (``file.read``) via
   ``_codex_tool_name_to_mcp`` before reaching ``tool_callback``.

2. ``agent_message`` fenced JSON blocks shaped like
   ``{"voxyflow_worker_complete": {...}}`` — used by Codex workers that do
   not have the lifecycle MCP tools loaded. These should be flattened into
   ``voxyflow.worker.complete`` callback invocations carrying the structured
   payload (summary / findings / pointers / next_step).

Both flavours flow through ``_handle_event`` / ``_emit_lifecycle_blocks`` so
the tests drive those methods directly rather than spawning subprocesses.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.services.llm import codex_backend as cb


def _make_backend() -> cb.CodexCliBackend:
    backend = cb.CodexCliBackend.__new__(cb.CodexCliBackend)
    backend._configured_cli_path = "codex"
    backend._last_usage = {}
    backend._last_thread_id = ""
    backend._thread_ids_by_chat = {}
    return backend


# ---------------------------------------------------------------------------
# (Test 3) _codex_tool_name_to_mcp — name mapping
# ---------------------------------------------------------------------------


class TestCodexToolNameMapping:
    def test_basic_local_tool(self):
        assert cb._codex_tool_name_to_mcp("mcp__voxyflow__file_read") == "file.read"

    def test_system_exec(self):
        assert cb._codex_tool_name_to_mcp("mcp__voxyflow__system_exec") == "system.exec"

    def test_worker_lifecycle_tools_keep_dotted_form(self):
        assert (
            cb._codex_tool_name_to_mcp("mcp__voxyflow__voxyflow_worker_claim")
            == "voxyflow.worker.claim"
        )
        assert (
            cb._codex_tool_name_to_mcp("mcp__voxyflow__voxyflow_worker_complete")
            == "voxyflow.worker.complete"
        )

    def test_voxyflow_card_actions(self):
        # The tool name in the MCP server is `voxyflow.card` (single tool with
        # action arg). Codex reports it as `mcp__voxyflow__voxyflow_card`.
        assert (
            cb._codex_tool_name_to_mcp("mcp__voxyflow__voxyflow_card")
            == "voxyflow.card"
        )

    def test_workers_read_artifact_namespace(self):
        assert (
            cb._codex_tool_name_to_mcp("mcp__voxyflow__voxyflow_workers_read_artifact")
            == "voxyflow.workers.read_artifact"
        )

    def test_already_dotted_passthrough(self):
        # If Codex (or a different MCP wiring) reports the dotted form already,
        # it should round-trip unchanged.
        assert cb._codex_tool_name_to_mcp("file.read") == "file.read"

    def test_empty_returns_fallback(self):
        assert cb._codex_tool_name_to_mcp("") == "mcp.tool"
        assert cb._codex_tool_name_to_mcp("   ") == "mcp.tool"


# ---------------------------------------------------------------------------
# (Test 3 cont.) _handle_event dispatches mcp_tool_call through the mapper
# ---------------------------------------------------------------------------


class TestMcpToolCallDispatch:
    async def test_mcp_tool_call_event_maps_name_before_callback(self):
        backend = _make_backend()
        received: list[tuple[str, dict, dict]] = []

        def cb_fn(name, args, result):
            received.append((name, args, result))

        event = {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "tool": "mcp__voxyflow__file_read",
                "arguments": {"path": "/tmp/x", "limit": 10},
                "result": {"content": "hello", "lines": 1},
                "status": "completed",
            },
        }
        await backend._handle_event(event, [], {}, cb_fn)

        assert len(received) == 1
        name, args, result = received[0]
        assert name == "file.read"
        assert args == {"path": "/tmp/x", "limit": 10}
        # Result is JSON-serialised back into ``content``.
        assert json.loads(result["content"]) == {"content": "hello", "lines": 1}
        assert result["is_error"] is False
        assert result["status"] == "completed"

    async def test_mcp_tool_call_error_flag_propagates(self):
        backend = _make_backend()
        received: list[tuple[str, dict, dict]] = []

        def cb_fn(name, args, result):
            received.append((name, args, result))

        event = {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "tool": "mcp__voxyflow__voxyflow_card",
                "arguments": {"action": "list"},
                "error": "workspace not found",
                "status": "failed",
            },
        }
        await backend._handle_event(event, [], {}, cb_fn)
        assert received[0][0] == "voxyflow.card"
        assert received[0][2]["is_error"] is True
        assert received[0][2]["error"] == "workspace not found"

    async def test_mcp_tool_call_with_async_callback_is_awaited(self):
        backend = _make_backend()
        seen: list[str] = []

        async def async_cb(name, args, result):
            await asyncio.sleep(0)
            seen.append(name)

        event = {
            "type": "item.completed",
            "item": {
                "type": "mcp_tool_call",
                "tool": "mcp__voxyflow__voxyflow_worker_claim",
                "arguments": {"task_id": "T1", "plan": "x"},
                "status": "completed",
            },
        }
        await backend._handle_event(event, [], {}, async_cb)
        assert seen == ["voxyflow.worker.claim"]

    async def test_command_execution_dispatches_codex_command(self):
        """``command_execution`` items are routed under a synthetic
        ``codex.command`` tool name so the worker pool can record them."""
        backend = _make_backend()
        received: list[tuple[str, dict, dict]] = []

        def cb_fn(name, args, result):
            received.append((name, args, result))

        event = {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "ls -la",
                "aggregated_output": "total 0",
                "exit_code": 0,
                "status": "completed",
            },
        }
        await backend._handle_event(event, [], {}, cb_fn)
        assert received[0][0] == "codex.command"
        assert received[0][1] == {"command": "ls -la"}
        assert received[0][2]["exit_code"] == 0


# ---------------------------------------------------------------------------
# (Test 2) _emit_lifecycle_blocks — fenced JSON → worker.complete callback
# ---------------------------------------------------------------------------


COMPLETE_TEXT_TEMPLATE = """Sure, here's the result:

```json
{json_block}
```

Done."""


class TestLifecycleBlockExtraction:
    async def test_worker_complete_block_emits_structured_payload(self):
        backend = _make_backend()
        received: list[tuple[str, dict, dict]] = []

        def cb_fn(name, args, result):
            received.append((name, args, result))

        payload = {
            "voxyflow_worker_complete": {
                "task_id": "task-42",
                "status": "success",
                "summary": "Refactored auth handler and ran the smoke test.",
                "findings": ["fixed bug X", "added test Y"],
                "pointers": [{"label": "diff", "offset": 0, "length": 500}],
                "next_step": "Open PR",
            }
        }
        text = COMPLETE_TEXT_TEMPLATE.format(json_block=json.dumps(payload))
        await backend._emit_lifecycle_blocks(text, cb_fn)

        assert len(received) == 1
        name, args, _ = received[0]
        assert name == "voxyflow.worker.complete"
        assert args["task_id"] == "task-42"
        assert args["status"] == "success"
        assert args["findings"] == ["fixed bug X", "added test Y"]
        assert args["pointers"][0]["label"] == "diff"
        assert args["next_step"] == "Open PR"

    async def test_worker_claim_block_emits_callback_too(self):
        backend = _make_backend()
        received: list[str] = []

        def cb_fn(name, args, result):
            received.append(name)

        payload = {"voxyflow_worker_claim": {"task_id": "T9", "plan": "do the thing"}}
        text = f"```json\n{json.dumps(payload)}\n```"
        await backend._emit_lifecycle_blocks(text, cb_fn)
        assert received == ["voxyflow.worker.claim"]

    async def test_no_voxyflow_marker_short_circuits(self):
        backend = _make_backend()
        received: list[str] = []

        def cb_fn(name, args, result):
            received.append(name)

        # Text contains a JSON block but no `voxyflow_worker_` marker, so the
        # regex scan is skipped entirely.
        await backend._emit_lifecycle_blocks(
            'Here is some output:\n```json\n{"x": 1}\n```',
            cb_fn,
        )
        assert received == []

    async def test_malformed_json_block_is_ignored(self):
        backend = _make_backend()
        received: list[str] = []

        def cb_fn(name, args, result):
            received.append(name)

        # The marker is present so we enter the scanner, but the JSON is bad.
        text = "voxyflow_worker_complete\n```json\n{not valid json\n```"
        await backend._emit_lifecycle_blocks(text, cb_fn)
        assert received == []

    async def test_lifecycle_block_supports_async_callback(self):
        backend = _make_backend()
        received: list[str] = []

        async def async_cb(name, args, result):
            await asyncio.sleep(0)
            received.append(name)

        payload = {"voxyflow_worker_complete": {"task_id": "T1", "status": "success", "summary": "x"}}
        text = f"```json\n{json.dumps(payload)}\n```"
        await backend._emit_lifecycle_blocks(text, async_cb)
        assert received == ["voxyflow.worker.complete"]

    async def test_agent_message_event_invokes_lifecycle_extractor(self):
        """End-to-end: an ``agent_message`` item carrying a fenced
        ``voxyflow_worker_complete`` block should trigger the same
        callback the structured MCP path would emit."""
        backend = _make_backend()
        received: list[tuple[str, dict]] = []

        def cb_fn(name, args, result):
            received.append((name, args))

        payload = {
            "voxyflow_worker_complete": {
                "task_id": "T7",
                "status": "success",
                "summary": "All done.",
            }
        }
        text = f"Here you go:\n```json\n{json.dumps(payload)}\n```"
        event = {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": text},
        }
        response_parts: list[str] = []
        await backend._handle_event(event, response_parts, {}, cb_fn)

        # The lifecycle callback fired ...
        assert len(received) == 1
        assert received[0][0] == "voxyflow.worker.complete"
        assert received[0][1]["task_id"] == "T7"
        # ... AND the raw text was appended to the response (so the dispatcher
        # still gets the worker's narration alongside the structured payload).
        assert any("All done." in part for part in response_parts)
