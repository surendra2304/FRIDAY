"""Model & Executor Routing Layer for FRIDAY Planning Architecture.

Scores and selects the best executor/model for each subtask based on:
- Capability matching (exact vs keyword)
- Modality & data type compatibility
- Locality preference (offline/local first)
- Cost efficiency (free-first policy)
- Latency profile
- Fallback selection for resilient failover
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.planning.executors import BaseExecutor, ExecutorRegistry
from friday.planning.types import TaskDataType, TaskStep

logger = get_logger("planning.router")


@dataclass
class RoutingEvaluation:
    """Detailed score breakdown for an executor candidate."""

    executor_name: str
    total_score: float
    capability_score: float
    type_compatibility_score: float
    locality_bonus: float
    cost_bonus: float
    latency_bonus: float
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "executor_name": self.executor_name,
            "total_score": round(self.total_score, 2),
            "capability_score": self.capability_score,
            "type_compatibility_score": self.type_compatibility_score,
            "locality_bonus": self.locality_bonus,
            "cost_bonus": self.cost_bonus,
            "latency_bonus": self.latency_bonus,
            "rationale": self.rationale,
        }


@dataclass
class RoutingResult:
    """The chosen primary executor and backup fallbacks for a subtask."""

    task_id: str
    primary_executor: BaseExecutor
    fallback_executors: list[BaseExecutor] = field(default_factory=list)
    score: float = 0.0
    evaluations: list[RoutingEvaluation] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "primary_executor": self.primary_executor.name,
            "fallback_executors": [e.name for e in self.fallback_executors],
            "score": round(self.score, 2),
            "evaluations": [e.to_dict() for e in self.evaluations],
        }


class ModelRouter:
    """Matches subtasks to the optimal executor from the ExecutorRegistry."""

    def __init__(self, registry: ExecutorRegistry) -> None:
        self.registry = registry

    def score_executor(self, task: TaskStep, executor: BaseExecutor) -> RoutingEvaluation:
        """Calculate transparent suitability score for a task-executor pair."""
        capability_score = 0.0
        type_score = 0.0
        locality_bonus = 0.0
        cost_bonus = 0.0
        latency_bonus = 0.0
        reasons = []

        # 1. Capability & Keyword Alignment (0 - 40 pts)
        desc_lower = f"{task.description} {task.objective} {task.tool_name or ''}".lower()
        cap_lower = executor.capability.lower()
        name_lower = executor.name.lower()

        if task.selected_executor and task.selected_executor.lower() == name_lower:
            capability_score = 40.0
            reasons.append("Exact executor name specified in task")
        elif task.tool_name and task.tool_name.lower() == name_lower:
            capability_score = 40.0
            reasons.append("Exact tool name specified in task")
        elif cap_lower in desc_lower or name_lower in desc_lower:
            capability_score = 35.0
            reasons.append("High semantic capability match")
        else:
            # Keyword partial overlap
            keywords = [k for k in desc_lower.split() if len(k) > 3]
            match_count = sum(1 for kw in keywords if kw in f"{executor.description} {executor.name}".lower())
            if match_count > 0:
                capability_score = min(25.0, match_count * 8.0)
                reasons.append(f"Matched {match_count} keywords")

        # 2. Modality & Data Type Compatibility (0 - 25 pts)
        has_any_input = TaskDataType.ANY in executor.input_types
        matched_inputs = any(it in executor.input_types for it in task.input_types)
        if has_any_input or matched_inputs:
            type_score += 15.0
            reasons.append("Input types compatible")

        if task.output_type in executor.output_types or TaskDataType.ANY in executor.output_types:
            type_score += 10.0
            reasons.append("Output type compatible")

        # 3. Locality Preference (0 - 15 pts)
        if executor.is_local:
            locality_bonus = 15.0
            reasons.append("Local deterministic execution")

        # 4. Cost Preference (0 - 10 pts)
        if executor.cost_profile == "free":
            cost_bonus = 10.0
        elif executor.cost_profile == "low":
            cost_bonus = 5.0

        # 5. Latency Preference (0 - 10 pts)
        if executor.latency_profile == "fast":
            latency_bonus = 10.0
        elif executor.latency_profile == "medium":
            latency_bonus = 5.0

        total = capability_score + type_score + locality_bonus + cost_bonus + latency_bonus
        return RoutingEvaluation(
            executor_name=executor.name,
            total_score=total,
            capability_score=capability_score,
            type_compatibility_score=type_score,
            locality_bonus=locality_bonus,
            cost_bonus=cost_bonus,
            latency_bonus=latency_bonus,
            rationale=", ".join(reasons) if reasons else "Default compatibility",
        )

    def route_task(self, task: TaskStep) -> RoutingResult | None:
        """Find the optimal primary executor and fallbacks for a given task."""
        executors = self.registry.list_executors()
        if not executors:
            logger.warning("No executors registered in ExecutorRegistry.")
            return None

        evaluations: list[tuple[BaseExecutor, RoutingEvaluation]] = []
        for exc in executors:
            ev = self.score_executor(task, exc)
            evaluations.append((exc, ev))

        # Sort by total score descending
        evaluations.sort(key=lambda x: x[1].total_score, reverse=True)

        primary_exc, top_eval = evaluations[0]
        fallbacks = [exc for exc, ev in evaluations[1:4] if ev.total_score >= 20.0]

        # Populate task fields
        task.selected_executor = primary_exc.name
        task.fallback_executors = [f.name for f in fallbacks]
        safety_ranks = {SafetyLevel.SAFE: 0, SafetyLevel.SENSITIVE: 1, SafetyLevel.DANGEROUS: 2}
        if safety_ranks.get(primary_exc.safety_level, 0) > safety_ranks.get(task.safety_level, 0):
            task.safety_level = primary_exc.safety_level
            task.requires_confirmation = True

        return RoutingResult(
            task_id=task.id,
            primary_executor=primary_exc,
            fallback_executors=fallbacks,
            score=top_eval.total_score,
            evaluations=[ev for _, ev in evaluations[:5]],
        )
