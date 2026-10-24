"""
FRIDAY/apps/core/src/friday_core/autonomous_decision_making.py — FRIDAY Autonomous Decision Making Engine.

Extends FRIDAY's capabilities with:
1. Multi-Agent Decision Coordination: coordinate decisions across agents
2. Action Planning: plan complex multi-step actions
3. Decision Evaluation: evaluate decision outcomes
4. Adaptive Strategy Selection: learn which strategies work
5. Conflict Resolution: resolve conflicting agent decisions
6. Action Execution: execute decisions with proper sequencing
7. Learning from Outcomes: improve future decisions
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class AgentProposal:
    """A proposal from an agent."""
    agent: str
    proposal_id: str
    action: str
    rationale: str
    expected_value: float = 0.0
    confidence: float = 0.5
    risk: str = "low"  # low, medium, high
    required_resources: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    timestamp: float = 0.0


@dataclass
class Decision:
    """A final decision."""
    decision_id: str
    action: str
    selected_agents: list[str]
    rejected_proposals: list[str]
    rationale: str
    expected_value: float = 0.0
    confidence: float = 0.5
    risk: str = "low"
    status: str = "pending"  # pending, executing, completed, failed
    created_at: float = 0.0
    completed_at: float = 0.0
    outcome: dict = field(default_factory=dict)


@dataclass
class ActionPlan:
    """A multi-step action plan."""
    plan_id: str
    goal: str
    steps: list[str]
    agents: list[str]
    dependencies: dict[str, list[str]] = field(default_factory=dict)
    estimated_duration: float = 0.0
    risk_level: str = "low"


@dataclass
class StrategyResult:
    """Result of using a strategy."""
    strategy: str
    success_count: int = 0
    total_count: int = 0
    avg_value: float = 0.0
    last_used: float = 0.0


@dataclass
class LearningRecord:
    """Record of learning from outcomes."""
    decision_id: str
    action: str
    outcome: str
    value: float
    lessons: list[str]
    timestamp: float = 0.0


class AutonomousDecisionMaker:
    """Autonomous decision making engine."""

    def __init__(self):
        self._proposals: dict[str, list[AgentProposal]] = {}  # group_id -> proposals
        self._decisions: dict[str, Decision] = {}
        self._plans: dict[str, ActionPlan] = {}
        self._strategies: dict[str, StrategyResult] = {}
        self._learnings: list[LearningRecord] = []

    # ── Proposal Collection ─────────────────────────────────────────────────

    def collect_proposals(
        self,
        group_id: str,
        proposals: list[AgentProposal],
    ) -> list[AgentProposal]:
        """Collect proposals from agents for a decision group."""
        group = self._proposals.setdefault(group_id, [])
        group.extend(proposals)
        return list(group)

    def propose(
        self,
        agent: str,
        action: str,
        rationale: str,
        expected_value: float = 0.0,
        confidence: float = 0.5,
        risk: str = "low",
        required_resources: list[str] | None = None,
        dependencies: list[str] | None = None,
    ) -> AgentProposal:
        """Create a proposal from an agent."""
        proposal = AgentProposal(
            agent=agent,
            proposal_id=hashlib.md5(
                f"proposal:{agent}:{action}:{time.time()}".encode()
            ).hexdigest()[:12],
            action=action,
            rationale=rationale,
            expected_value=expected_value,
            confidence=confidence,
            risk=risk,
            required_resources=required_resources or [],
            dependencies=dependencies or [],
            timestamp=time.time(),
        )
        return proposal

    # ── Decision Making ────────────────────────────────────────────────────

    def decide(
        self,
        group_id: str,
        goal: str,
        criteria: list[str] | None = None,
    ) -> Decision:
        """Make a decision from collected proposals."""
        proposals = self._proposals.get(group_id, [])
        if not proposals:
            raise HTTPException(400, f"No proposals found for group {group_id}")

        # Score each proposal
        scored = []
        for p in proposals:
            score = self._score_proposal(p, goal, criteria or [])
            scored.append((score, p))

        # Sort by score
        scored.sort(key=lambda x: -x[0])

        # Select best proposal
        best_score, best_proposal = scored[0]

        # Check for conflicting proposals
        rejected = []
        for score, p in scored[1:]:
            if self._is_conflicting(best_proposal, p):
                rejected.append(p.proposal_id)
            else:
                # Check if this proposal complements the best
                if self._complements(best_proposal, p):
                    rejected.append(p.proposal_id)
                else:
                    rejected.append(p.proposal_id)

        # Create decision
        decision = Decision(
            decision_id=hashlib.md5(
                f"decision:{group_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            action=best_proposal.action,
            selected_agents=[best_proposal.agent],
            rejected_proposals=rejected,
            rationale=best_proposal.rationale,
            expected_value=best_proposal.expected_value,
            confidence=best_proposal.confidence,
            risk=best_proposal.risk,
            status="pending",
            created_at=time.time(),
        )

        self._decisions[decision.decision_id] = decision

        # Learn from strategy
        self._learn_strategy(best_proposal.agent, best_proposal.action, best_score)

        return decision

    def _score_proposal(
        self,
        proposal: AgentProposal,
        goal: str,
        criteria: list[str],
    ) -> float:
        """Score a proposal against goal and criteria."""
        # Base score from expected value
        score = proposal.expected_value * 0.5

        # Confidence weight
        score += proposal.confidence * 0.3

        # Risk penalty
        risk_penalty = {"low": 0.0, "medium": -0.1, "high": -0.2}
        score += risk_penalty.get(proposal.risk, 0.0)

        # Criteria matching
        goal_words = set(goal.lower().split())
        rationale_words = set(proposal.rationale.lower().split())
        overlap = len(goal_words & rationale_words)
        score += overlap * 0.1

        # Strategy history bonus
        strategy = self._strategies.get(proposal.agent)
        if strategy and strategy.total_count > 5:
            success_rate = strategy.success_count / max(1, strategy.total_count)
            score += success_rate * 0.1

        return score

    def _is_conflicting(self, a: AgentProposal, b: AgentProposal) -> bool:
        """Check if two proposals conflict."""
        a_action = a.action.lower()
        b_action = b.action.lower()

        # Check for opposing actions
        conflicts = [
            ("expand", "shrink"),
            ("buy", "sell"),
            ("create", "delete"),
            ("start", "stop"),
            ("increase", "decrease"),
        ]

        for action, opposite in conflicts:
            if action in a_action and opposite in b_action:
                return True
            if opposite in a_action and action in b_action:
                return True

        return False

    def _complements(self, a: AgentProposal, b: AgentProposal) -> bool:
        """Check if two proposals complement each other."""
        a_resources = set(a.required_resources)
        b_resources = set(b.required_resources)

        # If they need different resources, they may complement
        if not a_resources & b_resources:
            return True

        return False

    # ── Action Planning ────────────────────────────────────────────────────

    def plan_action(
        self,
        goal: str,
        steps: list[dict],
        agents: list[str],
    ) -> ActionPlan:
        """Plan a multi-step action."""
        step_ids = []
        dependencies = {}

        for i, step in enumerate(steps):
            step_id = hashlib.md5(
                f"step:{goal}:{i}:{time.time()}".encode()
            ).hexdigest()[:8]
            step_ids.append(step_id)

            # Determine dependencies
            deps = []
            for j in range(i):
                # Check if previous steps produce resources needed by this step
                prev_resources = steps[j].get("resources_produced", [])
                needed = step.get("resources_required", [])
                overlap = set(prev_resources) & set(needed)
                if overlap:
                    deps.append(step_ids[j])

            dependencies[step_id] = deps

        # Estimate duration
        total_duration = sum(step.get("estimated_time", 60) for step in steps)

        # Risk level
        risk_levels = [step.get("risk", "low") for step in steps]
        if "high" in risk_levels:
            risk_level = "high"
        elif "medium" in risk_levels:
            risk_level = "medium"
        else:
            risk_level = "low"

        plan = ActionPlan(
            plan_id=hashlib.md5(
                f"plan:{goal}:{time.time()}".encode()
            ).hexdigest()[:12],
            goal=goal,
            steps=[s.get("description", str(s)) for s in steps],
            agents=agents,
            dependencies=dependencies,
            estimated_duration=total_duration,
            risk_level=risk_level,
        )

        self._plans[plan.plan_id] = plan
        return plan

    def execute_plan(self, plan_id: str) -> dict:
        """Execute a plan step by step."""
        plan = self._plans.get(plan_id)
        if not plan:
            raise HTTPException(404, f"Plan {plan_id} not found")

        executed = []
        failed = []

        # Simple execution order: respect dependencies
        remaining = list(plan.dependencies.keys())
        completed = set()

        while remaining:
            # Find steps that have all dependencies met
            ready = [
                sid for sid in remaining
                if not plan.dependencies.get(sid) or
                all(dep in completed for dep in plan.dependencies[sid])
            ]

            if not ready:
                # Circular dependency or missing prerequisites
                failed.extend(remaining)
                break

            for sid in ready:
                # Simulate execution
                step_success = self._execute_step(sid, plan)
                if step_success:
                    executed.append(sid)
                    completed.add(sid)
                else:
                    failed.append(sid)

            remaining = [s for s in remaining if s not in completed and s not in failed]

        return {
            "plan_id": plan_id,
            "status": "completed" if not failed else "partial",
            "executed": executed,
            "failed": failed,
            "total_steps": len(plan.steps),
        }

    def _execute_step(self, step_id: str, plan: ActionPlan) -> bool:
        """Execute a single step (simulated)."""
        # 90% success rate for simplicity
        return hash(step_id) % 10 != 0

    # ── Decision Evaluation ──────────────────────────────────────────────────

    def evaluate_decision(
        self,
        decision_id: str,
        actual_value: float,
        notes: str = "",
    ) -> dict:
        """Evaluate a decision's outcome."""
        decision = self._decisions.get(decision_id)
        if not decision:
            raise HTTPException(404, f"Decision {decision_id} not found")

        # Calculate outcome
        predicted = decision.expected_value
        error = abs(predicted - actual_value)
        accuracy = 1.0 - (error / max(1.0, abs(predicted)))

        # Determine success
        success = actual_value > 0 and accuracy > 0.5

        # Update decision
        decision.status = "completed"
        decision.completed_at = time.time()
        decision.outcome = {
            "actual_value": actual_value,
            "predicted_value": predicted,
            "accuracy": accuracy,
            "success": success,
            "notes": notes,
        }

        # Learn from outcome
        self._learn_from_outcome(decision, actual_value, success)

        return decision.__dict__

    def _learn_strategy(self, agent: str, action: str, score: float):
        """Update strategy tracking."""
        if agent not in self._strategies:
            self._strategies[agent] = StrategyResult(
                strategy=f"{agent}:{action}",
            )

        strategy = self._strategies[agent]
        strategy.total_count += 1
        strategy.avg_value = (
            (strategy.avg_value * (strategy.total_count - 1) + score)
            / strategy.total_count
        )
        strategy.last_used = time.time()

    def _learn_from_outcome(
        self,
        decision: Decision,
        actual_value: float,
        success: bool,
    ):
        """Learn from decision outcome."""
        lessons = []

        if success:
            lessons.append(f"Decision '{decision.action}' was successful")
            lessons.append(f"Agent {decision.selected_agents} provided good recommendations")
        else:
            lessons.append(f"Decision '{decision.action}' did not meet expectations")
            lessons.append("Consider reviewing the decision criteria")

        # Update strategy success rate
        for agent in decision.selected_agents:
            if agent in self._strategies:
                if success:
                    self._strategies[agent].success_count += 1

        learning = LearningRecord(
            decision_id=decision.decision_id,
            action=decision.action,
            outcome="success" if success else "failure",
            value=actual_value,
            lessons=lessons,
            timestamp=time.time(),
        )

        self._learnings.append(learning)

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_decision_history(self) -> dict[str, Any]:
        """Get decision history."""
        return {
            "total_decisions": len(self._decisions),
            "completed": sum(1 for d in self._decisions.values() if d.status == "completed"),
            "pending": sum(1 for d in self._decisions.values() if d.status == "pending"),
            "failed": sum(1 for d in self._decisions.values() if d.status == "failed"),
            "avg_confidence": sum(d.confidence for d in self._decisions.values()) / max(1, len(self._decisions)),
            "total_learnings": len(self._learnings),
        }


# Module-level singleton
autonomous_decision_maker = AutonomousDecisionMaker()


# ── API Routes ──────────────────────────────────────────────────────────────


@router.post("/api/v1/decisions/propose")
async def propose_action(payload: dict):
    """Propose an action."""
    proposal = autonomous_decision_maker.propose(
        agent=payload["agent"],
        action=payload["action"],
        rationale=payload["rationale"],
        expected_value=payload.get("expected_value", 0.0),
        confidence=payload.get("confidence", 0.5),
        risk=payload.get("risk", "low"),
        required_resources=payload.get("required_resources", []),
        dependencies=payload.get("dependencies", []),
    )
    return proposal.__dict__


@router.post("/api/v1/decisions/collect")
async def collect_proposals(payload: dict):
    """Collect proposals for a group."""
    proposals = autonomous_decision_maker.collect_proposals(
        payload["group_id"],
        [autonomous_decision_maker.propose(
            agent=p["agent"], action=p["action"], rationale=p["rationale"],
            expected_value=p.get("expected_value", 0.0),
            confidence=p.get("confidence", 0.5),
            risk=p.get("risk", "low"),
        ) for p in payload["proposals"]]
    )
    return {"group_id": payload["group_id"], "total": len(proposals)}


@router.post("/api/v1/decisions/make")
async def make_decision(payload: dict):
    """Make a decision."""
    decision = autonomous_decision_maker.decide(
        payload["group_id"],
        payload["goal"],
        payload.get("criteria", []),
    )
    return decision.__dict__


@router.post("/api/v1/decisions/plan")
async def plan_action(payload: dict):
    """Plan a multi-step action."""
    plan = autonomous_decision_maker.plan_action(
        payload["goal"],
        payload["steps"],
        payload.get("agents", []),
    )
    return plan.__dict__


@router.post("/api/v1/decisions/plan/{plan_id}/execute")
async def execute_plan(plan_id: str):
    """Execute a plan."""
    result = autonomous_decision_maker.execute_plan(plan_id)
    return result


@router.post("/api/v1/decisions/{decision_id}/evaluate")
async def evaluate_decision(decision_id: str, payload: dict):
    """Evaluate a decision."""
    result = autonomous_decision_maker.evaluate_decision(
        decision_id,
        payload["actual_value"],
        payload.get("notes", ""),
    )
    return result


@router.get("/api/v1/decisions/history")
async def decision_history():
    """Get decision history."""
    return autonomous_decision_maker.get_decision_history()
