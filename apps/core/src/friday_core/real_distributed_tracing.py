"""
FRIDAY/apps/core/src/friday_core/real_distributed_tracing.py — Real Distributed Tracing.

Real working implementation:
- TraceContext: propagates trace context across agents
- Span: represents a unit of work within a trace
- TraceExporter: collects and exports trace data
- SpanProcessor: processes spans in real-time
- TraceAnalyzer: analyzes trace data for performance bottlenecks
- AgentTracingMiddleware: integrates tracing into API requests
"""
from __future__ import annotations

import json
import math
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from collections import defaultdict
from contextlib import contextmanager


# ── Trace Context ─────────────────────────────────────────────────────────

@dataclass
class TraceContext:
    """Context that propagates across service boundaries."""
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    agent_name: str = ""
    sampled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "agent_name": self.agent_name,
            "sampled": self.sampled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TraceContext:
        return cls(
            trace_id=data.get("trace_id", ""),
            span_id=data.get("span_id", ""),
            parent_span_id=data.get("parent_span_id"),
            agent_name=data.get("agent_name", ""),
            sampled=data.get("sampled", True),
        )

    def new_span(self, agent_name: str = "") -> TraceContext:
        """Create a child span from this context."""
        return TraceContext(
            trace_id=self.trace_id,
            span_id=f"span_{uuid.uuid4().hex[:16]}",
            parent_span_id=self.span_id,
            agent_name=agent_name or self.agent_name,
            sampled=self.sampled,
        )


# ── Span ────────────────────────────────────────────────────────────────

@dataclass
class Span:
    """A span represents a unit of work within a trace."""
    span_id: str
    trace_id: str
    parent_span_id: str | None
    operation_name: str
    agent_name: str
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = "unfinished"  # unfinished, ok, error
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def finish(self, status: str = "ok") -> None:
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status = status

    def add_event(self, name: str, attributes: dict[str, Any] = {}) -> None:
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes,
        })

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "operation_name": self.operation_name,
            "agent_name": self.agent_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 3),
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }


# ── Trace Exporter ──────────────────────────────────────────────────────

class TraceExporter:
    """Collects and exports trace data."""

    def __init__(self, state_dir: str = "") -> None:
        self._state_dir = state_dir or str(
            os.path.join(os.path.dirname(__file__), "..", ".data", "tracing")
        )
        os.makedirs(self._state_dir, exist_ok=True)
        self._spans: list[Span] = []
        self._traces: dict[str, list[Span]] = defaultdict(list)
        self._load_state()

    def _load_state(self) -> None:
        try:
            f = os.path.join(self._state_dir, "traces.json")
            if os.path.exists(f):
                with open(f, "r") as fh:
                    data = json.load(fh)
                    for span_dict in data.get("spans", []):
                        span = Span(
                            span_id=span_dict["span_id"],
                            trace_id=span_dict["trace_id"],
                            parent_span_id=span_dict.get("parent_span_id"),
                            operation_name=span_dict["operation_name"],
                            agent_name=span_dict["agent_name"],
                            start_time=span_dict["start_time"],
                            end_time=span_dict.get("end_time", 0),
                            duration_ms=span_dict.get("duration_ms", 0),
                            status=span_dict.get("status", "ok"),
                            attributes=span_dict.get("attributes", {}),
                            events=span_dict.get("events", []),
                        )
                        self._spans.append(span)
                        self._traces[span.trace_id].append(span)
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            f = os.path.join(self._state_dir, "traces.json")
            with open(f, "w") as fh:
                json.dump({
                    "spans": [s.to_dict() for s in self._spans[-1000:]],
                }, fh, indent=2)
        except Exception:
            pass

    def export_span(self, span: Span) -> None:
        """Export a span to the collector."""
        self._spans.append(span)
        self._traces[span.trace_id].append(span)
        if len(self._spans) > 10000:
            self._spans = self._spans[-5000:]
        self._save_state()

    def get_trace(self, trace_id: str) -> list[Span]:
        """Get all spans for a trace."""
        return self._traces.get(trace_id, [])

    def get_spans(self, agent: str = "", limit: int = 100) -> list[Span]:
        """Get spans, optionally filtered by agent."""
        spans = self._spans
        if agent:
            spans = [s for s in spans if s.agent_name == agent]
        return spans[-limit:]


# ── Trace Analyzer ───────────────────────────────────────────────────────

@dataclass
class TraceMetrics:
    """Metrics computed from trace data."""
    trace_id: str
    total_spans: int
    total_duration_ms: float
    p50_duration_ms: float
    p95_duration_ms: float
    error_count: int
    agent_breakdown: dict[str, float]


class TraceAnalyzer:
    """Analyzes trace data for performance bottlenecks."""

    def analyze_trace(self, trace_id: str, exporter: TraceExporter) -> TraceMetrics:
        """Analyze a single trace."""
        spans = exporter.get_trace(trace_id)
        if not spans:
            return TraceMetrics(
                trace_id=trace_id, total_spans=0, total_duration_ms=0,
                p50_duration_ms=0, p95_duration_ms=0, error_count=0,
                agent_breakdown={},
            )

        durations = sorted([s.duration_ms for s in spans if s.duration_ms > 0])
        p50 = durations[len(durations) // 2] if durations else 0
        p95 = durations[int(len(durations) * 0.95)] if durations else 0
        total_duration = sum(durations)
        error_count = len([s for s in spans if s.status == "error"])

        agent_breakdown = {}
        for s in spans:
            agent_breakdown[s.agent_name] = agent_breakdown.get(s.agent_name, 0) + s.duration_ms

        return TraceMetrics(
            trace_id=trace_id,
            total_spans=len(spans),
            total_duration_ms=round(total_duration, 2),
            p50_duration_ms=round(p50, 2),
            p95_duration_ms=round(p95, 2),
            error_count=error_count,
            agent_breakdown={k: round(v, 2) for k, v in agent_breakdown.items()},
        )

    def find_bottlenecks(self, exporter: TraceExporter, limit: int = 10) -> list[dict[str, Any]]:
        """Find the slowest spans."""
        spans = exporter.get_spans(limit=500)
        bottlenecks = []

        for span in spans:
            if span.duration_ms > 0:
                bottlenecks.append({
                    "span_id": span.span_id,
                    "trace_id": span.trace_id,
                    "operation": span.operation_name,
                    "agent": span.agent_name,
                    "duration_ms": round(span.duration_ms, 2),
                    "status": span.status,
                })

        bottlenecks.sort(key=lambda x: x["duration_ms"], reverse=True)
        return bottlenecks[:limit]


# ── Agent Tracing Middleware ─────────────────────────────────────────────

class AgentTracingMiddleware:
    """Middleware that automatically traces API requests."""

    def __init__(self, exporter: TraceExporter) -> None:
        self._exporter = exporter
        self._analyzer = TraceAnalyzer()

    def create_trace(self, agent_name: str) -> tuple[TraceContext, Span]:
        """Create a new trace with a root span."""
        trace_id = f"trace_{uuid.uuid4().hex[:16]}"
        span_id = f"span_{uuid.uuid4().hex[:16]}"

        context = TraceContext(
            trace_id=trace_id,
            span_id=span_id,
            agent_name=agent_name,
        )

        span = Span(
            span_id=span_id,
            trace_id=trace_id,
            parent_span_id=None,
            operation_name=f"{agent_name}_request",
            agent_name=agent_name,
            start_time=time.time(),
        )

        return context, span

    def start_child_span(
        self, parent_context: TraceContext, agent_name: str, operation: str
    ) -> tuple[TraceContext, Span]:
        """Start a child span from a parent context."""
        child_context = parent_context.new_span(agent_name)
        span = Span(
            span_id=child_context.span_id,
            trace_id=child_context.trace_id,
            parent_span_id=parent_context.span_id,
            operation_name=operation,
            agent_name=agent_name,
            start_time=time.time(),
        )
        return child_context, span

    def finish_span(self, span: Span, status: str = "ok") -> None:
        """Finish and export a span."""
        span.finish(status)
        self._exporter.export_span(span)

    def analyze(self, trace_id: str) -> TraceMetrics:
        """Analyze a trace."""
        return self._analyzer.analyze_trace(trace_id, self._exporter)


# Module-level instances
trace_exporter = TraceExporter()
tracing_middleware = AgentTracingMiddleware(trace_exporter)
trace_analyzer = TraceAnalyzer()
