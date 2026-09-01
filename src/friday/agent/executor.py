"""Multi-Step Task Execution Engine, Progress Tracker & Self-Correction for FRIDAY.

Consumes validated TaskPlan objects and executes plan steps in dependency order:
- Dependency resolution: Prevents step execution until prerequisites succeed.
- Step failure cascading: Skips or blocks dependent steps if prerequisites fail.
- Safety & authorization gating: Enforces BaseAuthorizer and ToolRegistry policies.
- Formal Verification: Asserts step and task success criteria via StepVerifier.
- Bounded Self-Correction: Diagnoses verification failures and executes bounded retries.
- Progress tracking: Telemetry on completed, failed, skipped, and pending steps.
- Bounded execution: Enforces timeouts, step budgets, and loop limits.
- Provider independence: Zero cloud lock-in, fully operable offline.
"""

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.agent.planner import PlanStep, StepStatus, TaskPlan
from friday.agent.recovery import (
    AutonomousRecoveryManager,
    FailureAnalyzer,
)
from friday.agent.state import ReasoningStateMachine, TaskState
from friday.agent.verification import (
    StepVerifier,
    VerificationResult,
    VerificationStatus,
)
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.logging import get_logger
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    SafetyLevel,
    ToolResult,
)
from friday.tools.orchestrator import DataFlowResolver
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
    in_progress_step_id: str | None = None
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

    def to_dict(self) -> dict[str, Any]:
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
    result: Any | None = None
    error: str | None = None
    verification: VerificationResult | None = None
    retries_used: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "verification": self.verification.to_dict() if self.verification else None,
            "retries_used": self.retries_used,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": round(self.duration_seconds, 3),
        }


@dataclass
class TaskExecutionResult:
    """Overall outcome of executing a TaskPlan with verification status."""

    plan_id: str
    goal: str
    success: bool
    state: TaskState
    step_results: dict[str, StepExecutionResult] = field(default_factory=dict)
    plan_verification: VerificationResult | None = None
    duration_seconds: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "success": self.success,
            "state": self.state.value,
            "duration_seconds": round(self.duration_seconds, 3),
            "step_results": {k: v.to_dict() for k, v in self.step_results.items()},
            "plan_verification": self.plan_verification.to_dict() if self.plan_verification else None,
            "error": self.error,
        }


class TaskExecutionEngine:
    """Orchestrates structured step-by-step execution, verification, and self-correction of TaskPlans."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        authorizer: BaseAuthorizer | None = None,
        max_step_limit: int = 50,
        max_self_corrections_per_step: int = 3,
        step_timeout_seconds: float = 60.0,
        on_step_progress: Callable[[ExecutionProgress], None] | None = None,
        custom_corrector: Callable[[PlanStep, VerificationResult], PlanStep | None] | None = None,
        tool_fallbacks: dict[str, str] | None = None,
        allow_concurrent_safe_steps: bool = True,
    ) -> None:
        import threading
        from concurrent.futures import ThreadPoolExecutor
        self.tools = tool_registry
        self.authorizer = authorizer or DefaultSecureAuthorizer()
        self.max_step_limit = max_step_limit
        self.max_self_corrections_per_step = max_self_corrections_per_step
        self.step_timeout_seconds = step_timeout_seconds
        self.on_step_progress = on_step_progress
        self.custom_corrector = custom_corrector
        self.tool_fallbacks = tool_fallbacks or {}
        self.allow_concurrent_safe_steps = allow_concurrent_safe_steps
        self._cancel_token = threading.Event()
        self._thread_executor = ThreadPoolExecutor(max_workers=10, thread_name_prefix="friday-engine-worker")

    def cancel(self, reason: str = "Execution cancelled") -> None:
        """Signal immediate cancellation across all steps and workers."""
        self._cancel_token.set()

    def reset_cancellation(self) -> None:
        """Reset cancellation token for new execution runs."""
        self._cancel_token.clear()

    def execute_plan(
        self,
        plan: TaskPlan,
        state_machine: ReasoningStateMachine | None = None,
        task_context: Any | None = None,
        cancellation_token: Any | None = None,
    ) -> TaskExecutionResult:
        """Execute a TaskPlan in validated dependency DAG order with wave scheduling, safe concurrency, and self-correction."""
        from friday.security.scrubber import redact_secrets

        start_time = time.perf_counter()
        cancel_event = cancellation_token or self._cancel_token

        sm = state_machine or ReasoningStateMachine(task_id=plan.plan_id)

        # 0. Terminal state barrier: Reject execution if already in terminal state
        if sm.is_terminal:
            err_msg = f"Cannot execute plan '{plan.plan_id}': Task is in terminal state '{sm.current_state.value}'."
            logger.error(err_msg)
            return TaskExecutionResult(
                plan_id=plan.plan_id,
                goal=plan.goal,
                success=False,
                state=sm.current_state,
                step_results={},
                duration_seconds=0.0,
                error=redact_secrets(err_msg),
            )

        # Validate plan before execution if not already verified
        plan.validate(tool_registry=self.tools)

        if task_context:
            task_context.plan = plan
            task_context.goal = plan.goal

        # Validated state progression into EXECUTING
        if sm.current_state == TaskState.NOT_STARTED:
            sm.transition_to(TaskState.UNDERSTANDING, reason="Starting plan execution")
            sm.transition_to(TaskState.PLANNING, reason="Plan pre-validated")
            sm.transition_to(TaskState.EXECUTING, reason="Executing plan steps")
        elif sm.current_state == TaskState.UNDERSTANDING:
            sm.transition_to(TaskState.PLANNING, reason="Plan pre-validated")
            sm.transition_to(TaskState.EXECUTING, reason="Executing plan steps")
        elif sm.current_state == TaskState.PLANNING:
            sm.transition_to(TaskState.EXECUTING, reason="Executing plan steps")
        elif sm.current_state == TaskState.PAUSED:
            sm.resume(reason="Resuming paused plan execution")

        step_results: dict[str, StepExecutionResult] = {}
        for s in plan.steps:
            if s.status in (StepStatus.COMPLETED, StepStatus.SUCCEEDED) and s.result is not None:
                step_results[s.step_id] = StepExecutionResult(
                    step_id=s.step_id,
                    status=StepStatus.SUCCEEDED,
                    result=s.result,
                )

        recovery_mgr = AutonomousRecoveryManager(
            max_retries_per_step=self.max_self_corrections_per_step,
            max_global_task_retries=self.max_step_limit,
            tool_fallbacks=getattr(self, "tool_fallbacks", {}),
        )
        total_steps = len(plan.steps)
        executed_count = 0
        executed_action_fingerprints: set[str] = set()

        # Compute topological waves for dependency-aware scheduling
        schedule_waves = plan.compute_topological_schedule()
        logger.info(
            f"TaskExecutionEngine: Beginning execution of plan '{plan.plan_id}' with {total_steps} step(s) "
            f"across {len(schedule_waves)} topological wave(s)."
        )

        for wave_idx, wave in enumerate(schedule_waves):
            # Check cancellation barrier before wave
            if cancel_event.is_set() or sm.current_state == TaskState.CANCELLED:
                if sm.current_state != TaskState.CANCELLED:
                    sm.cancel(reason="Execution cancelled by cancellation signal")
                for s in wave:
                    if s.step_id not in step_results:
                        s.status = StepStatus.BLOCKED
                        s.error = "Execution cancelled."
                        step_results[s.step_id] = StepExecutionResult(
                            step_id=s.step_id,
                            status=StepStatus.BLOCKED,
                            error="Execution cancelled.",
                        )
                break

            # 1. Evaluate steps in wave for limit exceedance and prerequisites
            ready_steps: list[PlanStep] = []
            for step in wave:
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

                # 0. Check if step is already COMPLETED / SUCCEEDED (idempotency guard)
                if step.status in (StepStatus.COMPLETED, StepStatus.SUCCEEDED) and step.result is not None:
                    logger.info(f"Step '{step.step_id}': Already verified and completed in prior checkpoint. Skipping duplicate execution.")
                    if step.step_id not in step_results:
                        step_results[step.step_id] = StepExecutionResult(
                            step_id=step.step_id,
                            status=StepStatus.SUCCEEDED,
                            result=step.result,
                        )
                    self._notify_progress(plan, step_results, step.step_id, time.perf_counter() - start_time)
                    continue

                # 1. Dependency Resolution & Waiting Check
                missing_or_failed_deps = []
                for dep_id in step.depends_on:
                    dep_res = step_results.get(dep_id)
                    if not dep_res or dep_res.status not in (StepStatus.COMPLETED, StepStatus.SUCCEEDED):
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

                ready_steps.append(step)

            if sm.is_terminal:
                break

            if not ready_steps:
                continue

            # 2. Check if ready steps can run concurrently
            # Strict safety policy: Independent SAFE steps without confirmation requirement can run concurrently
            can_run_concurrently = (
                self.allow_concurrent_safe_steps
                and len(ready_steps) > 1
                and all(
                    s.safety_level == SafetyLevel.SAFE and not s.requires_confirmation
                    for s in ready_steps
                )
            )

            if can_run_concurrently:
                logger.info(f"Topological Scheduling: Executing wave {wave_idx + 1} ({len(ready_steps)} independent SAFE steps) concurrently.")
                futures_map = {}
                for r_step in ready_steps:
                    r_step.status = StepStatus.RUNNING
                    if task_context:
                        task_context.set_active_step(r_step.step_id)
                    self._notify_progress(plan, step_results, r_step.step_id, time.perf_counter() - start_time)

                    fut = self._thread_executor.submit(
                        self._execute_step_with_recovery,
                        step=r_step,
                        step_results=step_results,
                        state_machine=sm,
                        recovery_mgr=recovery_mgr,
                        task_context=task_context,
                        cancel_event=cancel_event,
                        executed_action_fingerprints=executed_action_fingerprints,
                    )
                    futures_map[fut] = r_step

                for fut, r_step in futures_map.items():
                    try:
                        step_final_res = fut.result()
                    except Exception as exc:
                        step_final_res = StepExecutionResult(
                            step_id=r_step.step_id,
                            status=StepStatus.FAILED,
                            error=str(exc),
                        )
                    step_results[r_step.step_id] = step_final_res
                    r_step.status = step_final_res.status
                    r_step.result = step_final_res.result
                    r_step.error = step_final_res.error

                    if task_context:
                        task_context.record_step_result(
                            step_id=r_step.step_id,
                            result=step_final_res.result or step_final_res.error,
                            verification=step_final_res.verification,
                        )
                    self._notify_progress(plan, step_results, None, time.perf_counter() - start_time)
            else:
                # Serialized execution: Required for state-changing, sensitive, dangerous, or single-step execution
                for s_step in ready_steps:
                    if cancel_event.is_set() or sm.current_state == TaskState.CANCELLED:
                        if sm.current_state != TaskState.CANCELLED:
                            sm.cancel(reason="Execution cancelled by cancellation signal")
                        s_step.status = StepStatus.BLOCKED
                        s_step.error = "Execution cancelled."
                        step_results[s_step.step_id] = StepExecutionResult(
                            step_id=s_step.step_id,
                            status=StepStatus.BLOCKED,
                            error="Execution cancelled.",
                        )
                        break

                    s_step.status = StepStatus.RUNNING
                    if task_context:
                        task_context.set_active_step(s_step.step_id)
                    self._notify_progress(plan, step_results, s_step.step_id, time.perf_counter() - start_time)

                    step_final_res = self._execute_step_with_recovery(
                        step=s_step,
                        step_results=step_results,
                        state_machine=sm,
                        recovery_mgr=recovery_mgr,
                        task_context=task_context,
                        cancel_event=cancel_event,
                        executed_action_fingerprints=executed_action_fingerprints,
                    )
                    step_results[s_step.step_id] = step_final_res
                    s_step.status = step_final_res.status
                    s_step.result = step_final_res.result
                    s_step.error = step_final_res.error

                    if task_context:
                        task_context.record_step_result(
                            step_id=s_step.step_id,
                            result=step_final_res.result or step_final_res.error,
                            verification=step_final_res.verification,
                        )
                    self._notify_progress(plan, step_results, None, time.perf_counter() - start_time)

            if cancel_event.is_set() or sm.current_state == TaskState.CANCELLED:
                break

        # 4. Overall Plan Verification & Assessment
        overall_duration = time.perf_counter() - start_time
        all_completed = all(r.status in (StepStatus.COMPLETED, StepStatus.SUCCEEDED) for r in step_results.values())
        any_failed = any(r.status in (StepStatus.FAILED, StepStatus.BLOCKED) for r in step_results.values())

        # Collect verification results
        step_v_map = {k: v.verification for k, v in step_results.items() if v.verification}
        plan_verification = StepVerifier.verify_plan_completion(plan, step_v_map)

        if sm.current_state == TaskState.CANCELLED or cancel_event.is_set():
            if sm.current_state != TaskState.CANCELLED:
                sm.cancel(reason="Execution cancelled by cancellation signal")
        elif sm.current_state == TaskState.EXECUTING:
            sm.transition_to(TaskState.VERIFYING, reason="Verifying overall plan outcome")
            if all_completed and not any_failed and plan_verification.passed:
                sm.transition_to(TaskState.COMPLETED, reason="All plan steps executed and formally verified")
            else:
                fail_reason = (
                    f"Plan verification failed: {plan_verification.diagnostics}"
                    if not plan_verification.passed
                    else "One or more plan steps failed during execution"
                )
                sm.fail(reason=fail_reason, metadata={"failed_steps": [k for k, v in step_results.items() if v.status == StepStatus.FAILED]})

        self._notify_progress(plan, step_results, None, overall_duration, is_done=True, success=(all_completed and plan_verification.passed and sm.current_state == TaskState.COMPLETED))

        return TaskExecutionResult(
            plan_id=plan.plan_id,
            goal=plan.goal,
            success=(all_completed and plan_verification.passed and sm.current_state == TaskState.COMPLETED),
            state=sm.current_state,
            step_results=step_results,
            plan_verification=plan_verification,
            duration_seconds=overall_duration,
            error=sm.failure_reason,
        )

    def _execute_step_with_recovery(
        self,
        step: PlanStep,
        step_results: dict[str, Any],
        state_machine: ReasoningStateMachine,
        recovery_mgr: AutonomousRecoveryManager,
        task_context: Any | None,
        cancel_event: Any,
        executed_action_fingerprints: set[str],
    ) -> StepExecutionResult:
        """Execute a step with idempotency checks, formal verification, and autonomous recovery."""
        current_step_target = step
        retries_performed = 0

        while True:
            # Check cancellation inside retry loop
            if cancel_event.is_set() or state_machine.current_state == TaskState.CANCELLED:
                if state_machine.current_state != TaskState.CANCELLED:
                    state_machine.cancel(reason="Execution cancelled by cancellation signal")
                return StepExecutionResult(
                    step_id=current_step_target.step_id,
                    status=StepStatus.BLOCKED,
                    error="Execution cancelled.",
                )

            # Idempotency duplicate execution guard for state-modifying actions
            action_fp = f"{current_step_target.tool_name}:{current_step_target.parameters}"
            if current_step_target.safety_level in (SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS):
                if action_fp in executed_action_fingerprints and retries_performed == 0:
                    err_msg = f"Duplicate state-modifying action blocked by idempotency guard: {action_fp}"
                    logger.warning(err_msg)
                    return StepExecutionResult(
                        step_id=current_step_target.step_id,
                        status=StepStatus.FAILED,
                        error=err_msg,
                    )

            step_res = self._execute_step(
                current_step_target,
                step_results=step_results,
                state_machine=state_machine,
                cancel_event=cancel_event,
            )
            step_res.retries_used = retries_performed

            if current_step_target.safety_level in (SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS) and step_res.status in (StepStatus.COMPLETED, StepStatus.SUCCEEDED):
                executed_action_fingerprints.add(action_fp)

            # 3. Formal Step Verification & Visual Inspection
            if step_res.status in (StepStatus.COMPLETED, StepStatus.SUCCEEDED):
                v_res = StepVerifier.verify_step_result(current_step_target, step_res.result)
                step_res.verification = v_res
                if not v_res.passed:
                    logger.warning(f"Step '{step.step_id}' failed verification: {v_res.diagnostics}")
                    step_res.status = StepStatus.FAILED
                    step_res.error = f"Verification Failure: {v_res.diagnostics or v_res.evidence}"
                else:
                    step_res.status = StepStatus.SUCCEEDED
            else:
                v_res = VerificationResult(
                    status=VerificationStatus.FAILED,
                    criterion=step.success_criteria or "Execution Success",
                    diagnostics=step_res.error or "Step execution failed",
                )
                step_res.verification = v_res

            # 4. Failure Diagnosis & Autonomous Recovery (Only if active, not terminal or cancelled)
            if step_res.status == StepStatus.FAILED and state_machine.current_state == TaskState.EXECUTING and not state_machine.is_terminal and not cancel_event.is_set():
                diagnosis = FailureAnalyzer.diagnose(
                    step=current_step_target,
                    error_msg=step_res.error or "",
                    verification=v_res,
                    tool_fallbacks=recovery_mgr.tool_fallbacks,
                )
                logger.info(
                    f"Step '{step.step_id}' failure diagnosed as {diagnosis.failure_type.value}: "
                    f"{diagnosis.reason} (Strategy: {diagnosis.recommended_strategy.value})"
                )

                if recovery_mgr.can_recover(step.step_id, diagnosis):
                    recovered_step = recovery_mgr.record_and_generate_recovery_step(
                        current_step_target,
                        diagnosis,
                    )
                    if recovered_step:
                        retries_performed += 1
                        current_step_target = recovered_step
                        continue

            return step_res

    def _execute_step(
        self,
        step: PlanStep,
        step_results: dict[str, Any] | None = None,
        state_machine: ReasoningStateMachine | None = None,
        cancel_event: Any | None = None,
    ) -> StepExecutionResult:
        """Execute a single PlanStep using the ToolRegistry and BaseAuthorizer with state barrier."""
        step_start_time = datetime.now(timezone.utc)
        start_perf = time.perf_counter()

        # State barrier: executing tools is strictly prohibited in FAILED, CANCELLED, PAUSED, COMPLETED, VERIFYING
        if state_machine and not state_machine.can_execute_tools:
            err = f"Tool execution forbidden: Task is in state '{state_machine.current_state.value}' (tools only permitted in EXECUTING state)."
            logger.error(err)
            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.FAILED,
                error=err,
                start_time=step_start_time,
                end_time=datetime.now(timezone.utc),
                duration_seconds=time.perf_counter() - start_perf,
            )

        # If step has no tool, it's a reasoning/synthesis milestone
        if not step.tool_name:
            duration = time.perf_counter() - start_perf
            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.SUCCEEDED,
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

        # 0. Resolve dynamic parameter templates from prior step results
        resolved_params = step.parameters
        if step_results:
            results_dict = {k: (v.result if hasattr(v, "result") else v) for k, v in step_results.items()}
            resolved_params, resolve_err = DataFlowResolver.resolve_parameters(
                parameters=step.parameters,
                step_results=results_dict,
                target_safety_level=tool.safety_level,
            )
            if resolve_err:
                err = f"Parameter resolution failed for step '{step.step_id}': {resolve_err}"
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
        valid, val_err = tool.validate_arguments(resolved_params)
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
        call_id = f"call_{uuid.uuid4().hex[:8]}"
        auth_req = AuthorizationRequest(
            tool_name=step.tool_name,
            safety_level=tool.safety_level,
            arguments=resolved_params,
            tool_call_id=call_id,
            purpose=step.description,
            affected_resource=str(resolved_params.get("path", "")),
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

        # 3. Direct Tool Execution via ToolRegistry (uses ToolRegistry's shared worker pool and timeout)
        exec_kwargs: dict[str, Any] = {
            "name": step.tool_name,
            "arguments": resolved_params,
            "tool_call_id": call_id,
            "authorization": auth_resp.capability,
            "timeout": self.step_timeout_seconds,
        }
        if cancel_event is not None:
            exec_kwargs["cancellation_token"] = cancel_event

        try:
            tool_result: ToolResult = self.tools.execute(**exec_kwargs)
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
                status=StepStatus.SUCCEEDED,
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
        step_results: dict[str, StepExecutionResult],
        in_progress_id: str | None,
        elapsed_seconds: float,
        is_done: bool = False,
        success: bool = False,
    ) -> None:
        """Calculate and dispatch progress telemetry callback."""
        if not self.on_step_progress:
            return

        completed = sum(1 for r in step_results.values() if r.status in (StepStatus.COMPLETED, StepStatus.SUCCEEDED))
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

