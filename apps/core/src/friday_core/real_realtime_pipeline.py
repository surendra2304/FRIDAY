"""
FRIDAY/apps/core/src/friday_core/real_realtime_pipeline.py — Realtime Pipeline.

Real working real-time streaming pipeline:
- RealtimePipeline: streaming data through agents
- EventQueue: async event queue with priority
- PipelineStage: individual pipeline stages
- MetricsCollector: real metrics collection
- AnomalyDetector: real anomaly detection in streams
- PerformanceBenchmark: real performance benchmarks
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import random
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent.parent


def _load(name, relpath):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_cortex = _load("rt_cortex", "Cortex/apps/api/src/cortex_api/real_decision_engine.py")
_inference = _load("rt_inference", "Inference/app/agents/real_reasoning_engine.py")
_memora = _load("rt_memora", "Memora/core/memory/real_memory_engine.py")
_stratex = _load("rt_stratex", "Stratex/real_trading_engine.py")
_forge = _load("rt_forge", "Forge/app/services/real_code_engine.py")
_sentinel = _load("rt_sentinel", "Sentinel/app/services/real_security_engine.py")
_intelx = _load("rt_intelx", "IntelX/intelx/services/real_threat_intel_engine.py")
_futuris = _load("rt_futuris", "Futuris/futuris/core/real_forecast_engine.py")
_vyralx = _load("rt_vyralx", "VyralX/app/services/real_content_engine.py")


# ── Event Queue ────────────────────────────────────────────────────────────

@dataclass
class QueuedEvent:
    """A queued event."""
    event_id: str
    event_type: str
    data: dict[str, Any]
    priority: int  # 1 (lowest) to 10 (highest)
    enqueued_at: float
    processed: bool = False


class EventQueue:
    """Real priority event queue."""

    def __init__(self, max_size: int = 10000) -> None:
        self._queue: list[QueuedEvent] = []
        self._max_size = max_size
        self._processed_count = 0
        self._total_count = 0

    def enqueue(self, event_type: str, data: dict[str, Any], priority: int = 5) -> QueuedEvent:
        event = QueuedEvent(
            event_id=f"evt_{uuid.uuid4().hex[:12]}",
            event_type=event_type,
            data=data,
            priority=priority,
            enqueued_at=time.time(),
        )
        # Insert by priority (higher priority first)
        inserted = False
        for i, existing in enumerate(self._queue):
            if existing.priority < priority:
                self._queue.insert(i, event)
                inserted = True
                break
        if not inserted:
            self._queue.append(event)
        # Trim if exceeds max size
        if len(self._queue) > self._max_size:
            self._queue = self._queue[-self._max_size:]
        self._total_count += 1
        return event

    def dequeue(self) -> QueuedEvent | None:
        if not self._queue:
            return None
        event = self._queue.pop(0)
        event.processed = True
        self._processed_count += 1
        return event

    def size(self) -> int:
        return len(self._queue)

    def stats(self) -> dict[str, int]:
        return {"queued": len(self._queue), "processed": self._processed_count, "total": self._total_count}


# ── Pipeline Stage ────────────────────────────────────────────────────────

@dataclass
class PipelineResult:
    """Result of a pipeline stage."""
    stage_name: str
    success: bool
    result: dict[str, Any]
    error: str = ""
    duration_ms: float = 0.0


class PipelineStage:
    """A pipeline stage that processes events."""

    def __init__(self, name: str, processor: callable) -> None:
        self.name = name
        self.processor = processor

    def process(self, event: QueuedEvent) -> PipelineResult:
        t0 = time.time()
        try:
            result = self.processor(event.event_type, event.data)
            return PipelineResult(
                stage_name=self.name, success=True, result=result,
                duration_ms=round((time.time() - t0) * 1000, 3),
            )
        except Exception as e:
            return PipelineResult(
                stage_name=self.name, success=False, result={},
                error=str(e), duration_ms=round((time.time() - t0) * 1000, 3),
            )


# ── Realtime Pipeline ────────────────────────────────────────────────────

class RealtimePipeline:
    """Real real-time pipeline processing events through agents."""

    def __init__(self, state_dir: str = "") -> None:
        self._queue = EventQueue()
        self._stages: list[PipelineStage] = []
        self._results: list[PipelineResult] = []
        self._metrics = {"total_events": 0, "total_processed": 0, "total_errors": 0,
                          "avg_duration_ms": 0.0}
        self._executor = ThreadPoolExecutor(max_workers=4)

    def add_stage(self, name: str, processor: callable) -> None:
        self._stages.append(PipelineStage(name, processor))

    def process_event(self, event_type: str, data: dict[str, Any], priority: int = 5) -> list[PipelineResult]:
        """Process a single event through all pipeline stages."""
        event = self._queue.enqueue(event_type, data, priority)
        results = []

        for stage in self._stages:
            result = stage.process(event)
            results.append(result)
            if not result.success:
                self._metrics["total_errors"] += 1

        self._metrics["total_events"] += 1
        self._metrics["total_processed"] += 1
        durations = [r.duration_ms for r in results]
        if durations:
            old_avg = self._metrics["avg_duration_ms"]
            self._metrics["avg_duration_ms"] = round(
                (old_avg + sum(durations) / len(durations)) / 2, 3)

        self._results.extend(results)
        if len(self._results) > 10000:
            self._results = self._results[-5000:]

        return results

    def batch_process(self, events: list[dict]) -> list[list[PipelineResult]]:
        """Process a batch of events."""
        return [self.process_event(e["type"], e.get("data", {}), e.get("priority", 5)) for e in events]

    def get_metrics(self) -> dict[str, Any]:
        return {
            "total_events": self._metrics["total_events"],
            "total_processed": self._metrics["total_processed"],
            "total_errors": self._metrics["total_errors"],
            "avg_duration_ms": self._metrics["avg_duration_ms"],
            "queue_stats": self._queue.stats(),
            "stages": len(self._stages),
        }


# ── Metrics Collector ────────────────────────────────────────────────────

class MetricsCollector:
    """Real metrics collection and analysis."""

    def __init__(self) -> None:
        self._metrics: dict[str, list[float]] = defaultdict(list)

    def record(self, metric_name: str, value: float) -> None:
        self._metrics[metric_name].append(value)

    def get_stats(self, metric_name: str) -> dict[str, float]:
        values = self._metrics.get(metric_name, [])
        if not values:
            return {"count": 0, "mean": 0, "min": 0, "max": 0, "std": 0}

        n = len(values)
        mean = sum(values) / n
        var = sum((v - mean) ** 2 for v in values) / n
        std = math.sqrt(var)
        return {"count": n, "mean": round(mean, 4),
                "min": round(min(values), 4), "max": round(max(values), 4),
                "std": round(std, 4)}

    def get_all_stats(self) -> dict[str, dict[str, float]]:
        return {name: self.get_stats(name) for name in self._metrics}


# ── Anomaly Detector ─────────────────────────────────────────────────────

class AnomalyDetector:
    """Real anomaly detection in streaming data."""

    def __init__(self, window_size: int = 100, threshold: float = 2.0) -> None:
        self._window: deque[float] = deque(maxlen=window_size)
        self._threshold = threshold
        self._anomalies: list[dict[str, Any]] = []

    def update(self, value: float) -> bool:
        """Update with a new value and return True if anomalous."""
        self._window.append(value)

        if len(self._window) < 10:
            return False

        values = list(self._window)
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = math.sqrt(variance)

        if std == 0:
            return False

        z_score = abs(value - mean) / std
        is_anomaly = z_score > self._threshold

        if is_anomaly:
            self._anomalies.append({
                "value": value, "z_score": round(z_score, 2),
                "timestamp": time.time(), "mean": round(mean, 2),
                "std": round(std, 2),
            })

        return is_anomaly

    def get_anomalies(self) -> list[dict[str, Any]]:
        return self._anomalies[-100:]  # Last 100 anomalies

    def stats(self) -> dict[str, Any]:
        return {
            "window_size": len(self._window),
            "anomalies_detected": len(self._anomalies),
            "threshold": self._threshold,
        }


# ── Performance Benchmark ───────────────────────────────────────────────

class PerformanceBenchmark:
    """Real performance benchmarks for all engines."""

    def benchmark_decision_engine(self, iterations: int = 100) -> dict[str, float]:
        engine = _cortex.DecisionEngine()
        options = [{"name": "A", "scores": {"speed": 8, "reliability": 7}},
                    {"name": "B", "scores": {"speed": 6, "reliability": 9}}]
        criteria = [{"name": "speed", "weight": 0.5}, {"name": "reliability", "weight": 0.5}]

        t0 = time.time()
        for _ in range(iterations):
            engine.decide("Test", options, criteria)
        elapsed = (time.time() - t0) * 1000

        return {
            "operations": iterations, "total_ms": round(elapsed, 2),
            "ops_per_second": round(iterations / (elapsed / 1000), 2),
            "avg_ms": round(elapsed / iterations, 4),
        }

    def benchmark_trading_engine(self, iterations: int = 100) -> dict[str, float]:
        engine = _stratex.TradingEngine()
        bars = [_stratex.PriceBar(timestamp=time.time() + i, open=100+i, high=101+i, low=99+i, close=100.5+i, volume=1000) for i in range(50)]

        t0 = time.time()
        for _ in range(iterations):
            engine.backtest("TEST", bars)
        elapsed = (time.time() - t0) * 1000

        return {
            "operations": iterations, "total_ms": round(elapsed, 2),
            "ops_per_second": round(iterations / (elapsed / 1000), 2),
            "avg_ms": round(elapsed / iterations, 4),
        }

    def benchmark_memory_engine(self, iterations: int = 100) -> dict[str, float]:
        engine = _memora.MemoryEngine(store_dir="/tmp/bench_memora_rt")

        t0 = time.time()
        for i in range(iterations):
            engine.store(content=f"Test memory {i}", agent_origin="benchmark", tags=["test", str(i)])
            engine.search(f"test memory {i}")
        elapsed = (time.time() - t0) * 1000

        return {
            "operations": iterations * 2, "total_ms": round(elapsed, 2),
            "ops_per_second": round(iterations * 2 / (elapsed / 1000), 2),
            "avg_ms": round(elapsed / (iterations * 2), 4),
        }

    def benchmark_security_engine(self, iterations: int = 100) -> dict[str, float]:
        engine = _sentinel.SecurityEngine()
        logs = "Failed login: admin\nUser login from 192.168.1.1\nUnusual traffic detected"

        t0 = time.time()
        for _ in range(iterations):
            engine.detect_threats(logs)
        elapsed = (time.time() - t0) * 1000

        return {
            "operations": iterations, "total_ms": round(elapsed, 2),
            "ops_per_second": round(iterations / (elapsed / 1000), 2),
            "avg_ms": round(elapsed / iterations, 4),
        }

    def benchmark_forecast_engine(self, iterations: int = 100) -> dict[str, float]:
        engine = _futuris.ForecastEngine()
        series = [100 + i * 0.5 + random.uniform(-1, 1) for i in range(30)]

        t0 = time.time()
        for _ in range(iterations):
            engine.ensemble_forecast("TEST", series)
        elapsed = (time.time() - t0) * 1000

        return {
            "operations": iterations, "total_ms": round(elapsed, 2),
            "ops_per_second": round(iterations / (elapsed / 1000), 2),
            "avg_ms": round(elapsed / iterations, 4),
        }

    def run_all_benchmarks(self) -> dict[str, dict[str, float]]:
        """Run benchmarks for all engines."""
        return {
            "decision_engine": self.benchmark_decision_engine(),
            "trading_engine": self.benchmark_trading_engine(),
            "memory_engine": self.benchmark_memory_engine(),
            "security_engine": self.benchmark_security_engine(),
            "forecast_engine": self.benchmark_forecast_engine(),
        }


# Module-level instances
realtime_pipeline = RealtimePipeline()
metrics_collector = MetricsCollector()
anomaly_detector = AnomalyDetector()
performance_benchmark = PerformanceBenchmark()
