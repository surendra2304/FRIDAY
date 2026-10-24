"""
FRIDAY/apps/core/src/friday_core/agent_mesh_router.py — FRIDAY Agent Mesh Router.

Smart routing of tasks to best-suited agents with capability matching,
load balancing, failover, and performance tracking.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class AgentCapability:
    """An agent's capability profile."""
    agent_name: str
    capabilities: list[str] = field(default_factory=list)
    success_rate: float = 0.5
    current_load: float = 0.0
    health: str = "healthy"
    response_time_ms: float = 0.0
    domain_expertise: dict[str, float] = field(default_factory=dict)


@dataclass
class RouteDecision:
    """A routing decision."""
    task_id: str
    routed_to: str
    reason: str
    alternatives: list[str] = field(default_factory=list)
    confidence: float = 0.5
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentRegistration:
    """An agent registration in the mesh."""
    agent_name: str
    capabilities: list[str]
    domain_expertise: dict[str, float]
    health_check_url: str = ""
    weight: float = 1.0
    registered_at: float = field(default_factory=time.time)


class AgentMeshRouter:
    """Router for intelligent task routing to agents."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentCapability] = {}
        self._registrations: dict[str, AgentRegistration] = {}
        self._routing_history: list[RouteDecision] = []

    def register_agent(self, agent_name: str, capabilities: list[str],
                       domain_expertise: dict[str, float] | None = None,
                       health_check_url: str = "") -> AgentRegistration:
        """Register an agent in the mesh."""
        reg = AgentRegistration(
            agent_name=agent_name,
            capabilities=capabilities,
            domain_expertise=domain_expertise or {},
            health_check_url=health_check_url,
        )
        self._registrations[agent_name] = reg
        self._agents[agent_name] = AgentCapability(
            agent_name=agent_name,
            capabilities=capabilities,
            domain_expertise=domain_expertise or {},
        )
        return reg

    def route_task(self, task_description: str, required_capability: str = "",
                   task_id: str | None = None) -> RouteDecision:
        """Route a task to the best-suited agent."""
        task_id = task_id or f"task_{uuid.uuid4().hex[:8]}"
        candidates = []
        for agent_name, reg in self._registrations.items():
            score = 0.0
            # Capability match
            if required_capability and required_capability in reg.capabilities:
                score += 0.4
            # Domain expertise match
            words = task_description.lower().split()
            for word in words:
                for domain, expertise in reg.domain_expertise.items():
                    if word in domain.lower():
                        score += expertise * 0.2
            # Load consideration
            agent_cap = self._agents[agent_name]
            score -= agent_cap.current_load * 0.1
            # Success rate
            score += agent_cap.success_rate * 0.3
            candidates.append((agent_name, score))

        if not candidates:
            raise HTTPException(status_code=400, detail="No agents registered")

        candidates.sort(key=lambda x: x[1], reverse=True)
        best_agent = candidates[0][0]
        best_score = candidates[0][1]
        alternatives = [a for a, _ in candidates[1:3]]

        decision = RouteDecision(
            task_id=task_id,
            routed_to=best_agent,
            reason=f"Best match with score {best_score:.2f}",
            alternatives=alternatives,
            confidence=min(1.0, best_score),
        )
        self._routing_history.append(decision)
        # Increment load
        self._agents[best_agent].current_load += 0.1
        return decision

    def update_agent_health(self, agent_name: str, health: str,
                            response_time_ms: float = 0.0) -> bool:
        """Update agent health status."""
        if agent_name not in self._agents:
            return False
        self._agents[agent_name].health = health
        self._agents[agent_name].response_time_ms = response_time_ms
        return True

    def get_agent_status(self, agent_name: str) -> dict[str, Any]:
        """Get agent status."""
        reg = self._registrations.get(agent_name)
        cap = self._agents.get(agent_name)
        if not reg or not cap:
            raise HTTPException(status_code=404, detail="Agent not found")
        return {
            "agent_name": agent_name,
            "capabilities": reg.capabilities,
            "health": cap.health,
            "current_load": cap.current_load,
            "success_rate": cap.success_rate,
            "response_time_ms": cap.response_time_ms,
            "domain_expertise": reg.domain_expertise,
        }

    def get_routing_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent routing decisions."""
        return [
            {
                "task_id": d.task_id,
                "routed_to": d.routed_to,
                "reason": d.reason,
                "confidence": d.confidence,
            }
            for d in self._routing_history[-limit:]
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_agents": len(self._agents),
            "total_routes": len(self._routing_history),
            "healthy_agents": sum(1 for a in self._agents.values() if a.health == "healthy"),
            "engine_status": "operational",
        }


engine = AgentMeshRouter()

# Register default agents
engine.register_agent("Inference", ["reasoning", "analysis"], {"logic": 0.9, "reasoning": 0.8})
engine.register_agent("Memora", ["memory", "context"], {"memory": 0.9, "knowledge": 0.8})
engine.register_agent("Stratex", ["trading", "finance"], {"trading": 0.9, "finance": 0.8})
engine.register_agent("Forge", ["coding", "development"], {"code": 0.9, "software": 0.8})
engine.register_agent("Cortex", ["decision", "strategy"], {"business": 0.8, "decision": 0.9})
engine.register_agent("Sentinel", ["security", "compliance"], {"security": 0.9, "audit": 0.8})
engine.register_agent("IntelX", ["research", "intel"], {"research": 0.9, "threat": 0.8})
engine.register_agent("Futuris", ["forecast", "prediction"], {"prediction": 0.9, "forecast": 0.8})
engine.register_agent("VyralX", ["content", "video"], {"content": 0.9, "media": 0.8})


@router.post("/mesh/register")
async def register_agent(agent_name: str, capabilities: list[str],
                         domain_expertise: dict[str, float] | None = None,
                         health_check_url: str = ""):
    """Register an agent in the mesh."""
    reg = engine.register_agent(agent_name, capabilities, domain_expertise, health_check_url)
    return {"agent_name": reg.agent_name, "capabilities": reg.capabilities, "status": "registered"}


@router.post("/mesh/route")
async def route_task(task_description: str, required_capability: str = "",
                     task_id: str | None = None):
    """Route a task to the best-suited agent."""
    decision = engine.route_task(task_description, required_capability, task_id)
    return {
        "task_id": decision.task_id,
        "routed_to": decision.routed_to,
        "reason": decision.reason,
        "alternatives": decision.alternatives,
        "confidence": decision.confidence,
    }


@router.get("/mesh/agents/{agent_name}")
async def get_agent_status(agent_name: str):
    """Get agent status."""
    return engine.get_agent_status(agent_name)


@router.get("/mesh/agents")
async def list_agents():
    """List all registered agents."""
    return {"report": engine.get_report()}


@router.post("/mesh/health/{agent_name}")
async def update_health(agent_name: str, health: str, response_time_ms: float = 0.0):
    """Update agent health."""
    if not engine.update_agent_health(agent_name, health, response_time_ms):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent_name": agent_name, "health": health}


@router.get("/mesh/history")
async def routing_history(limit: int = 20):
    """Get routing history."""
    return {"history": engine.get_routing_history(limit)}


@router.get("/mesh/report")
async def mesh_report():
    """Get mesh router report."""
    return engine.get_report()
