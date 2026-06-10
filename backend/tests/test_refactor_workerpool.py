"""Equivalence tests for the worker_pool.py decomposition.

Pins the contracts the split must preserve:
  - worker_pool re-exports (tests + model_resolution import from there)
  - DeepWorkerPool class-attribute aliases for the moved static helpers
  - execution-prompt byte-identity for a representative event
  - tool-callback behavior (lifecycle interception, content capture, buffers)
  - resolve_execution_plan policy guards (haiku→sonnet coding upgrade,
    Claude-alias remap on non-Claude providers)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.event_bus import ActionIntent


def _make_event(**overrides) -> ActionIntent:
    kwargs = dict(
        task_id="task-refactor-1",
        intent_type="complex",
        intent="research topic",
        summary="Investigate the thing",
        data={},
        session_id="sess-refactor",
        complexity="complex",
        model=None,
        callback_depth=0,
    )
    kwargs.update(overrides)
    return ActionIntent(**kwargs)


# ---------------------------------------------------------------------------
# Re-exports — the facade must keep every name external code imports.
# ---------------------------------------------------------------------------


def test_worker_pool_reexports_are_same_objects():
    from app.services.orchestration import worker_pool as wp
    from app.services.orchestration import intent_routing as ir
    from app.services.orchestration import result_formatting as rf

    assert wp.LIGHTWEIGHT_INTENTS is ir.LIGHTWEIGHT_INTENTS
    assert wp.LIGHTWEIGHT_KEYWORDS is ir.LIGHTWEIGHT_KEYWORDS
    assert wp.is_lightweight_intent is ir.is_lightweight_intent
    assert wp.PREVIEW_CHARS == rf.PREVIEW_CHARS == 500
    assert wp.DISPATCHER_PREVIEW_CHARS == rf.DISPATCHER_PREVIEW_CHARS
    assert wp.WS_RESULT_CHARS == rf.WS_RESULT_CHARS
    assert wp._preview is rf._preview
    assert wp._format_result_for_card is rf._format_result_for_card


def test_model_resolution_uses_shared_lightweight_intents():
    from app.services.orchestration import model_resolution as mr
    from app.services.orchestration import intent_routing as ir

    assert mr.LIGHTWEIGHT_INTENTS is ir.LIGHTWEIGHT_INTENTS


def test_deepworkerpool_static_aliases():
    from app.services.orchestration.worker_pool import DeepWorkerPool
    from app.services.orchestration import worker_cards as wc
    from app.services.orchestration import result_formatting as rf

    assert DeepWorkerPool._TRIVIAL_INTENTS is wc._TRIVIAL_INTENTS
    assert DeepWorkerPool._should_auto_create_card is wc._should_auto_create_card
    assert DeepWorkerPool._auto_create_card is wc._auto_create_card
    assert DeepWorkerPool._update_card_status is wc._update_card_status
    assert DeepWorkerPool._ledger_insert is wc._ledger_insert
    assert DeepWorkerPool._ledger_update is wc._ledger_update
    assert DeepWorkerPool._make_short_title is rf._make_short_title


# ---------------------------------------------------------------------------
# Execution prompt — byte identity against the pre-split template.
# ---------------------------------------------------------------------------


def test_execution_prompt_byte_identity_full_context():
    from app.services.orchestration.worker_runtime import build_execution_prompt

    event = _make_event(
        task_id="T-42",
        intent="move_card to done",
        summary="Move the deploy card to done",
        data={
            "workspace_id": "ws-1",
            "project_context": {"id": "ws-1", "title": "Proj"},
            "card_context": {
                "id": "c-9", "title": "Deploy", "status": "todo",
                "priority": "high", "description": "ship it",
            },
        },
    )

    prompt = build_execution_prompt(event)

    expected = (
        "Execute this action:\n"
        "Intent: move_card to done\n"
        "Summary: Move the deploy card to done\n"
        "Task ID: T-42\n"
        "\nLifecycle (strict):\n"
        "1. FIRST call voxyflow.worker.claim(task_id=\"T-42\", plan=\"<one sentence plan>\").\n"
        "2. Then do the work — use any MCP tools you need. All raw output is captured "
        "automatically to an artifact; don't try to keep it in your reply.\n"
        "3. LAST call voxyflow.worker.complete(task_id=\"T-42\", status=\"success|partial|failed\", "
        "summary=\"<2-4 sentences in your own words>\", findings=[...], pointers=[{label, offset, length}], "
        "next_step=\"...\"). Stop immediately after.\n"
        "\nThe summary is the ONLY thing the dispatcher sees. Write it for a reader who has "
        "not seen the raw output. Use pointers to flag important sections of the artifact.\n"
        "\n⚠️ worker.complete is what makes your work LAND. If you stop without calling it, "
        "the dispatcher only gets raw auto-extracted text and treats the task as unfinished — "
        "so the user re-asks. ALWAYS finish with worker.complete, even on partial/failed work "
        "(say what you did and why it stopped).\n"
        "\n⚠️ IMPORTANT: This is a MOVE/UPDATE operation on EXISTING cards.\n"
        "1. First call card.list to find the existing card(s) by name\n"
        "2. Then call card.move (for status change) or card.update (for content change)\n"
        "3. Do NOT create new cards — the cards already exist\n\n"
        + f"Data: {json.dumps({'workspace_id': 'ws-1'})}\n"
        + "\n## Current Context\n"
        "You are operating in the context of card \"Deploy\" "
        "(card_id: c-9) in workspace \"Proj\" "
        "(workspace_id: ws-1).\n"
        "Card status: todo | Priority: high\n"
        "Card description: ship it\n"
        "Use card_id=c-9 for any card operations. "
        "Use workspace_id=ws-1 for any workspace operations.\n"
    )
    assert prompt == expected


def test_resolve_chat_level_upgrades_general_when_workspace_signal():
    from app.services.orchestration.worker_runtime import resolve_chat_level

    assert resolve_chat_level(_make_event(data={})) == "general"
    assert resolve_chat_level(_make_event(data={"workspace_id": "w"})) == "workspace"
    assert resolve_chat_level(
        _make_event(intent="update card X", data={})
    ) == "workspace"
    assert resolve_chat_level(
        _make_event(data={"chat_level": "card"})
    ) == "card"


# ---------------------------------------------------------------------------
# Tool callback — lifecycle interception + content capture + pool buffers.
# ---------------------------------------------------------------------------


class _FakePoolBuffers:
    def __init__(self):
        self._task_tool_events: dict[str, list] = {}
        self._MAX_TOOL_EVENTS = 50
        self._task_tool_counts: dict[str, int] = {}
        self._send_task_event = AsyncMock()


@pytest.mark.asyncio
async def test_tool_callback_captures_content_and_buffers():
    from app.services.orchestration.worker_runtime import make_tool_callback

    pool = _FakePoolBuffers()
    event = _make_event(task_id="T-cb")
    supervisor = MagicMock()
    supervisor.check_repetition.return_value = False
    cancel_event = asyncio.Event()
    captured: list[str] = []

    cb = make_tool_callback(pool, event, supervisor, cancel_event, captured)

    big = "x" * 300
    await cb("file.read", {"path": "/tmp/a"}, {"content": json.dumps({"content": big})})

    assert captured == [big]
    assert pool._task_tool_counts["T-cb"] == 1
    assert pool._task_tool_events["T-cb"][0]["tool"] == "file.read"
    supervisor.record_tool_call.assert_called_once()
    pool._send_task_event.assert_awaited_once()
    args = pool._send_task_event.await_args.args
    assert args[0] == "tool:executed" and args[1] == "T-cb"
    assert not cancel_event.is_set()


@pytest.mark.asyncio
async def test_tool_callback_intercepts_worker_complete():
    from app.services.orchestration.worker_runtime import make_tool_callback

    pool = _FakePoolBuffers()
    event = _make_event(task_id="T-wc")
    supervisor = MagicMock()
    supervisor.check_repetition.return_value = False
    cb = make_tool_callback(pool, event, supervisor, asyncio.Event(), [])

    await cb(
        "voxyflow.worker_complete",
        {"task_id": "T-wc", "summary": "did the thing", "status": "success"},
        {"content": "{}"},
    )

    supervisor.mark_completed.assert_called_once()
    assert supervisor.mark_completed.call_args.args == ("T-wc", "did the thing", "success")


@pytest.mark.asyncio
async def test_tool_callback_repetition_sets_cancel_event():
    from app.services.orchestration.worker_runtime import make_tool_callback

    pool = _FakePoolBuffers()
    event = _make_event(task_id="T-rep")
    supervisor = MagicMock()
    supervisor.check_repetition.return_value = True
    cancel_event = asyncio.Event()
    cb = make_tool_callback(pool, event, supervisor, cancel_event, [])

    await cb("card.list", {}, {"content": "{}"})

    assert cancel_event.is_set()
    supervisor.mark_problem.assert_called_once_with("T-rep", "repetitive_loop")


# ---------------------------------------------------------------------------
# resolve_execution_plan — policy guards survive the move.
# ---------------------------------------------------------------------------


@pytest.fixture
def _no_worker_class(monkeypatch):
    """Force 'no worker class matched / no default-worker override' settings."""
    import app.services.llm.worker_class_resolver as wcr
    import app.services.settings_loader as sl
    from app.services.orchestration import worker_model_routing as wmr

    monkeypatch.setattr(wcr, "resolve_by_id", AsyncMock(return_value=None))
    monkeypatch.setattr(wcr, "resolve_by_intent", AsyncMock(return_value=None))
    monkeypatch.setattr(sl, "get_default_worker_effort", lambda: "")
    monkeypatch.setattr(sl, "get_default_worker_provider_type", lambda: "")
    monkeypatch.setattr(sl, "get_default_worker_endpoint_id", lambda: "")
    monkeypatch.setattr(wmr, "get_default_worker_model", lambda: "sonnet")
    return wmr


@pytest.mark.asyncio
async def test_resolve_execution_plan_default_model(_no_worker_class):
    wmr = _no_worker_class
    event = _make_event(intent="research topic", model=None)
    plan = await wmr.resolve_execution_plan(event)
    assert plan.effective_model == "sonnet"
    assert plan.endpoint_config is None
    assert plan.worker_class is None
    assert plan.effort == ""


@pytest.mark.asyncio
async def test_resolve_execution_plan_haiku_coding_guard(_no_worker_class):
    wmr = _no_worker_class
    event = _make_event(intent="fix_login_bug", summary="fix it", model="haiku")
    plan = await wmr.resolve_execution_plan(event)
    assert plan.effective_model == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_resolve_execution_plan_remaps_claude_alias_on_foreign_provider(
    monkeypatch, _no_worker_class,
):
    wmr = _no_worker_class
    import app.services.llm.worker_class_resolver as wcr
    import app.services.settings_loader as sl

    # Default worker explicitly routed to a codex endpoint with its own model.
    monkeypatch.setattr(sl, "get_default_worker_provider_type", lambda: "codex")
    monkeypatch.setattr(
        wcr, "resolve_endpoint_for_class",
        AsyncMock(return_value={"provider_type": "codex", "url": ""}),
    )
    monkeypatch.setattr(wmr, "get_default_worker_model", lambda: "gpt-5.3-codex")

    event = _make_event(intent="research topic", model="sonnet")
    plan = await wmr.resolve_execution_plan(event)

    # "sonnet" is a Claude alias — must be remapped to the provider-native model.
    assert plan.effective_model == "gpt-5.3-codex"
    assert plan.endpoint_config == {"provider_type": "codex", "url": ""}
    assert event.data["_resolved_worker_model"] == "gpt-5.3-codex"


# ---------------------------------------------------------------------------
# extract_follow_up — structured follow_up passthrough.
# ---------------------------------------------------------------------------


def test_extract_follow_up_json_and_plain():
    from app.services.orchestration.worker_completion import extract_follow_up

    fu, rc = extract_follow_up(json.dumps({"follow_up": "do next", "result": "done"}))
    assert fu == "do next"
    assert rc == "done"

    fu2, rc2 = extract_follow_up("plain text result")
    assert fu2 is None
    assert rc2 == "plain text result"
