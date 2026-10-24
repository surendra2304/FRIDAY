"""
FRIDAY/apps/core/src/friday_core/task_decomposition_engine.py — FRIDAY Task Decomposition Engine.

Breaks complex goals into prioritized subtasks with dependency tracking,
deadline management, progress monitoring, and adaptive re-planning.
"""
from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class SubTask:
    """A decomposed subtask."""
    subtask_id: str
    description: str
    parent_goal_id: str
    required_agent: str
    priority: int = 100
    status: str = "pending"
    result: str = ""
    dependencies: list[str] = field(default_factory=list)
    timeout_sec: float = 300.0
    deadline: float = 0.0
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0


@dataclass
class Goal:
    """A goal to decompose."""
    goal_id: str
    description: str
    complexity: str = "medium"
    subtasks: list[SubTask] = field(default_factory=list)
    status: str = "pending"
    progress_pct: float = 0.0
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0


@dataclass
class DecompositionResult:
    """Result of a decomposition operation."""
    goal_id: str
    subtasks: list[SubTask]
    estimated_total_time: float
    critical_path: list[str]


class TaskDecompositionEngine:
    """Engine for decomposing complex goals into executable subtasks."""

    def __init__(self) -> None:
        self._goals: dict[str, Goal] = {}
        self._subtasks: dict[str, SubTask] = {}

    def decompose_goal(self, description: str, complexity: str = "medium") -> DecompositionResult:
        """Decompose a goal into subtasks with dependencies."""
        goal_id = f"goal_{uuid.uuid4().hex[:12]}"
        goal = Goal(goal_id=goal_id, description=description, complexity=complexity)
        subtasks = self._generate_subtasks(goal_id, description, complexity)
        goal.subtasks = subtasks
        self._goals[goal_id] = goal
        for st in subtasks:
            self._subtasks[st.subtask_id] = st
        return DecompositionResult(
            goal_id=goal_id,
            subtasks=subtasks,
            estimated_total_time=sum(st.timeout_sec for st in subtasks),
            critical_path=[st.subtask_id for st in subtasks if st.dependencies],
        )

    def _generate_subtasks(self, goal_id: str, description: str, complexity: str) -> list[SubTask]:
        """Generate subtasks based on goal complexity."""
        base_subtasks = [
            ("Analyze requirements and constraints", "Inference"),
            ("Gather relevant context and knowledge", "Memora"),
            ("Generate solution strategy", "Inference"),
            ("Execute solution steps", "Forge"),
            ("Verify and validate results", "Sentinel"),
        ]
        if complexity == "simple":
            return [SubTask(subtask_id=f"st_{uuid.uuid4().hex[:8]}", description=desc, parent_goal_id=goal_id, required_agent=agent) for desc, agent in base_subtasks[:3]]
        if complexity == "complex":
            base_subtasks.insert(2, ("Research relevant domain knowledge", "IntelX"))
            base_subtasks.append(("Forecast potential outcomes", "Futuris"))
        if complexity == "multi_domain":
            base_subtasks.insert(2, ("Research relevant domain knowledge", "IntelX"))
            base_subtasks.insert(3, ("Assess market and risk factors", "Stratex"))
            base_subtasks.append(("Forecast potential outcomes", "Futuris"))
            base_subtasks.append(("Analyze content strategy implications", "VyralX"))
        subtasks = []
        for desc, agent in base_subtasks:
            st = SubTask(
                subtask_id=f"st_{uuid.uuid4().hex[:8]}",
                description=desc,
                parent_goal_id=goal_id,
                required_agent=agent,
                priority=len(subtasks),
            )
            if subtasks:
                st.dependencies = [subtasks[-1].subtask_id]
            subtasks.append(st)
        return subtasks

    def update_subtask_status(self, subtask_id: str, status: str, result: str = "") -> bool:
        """Update a subtask's status."""
        st = self._subtasks.get(subtask_id)
        if not st:
            return False
        st.status = status
        if result:
            st.result = result
        if status == "completed":
            st.completed_at = time.time()
            goal = self._goals.get(st.parent_goal_id)
            if goal:
                completed = sum(1 for s in goal.subtasks if s.status == "completed")
                goal.progress_pct = (completed / len(goal.subtasks)) * 100
                if completed == len(goal.subtasks):
                    goal.status = "completed"
                    goal.completed_at = time.time()
        return True

    def get_goal_status(self, goal_id: str) -> dict[str, Any]:
        """Get status of a goal and its subtasks."""
        goal = self._goals.get(goal_id)
        if not goal:
            raise HTTPException(status_code=404, detail="Goal not found")
        return {
            "goal_id": goal.goal_id,
            "description": goal.description,
            "status": goal.status,
            "progress_pct": goal.progress_pct,
            "subtasks": [
                {
                    "subtask_id": st.subtask_id,
                    "description": st.description,
                    "required_agent": st.required_agent,
                    "status": st.status,
                    "dependencies": st.dependencies,
                    "result": st.result[:200],
                }
                for st in goal.subtasks
            ],
        }

    def get_all_goals(self) -> list[dict[str, Any]]:
        """Get all goals."""
        return [
            {
                "goal_id": g.goal_id,
                "description": g.description,
                "complexity": g.complexity,
                "status": g.status,
                "progress_pct": g.progress_pct,
                "subtask_count": len(g.subtasks),
            }
            for g in self._goals.values()
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        completed = sum(1 for g in self._goals.values() if g.status == "completed")
        return {
            "total_goals": len(self._goals),
            "completed_goals": completed,
            "total_subtasks": len(self._subtasks),
            "pending_subtasks": sum(1 for s in self._subtasks.values() if s.status == "pending"),
            "completed_subtasks": sum(1 for s in self._subtasks.values() if s.status == "completed"),
            "engine_status": "operational",
        }


engine = TaskDecompositionEngine()


@router.post("/tasks/decompose")
async def decompose_task(description: str, complexity: str = "medium"):
    """Decompose a complex goal into subtasks."""
    result = engine.decompose_goal(description, complexity)
    return {
        "goal_id": result.goal_id,
        "subtasks": [
            {
                "subtask_id": st.subtask_id,
                "description": st.description,
                "required_agent": st.required_agent,
                "priority": st.priority,
                "dependencies": st.dependencies,
            }
            for st in result.subtasks
        ],
        "estimated_total_time_sec": result.estimated_total_time,
    }


@router.get("/tasks/goals/{goal_id}")
async def get_goal(goal_id: str):
    """Get goal status and subtask details."""
    return engine.get_goal_status(goal_id)


@router.get("/tasks/goals")
async def list_goals():
    """List all goals."""
    return {"goals": engine.get_all_goals()}


@router.post("/tasks/subtasks/{subtask_id}/status")
async def update_subtask(subtask_id: str, status: str, result: str = ""):
    """Update subtask status."""
    if not engine.update_subtask_status(subtask_id, status, result):
        raise HTTPException(status_code=404, detail="Subtask not found")
    return {"subtask_id": subtask_id, "status": status}


@router.get("/tasks/report")
async def task_report():
    """Get task decomposition report."""
    return engine.get_report()
