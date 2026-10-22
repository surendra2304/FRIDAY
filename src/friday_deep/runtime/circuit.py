from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from threading import Lock
from time import monotonic


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    threshold: int = 5
    cooldown: float = 30.0
    failures: int = 0
    opened_at: float = 0.0
    state: CircuitState = CircuitState.CLOSED

    def __post_init__(self):
        self._lock = Lock()

    def allow(self):
        with self._lock:
            if self.state is CircuitState.CLOSED:
                return True
            if self.state is CircuitState.OPEN and monotonic() - self.opened_at >= self.cooldown:
                self.state = CircuitState.HALF_OPEN
                return True
            return self.state is CircuitState.HALF_OPEN

    def success(self):
        with self._lock:
            self.failures = 0
            self.state = CircuitState.CLOSED

    def failure(self):
        with self._lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.state = CircuitState.OPEN
                self.opened_at = monotonic()
