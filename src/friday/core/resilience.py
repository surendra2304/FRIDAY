"""Resilience utilities: Async Circuit Breakers, Retry with Jitter, and Graceful Degradation."""

from __future__ import annotations

import asyncio
from enum import Enum
import functools
import logging
import random
import time
from typing import Any, Callable, Coroutine, TypeVar

logger = logging.getLogger("friday.core.resilience")

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(Exception):
    """Raised when an operation is attempted while the circuit breaker is open."""

    def __init__(self, service_name: str, retry_after_seconds: float) -> None:
        super().__init__(f"Circuit breaker for {service_name} is OPEN. Retry after {retry_after_seconds:.1f}s")
        self.service_name = service_name
        self.retry_after_seconds = retry_after_seconds


class AsyncCircuitBreaker:
    """Production async circuit breaker guarding inter-agent mesh and external calls."""

    def __init__(
        self,
        service_name: str = "service",
        failure_threshold: int = 5,
        recovery_time_seconds: float = 30.0,
        half_open_success_threshold: int = 2,
    ) -> None:
        self.service_name = service_name
        self.failure_threshold = failure_threshold
        self.recovery_time_seconds = recovery_time_seconds
        self.half_open_success_threshold = half_open_success_threshold

        self.state = CircuitState.CLOSED
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.last_failure_time: float = 0.0
        self._lock = asyncio.Lock()

    async def can_execute(self) -> bool:
        """Evaluate whether a request can be dispatched under current circuit state."""
        async with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                now = time.monotonic()
                if now - self.last_failure_time >= self.recovery_time_seconds:
                    logger.info("Circuit breaker for %s transitioned to HALF_OPEN", self.service_name)
                    self.state = CircuitState.HALF_OPEN
                    self.consecutive_successes = 0
                    return True
                return False
            # HALF_OPEN
            return True

    async def record_success(self) -> None:
        """Record successful execution."""
        async with self._lock:
            self.consecutive_failures = 0
            if self.state == CircuitState.HALF_OPEN:
                self.consecutive_successes += 1
                if self.consecutive_successes >= self.half_open_success_threshold:
                    logger.info("Circuit breaker for %s healed -> CLOSED", self.service_name)
                    self.state = CircuitState.CLOSED
                    self.consecutive_successes = 0

    async def record_failure(self, exc: Exception | None = None) -> None:
        """Record failed execution."""
        async with self._lock:
            self.last_failure_time = time.monotonic()
            self.consecutive_failures += 1
            if self.state == CircuitState.HALF_OPEN:
                logger.warning("Circuit breaker for %s failed during probe -> OPEN (%s)", self.service_name, exc)
                self.state = CircuitState.OPEN
            elif self.consecutive_failures >= self.failure_threshold:
                logger.warning(
                    "Circuit breaker for %s exceeded failure threshold (%d) -> OPEN (%s)",
                    self.service_name,
                    self.consecutive_failures,
                    exc,
                )
                self.state = CircuitState.OPEN

    async def call(self, func: Callable[..., Coroutine[Any, Any, T]], *args: Any, **kwargs: Any) -> T:
        """Execute a coroutine through the circuit breaker."""
        if not await self.can_execute():
            remaining = max(0.0, self.recovery_time_seconds - (time.monotonic() - self.last_failure_time))
            raise CircuitBreakerOpenError(self.service_name, remaining)

        try:
            result = await func(*args, **kwargs)
            await self.record_success()
            return result
        except Exception as exc:
            await self.record_failure(exc)
            raise


def retry_with_backoff(
    retries: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 3.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., Coroutine[Any, Any, T]]], Callable[..., Coroutine[Any, Any, T]]]:
    """Async retry decorator with exponential backoff and randomized jitter."""

    def decorator(func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            attempt = 0
            while True:
                try:
                    return await func(*args, **kwargs)
                except retryable_exceptions as exc:
                    attempt += 1
                    if attempt > retries:
                        logger.error(
                            "Operation %s failed after %d attempts: %s",
                            func.__name__,
                            attempt,
                            exc,
                        )
                        raise
                    delay = min(max_delay, base_delay * (backoff_factor ** (attempt - 1)))
                    if jitter:
                        delay = delay * (0.5 + random.random() * 0.5)
                    logger.debug(
                        "Retry %d/%d for %s in %.2fs due to %s",
                        attempt,
                        retries,
                        func.__name__,
                        delay,
                        type(exc).__name__,
                    )
                    await asyncio.sleep(delay)

        return wrapper

    return decorator


async def safe_peer_call(
    coro: Coroutine[Any, Any, T],
    fallback_data: Any = None,
    peer_name: str = "peer",
) -> Any:
    """Execute a peer coroutine with graceful degradation on failure."""
    try:
        return await coro
    except Exception as exc:
        logger.warning("Graceful degradation: call to %s failed (%s)", peer_name, type(exc).__name__)
        if fallback_data is not None:
            return fallback_data
        return {
            "status": "degraded",
            "peer": peer_name,
            "error": type(exc).__name__,
            "message": str(exc),
            "fallback": True,
        }
