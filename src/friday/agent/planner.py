# -*- coding: utf-8 -*-
"""Structured Task Planning and Goal Decomposition models for FRIDAY.

Provides explicit, validated, provider-independent task plans:
- Goal representation and intent
- Ordered execution steps with dependencies
- Step safety levels, required tools, and authorization requirements
- Pre-execution plan validation without executing actions
- Compatibility with MockLLMProvider and cloud LLMs
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import uuid

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.tools.registry import ToolRegistry

logger = get_logger("agent.planner")


class StepStatus(str, Enum):
    """Execution status of an individual plan step."""
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"


class PlanValidationError(ValueError):
    """Raised when a TaskPlan fails structural, dependency, or parameter validation."""
    pass


@dataclass
class PlanStep:
    """A discrete, structured action step within a TaskPlan."""

    step_id: str
    description: str
    tool_name: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    safety_level: SafetyLevel = SafetyLevel.SAFE
    requires_confirmation: bool = False
    status: StepStatus = StepStatus.PENDING
    success_criteria: Optional[str] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize plan step to audit-safe dictionary."""
        return {
            "step_id": self.step_id,
            "description": self.description,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "depends_on": self.depends_on,
            "safety_level": self.safety_level.value,
            "requires_confirmation": self.requires_confirmation,
            "status": self.status.value,
            "success_criteria": self.success_criteria,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class TaskPlan:
    """A complete, structured plan decomposing a user goal into validated execution steps."""

    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize plan to audit-safe dictionary."""
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    def get_step(self, step_id: str) -> Optional[PlanStep]:
        """Find a step by its ID."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def get_dependencies_for_step(self, step_id: str) -> List[PlanStep]:
        """Retrieve PlanStep objects that the given step depends on."""
        step = self.get_step(step_id)
        if not step:
            return []
        deps = []
        for dep_id in step.depends_on:
            dep_step = self.get_step(dep_id)
            if dep_step:
                deps.append(dep_step)
        return deps

    def validate(self, tool_registry: Optional[ToolRegistry] = None) -> bool:
        """Perform comprehensive pre-execution validation on the plan.

        Validates:
        1. Non-empty goal and non-empty steps.
        2. Unique step IDs.
        3. All dependencies exist and precede the dependent step (DAG check, no circular deps).
        4. If tools are specified, verify tool exists in registry and tool arguments validate.
        5. Sensitive and Dangerous steps require confirmation.
        """
        if not self.goal or not self.goal.strip():
            raise PlanValidationError("TaskPlan must specify a non-empty goal.")

        if not self.steps:
            raise PlanValidationError("TaskPlan must contain at least one step.")

        step_ids: Set[str] = set()
        for idx, step in enumerate(self.steps):
            if not step.step_id or not step.step_id.strip():
                raise PlanValidationError(f"Step at index {idx} has an invalid or empty step_id.")

            if step.step_id in step_ids:
                raise PlanValidationError(f"Duplicate step_id detected: '{step.step_id}'. Step IDs must be unique.")
            step_ids.add(step.step_id)

            # Check dependencies: must exist and be defined earlier in step list to enforce acyclic DAG
            for dep_id in step.depends_on:
                if dep_id not in step_ids:
                    raise PlanValidationError(
                        f"Step '{step.step_id}' depends on '{dep_id}' which does not exist or appears after this step."
                    )
                if dep_id == step.step_id:
                    raise PlanValidationError(f"Step '{step.step_id}' cannot depend on itself.")

            # Validate tools if registry provided
            if tool_registry and step.tool_name:
                tool = tool_registry.get(step.tool_name)
                if not tool:
                    raise PlanValidationError(f"Step '{step.step_id}' references unknown tool '{step.tool_name}'.")

                # Validate safety alignment
                if tool.safety_level in (SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS):
                    step.safety_level = tool.safety_level
                    step.requires_confirmation = True

                # Validate parameters against tool schema
                valid, err_msg = tool.validate_arguments(step.parameters)
                if not valid:
                    raise PlanValidationError(
                        f"Step '{step.step_id}' has invalid arguments for tool '{step.tool_name}': {err_msg}"
                    )

        return True


class GoalDecomposer:
    """Helper for decomposing natural language user goals into structured TaskPlans."""

    @staticmethod
    def create_single_step_plan(
        goal: str,
        description: str,
        tool_name: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
        safety_level: SafetyLevel = SafetyLevel.SAFE,
        requires_confirmation: bool = False,
        success_criteria: Optional[str] = None,
    ) -> TaskPlan:
        """Create a simple, single-step TaskPlan."""
        step = PlanStep(
            step_id="step_1",
            description=description,
            tool_name=tool_name,
            parameters=parameters or {},
            safety_level=safety_level,
            requires_confirmation=requires_confirmation,
            success_criteria=success_criteria,
        )
        return TaskPlan(goal=goal, steps=[step])

    @staticmethod
    def create_multi_step_plan(
        goal: str,
        step_definitions: List[Dict[str, Any]],
    ) -> TaskPlan:
        """Create a multi-step TaskPlan from a list of step definition dictionaries."""
        steps: List[PlanStep] = []
        for idx, sdef in enumerate(step_definitions, start=1):
            step_id = sdef.get("step_id", f"step_{idx}")
            desc = sdef.get("description", f"Execute step {idx}")
            tool_name = sdef.get("tool_name")
            params = sdef.get("parameters", {})
            depends_on = sdef.get("depends_on", [])
            safety = sdef.get("safety_level", SafetyLevel.SAFE)
            if isinstance(safety, str):
                try:
                    safety = SafetyLevel(safety.upper())
                except Exception:
                    safety = SafetyLevel.SAFE
            req_confirm = sdef.get("requires_confirmation", safety in (SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS))
            crit = sdef.get("success_criteria")

            steps.append(
                PlanStep(
                    step_id=step_id,
                    description=desc,
                    tool_name=tool_name,
                    parameters=params,
                    depends_on=depends_on,
                    safety_level=safety,
                    requires_confirmation=req_confirm,
                    success_criteria=crit,
                )
            )

        return TaskPlan(goal=goal, steps=steps)
