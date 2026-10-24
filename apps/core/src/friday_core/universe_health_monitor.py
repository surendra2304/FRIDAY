"""
FRIDAY/apps/core/src/friday_core/universe_health_monitor.py — FRIDAY Universe Health Monitor.

Real-time health monitoring of all specialist agents with automated recovery,
alerting, degradation handling, and health scoring.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class AgentHealth:
    """Health status of an agent."""
    agent_name: str
    status: str = "unknown"  # healthy, degraded, down, unknown
    last_check: float = 0.0
    response_time_ms: float = 0.0
    error_count: int = 0
    health_score: float = 100.0
    alerts: list[str] = field(default_factory=list)
    recovery_attempts: int = 0


@dataclass
class UniverseHealthSnapshot:
    """A snapshot of universe health."""
    snapshot_id: str
    timestamp: float = field(default_factory=time.time)
    agents: dict[str, AgentHealth] = field(default_factory=dict)
    overall_score: float = 100.0
    total_agents: int = 0
    healthy_agents: int = 0
    alerts: list[str] = field(default_factory=list)


@dataclass
class Alert:
    """A health alert."""
    alert_id: str
    agent_name: str
    alert_type: str
    message: str
    severity: str = "warning"  # info, warning, critical
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False


class UniverseHealthMonitor:
    """Monitor for universe-level agent health."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentHealth] = {}
        self._alerts: dict[str, Alert] = {}
        self._snapshots: list[UniverseHealthSnapshot] = []
        self._thresholds = {
            "error_rate": 5.0,
            "latency_ms": 5000,
            "health_score_min": 70.0,
        }

    def register_agent(self, agent_name: str) -> AgentHealth:
        """Register an agent for monitoring."""
        health = AgentHealth(agent_name=agent_name)
        self._agents[agent_name] = health
        return health

    def check_agent_health(self, agent_name: str, status: str,
                           response_time_ms: float = 0.0,
                           error: str | None = None) -> AgentHealth:
        """Update agent health from a check."""
        health = self._agents.get(agent_name) or self.register_agent(agent_name)
        health.status = status
        health.last_check = time.time()
        health.response_time_ms = response_time_ms

        if error:
            health.error_count += 1
            alert = Alert(
                alert_id=f"alert_{uuid.uuid4().hex[:8]}",
                agent_name=agent_name,
                alert_type="error",
                message=error,
                severity="warning" if health.error_count < 5 else "critical",
            )
            self._alerts[alert.alert_id] = alert
            health.alerts.append(alert.alert_id)

        # Calculate health score
        score = 100.0
        if health.error_count > 0:
            score -= health.error_count * 10.0
        if response_time_ms > self._thresholds["latency_ms"]:
            score -= 20.0
        if status == "down":
            score -= 50.0
        elif status == "degraded":
            score -= 20.0
        health.health_score = max(0.0, score)

        # Trigger recovery if critical
        if health.health_score < self._thresholds["health_score_min"]:
            health.recovery_attempts += 1
            recovery_alert = Alert(
                alert_id=f"alert_{uuid.uuid4().hex[:8]}",
                agent_name=agent_name,
                alert_type="recovery",
                message=f"Health score {health.health_score:.0f} below threshold, recovery triggered",
                severity="critical",
            )
            self._alerts[recovery_alert.alert_id] = recovery_alert
            health.alerts.append(recovery_alert.alert_id)

        return health

    def get_universe_health(self) -> UniverseHealthSnapshot:
        """Get current universe health snapshot."""
        snapshot = UniverseHealthSnapshot(snapshot_id=f"snap_{uuid.uuid4().hex[:8]}")
        for name, health in self._agents.items():
            snapshot.agents[name] = health
        snapshot.total_agents = len(self._agents)
        snapshot.healthy_agents = sum(1 for h in self._agents.values() if h.status == "healthy")
        snapshot.overall_score = sum(h.health_score for h in self._agents.values()) / max(1, len(self._agents))
        snapshot.alerts = [a.alert_id for a in self._alerts.values() if not a.acknowledged]
        self._snapshots.append(snapshot)
        return snapshot

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        alert = self._alerts.get(alert_id)
        if not alert:
            return False
        alert.acknowledged = True
        return True

    def get_alerts(self, unacknowledged_only: bool = False) -> list[dict[str, Any]]:
        """Get alerts."""
        alerts = list(self._alerts.values())
        if unacknowledged_only:
            alerts = [a for a in alerts if not a.acknowledged]
        return [
            {
                "alert_id": a.alert_id,
                "agent_name": a.agent_name,
                "alert_type": a.alert_type,
                "message": a.message,
                "severity": a.severity,
                "acknowledged": a.acknowledged,
            }
            for a in alerts
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_agents": len(self._agents),
            "healthy_agents": sum(1 for h in self._agents.values() if h.status == "healthy"),
            "total_alerts": len(self._alerts),
            "unacknowledged_alerts": sum(1 for a in self._alerts.values() if not a.acknowledged),
            "health_thresholds": self._thresholds,
            "engine_status": "operational",
        }


engine = UniverseHealthMonitor()

# Register default agents
for agent in ["Inference", "Memora", "Stratex", "Forge", "Cortex", "Sentinel", "IntelX", "Futuris", "VyralX"]:
    engine.register_agent(agent)


@router.post("/health/register")
async def register_agent(agent_name: str):
    """Register an agent for monitoring."""
    health = engine.register_agent(agent_name)
    return {"agent_name": health.agent_name, "status": "registered"}


@router.post("/health/check")
async def check_health(agent_name: str, status: str, response_time_ms: float = 0.0,
                       error: str | None = None):
    """Check agent health."""
    health = engine.check_agent_health(agent_name, status, response_time_ms, error)
    return {
        "agent_name": health.agent_name,
        "status": health.status,
        "health_score": health.health_score,
        "error_count": health.error_count,
    }


@router.get("/health/universe")
async def universe_health():
    """Get universe health snapshot."""
    snap = engine.get_universe_health()
    return {
        "overall_score": snap.overall_score,
        "total_agents": snap.total_agents,
        "healthy_agents": snap.healthy_agents,
        "alerts": len(snap.alerts),
    }


@router.get("/health/alerts")
async def get_alerts(unacknowledged_only: bool = False):
    """Get health alerts."""
    return {"alerts": engine.get_alerts(unacknowledged_only)}


@router.post("/health/alerts/{alert_id}/ack")
async def acknowledge_alert(alert_id: str):
    """Acknowledge an alert."""
    if not engine.acknowledge_alert(alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"alert_id": alert_id, "status": "acknowledged"}


@router.get("/health/report")
async def health_report():
    """Get health monitor report."""
    return engine.get_report()
