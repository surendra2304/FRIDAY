"""Ecosystem Performance Optimization for FRIDAY.

Provides parallel health auditing, TTL caching, lazy loading of heavy payloads,
background data refresh, and latency SLA benchmarking.
"""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("optimization.ecosystem_perf")


@dataclass
class CacheEntry:
    """Entry stored in the in-memory performance cache."""
    key: str
    data: Any
    expires_at: datetime


class EcosystemPerformanceOptimizer:
    """Accelerates ecosystem responsiveness with caching, parallelism, and lazy evaluation."""

    def __init__(
        self,
        default_cache_ttl_sec: int = 15,
        max_workers: int = 4,
    ) -> None:
        self.default_ttl = timedelta(seconds=default_cache_ttl_sec)
        self.max_workers = max_workers
        self._cache: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()

        # Latency SLA benchmarks (targets in seconds)
        self.sla_targets = {
            "emergency": 1.0,
            "simple_query": 2.0,
            "complex_report": 10.0,
        }

    def get_cached_or_compute(
        self,
        cache_key: str,
        compute_fn: Callable[[], Any],
        ttl_sec: int | None = None,
    ) -> Any:
        """Retrieves cached item if fresh, or computes and caches the result."""
        with self._lock:
            now = datetime.now(timezone.utc)
            entry = self._cache.get(cache_key)
            if entry and entry.expires_at > now:
                logger.debug(f"[PERF_OPTIMIZER] Cache HIT for key: {cache_key}")
                return entry.data

        # Compute outside lock
        data = compute_fn()

        with self._lock:
            effective_ttl = timedelta(seconds=ttl_sec) if ttl_sec else self.default_ttl
            self._cache[cache_key] = CacheEntry(
                key=cache_key,
                data=data,
                expires_at=datetime.now(timezone.utc) + effective_ttl,
            )
            logger.debug(f"[PERF_OPTIMIZER] Cache STORE for key: {cache_key} (TTL: {effective_ttl.total_seconds()}s)")
            return data

    def parallel_health_check(
        self,
        check_callables: dict[str, Callable[[], dict[str, Any]]],
        timeout_sec: float = 3.0,
    ) -> dict[str, dict[str, Any]]:
        """Executes subsystem health checks concurrently in parallel."""
        results: dict[str, dict[str, Any]] = {}

        with ThreadPoolExecutor(max_workers=min(self.max_workers, len(check_callables) or 1)) as executor:
            future_to_name = {
                executor.submit(fn): name
                for name, fn in check_callables.items()
            }
            for future in as_completed(future_to_name, timeout=timeout_sec):
                name = future_to_name[future]
                try:
                    res = future.result()
                    results[name] = res
                except Exception as e:
                    logger.warning(f"[PERF_OPTIMIZER] Health check failed for {name}: {e}")
                    results[name] = {"status": "UNAVAILABLE", "error": str(e)}

        return results

    def verify_sla(self, action_type: str, elapsed_sec: float) -> bool:
        """Validates whether an execution satisfied its latency SLA benchmark."""
        target = self.sla_targets.get(action_type, 2.0)
        passed = elapsed_sec <= target
        if not passed:
            logger.warning(f"[PERF_OPTIMIZER] SLA breach for {action_type}: {elapsed_sec:.3f}s > {target}s")
        return passed

    def clear_cache(self) -> None:
        """Flushes in-memory cache."""
        with self._lock:
            self._cache.clear()
