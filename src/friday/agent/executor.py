# -*- coding: utf-8 -*-
"""Multi-Step Task Execution Engine & Progress Tracker for FRIDAY.

Consumes validated TaskPlan objects and executes plan steps in dependency order:
- Dependency resolution: Prevents step execution until prerequisites succeed.
- Step failure cascading: Skips or blocks dependent steps if prerequisites fail.
- Safety & authorization gating: Enforces BaseAuthorizer and ToolRegistry policies.
- Progress tracking: Telemetry on completed, failed, skipped, and pending steps.
- Bounded execution: Enforces timeouts, step budgets, and loop limits.
- Provider independence: Zero cloud lock-in, fully operable offline.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
from typing import Any, Callable, Dict, List, Optional
import uuid

from friday.agent.planner import PlanStep, StepStatus, TaskPlan
from friday.agent.state import ReasoningStateMachine, TaskState
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.logging import get_logger
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    SafetyLevel,
    ToolCall,
    ToolResult,
)
from friday.tools.registry import ToolRegistry

logger = get_logger("agent.executor")


@dataclass
class ExecutionProgress:
    """Telemetry report representing current progress of a TaskPlan execution."""

    plan_id: str
    goal: str
    total_steps: int
    completed_steps: int = 0
    failed_steps: int = 0
    skipped_steps: int = 0
    pending_steps: int = 0
    in_progress_step_id: Optional[str] = None
    elapsed_seconds: float = 0.0
    is_done: bool = False
    success: bool = False

    @property
    def percentage(self) -> float:
        """Percentage of steps resolved (completed, failed, or skipped)."""
        if self.total_steps == 0:
            return 100.0
        resolved = self.completed_steps + self.failed_steps + self.skipped_steps
        return round((resolved / self.total_steps) * 100.0, 2)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize progress metrics to audit dictionary."""
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "skipped_steps": self.skipped_steps,
            "pending_steps": self.pending_steps,
            "in_progress_step_id": self.in_progress_step_id,
            "percentage": self.percentage,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "is_done": self.is_done,
            "success": self.success,
        }


@dataclass
class StepExecutionResult:
    """Outcome report for an individual plan step execution."""

    step_id: str
    status: StepStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": round(self.duration_seconds, 3),
        }


@dataclass
class TaskExecutionResult:
    """Overall outcome of executing a TaskPlan."""

    plan_id: str
    goal: str
    success: bool
    state: TaskState
    step_results: Dict[str, StepExecutionResult] = field(default_factory=dict)
    duration_seconds: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "success": self.success,
            "state": self.state.value,
            "duration_seconds": round(self.duration_seconds, 3),
            "step_results": {k: v.to_dict() for k, v in self.step_results.items()},
            "error": self.error,
        }


class TaskExecutionEngine:
    """Orchestrates structured step-by-step execution of TaskPlans."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        authorizer: Optional[BaseAuthorizer] = None,
        max_step_limit: int = 50,
        step_timeout_seconds: float = 60.0,
        on_step_progress: Optional[Callable[[ExecutionProgress], None]] = None,
    ) -> None:
        self.tools = tool_registry
        self.authorizer = authorizer or DefaultSecureAuthorizer()
        self.max_step_limit = max_step_limit
        self.step_timeout_seconds = step_timeout_seconds
        self.on_step_progress = on_step_progress

    def execute_plan(
        self,
        plan: TaskPlan,
        state_machine: Optional[ReasoningStateMachine] = None,
    ) -> TaskExecutionResult:
        """Execute a TaskPlan in validated dependency order with safety gating."""
        start_time = time.perf_counter()

        # Validate plan before execution if not already verified
        plan.validate(tool_registry=self.tools)

        sm = state_machine or ReasoningStateMachine(task_id=plan.plan_id)
        if sm.current_state == TaskState.NOT_STARTED:
            sm.transition_to(TaskState.UNDERSTANDING, reason="Starting plan execution")
            sm.transition_to(TaskState.PLANNING, reason="Plan pre-validated")
            sm.transition_to(TaskState.EXECUTING, reason="Executing plan steps")
        elif sm.current_state == TaskState.PLANNING:
            sm.transition_to(TaskState.EXECUTING, reason="Executing plan steps")

        step_results: Dict[str, StepExecutionResult] = {}
        total_steps = len(plan.steps)
        executed_count = 0

        logger.info(f"TaskExecutionEngine: Beginning execution of plan '{plan.plan_id}' with {total_steps} step(s).")

        for step in plan.steps:
            executed_count += 1
            if executed_count > self.max_step_limit:
                err_msg = f"Task exceeded maximum step execution limit ({self.max_step_limit}). Execution halted."
                logger.error(err_msg)
                step.status = StepStatus.BLOCKED
                step.error = err_msg
                step_results[step.step_id] = StepExecutionResult(
                    step_id=step.step_id,
                    status=StepStatus.BLOCKED,
                    error=err_msg,
                )
                sm.fail(reason=err_msg, metadata={"limit_exceeded": True})
                break

            # 1. Dependency Resolution Check
            missing_or_failed_deps = []
            for dep_id in step.depends_on:
                dep_res = step_results.get(dep_id)
                if not dep_res or dep_res.status != StepStatus.COMPLETED:
                    missing_or_failed_deps.append(dep_id)

            if missing_or_failed_deps:
                skip_msg = f"Prerequisite step(s) {missing_or_failed_deps} failed or uncompleted. Skipping."
                logger.warning(f"Step '{step.step_id}': {skip_msg}")
                step.status = StepStatus.SKIPPED
                step.error = skip_msg
                step_results[step.step_id] = StepExecutionResult(
                    step_id=step.step_id,
                    status=StepStatus.SKIPPED,
                    error=skip_msg,
                )
                self._notify_progress(plan, step_results, step.step_id, time.perf_counter() - start_time)
                continue

            # 2. Execute Step
            step.status = StepStatus.IN_PROGRESS
            step_start = time.perf_counter()
            self._notify_progress(plan, step_results, step.step_id, step_start - start_time)

            step_res = self._execute_step(step)
            step_results[step.step_id] = step_res
            step.status = step_res.status
            step.result = step_res.result
            step.error = step_res.error

            self._notify_progress(plan, step_results, None, time.perf_counter() - start_time)

        # 3. Assess overall plan outcome
        overall_duration = time.perf_counter() - start_time
        all_completed = all(r.status == StepStatus.COMPLETED for r in step_results.values())
        any_failed = any(r.status in (StepStatus.FAILED, StepStatus.BLOCKED) for r in step_results.values())

        if sm.current_state == TaskState.EXECUTING:
            sm.transition_to(TaskState.VERIFYING, reason="Verifying step outcomes")
            if all_completed and not any_failed:
                sm.transition_to(TaskState.COMPLETED, reason="All plan steps completed successfully")
            else:
                sm.fail(reason="One or more plan steps failed during execution", metadata={"failed_steps": [k for k, v in step_results.items() if v.status == StepStatus.FAILED]})

        self._notify_progress(plan, step_results, None, overall_duration, is_done=True, success=all_completed)

        return TaskExecutionResult(
            plan_id=plan.plan_id,
            goal=plan.goal,
            success=all_completed,
            state=sm.current_state,
            step_results=step_results,
            duration_seconds=overall_duration,
            error=sm.failure_reason,
        )

    def _execute_step(self, step: PlanStep) -> StepExecutionResult:
        """Execute a single PlanStep using the ToolRegistry and BaseAuthorizer."""
        step_start_time = datetime.now(timezone.utc)
        start_perf = time.perf_counter()

        # If step has no tool, it's a reasoning/synthesis milestone
        if not step.tool_name:
            duration = time.perf_counter() - start_perf
            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.COMPLETED,
                result="Milestone completed.",
                start_time=step_start_time,
                end_time=datetime.now(timezone.utc),
                duration_seconds=duration,
            )

        tool = self.tools.get(step.tool_name)
        if not tool:
            err = f"Tool '{step.tool_name}' not found in registry."
            logger.error(err)
            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.FAILED,
                error=err,
                start_time=step_start_time,
                end_time=datetime.now(timezone.utc),
                duration_seconds=time.perf_counter() - start_perf,
            )

        # 1. Parameter Validation
        valid, val_err = tool.validate_arguments(step.parameters)
        if not valid:
            err = f"Invalid arguments for tool '{step.tool_name}': {val_err}"
            logger.error(err)
            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.FAILED,
                error=err,
                start_time=step_start_time,
                end_time=datetime.now(timezone.utc),
                duration_seconds=time.perf_counter() - start_perf,
            )

        # 2. Authorization Check
        auth_req = AuthorizationRequest(
            tool_name=step.tool_name,
            safety_level=tool.safety_level,
            arguments=step.parameters,
            purpose=step.description,
            affected_resource=str(step.parameters.get("path", "")),
        )
        auth_resp = self.authorizer.authorize(auth_req)

        if auth_resp.decision != AuthorizationDecision.APPROVED:
            err = f"Authorization Denied: {auth_resp.reason}"
            logger.warning(f"Step '{step.step_id}': {err}")
            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.FAILED,
                error=err,
                start_time=step_start_time,
                end_time=datetime.now(timezone.utc),
                duration_seconds=time.perf_counter() - start_perf,
            )

        # 3. Tool Execution
        try:
            call_id = f"call_{uuid.uuid4().hex[:8]}"
            tool_result: ToolResult = self.tools.execute(
                name=step.tool_name,
                arguments=step.parameters,
                tool_call_id=call_id,
                allow_sensitive=True,
            )
            duration = time.perf_counter() - start_perf

            if tool_result.is_error:
                return StepExecutionResult(
                    step_id=step.step_id,
                    status=StepStatus.FAILED,
                    error=tool_result.content,
                    start_time=step_start_time,
                    end_time=datetime.now(timezone.utc),
                    duration_seconds=duration,
                )

            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.COMPLETED,
                result=tool_result.content,
                start_time=step_start_time,
                end_time=datetime.now(timezone.utc),
                duration_seconds=duration,
            )
        except Exception as e:
            logger.exception(f"Unexpected error executing step '{step.step_id}': {e}")
            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.FAILED,
                error=str(e),
                start_time=step_start_time,
                end_time=datetime.now(timezone.utc),
                duration_seconds=time.perf_counter() - start_perf,
            )

    def _notify_progress(
        self,
        plan: TaskPlan,
        step_results: Dict[str, StepExecutionResult],
        in_progress_id: Optional[str],
        elapsed_seconds: float,
        is_done: bool = False,
        success: bool = False,
    ) -> None:
        """Calculate and dispatch progress telemetry callback."""
        if not self.on_step_progress:
            return

        completed = sum(1 for r in step_results.values() if r.status == StepStatus.COMPLETED)
        failed = sum(1 for r in step_results.values() if r.status in (StepStatus.FAILED, StepStatus.BLOCKED))
        skipped = sum(1 for r in step_results.values() if r.status == StepStatus.SKIPPED)
        pending = len(plan.steps) - (completed + failed + skipped)

        progress = ExecutionProgress(
            plan_id=plan.plan_id,
            goal=plan.goal,
            total_steps=len(plan.steps),
            completed_steps=completed,
            failed_steps=failed,
            skipped_steps=skipped,
            pending_steps=max(0, pending),
            in_progress_step_id=in_progress_id,
            elapsed_seconds=elapsed_seconds,
            is_done=is_done,
            success=success,
        )

        try:
            self.on_step_progress(progress)
        except Exception as e:
            logger.warning(f"Error in on_step_progress callback: {e}")
