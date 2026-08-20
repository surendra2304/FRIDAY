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
from typing import Any, Dict, List, Optional, Set, Tuple
import uuid

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.agent.goal import Goal, GoalRequestType, GoalRiskLevel, SubGoal
from friday.tools.registry import ToolRegistry

logger = get_logger("agent.planner")


class StepStatus(str, Enum):
    """Execution status of an individual plan step."""
    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    IN_PROGRESS = "IN_PROGRESS"  # Alias
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    SUCCEEDED = "COMPLETED"      # Phase 9.3 standard status mapped to COMPLETED for complete backward compatibility
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"


class PlanValidationError(ValueError):
    """Raised when a TaskPlan fails structural, dependency, or parameter validation."""
    pass


@dataclass
class PlanStep:
    """A discrete, structured, typed action step within a TaskPlan."""

    step_id: str
    description: str
    tool_name: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)
    safety_level: SafetyLevel = SafetyLevel.SAFE
    requires_confirmation: bool = False
    status: StepStatus = StepStatus.PENDING
    success_criteria: Optional[str] = None
    expected_output_type: Optional[str] = None
    required_capabilities: List[str] = field(default_factory=list)
    rollback_step_id: Optional[str] = None
    checkpoint_enabled: bool = False
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
            "expected_output_type": self.expected_output_type,
            "required_capabilities": self.required_capabilities,
            "rollback_step_id": self.rollback_step_id,
            "checkpoint_enabled": self.checkpoint_enabled,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanStep":
        """Deserialize PlanStep from dictionary."""
        status_val = data.get("status", StepStatus.PENDING.value)
        safety_val = data.get("safety_level", SafetyLevel.SAFE.value)
        return cls(
            step_id=data["step_id"],
            description=data.get("description", ""),
            tool_name=data.get("tool_name"),
            parameters=data.get("parameters", {}),
            depends_on=data.get("depends_on", []),
            safety_level=SafetyLevel(safety_val) if safety_val in SafetyLevel._value2member_map_ else SafetyLevel.SAFE,
            requires_confirmation=data.get("requires_confirmation", False),
            status=StepStatus(status_val) if status_val in StepStatus._value2member_map_ else StepStatus.PENDING,
            success_criteria=data.get("success_criteria"),
            expected_output_type=data.get("expected_output_type"),
            required_capabilities=data.get("required_capabilities", []),
            rollback_step_id=data.get("rollback_step_id"),
            checkpoint_enabled=data.get("checkpoint_enabled", False),
            result=data.get("result"),
            error=data.get("error"),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(timezone.utc),
        )


@dataclass
class TaskPlan:
    """A complete, structured plan decomposing a user goal into validated execution steps."""

    goal: str
    steps: List[PlanStep] = field(default_factory=list)
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    goal_id: Optional[str] = None
    risk_level: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize plan to audit-safe dictionary."""
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "goal_id": self.goal_id,
            "risk_level": self.risk_level,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskPlan":
        """Deserialize TaskPlan and constituent PlanSteps from dictionary."""
        steps = [PlanStep.from_dict(s) for s in data.get("steps", [])]
        return cls(
            goal=data.get("goal", ""),
            steps=steps,
            plan_id=data.get("plan_id", str(uuid.uuid4())),
            goal_id=data.get("goal_id"),
            risk_level=data.get("risk_level"),
            created_at=datetime.fromisoformat(data["created_at"]) if "created_at" in data else datetime.now(timezone.utc),
            metadata=data.get("metadata", {}),
        )

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

    def compute_topological_schedule(self) -> List[List[PlanStep]]:
        """Compute waves/levels of steps that can be executed concurrently based on the dependency DAG."""
        completed_ids: Set[str] = set()
        remaining_steps = list(self.steps)
        schedule_waves: List[List[PlanStep]] = []

        while remaining_steps:
            ready_wave = [
                s for s in remaining_steps
                if all(dep in completed_ids for dep in s.depends_on)
            ]
            if not ready_wave:
                # Cycle or unresolvable prerequisite detected
                cycle_candidates = [s.step_id for s in remaining_steps]
                raise PlanValidationError(f"Cyclic dependency detected among steps: {cycle_candidates}")

            schedule_waves.append(ready_wave)
            for s in ready_wave:
                completed_ids.add(s.step_id)
                remaining_steps.remove(s)

        return schedule_waves

    def validate(self, tool_registry: Optional[ToolRegistry] = None, available_capabilities: Optional[Set[str]] = None) -> bool:
        """Perform comprehensive pre-execution validation on the plan DAG.

        Validates:
        1. Non-empty goal and non-empty steps.
        2. Unique step IDs.
        3. All dependencies exist and no self-dependencies.
        4. Acyclic DAG check (topological sort / cycle detection).
        5. If tools are specified, verify tool exists in registry and tool arguments validate.
        6. Capability availability check if provided.
        7. Sensitive and Dangerous steps require confirmation.
        """
        if not self.goal or not self.goal.strip():
            raise PlanValidationError("TaskPlan must specify a non-empty goal.")

        if not self.steps:
            raise PlanValidationError("TaskPlan must contain at least one step.")

        step_map: Dict[str, PlanStep] = {}
        for idx, step in enumerate(self.steps):
            if not step.step_id or not step.step_id.strip():
                raise PlanValidationError(f"Step at index {idx} has an invalid or empty step_id.")

            if step.step_id in step_map:
                raise PlanValidationError(f"Duplicate step_id detected: '{step.step_id}'. Step IDs must be unique.")
            step_map[step.step_id] = step

            for dep_id in step.depends_on:
                if dep_id not in [s.step_id for s in self.steps]:
                    raise PlanValidationError(
                        f"Step '{step.step_id}' depends on '{dep_id}' which does not exist in the plan."
                    )
                if dep_id == step.step_id:
                    raise PlanValidationError(f"Step '{step.step_id}' cannot depend on itself.")

        # Cycle detection via topological sort
        self.compute_topological_schedule()

        # Capability validation
        if available_capabilities:
            for step in self.steps:
                for cap in step.required_capabilities:
                    if cap not in available_capabilities:
                        raise PlanValidationError(
                            f"Step '{step.step_id}' requires unavailable capability '{cap}'."
                        )

        # Tool registry & safety validation
        for step in self.steps:
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
    """Helper for converting natural language user goals and structured Goal instances into executable TaskPlans."""

    @staticmethod
    def create_from_goal(goal: Goal, tool_registry: Optional[ToolRegistry] = None) -> TaskPlan:
        """Convert a Phase 9.1 structured Goal into an executable DAG TaskPlan."""
        if goal.is_ambiguous:
            raise PlanValidationError(f"Cannot generate plan for ambiguous goal: {goal.clarification_needed}")

        if goal.is_prohibited:
            raise PlanValidationError(f"Cannot generate plan for prohibited goal: {goal.prohibition_reason}")

        steps: List[PlanStep] = []
        for sg in goal.subgoals:
            # Map capability to tool if possible
            tool_name = None
            params: Dict[str, Any] = {}

            if "system_info" in sg.required_capabilities or "system_diagnostics" in sg.required_capabilities:
                tool_name = "get_system_info"
            elif "time_query" in sg.required_capabilities:
                tool_name = "get_current_time"
            elif "file_reading" in sg.required_capabilities or "read_file" in sg.description.lower():
                tool_name = "read_file"
            elif "file_listing" in sg.required_capabilities or "list_files" in sg.description.lower():
                tool_name = "list_files"
            elif "memory_search" in sg.required_capabilities or "search_memory" in sg.description.lower():
                tool_name = "search_memory"
                params = {"query": sg.description}
            elif "screen_capture" in sg.required_capabilities or "screen" in sg.description.lower():
                tool_name = "take_screenshot"
            elif "action_proposal" in sg.required_capabilities or "computer_action_proposal" in sg.required_capabilities:
                tool_name = "propose_computer_action"

            steps.append(
                PlanStep(
                    step_id=sg.subgoal_id,
                    description=sg.description,
                    tool_name=tool_name,
                    parameters=params,
                    depends_on=sg.dependencies,
                    safety_level=sg.safety_level,
                    requires_confirmation=sg.requires_confirmation,
                    success_criteria=sg.success_conditions[0] if sg.success_conditions else None,
                    required_capabilities=sg.required_capabilities,
                    checkpoint_enabled=True,
                )
            )

        plan = TaskPlan(
            goal=goal.normalized_intent or goal.original_request,
            steps=steps,
            goal_id=goal.goal_id,
            risk_level=goal.risk_level.value,
            metadata={"request_type": goal.request_type.value},
        )
        return plan

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
            out_type = sdef.get("expected_output_type")
            req_caps = sdef.get("required_capabilities", [])
            rb_id = sdef.get("rollback_step_id")
            chk_en = sdef.get("checkpoint_enabled", False)

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
                    expected_output_type=out_type,
                    required_capabilities=req_caps,
                    rollback_step_id=rb_id,
                    checkpoint_enabled=chk_en,
                )
            )

        return TaskPlan(goal=goal, steps=steps)

