"""
FRIDAY/apps/core/src/friday_core/universe_metrics.py — FRIDAY Universe Monitoring & Metrics.

Prometheus-style metrics for all agents, health scoring, alert thresholds,
and performance monitoring.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

router = APIRouter()


@dataclass
class AgentMetrics:
    """Metrics for a single agent."""
    agent_name: str
    request_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0
    health_score: float = 100.0
    last_request: float = 0.0
    status: str = "healthy"


@dataclass
class UniverseMetrics:
    """Universe-wide metrics."""
    total_requests: int = 0
    total_errors: int = 0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    overall_health_score: float = 100.0
    alert_count: int = 0
    last_updated: float = field(default_factory=time.time)


@dataclass
class AlertThreshold:
    """An alert threshold definition."""
    metric: str
    threshold: float
    severity: str = "warning"
    message: str = ""


class UniverseMetricsCollector:
    """Collector for universe-level metrics."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentMetrics] = {}
        self._latencies: list[float] = []
        self._alerts: list[dict[str, Any]] = []
        self._thresholds: list[AlertThreshold] = [
            AlertThreshold("error_rate", 0.05, "warning", "Error rate exceeds 5%"),
            AlertThreshold("latency_p95", 10000, "warning", "p95 latency exceeds 10s"),
            AlertThreshold("health_score", 70.0, "critical", "Health score below 70"),
        ]

    def register_agent(self, agent_name: str) -> AgentMetrics:
        """Register an agent for metrics collection."""
        metrics = AgentMetrics(agent_name=agent_name)
        self._agents[agent_name] = metrics
        return metrics

    def record_request(self, agent_name: str, latency_ms: float = 0.0,
                       error: bool = False) -> None:
        """Record a request metric."""
        metrics = self._agents.get(agent_name) or self.register_agent(agent_name)
        metrics.request_count += 1
        metrics.total_latency_ms += latency_ms
        metrics.last_request = time.time()
        self._latencies.append(latency_ms)
        if error:
            metrics.error_count += 1
            metrics.health_score = max(0, metrics.health_score - 5)
            metrics.status = "degraded"
        # Keep latency list bounded
        if len(self._latencies) > 10000:
            self._latencies = self._latencies[-5000:]

    def calculate_metrics(self) -> UniverseMetrics:
        """Calculate universe-wide metrics."""
        total_req = sum(m.request_count for m in self._agents.values())
        total_err = sum(m.error_count for m in self._agents.values())
        total_lat = sum(m.total_latency_ms for m in self._agents.values())
        avg_lat = total_lat / max(1, total_req)

        sorted_lat = sorted(self._latencies)
        p50 = sorted_lat[len(sorted_lat) // 2] if sorted_lat else 0
        p95 = sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0
        p99 = sorted_lat[int(len(sorted_lat) * 0.99)] if sorted_lat else 0

        health = sum(m.health_score for m in self._agents.values()) / max(1, len(self._agents))

        return UniverseMetrics(
            total_requests=total_req,
            total_errors=total_err,
            avg_latency_ms=round(avg_lat, 2),
            p50_latency_ms=round(p50, 2),
            p95_latency_ms=round(p95, 2),
            p99_latency_ms=round(p99, 2),
            overall_health_score=round(health, 1),
            alert_count=len(self._alerts),
            last_updated=time.time(),
        )

    def check_alerts(self) -> list[dict[str, Any]]:
        """Check alert thresholds."""
        metrics = self.calculate_metrics()
        self._alerts = []
        error_rate = metrics.total_errors / max(1, metrics.total_requests)
        if error_rate > 0.05:
            self._alerts.append({
                "alert_id": f"alert_{uuid.uuid4().hex[:8]}",
                "metric": "error_rate",
                "value": round(error_rate, 4),
                "threshold": 0.05,
                "severity": "warning",
                "message": f"Error rate {error_rate:.1%} exceeds 5%",
            })
        if metrics.overall_health_score < 70:
            self._alerts.append({
                "alert_id": f"alert_{uuid.uuid4().hex[:8]}",
                "metric": "health_score",
                "value": metrics.overall_health_score,
                "threshold": 70,
                "severity": "critical",
                "message": f"Health score {metrics.overall_health_score:.0f} below 70",
            })
        return self._alerts

    def get_agent_metrics(self, agent_name: str) -> dict[str, Any]:
        """Get metrics for a specific agent."""
        metrics = self._agents.get(agent_name)
        if not metrics:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {
            "agent_name": metrics.agent_name,
            "request_count": metrics.request_count,
            "error_count": metrics.error_count,
            "error_rate": metrics.error_count / max(1, metrics.request_count),
            "avg_latency_ms": metrics.total_latency_ms / max(1, metrics.request_count),
            "health_score": metrics.health_score,
            "status": metrics.status,
        }

    def get_prometheus_metrics(self) -> str:
        """Get metrics in Prometheus format."""
        self.check_alerts()
        lines = []
        for name, m in self._agents.items():
            lines.append(f"# TYPE agent_requests_total counter")
            lines.append(f'agent_requests_total{{agent="{name}"}} {m.request_count}')
            lines.append(f'# TYPE agent_errors_total counter')
            lines.append(f'agent_errors_total{{agent="{name}"}} {m.error_count}')
            lines.append(f'# TYPE agent_health_score gauge')
            lines.append(f'agent_health_score{{agent="{name}"}} {m.health_score}')
        lines.append(f'# TYPE universe_total_requests counter')
        lines.append(f"universe_total_requests {sum(m.request_count for m in self._agents.values())}")
        lines.append(f'# TYPE universe_overall_health gauge')
        lines.append(f"universe_overall_health {self.calculate_metrics().overall_health_score}")
        return "\n".join(lines)

    def get_report(self) -> dict[str, Any]:
        """Get metrics collector report."""
        metrics = self.calculate_metrics()
        return {
            "total_agents": len(self._agents),
            "total_requests": metrics.total_requests,
            "total_errors": metrics.total_errors,
            "overall_health_score": metrics.overall_health_score,
            "alert_count": len(self._alerts),
            "engine_status": "operational",
        }


engine = UniverseMetricsCollector()

# Register default agents
for agent in ["Inference", "Memora", "Stratex", "Forge", "Cortex", "Sentinel", "IntelX", "Futuris", "VyralX"]:
    engine.register_agent(agent)


@router.get("/metrics/universe")
async def universe_metrics():
    """Get universe-wide metrics."""
    metrics = engine.calculate_metrics()
    return {
        "total_requests": metrics.total_requests,
        "total_errors": metrics.total_errors,
        "avg_latency_ms": metrics.avg_latency_ms,
        "p50_latency_ms": metrics.p50_latency_ms,
        "p95_latency_ms": metrics.p95_latency_ms,
        "p99_latency_ms": metrics.p99_latency_ms,
        "overall_health_score": metrics.overall_health_score,
        "alert_count": metrics.alert_count,
    }


@router.get("/metrics/agents/{agent_name}")
async def get_agent_metrics(agent_name: str):
    """Get metrics for a specific agent."""
    return engine.get_agent_metrics(agent_name)


@router.get("/metrics/alerts")
async def get_alerts():
    """Get current alerts."""
    return {"alerts": engine.check_alerts()}


@router.get("/metrics/prometheus", response_class=PlainTextResponse)
async def prometheus_metrics():
    """Get metrics in Prometheus format."""
    return engine.get_prometheus_metrics()


@router.post("/metrics/record")
async def record_request(agent_name: str, latency_ms: float = 0.0, error: bool = False):
    """Record a request metric."""
    engine.record_request(agent_name, latency_ms, error)
    return {"agent_name": agent_name, "status": "recorded"}


@router.get("/metrics/report")
async def metrics_report():
    """Get metrics collector report."""
    return engine.get_report()
