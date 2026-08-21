# -*- coding: utf-8 -*-
"""Formal State Machine, Lifecycle, and Invariant Test Suite for FRIDAY."""

import threading
import time
import pytest
from datetime import datetime, timezone

from friday.agent.state import (
    InvalidStateTransitionError,
    ReasoningStateMachine,
    TaskState,
    VALID_TRANSITIONS,
)
from friday.agent.executor import TaskExecutionEngine, StepExecutionResult
from friday.agent.planner import PlanStep, StepStatus, TaskPlan
from friday.agent.checkpoint import (
    InterruptionReason,
    TaskCheckpoint,
    TaskCheckpointStore,
)
from friday.agent.recovery import (
    AutonomousRecoveryManager,
    FailureAnalyzer,
    FailureDiagnosis,
    FailureType,
    RecoveryStrategy,
)
from friday.core.auth import AutoApproveAuthorizer
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class DummyTool(BaseTool):
    name = "dummy_action"
    description = "Test action tool"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"msg": {"type": "string"}}}

    def __init__(self):
        super().__init__()
        self.call_count = 0

    def execute(self, msg: str = "", **kwargs) -> ToolResult:
        self.call_count += 1
        return ToolResult(
            name=self.name,
            content=f"Executed: {msg}",
            is_error=False,
            safety_level=self.safety_level,
        )


class SlowTool(BaseTool):
    name = "slow_action"
    description = "Slow test action"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def __init__(self):
        super().__init__()
        self.call_count = 0

    def execute(self, **kwargs) -> ToolResult:
        self.call_count += 1
        time.sleep(0.3)
        return ToolResult(
            name=self.name,
            content="Slow execution done",
            is_error=False,
            safety_level=self.safety_level,
        )


# ============================================================================
# 1. State Transition Matrix & Invariant Tests
# ============================================================================

def test_all_valid_state_transitions():
    """Verify that every valid state transition is accepted."""
    sm = ReasoningStateMachine()
    assert sm.current_state == TaskState.NOT_STARTED
    assert not sm.is_terminal

    sm.transition_to(TaskState.UNDERSTANDING)
    assert sm.current_state == TaskState.UNDERSTANDING

    sm.transition_to(TaskState.PLANNING)
    assert sm.current_state == TaskState.PLANNING

    sm.transition_to(TaskState.EXECUTING)
    assert sm.current_state == TaskState.EXECUTING
    assert sm.can_execute_tools

    sm.transition_to(TaskState.PAUSED)
    assert sm.current_state == TaskState.PAUSED
    assert not sm.can_execute_tools

    sm.resume()
    assert sm.current_state == TaskState.EXECUTING

    sm.transition_to(TaskState.VERIFYING)
    assert sm.current_state == TaskState.VERIFYING
    assert not sm.can_execute_tools

    sm.transition_to(TaskState.COMPLETED)
    assert sm.current_state == TaskState.COMPLETED
    assert sm.is_terminal


def test_invalid_state_transitions_rejected():
    """Verify that illegal state transitions raise InvalidStateTransitionError."""
    sm = ReasoningStateMachine(initial_state=TaskState.NOT_STARTED)

    # Cannot jump directly from NOT_STARTED to COMPLETED
    with pytest.raises(InvalidStateTransitionError):
        sm.transition_to(TaskState.COMPLETED)

    # Terminal state transitions must all be rejected
    for terminal_state in [TaskState.COMPLETED, TaskState.CANCELLED, TaskState.FAILED]:
        term_sm = ReasoningStateMachine(initial_state=terminal_state)
        assert term_sm.is_terminal
        for target in TaskState:
            with pytest.raises(InvalidStateTransitionError):
                term_sm.transition_to(target)


# ============================================================================
# 2. Tool Execution Barrier Tests
# ============================================================================

def test_tool_execution_barrier_in_non_executing_states():
    """Ensure FAILED, CANCELLED, PAUSED, COMPLETED, and VERIFYING states cannot execute tools."""
    registry = ToolRegistry()
    tool = DummyTool()
    registry.register(tool)
    authorizer = AutoApproveAuthorizer.create_for_testing()
    engine = TaskExecutionEngine(tool_registry=registry, authorizer=authorizer)

    step = PlanStep(step_id="s1", description="Execute dummy action", tool_name="dummy_action", parameters={"msg": "hello"})

    blocked_states = [
        TaskState.NOT_STARTED,
        TaskState.UNDERSTANDING,
        TaskState.PLANNING,
        TaskState.PAUSED,
        TaskState.VERIFYING,
        TaskState.COMPLETED,
        TaskState.CANCELLED,
        TaskState.FAILED,
    ]

    for state in blocked_states:
        sm = ReasoningStateMachine(initial_state=state)
        res = engine._execute_step(step, state_machine=sm)
        assert res.status == StepStatus.FAILED
        assert "forbidden" in res.error.lower()
        assert tool.call_count == 0, f"Tool was executed in forbidden state {state.value}!"


def test_terminal_state_execution_attempt_blocked():
    """Ensure TaskExecutionEngine rejects executing plans on already terminal state machines."""
    registry = ToolRegistry()
    tool = DummyTool()
    registry.register(tool)
    authorizer = AutoApproveAuthorizer.create_for_testing()
    engine = TaskExecutionEngine(tool_registry=registry, authorizer=authorizer)

    plan = TaskPlan(
        goal="Test goal",
        steps=[PlanStep(step_id="s1", description="Test action step", tool_name="dummy_action", parameters={"msg": "test"})]
    )

    for terminal_state in [TaskState.COMPLETED, TaskState.CANCELLED, TaskState.FAILED]:
        sm = ReasoningStateMachine(initial_state=terminal_state)
        res = engine.execute_plan(plan, state_machine=sm)
        assert not res.success
        assert res.state == terminal_state
        assert "terminal state" in res.error.lower()
        assert tool.call_count == 0


# ============================================================================
# 3. Cancellation & Immediate Propagation Tests
# ============================================================================

def test_cancellation_propagates_and_halts_execution():
    """Verify that cancellation stops execution of subsequent steps immediately."""
    registry = ToolRegistry()
    tool = DummyTool()
    registry.register(tool)
    authorizer = AutoApproveAuthorizer.create_for_testing()
    engine = TaskExecutionEngine(tool_registry=registry, authorizer=authorizer)

    plan = TaskPlan(
        goal="Multi-step test",
        steps=[
            PlanStep(step_id="s1", description="Step 1", tool_name="dummy_action", parameters={"msg": "1"}),
            PlanStep(step_id="s2", description="Step 2", tool_name="dummy_action", parameters={"msg": "2"}),
            PlanStep(step_id="s3", description="Step 3", tool_name="dummy_action", parameters={"msg": "3"}),
        ]
    )

    sm = ReasoningStateMachine()
    cancel_event = threading.Event()
    cancel_event.set()  # Cancel prior to execution start

    res = engine.execute_plan(plan, state_machine=sm, cancellation_token=cancel_event)
    assert not res.success
    assert res.state == TaskState.CANCELLED
    assert tool.call_count == 0


def test_concurrent_cancellation_during_execution():
    """Verify that triggering engine.cancel() during execution stops subsequent steps."""
    registry = ToolRegistry()
    slow_tool = SlowTool()
    dummy_tool = DummyTool()
    registry.register(slow_tool)
    registry.register(dummy_tool)
    authorizer = AutoApproveAuthorizer.create_for_testing()
    engine = TaskExecutionEngine(tool_registry=registry, authorizer=authorizer)

    plan = TaskPlan(
        goal="Async cancel test",
        steps=[
            PlanStep(step_id="s1", description="Slow step", tool_name="slow_action"),
            PlanStep(step_id="s2", description="Dummy step", tool_name="dummy_action", parameters={"msg": "should not run"}, depends_on=["s1"]),
        ]
    )

    sm = ReasoningStateMachine()

    # Cancel the engine after 100ms
    def _cancel_after_delay():
        time.sleep(0.1)
        engine.cancel(reason="User abort")

    cancel_thread = threading.Thread(target=_cancel_after_delay)
    cancel_thread.start()

    res = engine.execute_plan(plan, state_machine=sm)
    cancel_thread.join()

    assert not res.success
    assert res.state == TaskState.CANCELLED
    assert dummy_tool.call_count == 0


# ============================================================================
# 4. Failure, Verification & Autonomous Recovery Tests
# ============================================================================

def test_failure_during_verification_transitions_to_failed():
    """Verify that a plan step failing verification transitions plan to FAILED."""
    registry = ToolRegistry()
    tool = DummyTool()
    registry.register(tool)
    authorizer = AutoApproveAuthorizer.create_for_testing()
    engine = TaskExecutionEngine(tool_registry=registry, authorizer=authorizer)

    plan = TaskPlan(
        goal="Verification failure test",
        steps=[
            PlanStep(
                step_id="s1",
                description="Step with impossible criteria",
                tool_name="dummy_action",
                parameters={"msg": "hello"},
                success_criteria="contains:expected_secret_token",
            )
        ]
    )

    sm = ReasoningStateMachine()
    res = engine.execute_plan(plan, state_machine=sm)
    assert not res.success
    assert res.state == TaskState.FAILED
    assert "verification" in sm.failure_reason.lower() or "failed" in sm.failure_reason.lower()


def test_recovery_barrier_after_cancellation_or_terminal():
    """Verify recovery does not attempt to execute on cancelled tasks."""
    recovery_mgr = AutonomousRecoveryManager(max_retries_per_step=2)
    diagnosis = FailureDiagnosis(
        failure_type=FailureType.TOOL_ERROR,
        is_recoverable=True,
        recommended_strategy=RecoveryStrategy.RETRY,
        reason="Network blip",
        diagnostics="Timeout",
    )

    step = PlanStep(step_id="s1", description="Step 1", tool_name="dummy_action")
    # First recovery allowed
    recovered = recovery_mgr.record_and_generate_recovery_step(step, diagnosis)
    assert recovered is not None

    # Exhaust budget
    recovered2 = recovery_mgr.record_and_generate_recovery_step(step, diagnosis)
    assert recovered2 is not None

    # Third retry blocked by budget
    recovered3 = recovery_mgr.record_and_generate_recovery_step(step, diagnosis)
    assert recovered3 is None


# ============================================================================
# 5. Checkpoints & Resumption Tests
# ============================================================================

def test_resume_after_crash_from_checkpoint(tmp_path):
    """Verify state checkpoint save and resume restores step progress."""
    db_file = str(tmp_path / "checkpoint_test.db")
    store = TaskCheckpointStore(db_path=db_file)

    plan = TaskPlan(
        goal="Checkpoint recovery test",
        plan_id="task_123",
        steps=[
            PlanStep(step_id="s1", description="Step 1", tool_name="dummy_action", status=StepStatus.COMPLETED, result="Done 1"),
            PlanStep(step_id="s2", description="Step 2", tool_name="dummy_action", status=StepStatus.PENDING),
        ]
    )

    store.save_checkpoint(
        task_id="task_123",
        goal=plan.goal,
        plan=plan,
        state=TaskState.PAUSED,
        active_step_id="s2",
        step_results={"s1": "Done 1"},
        environment_hash="env_hash_v1",
        interruption_reason=InterruptionReason.APPLICATION_SHUTDOWN,
    )

    restored = store.get_latest_checkpoint("task_123")
    assert restored is not None
    assert restored.task_id == "task_123"
    assert restored.state == TaskState.PAUSED
    assert "s1" in restored.completed_steps
    assert "s2" in restored.pending_steps

    # Validate resumption with same environment
    valid_res = store.validate_resumption(restored, current_environment_hash="env_hash_v1")
    assert valid_res["can_resume"] is True
    assert valid_res["environment_valid"] is True
    assert valid_res["requires_replan"] is False


def test_resume_after_stale_environment(tmp_path):
    """Verify checkpoint store detects environment mismatch and requires replan."""
    db_file = str(tmp_path / "stale_env_test.db")
    store = TaskCheckpointStore(db_path=db_file)

    plan = TaskPlan(goal="Stale test", plan_id="task_stale")
    chk = store.save_checkpoint(
        task_id="task_stale",
        goal=plan.goal,
        plan=plan,
        state=TaskState.PAUSED,
        active_step_id=None,
        step_results={},
        environment_hash="screen_hash_123",
    )

    resumption = store.validate_resumption(chk, current_environment_hash="screen_hash_changed_456")
    assert resumption["environment_valid"] is False
    assert resumption["requires_replan"] is True


# ============================================================================
# 6. Secret Sanitization in State Persistence
# ============================================================================

def test_failure_reason_and_metadata_sanitization():
    """Verify secrets in failure reason and metadata are scrubbed before persistence."""
    sm = ReasoningStateMachine()
    sm.transition_to(TaskState.UNDERSTANDING)
    sm.transition_to(TaskState.PLANNING)
    sm.transition_to(TaskState.EXECUTING)

    secret_key = "AIzaSy" + "A" * 33
    sm.fail(
        reason=f"Crash with credential {secret_key}",
        metadata={"token": "sk-proj-" + "b" * 25, "safe_detail": "disk_full"}
    )

    assert secret_key not in sm.failure_reason
    assert "[REDACTED_SECRET]" in sm.failure_reason
    assert sm.failure_metadata["token"] == "[REDACTED_SECRET]"
    assert sm.failure_metadata["safe_detail"] == "disk_full"

    state_dict = sm.to_dict()
    assert secret_key not in str(state_dict)
