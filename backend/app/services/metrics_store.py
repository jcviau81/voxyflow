"""
In-memory metrics store for Voxyflow.

Tracks:
- HTTP request latencies (ring buffer, last 200 requests)
- System resource snapshots (CPU, RAM, process)
- Slow request log (requests > SLOW_THRESHOLD_MS)

Consumed by /api/metrics endpoint and the heartbeat scheduler job.
Thread-safe for asyncio (single-threaded event loop writes, no locks needed).
"""

import time
from collections import deque
from typing import Optional

SLOW_THRESHOLD_MS = 500
_MAX_REQUESTS = 200
_MAX_SLOW = 50
_MAX_RESOURCE_SNAPSHOTS = 30  # 1 per heartbeat ≈ 1 hour


class RequestRecord:
    __slots__ = ("path", "method", "status_code", "duration_ms", "ts")

    def __init__(self, path: str, method: str, status_code: int, duration_ms: float):
        self.path = path
        self.method = method
        self.status_code = status_code
        self.duration_ms = duration_ms
        self.ts = time.time()


class ResourceSnapshot:
    __slots__ = ("cpu_pct", "ram_used_mb", "ram_total_mb", "ram_pct", "process_ram_mb", "ts")

    def __init__(self, cpu_pct: float, ram_used_mb: float, ram_total_mb: float,
                 ram_pct: float, process_ram_mb: float):
        self.cpu_pct = cpu_pct
        self.ram_used_mb = ram_used_mb
        self.ram_total_mb = ram_total_mb
        self.ram_pct = ram_pct
        self.process_ram_mb = process_ram_mb
        self.ts = time.time()


class MetricsStore:
    def __init__(self):
        self._requests: deque[RequestRecord] = deque(maxlen=_MAX_REQUESTS)
        self._slow: deque[RequestRecord] = deque(maxlen=_MAX_SLOW)
        self._resources: deque[ResourceSnapshot] = deque(maxlen=_MAX_RESOURCE_SNAPSHOTS)

    def record_request(self, path: str, method: str, status_code: int, duration_ms: float) -> None:
        rec = RequestRecord(path, method, status_code, duration_ms)
        self._requests.append(rec)
        if duration_ms >= SLOW_THRESHOLD_MS:
            self._slow.append(rec)

    def record_resources(self, snap: ResourceSnapshot) -> None:
        self._resources.append(snap)

    def summary(self) -> dict:
        reqs = list(self._requests)
        slow = list(self._slow)
        snaps = list(self._resources)

        # Per-route aggregation
        by_route: dict[str, list[float]] = {}
        for r in reqs:
            key = f"{r.method} {r.path}"
            by_route.setdefault(key, []).append(r.duration_ms)

        route_stats = []
        for route, durations in sorted(by_route.items()):
            durations_sorted = sorted(durations)
            n = len(durations_sorted)
            route_stats.append({
                "route": route,
                "count": n,
                "avg_ms": round(sum(durations_sorted) / n, 1),
                "p50_ms": round(durations_sorted[n // 2], 1),
                "p95_ms": round(durations_sorted[int(n * 0.95)], 1),
                "max_ms": round(durations_sorted[-1], 1),
            })
        route_stats.sort(key=lambda x: x["avg_ms"], reverse=True)

        # Overall stats
        all_durations = [r.duration_ms for r in reqs]
        overall: Optional[dict] = None
        if all_durations:
            s = sorted(all_durations)
            n = len(s)
            overall = {
                "count": n,
                "avg_ms": round(sum(s) / n, 1),
                "p50_ms": round(s[n // 2], 1),
                "p95_ms": round(s[int(n * 0.95)], 1),
                "max_ms": round(s[-1], 1),
                "slow_count": len([d for d in s if d >= SLOW_THRESHOLD_MS]),
            }

        # Latest resource snapshot
        latest_res = None
        if snaps:
            snap = snaps[-1]
            latest_res = {
                "cpu_pct": snap.cpu_pct,
                "ram_used_mb": snap.ram_used_mb,
                "ram_total_mb": snap.ram_total_mb,
                "ram_pct": snap.ram_pct,
                "process_ram_mb": snap.process_ram_mb,
                "sampled_at": snap.ts,
            }

        return {
            "requests": {
                "overall": overall,
                "by_route": route_stats,
            },
            "slow_requests": [
                {
                    "method": r.method,
                    "path": r.path,
                    "status_code": r.status_code,
                    "duration_ms": round(r.duration_ms, 1),
                    "ts": r.ts,
                }
                for r in reversed(slow)
            ],
            "resources": latest_res,
            "resource_history": [
                {
                    "cpu_pct": s.cpu_pct,
                    "ram_pct": s.ram_pct,
                    "process_ram_mb": s.process_ram_mb,
                    "ts": s.ts,
                }
                for s in snaps
            ],
        }


# Singleton
_store = MetricsStore()


def get_metrics_store() -> MetricsStore:
    return _store
