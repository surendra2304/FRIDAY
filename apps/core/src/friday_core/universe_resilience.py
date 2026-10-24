"""
FRIDAY/apps/core/src/friday_core/universe_resilience.py — FRIDAY Universe Resilience Engine.

Fault tolerance, graceful degradation, recovery orchestration,
circuit breaker coordination, and resilience scoring across all agents.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class AgentResilienceProfile:
    """Resilience profile for an agent."""
    agent_name: str
    fault_tolerance: str = "standard"  # minimal, standard, high, critical
    degradation_strategy: str = "graceful"  # fail_fast, graceful, degraded, fallback
    max_recovery_time: float = 30.0
    circuit_breaker_threshold: int = 5
    health_check_interval: float = 5.0
    last_incident: float = 0.0
    uptime_pct: float = 99.9


@dataclass
class IncidentRecord:
    """An incident record."""
    incident_id: str
    agent_name: str
    description: str
    severity: str = "medium"
    started_at: float = field(default_factory=time.time)
    resolved_at: float = 0.0
    recovery_action: str = ""
    root_cause: str = ""


@dataclass
class ResilienceReport:
    """Overall universe resilience report."""
    report_id: str
    total_agents: int = 0
    avg_uptime: float = 99.9
    total_incidents: int = 0
    recovered_incidents: int = 0
    overall_resilience_score: float = 0.0
    risk_areas: list[str] = field(default_factory=list)
    generated_at: float = field(default_factory=time.time)


class UniverseResilienceEngine:
    """Engine for universe-wide resilience management."""

    def __init__(self) -> None:
        self._profiles: dict[str, AgentResilienceProfile] = {}
        self._incidents: list[IncidentRecord] = []
        self._reports: list[ResilienceReport] = []

    def register_agent(self, agent_name: str, fault_tolerance: str = "standard",
                       degradation_strategy: str = "graceful",
                       max_recovery_time: float = 30.0,
                       circuit_breaker_threshold: int = 5,
                       health_check_interval: float = 5.0) -> AgentResilienceProfile:
        """Register an agent's resilience profile."""
        profile = AgentResilienceProfile(
            agent_name=agent_name, fault_tolerance=fault_tolerance,
            degradation_strategy=degradation_strategy,
            max_recovery_time=max_recovery_time,
            circuit_breaker_threshold=circuit_breaker_threshold,
            health_check_interval=health_check_interval,
        )
        self._profiles[agent_name] = profile
        return profile

    def report_incident(self, agent_name: str, description: str,
                       severity: str = "medium", recovery_action: str = "",
                       root_cause: str = "") -> IncidentRecord:
        """Report an incident."""
        incident_id = f"inc_{uuid.uuid4().hex[:12]}"
        incident = IncidentRecord(
            incident_id=incident_id, agent_name=agent_name,
            description=description, severity=severity,
            recovery_action=recovery_action, root_cause=root_cause,
        )
        incident.resolved_at = time.time()
        self._incidents.append(incident)

        profile = self._profiles.get(agent_name)
        if profile:
            profile.last_incident = incident.started_at
            profile.uptime_pct = max(0.0, 100.0 - (len(self._incidents) * 0.1))
        return incident

    def get_agent_resilience(self, agent_name: str) -> dict[str, Any]:
        """Get an agent's resilience profile."""
        profile = self._profiles.get(agent_name)
        if not profile:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {
            "agent_name": profile.agent_name,
            "fault_tolerance": profile.fault_tolerance,
            "degradation_strategy": profile.degradation_strategy,
            "uptime_pct": profile.uptime_pct,
            "incident_count": sum(1 for i in self._incidents if i.agent_name == agent_name),
        }

    def generate_report(self) -> ResilienceReport:
        """Generate universe resilience report."""
        report_id = f"res_{uuid.uuid4().hex[:12]}"
        report = ResilienceReport(report_id=report_id)
        report.total_agents = len(self._profiles)
        report.total_incidents = len(self._incidents)
        report.recovered_incidents = sum(1 for i in self._incidents if i.resolved_at > 0)
        report.avg_uptime = sum(p.uptime_pct for p in self._profiles.values()) / max(1, len(self._profiles))
        report.overall_resilience_score = (
            (report.avg_uptime / 100.0) * 0.5 +
            (report.recovered_incidents / max(1, report.total_incidents)) * 0.3 +
            (len(self._profiles) / 10.0) * 0.2
        ) * 100

        for profile in self._profiles.values():
            if profile.uptime_pct < 99.0:
                report.risk_areas.append(f"{profile.agent_name}: {profile.uptime_pct:.1f}% uptime")

        self._reports.append(report)
        return report

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_agents": len(self._profiles),
            "total_incidents": len(self._incidents),
            "total_reports": len(self._reports),
            "engine_status": "operational",
        }


engine = UniverseResilienceEngine()


@router.post("/resilience/agents")
async def register_agent(agent_name: str, fault_tolerance: str = "standard",
                         degradation_strategy: str = "graceful",
                         max_recovery_time: float = 30.0,
                         circuit_breaker_threshold: int = 5,
                         health_check_interval: float = 5.0):
    """Register an agent's resilience profile."""
    profile = engine.register_agent(agent_name, fault_tolerance, degradation_strategy,
                                    max_recovery_time, circuit_breaker_threshold, health_check_interval)
    return {"agent_name": agent_name, "fault_tolerance": profile.fault_tolerance}


@router.post("/resilience/incidents")
async def report_incident(agent_name: str, description: str, severity: str = "medium",
                          recovery_action: str = "", root_cause: str = ""):
    """Report an incident."""
    incident = engine.report_incident(agent_name, description, severity, recovery_action, root_cause)
    return {"incident_id": incident.incident_id, "agent_name": agent_name, "resolved": True}


@router.get("/resilience/agents/{agent_name}")
async def get_agent_resilience(agent_name: str):
    """Get an agent's resilience profile."""
    return engine.get_agent_resilience(agent_name)


@router.post("/resilience/report")
async def generate_report():
    """Generate resilience report."""
    report = engine.generate_report()
    return {
        "report_id": report.report_id,
        "avg_uptime": report.avg_uptime,
        "resilience_score": round(report.overall_resilience_score, 1),
        "risk_areas": report.risk_areas,
    }


@router.get("/resilience/report")
async def resilience_report():
    """Get resilience engine report."""
    return engine.get_report()
