"""Transient-error retry + rate-limit-event parsing for the Claude CLI.

The CLI occasionally fails with transient errors (ECONNRESET, 529 overloaded,
spawn EAGAIN, etc.) that clear on a second attempt. This module supplies:

- ``is_transient_error(stderr, returncode)``: pattern match on stderr.
- ``parse_rate_limit_event(msg)``: extract ``{status, resets_at}`` from a
  stream-json ``rate_limit_event`` line.
- ``compute_backoff(attempt)``: exponential backoff with jitter.

The retry loop itself lives in ``cli_backend.py`` where it has access to the
subprocess and gate. This module is stateless so it can be unit-tested without
spawning subprocesses.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from typing import Optional

# Patterns that indicate a transient CLI failure worth retrying.
# Kept in sync with the equivalent list in jinn's engines/claude.ts.
_TRANSIENT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ECONNRESET",
        r"ETIMEDOUT",
        r"socket hang up",
        r"\b503\b",
        r"\b529\b",
        r"overloaded",
        r"rate limit",
        r"spawn.*EAGAIN",
    )
)

MAX_RETRIES = 2
_BASE_DELAY_S = 1.0


def is_transient_error(stderr: str, returncode: Optional[int]) -> bool:
    """Return True if the CLI failure is likely transient.

    Exit code 1 with near-empty stderr is often a transient crash (the CLI
    sometimes dies before writing anything useful). Otherwise match stderr
    against the transient patterns.
    """
    if returncode == 1 and len(stderr.strip()) < 10:
        return True
    return any(p.search(stderr) for p in _TRANSIENT_PATTERNS)


def compute_backoff(attempt: int) -> float:
    """Exponential backoff in seconds with ±20% jitter. attempt is 1-indexed."""
    base = _BASE_DELAY_S * (2 ** (attempt - 1))
    jitter = base * 0.2 * (random.random() * 2 - 1)
    return max(0.1, base + jitter)


@dataclass(frozen=True)
class RateLimitInfo:
    """Normalised rate-limit telemetry from a stream-json event."""
    status: str                # "allowed" | "allowed_warning" | "rejected"
    resets_at: Optional[float] # unix seconds, or None if unknown
    source: str = "stream"     # "stream" | "stderr"

    @property
    def is_rejected(self) -> bool:
        return self.status == "rejected"

    @property
    def cooldown_s(self) -> float:
        """Seconds until the limit resets (0 if already past / unknown)."""
        if self.resets_at is None:
            return 0.0
        return max(0.0, self.resets_at - time.time())


def parse_rate_limit_event(msg: dict) -> Optional[RateLimitInfo]:
    """Parse a stream-json ``rate_limit_event`` message.

    The CLI emits events shaped like::

        {"type": "rate_limit_event", "rate_limit_info": {
            "status": "rejected" | "allowed_warning" | "allowed",
            "resets_at": 1713916800,  # unix seconds
            ...
        }}

    Returns ``None`` if the message is not a rate_limit_event or is malformed.
    """
    if not isinstance(msg, dict) or msg.get("type") != "rate_limit_event":
        return None
    info = msg.get("rate_limit_info")
    if not isinstance(info, dict):
        return None
    status = str(info.get("status") or "").lower()
    if not status:
        return None
    resets_at_raw = info.get("resets_at")
    resets_at: Optional[float]
    try:
        resets_at = float(resets_at_raw) if resets_at_raw is not None else None
    except (TypeError, ValueError):
        resets_at = None
    return RateLimitInfo(status=status, resets_at=resets_at, source="stream")
