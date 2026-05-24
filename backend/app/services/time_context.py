"""Time / timezone helpers for prompt injection.

The dispatcher needs to know wall-clock "now" and to surface message
timestamps so the model can reason about elapsed time ("ce matin",
"il y a 2h", "hier soir") without hallucinating.

A single source of truth lives here — used by:
- ``personality_service.build_dynamic_context_block`` (current-time block)
- ``claude_service._get_windowed_history`` (per-message timestamp prefix)
- ``personality_service.build_session_handoff_block`` (resume-gap calc)
- ``session_store.save_message`` (timestamp default)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover — zoneinfo is stdlib on 3.9+
    ZoneInfo = None  # type: ignore


_FALLBACK_TZ = "America/Toronto"


def _settings_tz_name() -> str:
    """Resolve the configured timezone, falling back to America/Toronto.

    Imported lazily so this module stays importable from places that load
    before Settings is wired up (e.g. test harnesses).
    """
    try:
        from app.config import get_settings
        return get_settings().voxyflow_timezone or _FALLBACK_TZ
    except Exception:
        return _FALLBACK_TZ


def get_local_tz():
    """Return a tzinfo for the configured local timezone.

    Falls back to UTC if zoneinfo can't resolve the name (e.g. tzdata
    missing on a stripped-down container).
    """
    name = _settings_tz_name()
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:
        return timezone.utc


def now_local() -> datetime:
    """Aware ``datetime`` in the configured local timezone."""
    return datetime.now(get_local_tz())


def parse_iso_to_aware(raw: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp into an aware UTC datetime.

    Accepts:
    - aware ISO with offset (``2026-05-08T14:32:00+00:00``)
    - ``Z`` suffix (``2026-05-08T14:32:00Z``)
    - space-separator variant (``2026-05-08 14:32:00.123456``)
    - **naive** ISO with no offset — interpreted as **local** time, not UTC

    Naive-as-local is the important one: legacy session_store rows used
    ``datetime.now().isoformat()`` which is naive local. Treating those
    as UTC inflates resume gaps by the local offset (and shows e.g. a
    real 1h gap as 5h on America/Toronto in winter).
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # Accept "YYYY-MM-DD HH:MM:SS" by normalising the separator.
    if "T" not in s and " " in s:
        s = s.replace(" ", "T", 1)
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        # Legacy: naive timestamps from ``datetime.now().isoformat()`` are
        # local wall-clock. Anchor them to the configured local tz, then
        # normalise to UTC so callers can subtract from ``datetime.now(utc)``.
        dt = dt.replace(tzinfo=get_local_tz())
    return dt.astimezone(timezone.utc)


def format_now_block() -> str:
    """Render the "## Current time" prompt block.

    Designed for the dispatcher dynamic-context block — kept short so it
    doesn't crowd memory/workspace context. Includes weekday + ISO date +
    HH:MM in local tz + tz name; that's enough to ground "ce matin",
    "vendredi soir", "il y a 2h" without ambiguity.
    """
    n = now_local()
    weekday = n.strftime("%A")
    date_iso = n.strftime("%Y-%m-%d")
    hhmm = n.strftime("%H:%M")
    tz_abbrev = n.strftime("%Z") or _settings_tz_name()
    tz_name = _settings_tz_name()
    return (
        "## Current time\n"
        f"{weekday} {date_iso} {hhmm} {tz_abbrev} ({tz_name})"
    )


def format_message_timestamp(raw: Optional[str]) -> str:
    """Render a per-message timestamp prefix, e.g. ``2026-05-08 14:32 EDT``.

    Returns an empty string if *raw* can't be parsed — caller should
    short-circuit and skip the prefix rather than emit garbage.
    """
    dt = parse_iso_to_aware(raw)
    if dt is None:
        return ""
    local = dt.astimezone(get_local_tz())
    tz_abbrev = local.strftime("%Z") or ""
    base = local.strftime("%Y-%m-%d %H:%M")
    return f"{base} {tz_abbrev}".rstrip()


def utc_now_iso() -> str:
    """Aware UTC ISO string suitable for storage.

    New code should write timestamps via this helper so the parser side
    never has to guess timezone — the offset is in the string.
    """
    return datetime.now(timezone.utc).isoformat()
