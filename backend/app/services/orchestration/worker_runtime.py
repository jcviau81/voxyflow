"""Worker runtime plumbing — execution prompt, tool callback, stall monitor.

These were closures inside ``DeepWorkerPool._execute_event`` capturing the
pool's dicts and the per-task ``cancel_event`` / ``message_queue`` /
``supervisor`` / captured-output list. They are now factories taking those
captures as explicit parameters. Logic is verbatim from worker_pool.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Awaitable, Callable

from app.services.event_bus import ActionIntent

if TYPE_CHECKING:
    from app.services.orchestration.worker_pool import DeepWorkerPool
    from app.services.worker_supervisor import WorkerSupervisor

logger = logging.getLogger("voxyflow.orchestration")

# Accumulate raw tool output — the LLM's text response is often
# a summary; the real content lives in tool_results from file.read,
# system.exec, etc.
_CONTENT_TOOLS = frozenset({"file.read", "file_read", "system.exec", "system_exec"})


def build_execution_prompt(event: ActionIntent) -> str:
    """Assemble the worker execution prompt (lifecycle protocol + context)."""
    intent_lower = (event.intent or "unknown").lower()
    is_move_or_update = any(kw in intent_lower for kw in [
        "move", "update", "change_status", "complete", "finish",
        "start_work", "mark_done", "mark_complete"
    ])

    execution_prompt = (
        f"Execute this action:\n"
        f"Intent: {event.intent}\n"
        f"Summary: {event.summary}\n"
        f"Task ID: {event.task_id}\n"
        f"\nLifecycle (strict):\n"
        f"1. FIRST call voxyflow.worker.claim(task_id=\"{event.task_id}\", plan=\"<one sentence plan>\").\n"
        f"2. Then do the work — use any MCP tools you need. All raw output is captured "
        f"automatically to an artifact; don't try to keep it in your reply.\n"
        f"3. LAST call voxyflow.worker.complete(task_id=\"{event.task_id}\", status=\"success|partial|failed\", "
        f"summary=\"<2-4 sentences in your own words>\", findings=[...], pointers=[{{label, offset, length}}], "
        f"next_step=\"...\"). Stop immediately after.\n"
        f"\nThe summary is the ONLY thing the dispatcher sees. Write it for a reader who has "
        f"not seen the raw output. Use pointers to flag important sections of the artifact.\n"
        f"\n⚠️ worker.complete is what makes your work LAND. If you stop without calling it, "
        f"the dispatcher only gets raw auto-extracted text and treats the task as unfinished — "
        f"so the user re-asks. ALWAYS finish with worker.complete, even on partial/failed work "
        f"(say what you did and why it stopped).\n"
    )

    if is_move_or_update:
        execution_prompt += (
            "\n⚠️ IMPORTANT: This is a MOVE/UPDATE operation on EXISTING cards.\n"
            "1. First call card.list to find the existing card(s) by name\n"
            "2. Then call card.move (for status change) or card.update (for content change)\n"
            "3. Do NOT create new cards — the cards already exist\n\n"
        )
    if event.data:
        action_data = {k: v for k, v in event.data.items()
                       if k not in ("project_context", "card_context")}
        execution_prompt += f"Data: {json.dumps(action_data)}\n"

    _project_ctx = event.data.get("project_context")
    _card_ctx = event.data.get("card_context")
    if _card_ctx and _project_ctx:
        execution_prompt += (
            f"\n## Current Context\n"
            f"You are operating in the context of card \"{_card_ctx.get('title', '?')}\" "
            f"(card_id: {_card_ctx.get('id', '?')}) in workspace \"{_project_ctx.get('title', '?')}\" "
            f"(workspace_id: {_project_ctx.get('id', '?')}).\n"
            f"Card status: {_card_ctx.get('status', '?')} | "
            f"Priority: {_card_ctx.get('priority', '?')}\n"
        )
        if _card_ctx.get("description"):
            execution_prompt += f"Card description: {_card_ctx['description'][:500]}\n"
        execution_prompt += (
            f"Use card_id={_card_ctx.get('id', '?')} for any card operations. "
            f"Use workspace_id={_project_ctx.get('id', '?')} for any workspace operations.\n"
        )
    elif _project_ctx:
        execution_prompt += (
            f"\n## Current Context\n"
            f"You are operating in the context of workspace \"{_project_ctx.get('title', '?')}\" "
            f"(workspace_id: {_project_ctx.get('id', '?')}).\n"
            f"Use workspace_id={_project_ctx.get('id', '?')} for any workspace/card operations.\n"
        )

    return execution_prompt


def resolve_chat_level(event: ActionIntent) -> str:
    """Resolve the effective chat_level for the worker call."""
    chat_level = event.data.get("chat_level", "general")
    if chat_level == "general":
        intent_lower = (event.intent or "unknown").lower()
        if (
            event.data.get("workspace_id")
            or "workspace" in intent_lower
            or "card" in intent_lower
            or "main_board" in intent_lower
            or "mainboard" in intent_lower
        ):
            chat_level = "workspace"
    return chat_level


def make_tool_callback(
    pool: "DeepWorkerPool",
    event: ActionIntent,
    supervisor,
    cancel_event: asyncio.Event,
    captured_tool_outputs: list[str],
) -> Callable[[str, dict, dict], Awaitable[None]]:
    """Build the per-task tool callback.

    Records tool calls against the supervisor, intercepts the worker
    lifecycle tools (claim/complete propagation from the MCP subprocess to
    the main-process supervisor), captures raw output from content-producing
    tools, maintains the pool's tool-event buffers, and emits tool:executed
    WS events.
    """

    async def _tool_callback(tool_name: str, arguments: dict, result: dict):
        supervisor.record_tool_call(event.task_id, tool_name, arguments)

        # Lifecycle interception — the MCP handlers run in a subprocess
        # with their own supervisor instance, so we must propagate
        # claim/complete into the main-process supervisor here.
        # Claude CLI's MCP bridge flattens dots → underscores, and our
        # cli_steerable only restores the first dot, so match against
        # the fully-underscored form.
        _norm = tool_name.replace(".", "_")
        if _norm in ("voxyflow_worker_claim", "worker_claim"):
            wc_task_id = arguments.get("task_id", event.task_id)
            wc_plan = arguments.get("plan", "")
            if wc_plan:
                supervisor.mark_claimed(wc_task_id, wc_plan)
        elif _norm in ("voxyflow_worker_complete", "worker_complete"):
            wc_task_id = arguments.get("task_id", event.task_id)
            wc_summary = (arguments.get("summary") or "").strip()
            wc_status = arguments.get("status", "success")
            wc_findings = arguments.get("findings") or []
            wc_pointers = arguments.get("pointers") or []
            wc_next = arguments.get("next_step") or None
            if wc_summary and wc_status in ("success", "partial", "failed"):
                supervisor.mark_completed(
                    wc_task_id, wc_summary, wc_status,
                    findings=wc_findings if isinstance(wc_findings, list) else None,
                    pointers=wc_pointers if isinstance(wc_pointers, list) else None,
                    next_step=wc_next,
                    source="worker.complete",
                )
        # Capture raw output from content-producing tools.
        # tool_result from CLI is {"content": "<json_string>"} where
        # the json_string is the MCP tool's serialized response.
        if tool_name in _CONTENT_TOOLS and isinstance(result, dict):
            raw = result.get("content", "")
            # Try to parse the JSON to extract the actual content
            parsed = None
            if isinstance(raw, str):
                try:
                    parsed = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    pass
            if isinstance(parsed, dict):
                output = (
                    parsed.get("content")   # file.read
                    or parsed.get("stdout")  # system.exec
                    or parsed.get("output")
                    or ""
                )
            else:
                output = raw  # fallback to raw text
            if isinstance(output, str) and len(output) > 200:
                captured_tool_outputs.append(output)

        # Buffer tool event for dispatcher peek (bounded recent-events window)
        tool_buf = pool._task_tool_events.setdefault(event.task_id, [])
        tool_buf.append({"tool": tool_name, "at": time.time()})
        if len(tool_buf) > pool._MAX_TOOL_EVENTS:
            tool_buf[:] = tool_buf[-pool._MAX_TOOL_EVENTS:]
        # Monotone lifetime counter (not trimmed) for accurate UI display
        pool._task_tool_counts[event.task_id] = pool._task_tool_counts.get(event.task_id, 0) + 1

        if supervisor.check_repetition(event.task_id):
            logger.warning(f"[Supervisor] Cancelling task {event.task_id} — repetitive loop detected")
            supervisor.mark_problem(event.task_id, "repetitive_loop")
            cancel_event.set()

        tool_count = pool._task_tool_counts.get(event.task_id, 0)
        await pool._send_task_event("tool:executed", event.task_id, {
            "tool": tool_name,
            "args": arguments,
            "result": result,
            "sessionId": event.session_id,
            "toolCount": tool_count,
        })

    return _tool_callback


async def stall_monitor(
    event: ActionIntent,
    supervisor,
    cancel_event: asyncio.Event,
    message_queue: asyncio.Queue,
) -> None:
    """Watch a running worker for claim-protocol violations and stalls.

    Nudges the worker once if it skipped voxyflow.worker.claim, warns it when
    it idles past the warning threshold, and cancels it past the stall
    timeout. CLI subprocess liveness (session registry activity) resets the
    stall counter while the process is actively producing output.
    """
    import os
    from app.services.cli_session_registry import get_cli_session_registry

    stall_timeout = int(os.environ.get("WORKER_STALL_TIMEOUT", "1800"))
    stall_warning = int(os.environ.get("WORKER_STALL_WARNING", str(stall_timeout - 300)))
    claim_nudge_after = int(os.environ.get("WORKER_CLAIM_NUDGE_AFTER", "5"))
    warned = False
    claim_nudged = False
    while not cancel_event.is_set():
        await asyncio.sleep(15)

        # Claim watchdog: nudge the worker once if it has called
        # several tools without first calling voxyflow.worker.claim.
        if (
            not claim_nudged
            and not supervisor.is_claimed(event.task_id)
            and supervisor.tool_calls_since_register(event.task_id) >= claim_nudge_after
        ):
            claim_nudged = True
            message_queue.put_nowait(
                "PROTOCOL REMINDER: you have not called voxyflow.worker.claim yet. "
                "Call it NOW with a one-sentence plan before any further actions."
            )
            logger.info(
                f"[Supervisor] Claim nudge sent to task {event.task_id} "
                f"(tool_calls={supervisor.tool_calls_since_register(event.task_id)})"
            )

        # Check supervisor's tool-call-based activity
        stall_secs = supervisor.check_stall(event.task_id)

        # Also check CLI subprocess liveness — the stream loop
        # touches the session registry every ~10s while producing output
        cli_session = get_cli_session_registry().get_by_task_id(event.task_id)
        if cli_session and cli_session.last_activity > 0:
            cli_idle = time.time() - cli_session.last_activity
            if cli_idle < 60:
                # Process is actively producing output — reset stall counter
                supervisor.record_activity(event.task_id)
                stall_secs = min(stall_secs, cli_idle)

        if stall_secs > stall_warning and not warned:
            warned = True
            message_queue.put_nowait(
                f"WARNING: You have been idle for {stall_secs:.0f}s. "
                "Wrap up now and call voxyflow.worker.complete (with a real summary, "
                "findings, and pointers) or you will be cancelled."
            )
        if stall_secs > stall_timeout:
            logger.warning(
                f"[Supervisor] Task {event.task_id} stalled for {stall_secs:.0f}s — cancelling"
            )
            supervisor.mark_problem(event.task_id, f"stalled_{stall_secs:.0f}s")
            cancel_event.set()
            break
