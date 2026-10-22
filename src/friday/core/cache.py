"""Thread-safe in-memory TTL/LRU cache for high-throughput service telemetry and queries."""

from __future__ import annotations

import functools
import threading
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")


class TTLCache:
    """Thread-safe in-memory cache with Time-To-Live (TTL) expiration."""

    def __init__(self, default_ttl: float = 60.0, maxsize: int = 256) -> None:
        self.default_ttl = float(default_ttl)
        self.maxsize = maxsize
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.RLock()

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value if present and not expired."""
        with self._lock:
            if key not in self._cache:
                return default
            val, expiry = self._cache[key]
            if time.monotonic() > expiry:
                del self._cache[key]
                return default
            return val

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        """Store a value with an expiration timestamp."""
        ttl = float(ttl) if ttl is not None else self.default_ttl
        expiry = time.monotonic() + ttl
        with self._lock:
            if len(self._cache) >= self.maxsize and key not in self._cache:
                # Evict oldest entry
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]
            self._cache[key] = (value, expiry)

    def delete(self, key: str) -> bool:
        """Remove a key from the cache."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    def clear(self) -> None:
        """Clear all entries."""
        with self._lock:
            self._cache.clear()

    def __len__(self) -> int:
        with self._lock:
            now = time.monotonic()
            return sum(1 for _, expiry in self._cache.values() if expiry > now)


def ttl_cached(ttl_seconds: float = 60.0, maxsize: int = 256) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to cache function results with a TTL."""
    cache = TTLCache(default_ttl=ttl_seconds, maxsize=maxsize)

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            key = f"{func.__name__}:{repr(args)}:{repr(sorted(kwargs.items()))}"
            hit = cache.get(key)
            if hit is not None:
                return hit
            result = func(*args, **kwargs)
            cache.set(key, result)
            return result

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> T:
            key = f"{func.__name__}:{repr(args)}:{repr(sorted(kwargs.items()))}"
            hit = cache.get(key)
            if hit is not None:
                return hit
            result = await func(*args, **kwargs)
            cache.set(key, result)
            return result

        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper

    return decorator
