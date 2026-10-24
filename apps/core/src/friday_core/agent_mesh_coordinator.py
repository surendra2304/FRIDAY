"""
FRIDAY/apps/core/src/friday_core/agent_mesh_coordinator.py — FRIDAY Agent Mesh Coordinator.

Extends FRIDAY's orchestration capabilities with:
1. Multi-Agent Task Distribution: distribute tasks across agents based on capability
2. Agent Health Monitoring: monitor agent health and readiness
3. Dynamic Load Balancing: balance load across agents
4. Agent Capability Discovery: discover what each agent can do
5. Failure Recovery: recover from agent failures
6. Cross-Agent Communication: enable agent-to-agent communication
7. Mesh Topology Management: manage the agent mesh topology
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
    """An agent's capabilities."""
    agent_name: str
    capabilities: list[str] = field(default_factory=list)
    status: str = "unknown"  # online, offline, degraded, unknown
    last_heartbeat: float = 0.0
    current_load: float = 0.0  # 0-1
    max_load: float = 1.0
    success_rate: float = 0.5
    avg_response_time: float = 0.0
    available: bool = True


@dataclass
class TaskAssignment:
    """A task assignment to an agent."""
    task_id: str
    agent: str
    task_type: str
    priority: int = 1
    status: str = "assigned"  # assigned, in_progress, completed, failed
    assigned_at: float = 0.0
    completed_at: float = 0.0
    result: dict = field(default_factory=dict)
    attempts: int = 0


@dataclass
class MeshTopology:
    """Agent mesh topology."""
    nodes: list[str]
    edges: list[tuple[str, str]]
    latency: dict[str, float]
    bandwidth: dict[str, float]
    health: dict[str, str]


@dataclass
class LoadBalanceDecision:
    """Load balancing decision."""
    task_id: str
    task_type: str
    candidates: list[str]
    selected: str
    reason: str
    estimated_time: float
    load_score: float


@dataclass
class RecoveryPlan:
    """Failure recovery plan."""
    failed_agent: str
    affected_tasks: list[str]
    recovery_steps: list[str]
    reassignment_plan: dict[str, str]  # task_id -> new_agent
    estimated_recovery_time: float


@dataclass
class MeshReport:
    """Mesh health report."""
    total_agents: int
    online_agents: int
    degraded_agents: int
    offline_agents: int
    avg_load: float
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    avg_success_rate: float
    mesh_health: str  # healthy, degraded, critical


class AgentMeshCoordinator:
    """Agent mesh coordination engine."""

    def __init__(self):
        self._agents: dict[str, AgentCapability] = {}
        self._tasks: dict[str, TaskAssignment] = {}
        self._topology: MeshTopology | None = None
        self._assignments: list[TaskAssignment] = []
        self._recovery_plans: dict[str, RecoveryPlan] = {}

    # ── Agent Capability Discovery ────────────────────────────────────────

    def register_agent(
        self,
        agent_name: str,
        capabilities: list[str],
        max_load: float = 1.0,
    ) -> AgentCapability:
        """Register an agent with its capabilities."""
        agent = AgentCapability(
            agent_name=agent_name,
            capabilities=capabilities,
            status="online",
            last_heartbeat=time.time(),
            max_load=max_load,
            available=True,
        )
        self._agents[agent_name] = agent
        return agent

    def heartbeat(self, agent_name: str, load: float = 0.0) -> bool:
        """Receive heartbeat from an agent."""
        agent = self._agents.get(agent_name)
        if not agent:
            return False

        agent.last_heartbeat = time.time()
        agent.current_load = load
        agent.status = "online" if load < 0.8 else "degraded"
        agent.available = load < 0.9
        return True

    def discover_capabilities(self, agent_name: str) -> list[str]:
        """Discover an agent's capabilities."""
        agent = self._agents.get(agent_name)
        return agent.capabilities if agent else []

    def find_agents_for_task(self, task_type: str) -> list[AgentCapability]:
        """Find agents capable of handling a task type."""
        candidates = []
        for agent in self._agents.values():
            if agent.available and task_type in agent.capabilities:
                candidates.append(agent)

        # Sort by load (lowest first) and success rate (highest first)
        candidates.sort(key=lambda a: (a.current_load, -a.success_rate))
        return candidates

    # ── Multi-Agent Task Distribution ─────────────────────────────────────

    def distribute_task(
        self,
        task_type: str,
        task_data: dict,
        priority: int = 1,
    ) -> TaskAssignment | None:
        """Distribute a task to the best-suited agent."""
        candidates = self.find_agents_for_task(task_type)
        if not candidates:
            return None

        # Select best candidate
        best = candidates[0]

        task_id = hashlib.md5(
            f"task:{task_type}:{time.time()}".encode()
        ).hexdigest()[:12]

        assignment = TaskAssignment(
            task_id=task_id,
            agent=best.agent_name,
            task_type=task_type,
            priority=priority,
            status="assigned",
            assigned_at=time.time(),
            attempts=1,
        )

        self._tasks[task_id] = assignment
        self._assignments.append(assignment)

        # Update agent load
        best.current_load = min(best.max_load, best.current_load + 0.1)

        return assignment

    def distribute_batch(
        self,
        tasks: list[dict],
    ) -> list[TaskAssignment]:
        """Distribute a batch of tasks across agents."""
        assignments = []

        for task in tasks:
            assignment = self.distribute_task(
                task_type=task.get("type", ""),
                task_data=task,
                priority=task.get("priority", 1),
            )
            if assignment:
                assignments.append(assignment)

        return assignments

    def complete_task(
        self,
        task_id: str,
        result: dict | None = None,
        success: bool = True,
    ) -> dict:
        """Mark a task as completed."""
        task = self._tasks.get(task_id)
        if not task:
            raise HTTPException(404, f"Task {task_id} not found")

        task.status = "completed" if success else "failed"
        task.completed_at = time.time()
        task.result = result or {}

        # Update agent stats
        agent = self._agents.get(task.agent)
        if agent:
            agent.current_load = max(0.0, agent.current_load - 0.1)

            # Update success rate
            agent.success_rate = (
                (agent.success_rate * (task.attempts - 1) + (1.0 if success else 0.0))
                / task.attempts
            )

        return task.__dict__

    # ── Dynamic Load Balancing ────────────────────────────────────────────

    def balance_load(
        self,
        task_id: str,
        task_type: str,
    ) -> LoadBalanceDecision | None:
        """Make a load balancing decision."""
        candidates = self.find_agents_for_task(task_type)
        if not candidates:
            return None

        # Score candidates
        scored = []
        for agent in candidates:
            load_score = 1.0 - agent.current_load / agent.max_load
            success_bonus = agent.success_rate * 0.3
            latency_penalty = agent.avg_response_time * 0.001

            score = load_score * 0.5 + success_bonus + latency_penalty
            scored.append((score, agent))

        scored.sort(key=lambda x: -x[0])

        best_score, best_agent = scored[0]

        decision = LoadBalanceDecision(
            task_id=task_id,
            task_type=task_type,
            candidates=[a.agent_name for _, a in scored],
            selected=best_agent.agent_name,
            reason=f"Lowest load ({best_agent.current_load:.2f}) and highest success rate ({best_agent.success_rate:.2f})",
            estimated_time=best_agent.avg_response_time or 30.0,
            load_score=best_score,
        )

        return decision

    def rebalance_mesh(self) -> list[LoadBalanceDecision]:
        """Rebalance the entire mesh."""
        # Find overloaded agents
        overloaded = [
            a for a in self._agents.values()
            if a.current_load > a.max_load * 0.7
        ]

        decisions = []
        for agent in overloaded:
            # Find tasks assigned to this agent that could be moved
            agent_tasks = [
                t for t in self._tasks.values()
                if t.agent == agent.agent_name and t.status == "assigned"
            ]

            for task in agent_tasks[:2]:  # Move at most 2 tasks
                decision = self.balance_load(task.task_id, task.task_type)
                if decision and decision.selected != agent.agent_name:
                    # Reassign
                    task.agent = decision.selected
                    decisions.append(decision)

        return decisions

    # ── Agent Health Monitoring ──────────────────────────────────────────

    def check_agent_health(self, agent_name: str) -> dict:
        """Check an agent's health."""
        agent = self._agents.get(agent_name)
        if not agent:
            return {"status": "unknown", "reason": "Agent not registered"}

        # Check heartbeat
        age = time.time() - agent.last_heartbeat
        if age > 120:
            agent.status = "offline"
            agent.available = False
        elif age > 60:
            agent.status = "degraded"
            agent.available = False

        # Check load
        if agent.current_load > agent.max_load:
            agent.status = "overloaded"

        return {
            "agent": agent_name,
            "status": agent.status,
            "available": agent.available,
            "load": agent.current_load,
            "success_rate": agent.success_rate,
            "last_heartbeat": agent.last_heartbeat,
            "heartbeat_age": age,
            "capabilities": agent.capabilities,
        }

    def get_mesh_health(self) -> MeshReport:
        """Get overall mesh health."""
        total = len(self._agents)
        online = sum(1 for a in self._agents.values() if a.status == "online")
        degraded = sum(1 for a in self._agents.values() if a.status in ("degraded", "overloaded"))
        offline = sum(1 for a in self._agents.values() if a.status == "offline")

        avg_load = sum(a.current_load for a in self._agents.values()) / max(1, total)
        avg_success = sum(a.success_rate for a in self._agents.values()) / max(1, total)

        completed = sum(1 for t in self._tasks.values() if t.status == "completed")
        failed = sum(1 for t in self._tasks.values() if t.status == "failed")

        # Overall health
        if offline == 0 and degraded == 0 and avg_load < 0.5:
            mesh_health = "healthy"
        elif offline < total * 0.3 and degraded < total * 0.3:
            mesh_health = "degraded"
        else:
            mesh_health = "critical"

        return MeshReport(
            total_agents=total,
            online_agents=online,
            degraded_agents=degraded,
            offline_agents=offline,
            avg_load=avg_load,
            total_tasks=len(self._tasks),
            completed_tasks=completed,
            failed_tasks=failed,
            avg_success_rate=avg_success,
            mesh_health=mesh_health,
        )

    # ── Failure Recovery ───────────────────────────────────────────────────

    def detect_failure(self, agent_name: str) -> RecoveryPlan | None:
        """Detect and plan for agent failure."""
        agent = self._agents.get(agent_name)
        if not agent or agent.status != "offline":
            return None

        # Find affected tasks
        affected = [
            t for t in self._tasks.values()
            if t.agent == agent_name and t.status == "assigned"
        ]

        # Plan reassignment
        reassignment = {}
        recovery_steps = []

        for task in affected:
            # Find replacement
            candidates = self.find_agents_for_task(task.task_type)
            replacements = [c for c in candidates if c.agent_name != agent_name]

            if replacements:
                best = replacements[0]
                reassignment[task.task_id] = best.agent_name
                recovery_steps.append(
                    f"Reassign task {task.task_id} from {agent_name} to {best.agent_name}"
                )
            else:
                recovery_steps.append(
                    f"No replacement found for task {task.task_id}; queue for later"
                )

        plan = RecoveryPlan(
            failed_agent=agent_name,
            affected_tasks=[t.task_id for t in affected],
            recovery_steps=recovery_steps,
            reassignment_plan=reassignment,
            estimated_recovery_time=len(affected) * 30.0,
        )

        self._recovery_plans[agent_name] = plan
        return plan

    def execute_recovery(self, agent_name: str) -> dict:
        """Execute a recovery plan."""
        plan = self._recovery_plans.get(agent_name)
        if not plan:
            return {"status": "no_plan", "agent": agent_name}

        executed = []
        for task_id, new_agent in plan.reassignment_plan.items():
            task = self._tasks.get(task_id)
            if task:
                task.agent = new_agent
                task.attempts += 1
                executed.append({"task_id": task_id, "new_agent": new_agent})

        return {
            "status": "recovered",
            "agent": agent_name,
            "reassigned": executed,
            "remaining_steps": len(plan.recovery_steps) - len(executed),
        }

    # ── Cross-Agent Communication ─────────────────────────────────────────

    def send_agent_message(
        self,
        from_agent: str,
        to_agent: str,
        message_type: str,
        content: dict,
    ) -> dict:
        """Send a message between agents."""
        if from_agent not in self._agents:
            raise HTTPException(404, f"Agent {from_agent} not registered")
        if to_agent not in self._agents:
            raise HTTPException(404, f"Agent {to_agent} not registered")

        msg_id = hashlib.md5(
            f"msg:{from_agent}:{to_agent}:{time.time()}".encode()
        ).hexdigest()[:12]

        return {
            "message_id": msg_id,
            "from": from_agent,
            "to": to_agent,
            "type": message_type,
            "content": content,
            "timestamp": time.time(),
        }

    # ── Mesh Topology Management ──────────────────────────────────────────

    def build_topology(self) -> MeshTopology:
        """Build mesh topology from registered agents."""
        nodes = list(self._agents.keys())
        edges = []

        # Create edges between agents that share capabilities
        for i, a1 in enumerate(nodes):
            for a2 in nodes[i+1:]:
                caps1 = set(self._agents[a1].capabilities)
                caps2 = set(self._agents[a2].capabilities)
                if caps1 & caps2:
                    edges.append((a1, a2))

        topology = MeshTopology(
            nodes=nodes,
            edges=edges,
            latency={n: self._agents[n].avg_response_time for n in nodes},
            bandwidth={n: 1.0 for n in nodes},
            health={n: self._agents[n].status for n in nodes},
        )

        self._topology = topology
        return topology


# Module-level singleton
mesh_coordinator = AgentMeshCoordinator()


# ── API Routes ──────────────────────────────────────────────────────────────


@router.post("/api/v1/mesh/agents/register")
async def register_agent(payload: dict):
    """Register an agent."""
    agent = mesh_coordinator.register_agent(
        agent_name=payload["agent_name"],
        capabilities=payload["capabilities"],
        max_load=payload.get("max_load", 1.0),
    )
    return agent.__dict__


@router.post("/api/v1/mesh/agents/{agent_name}/heartbeat")
async def heartbeat(agent_name: str, payload: dict):
    """Receive heartbeat from agent."""
    success = mesh_coordinator.heartbeat(
        agent_name,
        payload.get("load", 0.0),
    )
    return {"status": "ok" if success else "unregistered"}


@router.get("/api/v1/mesh/agents/{agent_name}/health")
async def check_health(agent_name: str):
    """Check agent health."""
    return mesh_coordinator.check_agent_health(agent_name)


@router.get("/api/v1/mesh/agents/{agent_name}/capabilities")
async def discover_capabilities(agent_name: str):
    """Discover agent capabilities."""
    caps = mesh_coordinator.discover_capabilities(agent_name)
    return {"agent": agent_name, "capabilities": caps}


@router.post("/api/v1/mesh/tasks/distribute")
async def distribute_task(payload: dict):
    """Distribute a task."""
    assignment = mesh_coordinator.distribute_task(
        task_type=payload["task_type"],
        task_data=payload,
        priority=payload.get("priority", 1),
    )
    if not assignment:
        raise HTTPException(400, "No available agent for this task type")
    return assignment.__dict__


@router.post("/api/v1/mesh/tasks/batch")
async def distribute_batch(payload: dict):
    """Distribute a batch of tasks."""
    assignments = mesh_coordinator.distribute_batch(payload["tasks"])
    return {"count": len(assignments), "assignments": [a.__dict__ for a in assignments]}


@router.post("/api/v1/mesh/tasks/{task_id}/complete")
async def complete_task(task_id: str, payload: dict):
    """Complete a task."""
    return mesh_coordinator.complete_task(
        task_id,
        payload.get("result"),
        payload.get("success", True),
    )


@router.post("/api/v1/mesh/balance")
async def balance_load(payload: dict):
    """Make load balancing decision."""
    decision = mesh_coordinator.balance_load(
        payload["task_id"],
        payload["task_type"],
    )
    if not decision:
        raise HTTPException(400, "No available candidates")
    return decision.__dict__


@router.get("/api/v1/mesh/rebalance")
async def rebalance_mesh():
    """Rebalance the mesh."""
    decisions = mesh_coordinator.rebalance_mesh()
    return {"count": len(decisions), "decisions": [d.__dict__ for d in decisions]}


@router.get("/api/v1/mesh/health")
async def mesh_health():
    """Get mesh health report."""
    return mesh_coordinator.get_mesh_health().__dict__


@router.post("/api/v1/mesh/recovery/{agent_name}/detect")
async def detect_failure(agent_name: str):
    """Detect agent failure and create recovery plan."""
    plan = mesh_coordinator.detect_failure(agent_name)
    if not plan:
        return {"status": "no_failure_detected"}
    return plan.__dict__


@router.post("/api/v1/mesh/recovery/{agent_name}/execute")
async def execute_recovery(agent_name: str):
    """Execute recovery plan."""
    return mesh_coordinator.execute_recovery(agent_name)


@router.post("/api/v1/mesh/messages")
async def send_message(payload: dict):
    """Send message between agents."""
    return mesh_coordinator.send_agent_message(
        payload["from_agent"],
        payload["to_agent"],
        payload["message_type"],
        payload.get("content", {}),
    )


@router.get("/api/v1/mesh/topology")
async def get_topology():
    """Get mesh topology."""
    topology = mesh_coordinator.build_topology()
    return {
        "nodes": topology.nodes,
        "edges": [list(e) for e in topology.edges],
        "health": topology.health,
    }
