"""
FRIDAY/apps/core/src/friday_core/goal_planning_engine.py — FRIDAY Goal Planning Engine.

Long-term goal planning with milestone tracking, adaptive planning based on
progress, obstacle handling, and strategic refinement.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class Milestone:
    """A milestone in a goal plan."""
    milestone_id: str
    name: str
    description: str
    target_date: float = 0.0
    status: str = "pending"
    progress_pct: float = 0.0
    obstacles: list[str] = field(default_factory=list)
    strategies: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)


@dataclass
class GoalPlan:
    """A comprehensive goal plan."""
    plan_id: str
    goal: str
    milestones: list[Milestone] = field(default_factory=list)
    status: str = "active"
    created_at: float = field(default_factory=time.time)
    updated_at: float = 0.0
    strategy: str = ""
    obstacles: list[str] = field(default_factory=list)


class GoalPlanningEngine:
    """Engine for long-term goal planning and adaptation."""

    def __init__(self) -> None:
        self._plans: dict[str, GoalPlan] = {}

    def create_plan(self, goal: str, strategy: str = "") -> GoalPlan:
        """Create a goal plan with milestones."""
        plan_id = f"plan_{uuid.uuid4().hex[:12]}"
        plan = GoalPlan(plan_id=plan_id, goal=goal, strategy=strategy)
        plan.milestones = self._generate_milestones(goal)
        plan.updated_at = time.time()
        self._plans[plan_id] = plan
        return plan

    def _generate_milestones(self, goal: str) -> list[Milestone]:
        """Generate milestones for a goal."""
        base_milestones = [
            ("Define Objectives", "Establish clear, measurable objectives aligned with the goal"),
            ("Research & Analysis", "Gather relevant information and analyze the landscape"),
            ("Strategy Development", "Develop detailed strategy with resource allocation"),
            ("Implementation", "Execute the plan with monitoring and adaptation"),
            ("Evaluation", "Measure outcomes and refine approach"),
        ]
        milestones = []
        for i, (name, desc) in enumerate(base_milestones):
            milestones.append(Milestone(
                milestone_id=f"ms_{uuid.uuid4().hex[:8]}",
                name=name,
                description=desc,
                strategies=[f"Standard approach for {name}"],
            ))
        return milestones

    def update_milestone(self, plan_id: str, milestone_id: str, status: str,
                         progress: float = 0.0, obstacles: list[str] | None = None,
                         strategies: list[str] | None = None) -> bool:
        """Update a milestone's status and progress."""
        plan = self._plans.get(plan_id)
        if not plan:
            return False
        for ms in plan.milestones:
            if ms.milestone_id == milestone_id:
                ms.status = status
                ms.progress_pct = progress
                if obstacles is not None:
                    ms.obstacles = obstacles
                if strategies is not None:
                    ms.strategies = strategies
                plan.updated_at = time.time()
                return True
        return False

    def adapt_plan(self, plan_id: str, adaptation: str) -> GoalPlan:
        """Adapt a plan based on new information or obstacles."""
        plan = self._plans.get(plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        plan.strategy = adaptation
        plan.updated_at = time.time()
        return plan

    def get_plan(self, plan_id: str) -> dict[str, Any]:
        """Get a plan by ID."""
        plan = self._plans.get(plan_id)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        overall_progress = sum(ms.progress_pct for ms in plan.milestones) / len(plan.milestones) if plan.milestones else 0
        return {
            "plan_id": plan.plan_id,
            "goal": plan.goal,
            "status": plan.status,
            "strategy": plan.strategy,
            "overall_progress_pct": overall_progress,
            "milestones": [
                {
                    "milestone_id": ms.milestone_id,
                    "name": ms.name,
                    "status": ms.status,
                    "progress_pct": ms.progress_pct,
                    "obstacles": ms.obstacles,
                    "strategies": ms.strategies,
                }
                for ms in plan.milestones
            ],
        }

    def get_all_plans(self) -> list[dict[str, Any]]:
        """Get all plans."""
        return [
            {
                "plan_id": p.plan_id,
                "goal": p.goal,
                "status": p.status,
                "milestone_count": len(p.milestones),
                "overall_progress_pct": sum(ms.progress_pct for ms in p.milestones) / len(p.milestones) if p.milestones else 0,
            }
            for p in self._plans.values()
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        active = sum(1 for p in self._plans.values() if p.status == "active")
        return {
            "total_plans": len(self._plans),
            "active_plans": active,
            "total_milestones": sum(len(p.milestones) for p in self._plans.values()),
            "engine_status": "operational",
        }


engine = GoalPlanningEngine()


@router.post("/goals/plans")
async def create_plan(goal: str, strategy: str = ""):
    """Create a goal plan."""
    plan = engine.create_plan(goal, strategy)
    return {
        "plan_id": plan.plan_id,
        "goal": plan.goal,
        "milestones": [ms.name for ms in plan.milestones],
    }


@router.get("/goals/plans/{plan_id}")
async def get_plan(plan_id: str):
    """Get a plan by ID."""
    return engine.get_plan(plan_id)


@router.get("/goals/plans")
async def list_plans():
    """List all plans."""
    return {"plans": engine.get_all_plans()}


@router.post("/goals/plans/{plan_id}/milestones/{milestone_id}")
async def update_milestone(plan_id: str, milestone_id: str, status: str,
                           progress: float = 0.0, obstacles: list[str] | None = None,
                           strategies: list[str] | None = None):
    """Update a milestone."""
    if not engine.update_milestone(plan_id, milestone_id, status, progress, obstacles, strategies):
        raise HTTPException(status_code=404, detail="Milestone not found")
    return {"milestone_id": milestone_id, "status": status, "progress_pct": progress}


@router.post("/goals/plans/{plan_id}/adapt")
async def adapt_plan(plan_id: str, adaptation: str):
    """Adapt a plan with new strategy."""
    plan = engine.adapt_plan(plan_id, adaptation)
    return {"plan_id": plan.plan_id, "strategy": plan.strategy, "status": "updated"}


@router.get("/goals/report")
async def goal_report():
    """Get goal planning report."""
    return engine.get_report()
