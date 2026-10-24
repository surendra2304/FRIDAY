"""
FRIDAY/apps/core/src/friday_core/universe_task_router.py — FRIDAY Universe Task Router.

Intelligent task routing, agent capability matching, load-aware dispatch,
and task prioritization across the universe.
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
    """Agent capability profile."""
    agent: str
    capabilities: list[str] = field(default_factory=list)
    current_load: float = 0.0  # 0.0 to 1.0
    success_rate: float = 0.8
    avg_response_time: float = 0.0


@dataclass
class Task:
    """A task to route."""
    task_id: str
    description: str
    required_capabilities: list[str] = field(default_factory=list)
    priority: int = 5  # 1-10
    deadline: float = 0.0
    status: str = "pending"  # pending, routed, in_progress, completed, failed


@dataclass
class RoutingDecision:
    """A routing decision."""
    decision_id: str
    task_id: str
    assigned_agent: str
    confidence: float = 0.0
    alternatives: list[str] = field(default_factory=list)
    reason: str = ""
    routed_at: float = field(default_factory=time.time)


class UniverseTaskRouter:
    """Engine for intelligent task routing."""

    def __init__(self) -> None:
        self._capabilities: dict[str, AgentCapability] = {}
        self._tasks: dict[str, Task] = {}
        self._decisions: list[RoutingDecision] = []

    def register_agent(self, agent: str, capabilities: list[str],
                       success_rate: float = 0.8) -> AgentCapability:
        """Register an agent's capabilities."""
        cap = AgentCapability(
            agent=agent, capabilities=capabilities,
            success_rate=success_rate,
        )
        self._capabilities[agent] = cap
        return cap

    def update_load(self, agent: str, load: float) -> None:
        """Update agent load."""
        cap = self._capabilities.get(agent)
        if cap:
            cap.current_load = load

    def submit_task(self, description: str, required_capabilities: list[str] | None = None,
                    priority: int = 5, deadline: float = 0.0) -> Task:
        """Submit a task for routing."""
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        task = Task(
            task_id=task_id, description=description,
            required_capabilities=required_capabilities or [],
            priority=priority, deadline=deadline,
        )
        self._tasks[task_id] = task
        return task

    def route_task(self, task_id: str) -> RoutingDecision:
        """Route a task to the best agent."""
        task = self._tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        decision_id = f"route_{uuid.uuid4().hex[:12]}"
        decision = RoutingDecision(decision_id=decision_id, task_id=task_id, assigned_agent="")

        # Score agents
        scores = {}
        for agent, cap in self._capabilities.items():
            # Check capability match
            if task.required_capabilities:
                matched = sum(1 for c in task.required_capabilities if c in cap.capabilities)
                cap_score = matched / len(task.required_capabilities)
            else:
                cap_score = 0.5

            # Load penalty
            load_score = 1.0 - cap.current_load
            # Success rate bonus
            success_score = cap.success_rate

            scores[agent] = cap_score * 0.5 + load_score * 0.2 + success_score * 0.3

        if not scores:
            raise HTTPException(status_code=400, detail="No agents registered")

        # Sort and pick best
        sorted_agents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_agent, best_score = sorted_agents[0]
        decision.assigned_agent = best_agent
        decision.confidence = best_score
        decision.alternatives = [a for a, _ in sorted_agents[1:3]]
        decision.reason = f"Best match: {best_agent} with score {best_score:.2f}"
        task.status = "routed"

        self._decisions.append(decision)
        return decision

    def get_tasks(self, status: str | None = None) -> list[dict[str, Any]]:
        """Get tasks."""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return [
            {"description": t.description[:80], "priority": t.priority,
             "status": t.status, "capabilities": len(t.required_capabilities)}
            for t in tasks
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_agents": len(self._capabilities),
            "total_tasks": len(self._tasks),
            "total_routes": len(self._decisions),
            "routed_tasks": sum(1 for t in self._tasks.values() if t.status == "routed"),
            "engine_status": "operational",
        }


engine = UniverseTaskRouter()


@router.post("/taskrouter/agents")
async def register_agent(agent: str, capabilities: list[str], success_rate: float = 0.8):
    """Register an agent's capabilities."""
    cap = engine.register_agent(agent, capabilities, success_rate)
    return {"agent": agent, "capability_count": len(cap.capabilities)}


@router.post("/taskrouter/tasks")
async def submit_task(description: str, required_capabilities: list[str] | None = None,
                      priority: int = 5, deadline: float = 0.0):
    """Submit a task for routing."""
    task = engine.submit_task(description, required_capabilities, priority, deadline)
    return {"task_id": task.task_id, "priority": task.priority}


@router.post("/taskrouter/route/{task_id}")
async def route_task(task_id: str):
    """Route a task to the best agent."""
    decision = engine.route_task(task_id)
    return {
        "task_id": task_id,
        "assigned_agent": decision.assigned_agent,
        "confidence": decision.confidence,
        "alternatives": decision.alternatives,
    }


@router.get("/taskrouter/tasks")
async def get_tasks(status: str | None = None):
    """Get tasks."""
    return {"tasks": engine.get_tasks(status)}


@router.get("/taskrouter/report")
async def taskrouter_report():
    """Get task router report."""
    return engine.get_report()
