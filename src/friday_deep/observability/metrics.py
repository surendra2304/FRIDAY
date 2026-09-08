from __future__ import annotations
from dataclasses import dataclass, field
from statistics import mean
from threading import Lock


@dataclass
class Metrics:
    calls: int = 0
    successes: int = 0
    failures: int = 0
    latencies: list[float] = field(default_factory=list)

    def record(self, success: bool, latency_ms: float):
        self.calls += 1
        self.successes += int(success)
        self.failures += int(not success)
        self.latencies.append(latency_ms)

    def summary(self):
        return {
            "calls": self.calls,
            "successes": self.successes,
            "failures": self.failures,
            "success_rate": self.successes / self.calls if self.calls else 0.0,
            "avg_latency_ms": mean(self.latencies) if self.latencies else 0.0,
        }


class MetricsRegistry:
    def __init__(self):
        self._m = {}
        self._lock = Lock()

    def get(self, name):
        with self._lock:
            if name not in self._m:
                self._m[name] = Metrics()
            return self._m[name]

    def snapshot(self):
        with self._lock:
            return {k: v.summary() for k, v in self._m.items()}


DEFAULT = MetricsRegistry()
