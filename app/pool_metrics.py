"""In-Memory Connection Pool Metrics & Latency Registry.

Tracks thread-safe counters for pool checkouts, connections, errors, retries,
and rolling 5-minute checkout latency percentiles (p50/p95).
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Dict, List, Tuple


class PoolMetricsRegistry:
    def __init__(self, window_seconds: int = 300):
        self._window_seconds = window_seconds
        self._lock = threading.Lock()
        self._latencies: deque[Tuple[float, float]] = deque()  # (timestamp, latency_ms)
        self._timeouts: deque[float] = deque()  # timestamps of timeout events
        self._fallbacks: deque[float] = deque()  # timestamps of fallback events

        self._counters: Dict[str, int] = {
            "checkouts_total": 0,
            "checkouts_reused": 0,
            "new_connections_created": 0,
            "unpooled_fallbacks": 0,
            "pool_timeout_errors": 0,
            "query_retries": 0,
            "query_failures": 0,
            "reconnects": 0,
            "connection_close_events": 0,
        }

    def increment(self, counter_name: str, amount: int = 1) -> None:
        with self._lock:
            if counter_name in self._counters:
                self._counters[counter_name] += amount
            else:
                self._counters[counter_name] = amount

    def record_checkout(self, latency_ms: float, reused: bool = True) -> None:
        now = time.time()
        with self._lock:
            self._counters["checkouts_total"] += 1
            if reused:
                self._counters["checkouts_reused"] += 1
            self._latencies.append((now, latency_ms))
            self._prune_window(now)

    def record_unpooled_fallback(self) -> None:
        now = time.time()
        with self._lock:
            self._counters["unpooled_fallbacks"] += 1
            self._fallbacks.append(now)

    def record_pool_timeout(self) -> None:
        now = time.time()
        with self._lock:
            self._counters["pool_timeout_errors"] += 1
            self._timeouts.append(now)

    def record_connection_created(self) -> None:
        with self._lock:
            self._counters["new_connections_created"] += 1

    def record_connection_closed(self) -> None:
        with self._lock:
            self._counters["connection_close_events"] += 1

    def record_reconnect(self) -> None:
        with self._lock:
            self._counters["reconnects"] += 1

    def record_query_retry(self) -> None:
        with self._lock:
            self._counters["query_retries"] += 1

    def record_query_failure(self) -> None:
        with self._lock:
            self._counters["query_failures"] += 1

    def _prune_window(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._latencies and self._latencies[0][0] < cutoff:
            self._latencies.popleft()
        while self._fallbacks and self._fallbacks[0] < cutoff:
            self._fallbacks.popleft()
        # Timeouts tracked for last 60 seconds
        timeout_cutoff = now - 60.0
        while self._timeouts and self._timeouts[0] < timeout_cutoff:
            self._timeouts.popleft()

    def get_timeouts_last_minute(self) -> int:
        now = time.time()
        with self._lock:
            self._prune_window(now)
            return len(self._timeouts)

    def get_fallbacks_last_5m(self) -> int:
        now = time.time()
        with self._lock:
            self._prune_window(now)
            return len(self._fallbacks)

    def get_percentiles(self) -> Tuple[float, float, int]:
        """Compute p50 and p95 checkout latency in ms over rolling window."""
        now = time.time()
        with self._lock:
            self._prune_window(now)
            if not self._latencies:
                return 0.0, 0.0, 0
            values = sorted(lat for _, lat in self._latencies)
            count = len(values)
            p50 = values[int(count * 0.50)]
            p95_idx = min(int(count * 0.95), count - 1)
            p95 = values[p95_idx]
            return round(p50, 2), round(p95, 2), count

    def get_metrics(self) -> Dict[str, Any]:
        """Return complete snapshot of pool metrics."""
        p50, p95, samples = self.get_percentiles()
        with self._lock:
            data = dict(self._counters)
            data["recent_fallbacks_5m"] = len(self._fallbacks)
            data["recent_timeouts_1m"] = len(self._timeouts)
        data["p50_checkout_ms"] = p50
        data["p95_checkout_ms"] = p95
        data["latency_samples_5m"] = samples
        return data

    def reset(self) -> None:
        """Reset all counters and rolling windows (used in unit tests)."""
        with self._lock:
            self._latencies.clear()
            self._timeouts.clear()
            self._fallbacks.clear()
            for k in self._counters:
                self._counters[k] = 0


# Global singleton metrics registry
POOL_METRICS = PoolMetricsRegistry(window_seconds=300)


def get_pool_metrics() -> Dict[str, Any]:
    return POOL_METRICS.get_metrics()
