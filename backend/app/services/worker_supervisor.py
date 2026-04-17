"""Worker Supervisor — tracks worker task activity, detects loops and stalls.

Provides per-task monitoring:
- Tool call recording with repetition detection
- Stall detection (time since last activity)
- Lifecycle enforcement: claim → work → complete (strict protocol)
- Completion tracking via worker.complete / task.complete tools
"""

import logging
import time
from typing import Any, Optional

logger = logging.getLogger("voxyflow.worker_supervisor")


class WorkerSupervisor:
    """Tracks worker task lifecycle: tool calls, repetition, stalls, completion."""

    # Completed/problem tasks older than this are garbage-collected on the next
    # register_task. Keeps long-running servers from holding stale history forever.
    _RETENTION_SECONDS = 3600  # 1 hour
    _HARD_CAP = 2000  # absolute ceiling; evicts oldest regardless of status

    def __init__(self):
        self._tasks: dict[str, dict] = {}

    def _gc_old_tasks(self) -> None:
        """Drop terminal tasks past the retention window, then enforce a hard cap."""
        now = time.time()
        expired = [
            tid for tid, t in self._tasks.items()
            if t.get("status") != "active"
            and (now - t.get("last_activity", now)) > self._RETENTION_SECONDS
        ]
        for tid in expired:
            self._tasks.pop(tid, None)

        if len(self._tasks) > self._HARD_CAP:
            # Sort by last_activity asc, drop oldest until at cap.
            overflow = len(self._tasks) - self._HARD_CAP
            oldest = sorted(
                self._tasks.items(),
                key=lambda kv: kv[1].get("last_activity", 0.0),
            )[:overflow]
            for tid, _ in oldest:
                self._tasks.pop(tid, None)
            logger.warning(
                f"[Supervisor] Hard cap reached — evicted {overflow} oldest tasks"
            )

    def register_task(self, task_id: str) -> None:
        """Start tracking a new task."""
        self._gc_old_tasks()
        self._tasks[task_id] = {
            "last_activity": time.time(),
            "tool_calls": [],
            "status": "active",
            "phase": "spawned",  # spawned → claimed → completing → completed/problem
            "created_at": time.time(),
            "claim_plan": None,
            "claimed_at": None,
            "completion_summary": None,
            "completion_status": None,
            "completion_findings": None,
            "completion_pointers": None,
            "completion_next_step": None,
            "completion_source": None,
        }
        logger.debug(f"[Supervisor] Registered task {task_id}")

    def record_activity(self, task_id: str) -> None:
        """Bump last_activity without recording a tool call (e.g. stream output)."""
        task = self._tasks.get(task_id)
        if task:
            task["last_activity"] = time.time()

    def record_tool_call(self, task_id: str, tool_name: str, params: dict) -> None:
        """Record a tool call for a task. Updates last_activity."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task["last_activity"] = time.time()
        task["tool_calls"].append({
            "tool": tool_name,
            "params": params,
            "timestamp": time.time(),
        })

    # Tools that legitimately repeat with the same params (polling, status checks)
    _POLL_TOOLS = frozenset({"tmux.capture", "tmux.read", "workers_list", "workers_get_result"})

    def check_repetition(self, task_id: str, window: int = 8) -> bool:
        """Check if the same tool+params has been called 4+ times in the last N calls.

        Returns True if a repetitive loop is detected.
        Polling tools (tmux.capture, etc.) are excluded — they legitimately
        repeat with the same params while waiting for command output.
        """
        task = self._tasks.get(task_id)
        if not task:
            return False
        calls = task["tool_calls"]
        if len(calls) < 4:
            return False

        recent = calls[-window:]
        # Build signature for each call (tool + sorted params)
        signatures: list[str] = []
        for c in recent:
            # Skip polling tools — repeated calls are expected
            if c["tool"] in self._POLL_TOOLS:
                continue
            # Normalize params to a stable string for comparison
            try:
                sig = f"{c['tool']}:{sorted(c['params'].items())}"
            except (AttributeError, TypeError):
                sig = f"{c['tool']}:{c['params']}"
            signatures.append(sig)

        # Check if any signature appears 4+ times
        from collections import Counter
        counts = Counter(signatures)
        for sig, count in counts.items():
            if count >= 4:
                logger.warning(
                    f"[Supervisor] Repetition detected for task {task_id}: "
                    f"{sig} called {count} times in last {window} calls"
                )
                return True
        return False

    def check_stall(self, task_id: str) -> float:
        """Returns seconds since last activity for the task. Returns 0 if not tracked."""
        task = self._tasks.get(task_id)
        if not task or task["status"] != "active":
            return 0.0
        return time.time() - task["last_activity"]

    def mark_claimed(self, task_id: str, plan: str) -> None:
        """Record the worker's plan when it claims the task (worker.claim)."""
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"[Supervisor] mark_claimed for unknown task {task_id}")
            return
        if task.get("phase") != "spawned":
            logger.info(
                f"[Supervisor] Task {task_id} re-claimed (phase was {task.get('phase')})"
            )
        task["phase"] = "claimed"
        task["claim_plan"] = plan
        task["claimed_at"] = time.time()
        task["last_activity"] = time.time()
        logger.info(f"[Supervisor] Task {task_id} claimed: plan={plan[:200]!r}")

    def is_claimed(self, task_id: str) -> bool:
        """Has the worker called worker.claim yet?"""
        task = self._tasks.get(task_id)
        return task is not None and task.get("phase") != "spawned"

    def tool_calls_since_register(self, task_id: str) -> int:
        """Count of tool calls recorded for this task (used by claim watchdog)."""
        task = self._tasks.get(task_id)
        return len(task["tool_calls"]) if task else 0

    def mark_completed(
        self,
        task_id: str,
        summary: str,
        status: str = "success",
        findings: Optional[list[str]] = None,
        pointers: Optional[list[dict[str, Any]]] = None,
        next_step: Optional[str] = None,
        source: str = "legacy",
    ) -> None:
        """Mark a task as completed.

        source identifies which path delivered the completion:
        - "worker.complete" — structured payload (preferred)
        - "task.complete"   — legacy summary-only
        - "auto"            — orchestrator fallback
        - "closeout"        — closeout-pass subprocess
        """
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"[Supervisor] mark_completed for unknown task {task_id}")
            return
        task["status"] = "completed"
        task["phase"] = "completed"
        task["completion_summary"] = summary
        task["completion_status"] = status
        task["completion_findings"] = list(findings) if findings else None
        task["completion_pointers"] = list(pointers) if pointers else None
        task["completion_next_step"] = next_step or None
        task["completion_source"] = source
        task["last_activity"] = time.time()
        logger.info(
            f"[Supervisor] Task {task_id} completed ({source}): "
            f"status={status}, summary={summary[:100]}, "
            f"findings={len(findings) if findings else 0}, "
            f"pointers={len(pointers) if pointers else 0}"
        )

    def is_structured_complete(self, task_id: str) -> bool:
        """True only if the worker delivered a structured voxyflow.worker.complete."""
        task = self._tasks.get(task_id)
        return bool(
            task
            and task.get("phase") == "completed"
            and task.get("completion_source") == "worker.complete"
        )

    def get_completion_payload(self, task_id: str) -> Optional[dict[str, Any]]:
        """Return the structured completion payload (for dispatcher injection)."""
        task = self._tasks.get(task_id)
        if not task or task.get("phase") != "completed":
            return None
        return {
            "status": task.get("completion_status") or "success",
            "summary": task.get("completion_summary") or "",
            "findings": task.get("completion_findings") or [],
            "pointers": task.get("completion_pointers") or [],
            "next_step": task.get("completion_next_step"),
            "plan": task.get("claim_plan"),
        }

    def mark_problem(self, task_id: str, reason: str) -> None:
        """Mark a task as having a problem (stall, repetition, missing completion)."""
        task = self._tasks.get(task_id)
        if not task:
            return
        task["status"] = "problem"
        task["problem_reason"] = reason
        logger.warning(f"[Supervisor] Task {task_id} marked as problem: {reason}")

    def get_status(self, task_id: str) -> Optional[dict]:
        """Get current state for a task."""
        return self._tasks.get(task_id)

    def get_active_tasks(self) -> dict[str, dict]:
        """Return all tasks with 'active' status."""
        return {
            tid: task for tid, task in self._tasks.items()
            if task["status"] == "active"
        }

    def is_completed(self, task_id: str) -> bool:
        """Check if a task called task.complete."""
        task = self._tasks.get(task_id)
        return task is not None and task["status"] == "completed"

    def cleanup_task(self, task_id: str) -> None:
        """Remove a task from tracking (after final processing)."""
        self._tasks.pop(task_id, None)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_supervisor: Optional[WorkerSupervisor] = None


def get_worker_supervisor() -> WorkerSupervisor:
    global _supervisor
    if _supervisor is None:
        _supervisor = WorkerSupervisor()
        logger.info("WorkerSupervisor initialized")
    return _supervisor


# ---------------------------------------------------------------------------
# task.complete tool handler (registered as system tool in mcp_server)
# ---------------------------------------------------------------------------

async def handle_task_complete(params: dict) -> dict:
    """Handler for the legacy task.complete MCP tool (kept for back-compat)."""
    task_id = params.get("task_id")
    summary = params.get("summary", "")
    status = params.get("status", "success")

    if not task_id:
        return {"success": False, "error": "task_id is required"}

    if status not in ("success", "partial", "failed"):
        return {"success": False, "error": f"Invalid status: {status}. Must be success|partial|failed"}

    supervisor = get_worker_supervisor()
    supervisor.mark_completed(task_id, summary, status, source="task.complete")

    return {
        "success": True,
        "message": f"Task {task_id} marked as {status}",
        "task_id": task_id,
        "status": status,
    }


# ---------------------------------------------------------------------------
# Strict worker lifecycle: worker.claim + worker.complete
# ---------------------------------------------------------------------------

_MIN_SUMMARY_CHARS = 20  # guard against "ok" / "done" / empty summaries
_MAX_SUMMARY_CHARS = 8_000
_MAX_FINDINGS = 20
_MAX_POINTERS = 20


async def handle_worker_claim(params: dict) -> dict:
    """Handler for the voxyflow.worker.claim MCP tool.

    The worker calls this at the very start of its run to declare a plan.
    The orchestrator uses the claim as a health signal; workers that do not
    claim within the first few tool calls will be flagged by the watchdog.
    """
    task_id = params.get("task_id")
    plan = (params.get("plan") or "").strip()

    if not task_id:
        return {"success": False, "error": "task_id is required"}
    if not plan:
        return {
            "success": False,
            "error": "plan is required — describe what you intend to do in one or two sentences",
        }
    if len(plan) > 2_000:
        plan = plan[:2_000] + "…"

    supervisor = get_worker_supervisor()
    supervisor.mark_claimed(task_id, plan)

    return {
        "success": True,
        "message": f"Task {task_id} claimed. Proceed with the plan; call voxyflow.worker.complete when done.",
        "task_id": task_id,
    }


def _validate_findings(raw: Any) -> tuple[Optional[list[str]], Optional[str]]:
    """Normalise findings to list[str]. Returns (findings, error)."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "findings must be an array of short strings"
    out: list[str] = []
    for item in raw[:_MAX_FINDINGS]:
        if isinstance(item, str) and item.strip():
            out.append(item.strip()[:500])
        elif isinstance(item, dict) and "text" in item:
            text = str(item.get("text", "")).strip()
            if text:
                out.append(text[:500])
    return out, None


def _validate_pointers(raw: Any) -> tuple[Optional[list[dict]], Optional[str]]:
    """Normalise pointers to [{label, offset, length}]. Returns (pointers, error)."""
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "pointers must be an array of {label, offset, length} objects"
    out: list[dict] = []
    for item in raw[:_MAX_POINTERS]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:120]
        offset = item.get("offset")
        length = item.get("length")
        if not label:
            continue
        entry: dict[str, Any] = {"label": label}
        if isinstance(offset, int) and offset >= 0:
            entry["offset"] = offset
        if isinstance(length, int) and length > 0:
            entry["length"] = length
        out.append(entry)
    return out, None


async def handle_worker_complete(params: dict) -> dict:
    """Handler for the voxyflow.worker.complete MCP tool.

    Structured completion payload that replaces the loose task.complete:
    - summary (required, meaningful length)
    - status (success|partial|failed)
    - findings (list of short bullets, optional)
    - pointers (list of {label, offset, length} into the artifact, optional)
    - next_step (one-line suggestion for the dispatcher, optional)
    """
    task_id = params.get("task_id")
    summary = (params.get("summary") or "").strip()
    status = params.get("status", "success")

    if not task_id:
        return {"success": False, "error": "task_id is required"}
    if status not in ("success", "partial", "failed"):
        return {
            "success": False,
            "error": f"Invalid status: {status}. Must be success|partial|failed",
        }
    if not summary:
        return {
            "success": False,
            "error": "summary is required — describe what you actually did and what the dispatcher needs to know",
        }
    if len(summary) < _MIN_SUMMARY_CHARS:
        return {
            "success": False,
            "error": f"summary is too short (<{_MIN_SUMMARY_CHARS} chars) — write a real dispatcher-facing summary, not 'ok' or 'done'",
        }
    if len(summary) > _MAX_SUMMARY_CHARS:
        summary = summary[:_MAX_SUMMARY_CHARS] + "\n[... summary truncated ...]"

    findings, ferr = _validate_findings(params.get("findings"))
    if ferr:
        return {"success": False, "error": ferr}
    pointers, perr = _validate_pointers(params.get("pointers"))
    if perr:
        return {"success": False, "error": perr}

    next_step = (params.get("next_step") or "").strip()
    if len(next_step) > 500:
        next_step = next_step[:500] + "…"

    supervisor = get_worker_supervisor()
    if not supervisor.is_claimed(task_id):
        # Not fatal — log but accept. The worker protocol is claim-first, but
        # if a worker skips claim we still want its structured completion.
        logger.warning(
            f"[Supervisor] Task {task_id} completed without a prior worker.claim"
        )
    supervisor.mark_completed(
        task_id,
        summary,
        status,
        findings=findings,
        pointers=pointers,
        next_step=next_step or None,
        source="worker.complete",
    )

    return {
        "success": True,
        "message": f"Task {task_id} completed ({status}). Result is now delivered to the dispatcher.",
        "task_id": task_id,
        "status": status,
    }
