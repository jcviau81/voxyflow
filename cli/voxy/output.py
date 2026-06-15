"""Shared rich output helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from rich.console import Console

console = Console()


def print_json(data: Any) -> None:
    """Plain JSON to stdout for scripting (no rich markup)."""
    print(json.dumps(data, indent=2, default=str))


def fmt_age(iso_ts: str | None) -> str:
    """Human age from an ISO timestamp (assumes UTC when naive)."""
    if not iso_ts:
        return "-"
    try:
        ts = datetime.fromisoformat(iso_ts)
    except ValueError:
        return "-"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - ts).total_seconds()
    if secs < 0:
        secs = 0
    if secs < 60:
        return f"{int(secs)}s"
    if secs < 3600:
        return f"{int(secs // 60)}m"
    if secs < 86400:
        return f"{secs / 3600:.1f}h"
    return f"{secs / 86400:.1f}d"


STATUS_COLORS = {
    "running": "yellow",
    "pending": "cyan",
    "done": "green",
    "failed": "red",
    "cancelled": "dim",
    "active": "green",
    "archived": "dim",
}


def fmt_status(status: str | None) -> str:
    s = status or "-"
    color = STATUS_COLORS.get(s)
    return f"[{color}]{s}[/{color}]" if color else s
