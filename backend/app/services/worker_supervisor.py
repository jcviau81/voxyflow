"""Worker Supervisor — tracks worker task activity, detects loops and stalls.

Provides per-task monitoring:
- Tool call recording with repetition detection
- Stall detection (time since last activity)
- Completion tracking via task.complete tool
"""

import logging
import time
from typing import Optional

logger = logging.getLogger("voxyflow.worker_supervisor")


class WorkerSupervisor:
    """Tracks worker task lifecycle: tool calls, repetition, stalls, completion."""

    def __init__(self):
        self._tasks: dict[str, dict] = {}

    def register_task(self, task_id: str) -> None:
        """Start tracking a new task."""
        self._tasks[task_id] = {
            "last_activity": time.time(),
            "tool_calls": [],
            "status": "active",
            "created_at": time.time(),
            "completion_summary": None,
            "completion_status": None,
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

    def mark_completed(self, task_id: str, summary: str, status: str = "success") -> None:
        """Mark a task as completed (called when task.complete tool is invoked)."""
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"[Supervisor] mark_completed for unknown task {task_id}")
            return
        task["status"] = "completed"
        task["completion_summary"] = summary
        task["completion_status"] = status
        task["last_activity"] = time.time()
        logger.info(
            f"[Supervisor] Task {task_id} marked completed: "
            f"status={status}, summary={summary[:100]}"
        )

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
    """Handler for the task.complete MCP tool."""
    task_id = params.get("task_id")
    summary = params.get("summary", "")
    status = params.get("status", "success")

    if not task_id:
        return {"success": False, "error": "task_id is required"}

    if status not in ("success", "partial", "failed"):
        return {"success": False, "error": f"Invalid status: {status}. Must be success|partial|failed"}

    supervisor = get_worker_supervisor()
    supervisor.mark_completed(task_id, summary, status)

    return {
        "success": True,
        "message": f"Task {task_id} marked as {status}",
        "task_id": task_id,
        "status": status,
    }
