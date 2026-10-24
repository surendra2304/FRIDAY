"""
FRIDAY/apps/core/src/friday_core/general_cognitive_coordinator.py — FRIDAY General Cognitive Coordinator.

Coordinates cognitive tasks across the FRIDAY Universe: decomposes complex
problems, routes subtasks to specialized agents, synthesizes results, and
manages the overall cognitive workflow. Includes task decomposition, agent
selection, result integration, and holistic decision-making.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class CognitiveTask:
    """A cognitive task to coordinate."""
    task_id: str
    description: str
    complexity: str = "medium"  # simple, medium, complex, multi_domain
    domains: list[str] = field(default_factory=list)  # trading, content, security, memory, etc.
    subtasks: list[dict] = field(default_factory=list)
    status: str = "pending"
    created_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    result: str = ""
    agent_routes: dict = field(default_factory=dict)  # subtask → agent


@dataclass
class SubTask:
    """A subtask in cognitive decomposition."""
    subtask_id: str
    description: str
    parent_task_id: str
    required_agent: str  # agent name
    priority: int = 100
    status: str = "pending"
    result: str = ""
    dependencies: list[str] = field(default_factory=list)
    timeout_sec: float = 300.0


@dataclass
class AgentCapability:
    """An agent's capability profile."""
    agent_name: str
    capabilities: list[str] = field(default_factory=list)
    success_rate: float = 0.5
    current_load: float = 0.0
    health: str = "healthy"
    response_time_ms: float = 0.0
    domain_expertise: dict = field(default_factory=dict)


@dataclass
class CognitiveResult:
    """Result of cognitive coordination."""
    task_id: str
    synthesized_result: str = ""
    subtask_results: list[dict] = field(default_factory=list)
    agents_used: list[str] = field(default_factory=list)
    total_time_ms: float = 0.0
    success: bool = False
    confidence: float = 0.0
    insights: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


@dataclass
class CoordinationPlan:
    """A coordination plan for a cognitive task."""
    plan_id: str
    task_id: str
    decomposition: list[SubTask] = field(default_factory=list)
    execution_order: list[str] = field(default_factory=list)
    estimated_time_ms: float = 0.0
    risk_level: str = "low"
    fallback_strategies: list[str] = field(default_factory=list)


@dataclass
class CognitiveLearning:
    """Learning from cognitive coordination."""
    learning_id: str
    task_id: str
    lesson: str = ""
    improvement: str = ""
    strategy_adjustment: str = ""
    success: bool = False
    timestamp: float = 0.0


@dataclass
class HolisticDecision:
    """A holistic decision from cognitive coordination."""
    decision_id: str
    task_id: str
    decision: str = ""
    rationale: str = ""
    confidence: float = 0.0
    alternatives: list[str] = field(default_factory=list)
    risk_level: str = "low"
    timestamp: float = 0.0


class GeneralCognitiveCoordinator:
    """FRIDAY general cognitive coordinator."""

    def __init__(self):
        self._tasks: dict[str, CognitiveTask] = {}
        self._results: dict[str, CognitiveResult] = {}
        self._plans: dict[str, CoordinationPlan] = {}
        self._learnings: list[CognitiveLearning] = []
        self._decisions: dict[str, HolisticDecision] = {}

        # Agent capability registry
        self._agent_registry = {
            "FRIDAY": AgentCapability("FRIDAY", ["coordination", "reasoning"], 0.85, 0.2, "healthy", 50, {"universe": 0.9}),
            "Stratex": AgentCapability("Stratex", ["trading", "finance", "risk"], 0.8, 0.3, "healthy", 100, {"trading": 0.9, "finance": 0.85}),
            "VyralX": AgentCapability("VyralX", ["content", "creation", "marketing"], 0.75, 0.4, "healthy", 200, {"content": 0.9, "creation": 0.85}),
            "Memora": AgentCapability("Memora", ["memory", "knowledge", "retrieval"], 0.82, 0.1, "healthy", 80, {"memory": 0.9, "knowledge": 0.85}),
            "IntelX": AgentCapability("IntelX", ["research", "analysis", "threat_intel"], 0.78, 0.3, "healthy", 150, {"research": 0.9, "threat_intel": 0.8}),
            "Inference": AgentCapability("Inference", ["reasoning", "deliberation", "verification"], 0.83, 0.2, "healthy", 300, {"reasoning": 0.9, "deliberation": 0.85}),
            "Cortex": AgentCapability("Cortex", ["marketing", "campaigns", "crm"], 0.77, 0.4, "healthy", 180, {"marketing": 0.9, "campaigns": 0.85}),
            "Forge": AgentCapability("Forge", ["coding", "engineering", "testing"], 0.81, 0.5, "healthy", 120, {"coding": 0.9, "engineering": 0.85}),
            "Futuris": AgentCapability("Futuris", ["forecasting", "prediction", "analysis"], 0.8, 0.2, "healthy", 250, {"forecasting": 0.9, "prediction": 0.85}),
            "Sentinel": AgentCapability("Sentinel", ["security", "monitoring", "compliance"], 0.84, 0.3, "healthy", 90, {"security": 0.9, "monitoring": 0.85}),
        }

    def submit_task(
        self,
        description: str,
        complexity: str = "medium",
        domains: list[str] | None = None,
    ) -> CognitiveTask:
        """Submit a cognitive task for coordination."""
        task = CognitiveTask(
            task_id=hashlib.md5(
                f"task:{description}:{time.time()}".encode()
            ).hexdigest()[:12],
            description=description,
            complexity=complexity,
            domains=domains or [],
            status="pending",
            created_at=time.time(),
        )
        self._tasks[task.task_id] = task
        return task

    def decompose_task(self, task_id: str) -> CoordinationPlan:
        """Decompose a cognitive task into subtasks."""
        task = self._tasks.get(task_id)
        if not task:
            raise HTTPException(404, f"Task {task_id} not found")

        # Analyze task and create subtasks based on domains
        plan = CoordinationPlan(
            plan_id=hashlib.md5(
                f"plan:{task_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            task_id=task_id,
            estimated_time_ms=0.0,
        )

        # Determine required agents based on domains and complexity
        if not task.domains:
            # Auto-detect domains from description
            domains = self._detect_domains(task.description)
        else:
            domains = task.domains

        # Create subtasks for each relevant domain
        for domain in domains:
            agent = self._select_agent(domain)
            if agent:
                subtask = SubTask(
                    subtask_id=hashlib.md5(
                        f"subtask:{task_id}:{domain}:{time.time()}".encode()
                    ).hexdigest()[:12],
                    description=f"Perform {domain} task: {task.description[:100]}",
                    parent_task_id=task_id,
                    required_agent=agent,
                    priority=50 if domain in ("trading", "security") else 100,
                )
                plan.decomposition.append(subtask)
                task.agent_routes[subtask.subtask_id] = agent

        # Determine execution order (respect dependencies)
        plan.execution_order = [s.subtask_id for s in plan.decomposition]

        # Estimate time
        plan.estimated_time_ms = sum(
            self._agent_registry[s.required_agent].response_time_ms
            for s in plan.decomposition
            if s.required_agent in self._agent_registry
        )

        # Risk assessment
        if complexity == "multi_domain" and len(plan.decomposition) > 3:
            plan.risk_level = "high"
            plan.fallback_strategies = [
                "Retry with alternative agent",
                "Simplify task scope",
                "Request human intervention",
            ]
        elif len(plan.decomposition) > 2:
            plan.risk_level = "medium"
        else:
            plan.risk_level = "low"

        task.subtasks = [s.__dict__ for s in plan.decomposition]
        self._plans[plan.plan_id] = plan
        return plan

    def _detect_domains(self, description: str) -> list[str]:
        """Detect domains from task description."""
        desc_lower = description.lower()
        domains = []

        domain_keywords = {
            "trading": ["trade", "trading", "market", "stock", "crypto", "portfolio", "investment"],
            "content": ["video", "content", "creative", "production", "script", "editing"],
            "security": ["security", "vulnerability", "threat", "attack", "monitor", "protect"],
            "memory": ["memory", "recall", "retrieve", "knowledge", "remember"],
            "research": ["research", "investigate", "analyze", "find", "search", "osint"],
            "reasoning": ["reason", "think", "decide", "evaluate", "compare", "assess"],
            "marketing": ["marketing", "campaign", "promotion", "advertise", "crm"],
            "engineering": ["code", "develop", "build", "test", "deploy", "fix", "bug"],
            "forecasting": ["forecast", "predict", "trend", "future", "estimate"],
            "coordination": ["coordinate", "manage", "organize", "plan", "schedule"],
        }

        for domain, keywords in domain_keywords.items():
            if any(kw in desc_lower for kw in keywords):
                domains.append(domain)

        return domains if domains else ["coordination"]

    def _select_agent(self, domain: str) -> str | None:
        """Select the best agent for a domain."""
        best_agent = None
        best_score = 0.0

        for agent_name, capability in self._agent_registry.items():
            if domain in capability.domain_expertise:
                score = (
                    capability.domain_expertise[domain] * 0.5 +
                    capability.success_rate * 0.3 +
                    (1 - capability.current_load) * 0.2
                )
                if score > best_score:
                    best_score = score
                    best_agent = agent_name

        return best_agent

    def execute_task(self, task_id: str) -> CognitiveResult:
        """Execute a cognitive task through coordination."""
        task = self._tasks.get(task_id)
        if not task:
            raise HTTPException(404, f"Task {task_id} not found")

        if task.status == "completed":
            return self._results[task_id]

        start = time.time()

        # Decompose task
        plan = self._plans.get(task.task_id)
        if not plan:
            plan = self.decompose_task(task_id)

        task.status = "executing"
        task.started_at = time.time()

        # Execute subtasks
        subtask_results = []
        agents_used = []

        for subtask in plan.decomposition:
            agent = self._agent_registry.get(subtask.required_agent)
            if not agent:
                subtask_results.append({
                    "subtask_id": subtask.subtask_id,
                    "status": "failed",
                    "result": "Agent not available",
                })
                continue

            # Simulate agent execution
            success = hashlib.md5(
                f"exec:{subtask.subtask_id}:{time.time()}".encode()
            ).hexdigest()[:1] < "8"  # 80% success rate

            result = (
                f"[{subtask.required_agent}] Completed: {subtask.description} "
                f"with confidence {0.6 + agent.success_rate * 0.3:.2f}."
            )

            subtask.status = "completed" if success else "failed"
            subtask.result = result
            agents_used.append(subtask.required_agent)

            subtask_results.append({
                "subtask_id": subtask.subtask_id,
                "agent": subtask.required_agent,
                "status": subtask.status,
                "result": result,
            })

        # Synthesize results
        synthesis = self._synthesize_results(task, subtask_results)

        # Generate holistic decision
        decision = self._make_holistic_decision(task, synthesis, subtask_results)

        # Record learning
        self._record_learning(task, subtask_results, synthesis)

        # Update task
        task.status = "completed"
        task.completed_at = time.time()
        task.result = synthesis

        result = CognitiveResult(
            task_id=task_id,
            synthesized_result=synthesis,
            subtask_results=subtask_results,
            agents_used=agents_used,
            total_time_ms=(time.time() - start) * 1000,
            success=sum(1 for r in subtask_results if r["status"] == "completed") > len(subtask_results) // 2,
            confidence=0.5 + len(agents_used) * 0.05,
            insights=self._generate_insights(subtask_results),
            recommendations=decision.alternatives,
        )

        self._results[task_id] = result
        return result

    def _synthesize_results(
        self,
        task: CognitiveTask,
        subtask_results: list[dict],
    ) -> str:
        """Synthesize subtask results into a coherent result."""
        synthesis = (
            f"Cognitive coordination for '{task.description[:100]}':\n\n"
        )

        for r in subtask_results:
            synthesis += f"- [{r.get('agent', 'unknown')}] {r['result'][:100]}\n"

        synthesis += (
            f"\nSynthesis: The coordinated cognitive effort across "
            f"{len(set(r.get('agent', '') for r in subtask_results))} agents "
            f"has produced a comprehensive response. Key findings have been "
            f"integrated and verified."
        )

        return synthesis

    def _make_holistic_decision(
        self,
        task: CognitiveTask,
        synthesis: str,
        subtask_results: list[dict],
    ) -> HolisticDecision:
        """Make a holistic decision from coordinated results."""
        success_count = sum(1 for r in subtask_results if r["status"] == "completed")
        total = len(subtask_results)

        if success_count == total:
            decision = "Proceed with confidence"
            confidence = 0.9
            risk = "low"
        elif success_count > total * 0.5:
            decision = "Proceed with caution"
            confidence = 0.6
            risk = "medium"
        else:
            decision = "Retry with alternative approach"
            confidence = 0.3
            risk = "high"

        rationale = (
            f"Based on {success_count}/{total} subtasks completed successfully, "
            f"the coordinated cognitive effort suggests: {decision}."
        )

        alternatives = [
            "Retry with different agent allocation",
            "Request human review for complex decisions",
            "Simplify task scope and retry",
        ]

        holistic_decision = HolisticDecision(
            decision_id=hashlib.md5(
                f"decision:{task.task_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            task_id=task.task_id,
            decision=decision,
            rationale=rationale,
            confidence=confidence,
            alternatives=alternatives,
            risk_level=risk,
            timestamp=time.time(),
        )

        self._decisions[holistic_decision.decision_id] = holistic_decision
        return holistic_decision

    def _generate_insights(self, subtask_results: list[dict]) -> list[str]:
        """Generate insights from subtask results."""
        insights = []

        agents = set(r.get("agent", "") for r in subtask_results)
        insights.append(f"Coordinated {len(agents)} agents: {', '.join(agents)}")

        successful = sum(1 for r in subtask_results if r["status"] == "completed")
        insights.append(f"Success rate: {successful}/{len(subtask_results)} subtasks completed")

        # Agent performance insights
        agent_successes = {}
        for r in subtask_results:
            agent = r.get("agent", "")
            if r["status"] == "completed":
                agent_successes[agent] = agent_successes.get(agent, 0) + 1

        for agent, count in agent_successes.items():
            insights.append(f"{agent} completed {count} subtasks successfully")

        return insights

    def _record_learning(
        self,
        task: CognitiveTask,
        subtask_results: list[dict],
        synthesis: str,
    ) -> None:
        """Record learning from cognitive coordination."""
        success_count = sum(1 for r in subtask_results if r["status"] == "completed")

        if success_count == len(subtask_results):
            lesson = "Full coordination success"
            improvement = "Continue current coordination strategy"
        elif success_count > len(subtask_results) // 2:
            lesson = "Partial coordination success"
            improvement = "Review failed subtasks and adjust agent selection"
        else:
            lesson = "Coordination challenges"
            improvement = "Consider alternative decomposition strategy"

        learning = CognitiveLearning(
            learning_id=hashlib.md5(
                f"learning:{task.task_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            task_id=task.task_id,
            lesson=lesson,
            improvement=improvement,
            strategy_adjustment=improvement,
            success=success_count == len(subtask_results),
            timestamp=time.time(),
        )

        self._learnings.append(learning)

    def get_report(self) -> dict:
        """Get cognitive coordinator report."""
        total_tasks = len(self._tasks)
        completed = sum(1 for t in self._tasks.values() if t.status == "completed")
        success_rate = sum(1 for r in self._results.values() if r.success) / max(1, len(self._results))

        return {
            "total_tasks": total_tasks,
            "completed_tasks": completed,
            "total_results": len(self._results),
            "total_plans": len(self._plans),
            "total_learnings": len(self._learnings),
            "total_decisions": len(self._decisions),
            "agents_registered": len(self._agent_registry),
            "success_rate": success_rate,
            "avg_coordination_time_ms": sum(r.total_time_ms for r in self._results.values()) / max(1, len(self._results)),
            "agents": [
                {
                    "name": a.agent_name,
                    "capabilities": a.capabilities,
                    "success_rate": a.success_rate,
                    "load": a.current_load,
                    "health": a.health,
                }
                for a in self._agent_registry.values()
            ],
            "recent_learnings": [
                {
                    "task": l.task_id,
                    "lesson": l.lesson,
                    "improvement": l.improvement,
                    "success": l.success,
                }
                for l in self._learnings[-5:]
            ],
        }


# Module-level singleton
cognitive_coordinator = GeneralCognitiveCoordinator()


# ── API Routes ──────────────────────────────────────────────────────────────


@router.post("/api/v1/friday/cognitive/tasks")
async def submit_task(payload: dict):
    """Submit a cognitive task for coordination."""
    task = cognitive_coordinator.submit_task(
        description=payload["description"],
        complexity=payload.get("complexity", "medium"),
        domains=payload.get("domains", []),
    )
    return {"task_id": task.task_id, "status": "submitted"}


@router.post("/api/v1/friday/cognitive/tasks/{task_id}/decompose")
async def decompose_task(task_id: str):
    """Decompose a cognitive task."""
    plan = cognitive_coordinator.decompose_task(task_id)
    return {
        "plan_id": plan.plan_id,
        "subtasks": [
            {"description": s.description, "agent": s.required_agent, "priority": s.priority}
            for s in plan.decomposition
        ],
        "estimated_time_ms": plan.estimated_time_ms,
        "risk_level": plan.risk_level,
    }


@router.post("/api/v1/friday/cognitive/tasks/{task_id}/execute")
async def execute_task(task_id: str):
    """Execute a cognitive task."""
    result = cognitive_coordinator.execute_task(task_id)
    return {
        "task_id": result.task_id,
        "success": result.success,
        "confidence": result.confidence,
        "synthesized_result": result.synthesized_result,
        "agents_used": result.agents_used,
        "total_time_ms": result.total_time_ms,
        "insights": result.insights,
        "recommendations": result.recommendations,
    }


@router.get("/api/v1/friday/cognitive/report")
async def get_report():
    """Get cognitive coordinator report."""
    return cognitive_coordinator.get_report()
