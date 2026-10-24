"""
FRIDAY/src/friday/services/multi_agent_coordinator.py — FRIDAY Multi-Agent Coordinator.

Coordinates multiple agents for complex tasks: task distribution, agent
selection, result aggregation, conflict resolution between agents, and
cross-agent communication. Manages the agent mesh for collaborative work.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class AgentCapability:
    """An agent's capability profile."""
    agent_id: str
    agent_name: str
    capabilities: list[str] = field(default_factory=list)
    current_load: float = 0.0
    status: str = "available"  # available, busy, offline
    last_heartbeat: float = 0.0
    success_rate: float = 0.0


@dataclass
class TaskAssignment:
    """A task assigned to an agent."""
    assignment_id: str
    task_id: str
    agent_id: str
    status: str = "pending"  # pending, in_progress, completed, failed
    priority: int = 1
    assigned_at: float = 0.0
    completed_at: float = 0.0
    result: str = ""


@dataclass
class CoordinationPlan:
    """A plan for coordinating multiple agents."""
    plan_id: str
    task_description: str
    assignments: list[dict] = field(default_factory=list)
    dependencies: list[dict] = field(default_factory=list)
    status: str = "planning"  # planning, executing, completed, failed
    created_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class AgentResult:
    """Result from an agent."""
    result_id: str
    task_id: str
    agent_id: str
    output: str = ""
    confidence: float = 0.0
    duration_ms: float = 0.0
    status: str = "success"
    errors: list[str] = field(default_factory=list)


@dataclass
class AgentConflict:
    """A conflict between agent results."""
    conflict_id: str
    task_id: str
    agent_a: str
    agent_b: str
    description: str = ""
    resolution: str = ""
    resolution_strategy: str = ""  # majority_vote, expert_opinion, highest_confidence
    resolved: bool = False


@dataclass
class AggregationResult:
    """Final aggregated result from multiple agents."""
    aggregation_id: str
    task_id: str
    final_result: str = ""
    contributing_agents: list[str] = field(default_factory=list)
    confidence: float = 0.0
    conflicts_resolved: int = 0
    consensus_level: str = ""  # low, medium, high, full


@dataclass
class CoordinationHistory:
    """History of coordination activities."""
    total_plans: int = 0
    completed_plans: int = 0
    failed_plans: int = 0
    avg_completion_time_ms: float = 0.0
    avg_confidence: float = 0.0
    avg_agents_per_plan: float = 0.0


class MultiAgentCoordinator:
    """Multi-agent coordination engine."""

    def __init__(self):
        self._agents: dict[str, AgentCapability] = {}
        self._assignments: dict[str, TaskAssignment] = {}
        self._plans: dict[str, CoordinationPlan] = {}
        self._results: list[AgentResult] = []
        self._conflicts: list[AgentConflict] = []
        self._aggregations: list[AggregationResult] = []
        self._history: CoordinationHistory = CoordinationHistory()

        # Register known agents
        self._register_agents()

    def _register_agents(self):
        """Register known agents with their capabilities."""
        agents = [
            ("stratex", "Stratex", ["trading", "finance", "market_analysis", "risk_management"]),
            ("vyralx", "VyralX", ["video", "content", "analytics", "social_media"]),
            ("cortex", "Cortex", ["decisions", "analytics", "scenarios", "experiments"]),
            ("inference", "Inference", ["reasoning", "knowledge_graphs", "logic", "inference"]),
            ("forge", "Forge", ["coding", "development", "deployment", "testing"]),
            ("memora", "Memora", ["memory", "storage", "knowledge", "context"]),
            ("intelex", "IntelX", ["threat_intel", "security", "osint", "cyber"]),
            ("futuris", "Futuris", ["forecasting", "prediction", "scenarios", "maintenance"]),
            ("sentinel", "Sentinel", ["security", "monitoring", "compliance", "threat_hunting"]),
        ]
        for agent_id, name, caps in agents:
            self._agents[agent_id] = AgentCapability(
                agent_id=agent_id,
                agent_name=name,
                capabilities=caps,
                current_load=0.0,
                status="available",
                last_heartbeat=time.time(),
                success_rate=0.85 + (ord(hashlib.md5(agent_id.encode()).hexdigest()[:1]) % 10) / 100,
            )

    def select_agents(self, required_capabilities: list[str], count: int = 3) -> list[AgentCapability]:
        """Select agents based on required capabilities."""
        matched = []
        for agent in self._agents.values():
            if agent.status != "available":
                continue
            score = len(set(required_capabilities) & set(agent.capabilities))
            if score > 0:
                matched.append((agent, score))

        # Sort by score, then by success rate
        matched.sort(key=lambda x: (x[1], x[0].success_rate), reverse=True)

        return [agent for agent, _ in matched[:count]]

    def create_plan(self, task_description: str, subtasks: list[dict]) -> CoordinationPlan:
        """Create a coordination plan."""
        plan = CoordinationPlan(
            plan_id=hashlib.md5(
                f"plan:{task_description[:30]}:{time.time()}".encode()
            ).hexdigest()[:12],
            task_description=task_description,
            created_at=time.time(),
        )

        for subtask in subtasks:
            required_caps = subtask.get("capabilities", [])
            agents = self.select_agents(required_caps, count=1)

            if agents:
                agent = agents[0]
                assignment = TaskAssignment(
                    assignment_id=hashlib.md5(
                        f"assignment:{plan.plan_id}:{subtask.get('id', '')}:{time.time()}".encode()
                    ).hexdigest()[:12],
                    task_id=subtask.get("id", ""),
                    agent_id=agent.agent_id,
                    priority=subtask.get("priority", 1),
                    assigned_at=time.time(),
                )
                self._assignments[assignment.assignment_id] = assignment
                agent.current_load += 0.1
                agent.status = "busy"

                plan.assignments.append({
                    "assignment_id": assignment.assignment_id,
                    "agent_id": agent.agent_id,
                    "agent_name": agent.agent_name,
                    "task": subtask.get("description", ""),
                    "priority": subtask.get("priority", 1),
                })

            if subtask.get("depends_on"):
                plan.dependencies.append({
                    "task": subtask.get("id", ""),
                    "depends_on": subtask["depends_on"],
                })

        plan.status = "executing"
        self._plans[plan.plan_id] = plan
        return plan

    def submit_result(self, assignment_id: str, output: str, confidence: float = 0.8) -> AgentResult:
        """Submit a result from an agent."""
        assignment = self._assignments.get(assignment_id)
        if not assignment:
            raise HTTPException(404, f"Assignment {assignment_id} not found")

        agent = self._agents.get(assignment.agent_id)
        if not agent:
            raise HTTPException(404, f"Agent {assignment.agent_id} not found")

        start = assignment.assigned_at
        result = AgentResult(
            result_id=hashlib.md5(
                f"result:{assignment_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            task_id=assignment.task_id,
            agent_id=assignment.agent_id,
            output=output,
            confidence=confidence,
            duration_ms=(time.time() - start) * 1000,
            status="success",
        )

        self._results.append(result)
        assignment.status = "completed"
        assignment.completed_at = time.time()
        assignment.result = output
        agent.current_load -= 0.1
        agent.status = "available"
        agent.last_heartbeat = time.time()

        return result

    def resolve_conflict(self, task_id: str) -> AgentConflict:
        """Detect and resolve conflicts between agent results."""
        # Find results for the same task
        task_results = [r for r in self._results if r.task_id == task_id]

        if len(task_results) < 2:
            return AgentConflict(
                conflict_id="",
                task_id=task_id,
                agent_a="",
                agent_b="",
                description="No conflict: only one result",
                resolved=True,
            )

        # Check for conflicting outputs
        unique_outputs = set(r.output[:50] for r in task_results)

        if len(unique_outputs) <= 1:
            return AgentConflict(
                conflict_id="",
                task_id=task_id,
                agent_a="",
                agent_b="",
                description="No conflict: all agents agree",
                resolved=True,
            )

        # Pick the two most different results
        sorted_results = sorted(task_results, key=lambda r: r.confidence, reverse=True)

        conflict = AgentConflict(
            conflict_id=hashlib.md5(
                f"conflict:{task_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            task_id=task_id,
            agent_a=sorted_results[0].agent_id,
            agent_b=sorted_results[1].agent_id,
            description=f"Agents disagree on result for task {task_id}",
            resolution=sorted_results[0].output[:100],
            resolution_strategy="highest_confidence",
            resolved=True,
        )

        self._conflicts.append(conflict)
        return conflict

    def aggregate_results(self, task_id: str, final_output: str) -> AggregationResult:
        """Aggregate results from multiple agents."""
        task_results = [r for r in self._results if r.task_id == task_id]
        task_conflicts = [c for c in self._conflicts if c.task_id == task_id]

        agg = AggregationResult(
            aggregation_id=hashlib.md5(
                f"aggregation:{task_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            task_id=task_id,
            final_result=final_output,
            contributing_agents=list(set(r.agent_id for r in task_results)),
            confidence=sum(r.confidence for r in task_results) / max(1, len(task_results)),
            conflicts_resolved=sum(1 for c in task_conflicts if c.resolved),
            consensus_level="high" if len(task_results) >= 3 and len(set(r.output[:20] for r in task_results)) <= 2 else "medium" if len(task_results) >= 2 else "low",
        )

        self._aggregations.append(agg)

        # Update history
        self._history.total_plans += 1
        self._history.completed_plans += 1
        self._history.avg_confidence = (
            self._history.avg_confidence * 0.9 + agg.confidence * 0.1
        )
        self._history.avg_agents_per_plan = (
            self._history.avg_agents_per_plan * 0.9 + len(agg.contributing_agents) * 0.1
        )

        return agg

    def get_report(self) -> dict:
        """Get multi-agent coordinator report."""
        return {
            "total_agents": len(self._agents),
            "available_agents": sum(1 for a in self._agents.values() if a.status == "available"),
            "busy_agents": sum(1 for a in self._agents.values() if a.status == "busy"),
            "total_plans": len(self._plans),
            "total_assignments": len(self._assignments),
            "total_results": len(self._results),
            "total_conflicts": len(self._conflicts),
            "total_aggregations": len(self._aggregations),
            "resolved_conflicts": sum(1 for c in self._conflicts if c.resolved),
            "agent_capabilities": {
                a.agent_name: {
                    "capabilities": a.capabilities,
                    "status": a.status,
                    "success_rate": a.success_rate,
                }
                for a in self._agents.values()
            },
            "recent_plans": [
                {
                    "description": p.task_description[:50],
                    "agents": len(p.assignments),
                    "status": p.status,
                }
                for p in list(self._plans.values())[-5:]
            ],
            "recent_aggregations": [
                {
                    "task": a.task_id,
                    "agents": len(a.contributing_agents),
                    "confidence": a.confidence,
                    "consensus": a.consensus_level,
                }
                for a in self._aggregations[-5:]
            ],
            "history": {
                "total_plans": self._history.total_plans,
                "completed": self._history.completed_plans,
                "failed": self._history.failed_plans,
                "avg_confidence": self._history.avg_confidence,
                "avg_agents": self._history.avg_agents_per_plan,
            },
        }


coordinator = MultiAgentCoordinator()


@router.post("/api/v1/friday/coordination/agents")
async def list_agents():
    """List all registered agents."""
    return {
        "total": len(coordinator._agents),
        "agents": [
            {"id": a.agent_id, "name": a.agent_name, "capabilities": a.capabilities, "status": a.status, "success_rate": a.success_rate}
            for a in coordinator._agents.values()
        ],
    }


@router.post("/api/v1/friday/coordination/select")
async def select_agents(payload: dict):
    """Select agents based on capabilities."""
    agents = coordinator.select_agents(
        required_capabilities=payload["capabilities"],
        count=payload.get("count", 3),
    )
    return {
        "selected": [a.agent_name for a in agents],
        "count": len(agents),
    }


@router.post("/api/v1/friday/coordination/plans")
async def create_plan(payload: dict):
    """Create a coordination plan."""
    plan = coordinator.create_plan(
        task_description=payload["task_description"],
        subtasks=payload.get("subtasks", []),
    )
    return {"plan_id": plan.plan_id, "assignments": len(plan.assignments), "status": plan.status}


@router.post("/api/v1/friday/coordination/results")
async def submit_result(payload: dict):
    """Submit a result from an agent."""
    result = coordinator.submit_result(
        assignment_id=payload["assignment_id"],
        output=payload["output"],
        confidence=payload.get("confidence", 0.8),
    )
    return {"result_id": result.result_id, "agent": result.agent_id, "status": result.status}


@router.post("/api/v1/friday/coordination/aggregate")
async def aggregate_results(payload: dict):
    """Aggregate results from multiple agents."""
    agg = coordinator.aggregate_results(
        task_id=payload["task_id"],
        final_output=payload["final_output"],
    )
    return {
        "aggregation_id": agg.aggregation_id,
        "agents": len(agg.contributing_agents),
        "confidence": agg.confidence,
        "consensus": agg.consensus_level,
        "conflicts_resolved": agg.conflicts_resolved,
    }


@router.get("/api/v1/friday/coordination/report")
async def get_report():
    """Get multi-agent coordinator report."""
    return coordinator.get_report()
