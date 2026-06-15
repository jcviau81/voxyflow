"""Ambient context blocks (Live state + Worker activity + Session handoff).

These render at the top of the dynamic context each turn. They replace the
old "worker completion re-triggers a dispatcher turn" flow — Voxy now sees
ambient signals without being forced into a response turn.

Pure module-level functions — no PersonalityService dependency beyond a lazy
lookup of the configured user name in build_session_handoff_block.
"""

from typing import Optional

_STATUS_GLYPH = {
    "success": "✓", "ok": "✓",
    "failed": "✗", "error": "✗",
    "partial": "◐",
    "cancelled": "⊘",
    "timed_out": "⏱",
}


def _fmt_delta_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    mins, sec = divmod(seconds, 60)
    if mins < 60:
        return f"{mins}m{sec:02d}s"
    hours, mins = divmod(mins, 60)
    if hours < 24:
        return f"{hours}h{mins:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours:02d}h"


def build_session_handoff_block(
    recent_messages: Optional[list[dict]] = None,
    *,
    gap_minutes: int = 30,
    min_history: int = 4,
) -> str:
    """Render a "where we left off" block when the dispatcher resumes cold.

    *recent_messages* is the persisted session history (ordered oldest →
    newest) — each item should carry ``role``, ``content``, and a
    ``timestamp`` ISO string. Only triggers when the last **conversational**
    assistant turn is older than *gap_minutes* AND history has at least
    *min_history* messages. Silent otherwise.

    Skips ``type=enrichment`` (memory/system injections) and any other
    non-user-visible messages so an autonomy heartbeat or worker
    enrichment doesn't reset the resume anchor and falsely shrink the gap.

    Timestamp parsing goes through ``time_context.parse_iso_to_aware``,
    which interprets naive legacy timestamps as **local** time, not UTC.
    The previous local-as-UTC bug inflated gaps by the local offset.

    Hard cap: last user + last assistant turn, ~400 chars each.
    """
    if not recent_messages or len(recent_messages) < min_history:
        return ""

    from datetime import datetime, timezone
    from app.services.time_context import parse_iso_to_aware

    def _is_conversational(m: dict) -> bool:
        # Only real chat turns count: skip enrichments, system, and any
        # message that looks like an autonomy/worker side-channel.
        if m.get("type") in ("enrichment", "autonomy", "worker_event", "system"):
            return False
        if not m.get("content"):
            return False
        return m.get("role") in ("user", "assistant")

    last_assistant = None
    last_user = None
    for m in reversed(recent_messages):
        if not _is_conversational(m):
            continue
        role = m.get("role")
        if role == "assistant" and last_assistant is None:
            last_assistant = m
        elif role == "user" and last_user is None:
            last_user = m
        if last_assistant and last_user:
            break

    if not last_assistant:
        return ""

    ts = parse_iso_to_aware(last_assistant.get("timestamp"))
    if not ts:
        return ""
    now = datetime.now(timezone.utc)
    delta_sec = (now - ts).total_seconds()
    if delta_sec < gap_minutes * 60:
        return ""

    def _truncate(text: str, n: int = 400) -> str:
        text = (text or "").strip().replace("\n", " ")
        return text if len(text) <= n else text[: n - 1].rstrip() + "…"

    lines: list[str] = [
        f"## Session handoff (resumed after {_fmt_delta_seconds(int(delta_sec))})",
    ]
    from app.services.personality_service import get_personality_service
    user_name = get_personality_service().get_user_name() or "User"
    if last_user:
        lines.append(f"- Last {user_name} said: {_truncate(last_user.get('content', ''))}")
    lines.append(f"- Last you said: {_truncate(last_assistant.get('content', ''))}")
    lines.append(
        "- Treat this as memory, not an unread message — don't apologise for the gap, "
        "just pick up if the user resumes the thread."
    )
    return "\n".join(lines)


_WORKER_BLOCK_MAX_CHARS = 8000
_PER_WORKER_FINDINGS_MAX = 7
_PER_FINDING_MAX_CHARS = 280
_PER_POINTER_MAX_CHARS = 160


def build_worker_events_block(events: list[dict]) -> str:
    """Render completed worker events with their structured deliverable.

    NOT a turn — an ambient context block prepended to the next dispatcher
    prompt. Each event includes the worker's ``voxyflow.worker.complete``
    payload (summary + findings + pointers + next_step) so Voxy sees the
    actual deliverable up front. Without this, Fast-tier dispatchers tend to
    skip ``workers.get_result`` and answer from the one-line summary alone.

    Hard cap _WORKER_BLOCK_MAX_CHARS protects context budget when many
    workers complete in the same window.
    """
    if not events:
        return ""

    lines: list[str] = ["## Worker activity since your last turn"]
    for ev in events[:10]:
        status = (ev.get("status") or "success").lower()
        glyph = _STATUS_GLYPH.get(status, "•")
        intent = ev.get("intent") or "unknown"
        task_id = ev.get("task_id") or "?"
        completion = ev.get("completion") or None

        # Header line — task identity at a glance.
        lines.append(f"- {glyph} {task_id} — {intent} ({status})")

        if completion:
            summary = (completion.get("summary") or "").strip()
            if summary:
                # Keep summary readable but cap to avoid runaway workers
                # blowing the block. Workers are told (WORKER.md §2a) to
                # write 2–4 compressed sentences.
                if len(summary) > 1200:
                    summary = summary[:1180].rstrip() + "…"
                lines.append(f"  Summary: {summary}")

            findings = completion.get("findings") or []
            if findings:
                lines.append(f"  Findings ({len(findings)}):")
                for f in findings[:_PER_WORKER_FINDINGS_MAX]:
                    text = str(f).strip() if not isinstance(f, dict) else _summarize_finding_dict(f)
                    if len(text) > _PER_FINDING_MAX_CHARS:
                        text = text[: _PER_FINDING_MAX_CHARS - 1].rstrip() + "…"
                    lines.append(f"    • {text}")
                if len(findings) > _PER_WORKER_FINDINGS_MAX:
                    extra = len(findings) - _PER_WORKER_FINDINGS_MAX
                    lines.append(
                        f"    • [+{extra} more — use workers.get_result for full list]"
                    )

            pointers = completion.get("pointers") or []
            if pointers:
                ptr_strs: list[str] = []
                for p in pointers[:6]:
                    if isinstance(p, dict):
                        label = (p.get("label") or "section").strip()
                        offset = p.get("offset")
                        length = p.get("length")
                        bits = [f"`{label}`"]
                        if offset is not None:
                            bits.append(f"@{offset}")
                        if length is not None:
                            bits.append(f"+{length}")
                        chunk = " ".join(bits)
                    else:
                        chunk = str(p)
                    if len(chunk) > _PER_POINTER_MAX_CHARS:
                        chunk = chunk[: _PER_POINTER_MAX_CHARS - 1] + "…"
                    ptr_strs.append(chunk)
                lines.append("  Pointers: " + " · ".join(ptr_strs))

            next_step = (completion.get("next_step") or "").strip()
            if next_step:
                if len(next_step) > 400:
                    next_step = next_step[:380].rstrip() + "…"
                lines.append(f"  Next step: {next_step}")
        else:
            # No structured payload (e.g. failure event) — fall back to the
            # one-line summary so the dispatcher at least knows what happened.
            summary = (ev.get("summary_line") or "").strip()
            tail = summary if summary else "use workers.get_result for details"
            lines.append(f"  {tail[:600]}")

    rendered = "\n".join(lines)
    if len(rendered) > _WORKER_BLOCK_MAX_CHARS:
        rendered = (
            rendered[: _WORKER_BLOCK_MAX_CHARS - 100].rstrip()
            + "\n[... worker block truncated — use workers.list / workers.get_result for the rest ...]"
        )
    return rendered


def _summarize_finding_dict(d: dict) -> str:
    """Render a finding dict as one compact line."""
    # Prefer the most natural keys first; fall back to JSON.
    for key in ("text", "summary", "title", "label"):
        if key in d and d[key]:
            return str(d[key]).strip()
    try:
        import json as _json

        return _json.dumps(d, ensure_ascii=False)
    except Exception:
        return str(d)


def build_live_state_block(
    *,
    active_workers: int,
    next_job: Optional[dict] = None,
    pending_actions: Optional[int] = None,
    cards_updated_today: Optional[int] = None,
    last_user_turn_ago: Optional[str] = None,
    running_worker_intents: Optional[list[str]] = None,
) -> str:
    """Render the ambient "what is currently running" block.

    Silent on any field we don't have data for — don't render `unknown`
    placeholders because that's noise for Voxy. Hard cap ~8 lines, ~300 chars.
    """
    lines: list[str] = ["## Live state"]
    if running_worker_intents:
        # List active workers one per line so Voxy sees *what each is doing*
        # (intent + claim plan), not just a count. Capped at 3 to stay within
        # the block's small budget.
        lines.append(f"- Active workers: {int(active_workers or 0)}")
        for intent in running_worker_intents[:3]:
            lines.append(f"    • {intent}")
        if len(running_worker_intents) > 3:
            lines.append(f"    • +{len(running_worker_intents) - 3} more")
    else:
        lines.append(f"- Active workers: {int(active_workers or 0)}")
    if next_job and next_job.get("name"):
        eta = next_job.get("eta_seconds")
        eta_str = f"in {_fmt_delta_seconds(eta)}" if isinstance(eta, (int, float)) else "scheduled"
        lines.append(f"- Next scheduled job: {next_job['name']} {eta_str}")
    if cards_updated_today is not None and cards_updated_today > 0:
        lines.append(f"- Cards touched today: {cards_updated_today}")
    if last_user_turn_ago:
        lines.append(f"- Last user turn: {last_user_turn_ago} ago")
    if pending_actions is not None:
        if pending_actions > 0:
            lines.append(f"- Pending user actions: {pending_actions}")
        else:
            lines.append("- Pending user actions: (none)")
    return "\n".join(lines)
