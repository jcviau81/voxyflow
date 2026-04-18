"""CLI rate gate — dual-semaphore concurrency limiter for CLI API calls.

Extracted from ``cli_backend.py`` so the rate-limiting utility can be reused
without pulling in the full backend (subprocess management, streaming parser,
etc.). Module-level singleton is shared across all ``ClaudeCliBackend``
instances via ``get_rate_gate()``.

Environment variables:
  CLI_SESSION_CONCURRENT — max concurrent dispatcher/chat calls (default 5)
  CLI_WORKER_CONCURRENT  — max concurrent worker calls (default 15)
  CLI_MIN_SPACING_MS     — minimum spacing between call starts (default 0)
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)


_CLI_SESSION_CONCURRENT = int(os.environ.get("CLI_SESSION_CONCURRENT", "5"))
_CLI_WORKER_CONCURRENT = int(os.environ.get("CLI_WORKER_CONCURRENT", "15"))
_CLI_MIN_SPACING_MS = int(os.environ.get("CLI_MIN_SPACING_MS", "0"))


class CliRateGate:
    """Dual-semaphore concurrency limiter for CLI API calls.

    Two independent semaphores ensure dispatcher (interactive chat) and
    workers never starve each other:
    - Session semaphore: caps concurrent dispatcher/chat CLI calls.
    - Worker semaphore: caps concurrent worker CLI calls.
    - Minimum spacing prevents burst-spawning multiple calls at once.
    """

    def __init__(
        self,
        session_concurrent: int = _CLI_SESSION_CONCURRENT,
        worker_concurrent: int = _CLI_WORKER_CONCURRENT,
        min_spacing_ms: int = _CLI_MIN_SPACING_MS,
    ):
        self._session_sem = asyncio.Semaphore(session_concurrent)
        self._worker_sem = asyncio.Semaphore(worker_concurrent)
        self._min_spacing = min_spacing_ms / 1000.0
        self._last_call: float = 0.0
        self._spacing_lock = asyncio.Lock()
        self._active: int = 0
        self._active_workers: int = 0
        self.session_concurrent = session_concurrent
        self.worker_concurrent = worker_concurrent
        self.min_spacing_ms = min_spacing_ms
        logger.info(
            f"[RateGate] Initialized: session_concurrent={session_concurrent}, "
            f"worker_concurrent={worker_concurrent}, "
            f"min_spacing={min_spacing_ms}ms"
        )

    async def acquire(self, is_worker: bool = False) -> None:
        """Acquire a slot — blocks if at capacity or too soon after last call.

        Workers acquire the worker semaphore; dispatchers acquire the session
        semaphore. The two pools are independent so they never starve each other.
        """
        if is_worker:
            await self._worker_sem.acquire()
            self._active_workers += 1
        else:
            await self._session_sem.acquire()
        self._active += 1
        # Enforce minimum spacing
        async with self._spacing_lock:
            now = time.monotonic()
            wait = self._min_spacing - (now - self._last_call)
            if wait > 0:
                logger.debug(f"[RateGate] Spacing wait: {wait:.3f}s")
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()

    def release(self, is_worker: bool = False) -> None:
        """Release a slot after the API call completes."""
        self._active -= 1
        if is_worker:
            self._active_workers -= 1
            self._worker_sem.release()
        else:
            self._session_sem.release()

    @property
    def active(self) -> int:
        """Number of currently in-flight calls."""
        return self._active

    @property
    def active_workers(self) -> int:
        """Number of currently in-flight worker calls."""
        return self._active_workers

    @property
    def max_concurrent(self) -> int:
        """Total max concurrent (session + worker) for log compatibility."""
        return self.session_concurrent + self.worker_concurrent


# Module-level singleton — shared across all ClaudeCliBackend instances
_rate_gate: CliRateGate | None = None


def get_rate_gate() -> CliRateGate:
    global _rate_gate
    if _rate_gate is None:
        _rate_gate = CliRateGate()
    return _rate_gate
