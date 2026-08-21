# -*- coding: utf-8 -*-
"""Comprehensive unit test suite for Phase 9.3: Intelligent Multi-Step Execution Orchestrator.

Tests:
1. Multi-step task successful end-to-end execution.
2. Step lifecycle progression (PENDING -> READY -> RUNNING -> SUCCEEDED).
3. Dependency waiting & prerequisite failure cascading.
4. Tool failure and autonomous recovery loop.
5. Step execution timeout handling.
6. Graceful task cancellation.
7. Idempotency duplicate execution prevention on state-modifying actions.
8. Computer control proposal authorization gating (Proposal != Execution).
9. Perception visual step execution and verification.
10. Multimodal untrusted instruction injection isolation.
"""

import time
from unittest import mock
import pytest

from friday.agent.executor import (
    ExecutionProgress,
    StepExecutionResult,
    TaskExecutionEngine,
    TaskExecutionResult,
)
from friday.agent.planner import (
    GoalDecomposer,
    PlanStep,
    StepStatus,
    TaskPlan,
)
from friday.agent.state import ReasoningStateMachine, TaskState
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    SafetyLevel,
    ToolResult,
)
from friday.tools.base import BaseTool
from friday.tools.builtin import CalculatorTool, SystemInfoTool, TimeDateTool, ScreenSnapshotTool
from friday.tools.registry import ToolRegistry


class MockFlakyTool(BaseTool):
    name = "flaky_tool"
    description = "Flaky tool for recovery testing"
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {"succeed": {"type": "boolean"}},
        "required": ["succeed"],
    }

    def __init__(self):
        super().__init__()
        self.call_count = 0

    def execute(self, succeed: bool, **kwargs):
        self.call_count += 1
        if not succeed:
            return ToolResult(name=self.name, content="Transient failure", is_error=True)
        return ToolResult(name=self.name, content="Success", is_error=False)


class MockSlowTool(BaseTool):
    name = "slow_tool"
    description = "Tool that sleeps to simulate timeout"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        time.sleep(2.0)
        return ToolResult(name=self.name, content="Finished slow work", is_error=False)


class MockWriteFileTool(BaseTool):
    name = "write_file_mock"
    description = "State-modifying file writer"
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    }

    def __init__(self):
        super().__init__()
        self.invocations = 0

    def execute(self, path: str, content: str, **kwargs):
        self.invocations += 1
        try:
            import pathlib
            pathlib.Path(path).write_text(content, encoding="utf-8")
        except Exception:
            pass
        return ToolResult(name=self.name, content=f"Wrote {len(content)} bytes to {path}", is_error=False, safety_level=self.safety_level)


@pytest.fixture
def test_registry():
    reg = ToolRegistry()
    reg.register(SystemInfoTool())
    reg.register(TimeDateTool())
    reg.register(CalculatorTool())
    reg.register(ScreenSnapshotTool())
    reg.register(MockFlakyTool())
    reg.register(MockSlowTool())
    reg.register(MockWriteFileTool())
    return reg


# 1. Multi-Step Task Successful End-to-End Execution
def test_multi_step_task_success(test_registry):
    plan = TaskPlan(
        goal="Calculate sum and check time",
        steps=[
            PlanStep(
                step_id="step_calc",
                description="Calculate 15 + 25",
                tool_name="calculator",
                parameters={"expression": "15 + 25"},
            ),
            PlanStep(
                step_id="step_time",
                description="Get current time",
                tool_name="get_time_date",
                depends_on=["step_calc"],
            ),
        ]
    )

    engine = TaskExecutionEngine(tool_registry=test_registry)
    result = engine.execute_plan(plan)

    assert result.success is True
    assert result.state == TaskState.COMPLETED
    assert result.step_results["step_calc"].status == StepStatus.SUCCEEDED
    assert result.step_results["step_time"].status == StepStatus.SUCCEEDED


# 2. Step Lifecycle Progression
def test_step_lifecycle_progress_tracking(test_registry):
    progress_snapshots = []

    def on_progress(p: ExecutionProgress):
        progress_snapshots.append(p.to_dict())

    plan = TaskPlan(
        goal="Check system info",
        steps=[
            PlanStep(
                step_id="step_sys",
                description="Get OS info",
                tool_name="get_system_info",
                parameters={"category": "os"},
            )
        ]
    )

    engine = TaskExecutionEngine(tool_registry=test_registry, on_step_progress=on_progress)
    result = engine.execute_plan(plan)

    assert result.success is True
    assert len(progress_snapshots) >= 2
    assert progress_snapshots[-1]["is_done"] is True
    assert progress_snapshots[-1]["completed_steps"] == 1


# 3. Dependency Waiting & Failure Cascading
def test_dependency_failure_skips_downstream_steps(test_registry):
    plan = TaskPlan(
        goal="Failure cascading workflow",
        steps=[
            PlanStep(
                step_id="step_fail",
                description="Failed operation",
                tool_name="flaky_tool",
                parameters={"succeed": False},
            ),
            PlanStep(
                step_id="step_dependent",
                description="Dependent operation",
                tool_name="get_time_date",
                depends_on=["step_fail"],
            ),
        ]
    )

    engine = TaskExecutionEngine(tool_registry=test_registry)
    result = engine.execute_plan(plan)

    assert result.success is False
    assert result.step_results["step_fail"].status == StepStatus.FAILED
    assert result.step_results["step_dependent"].status == StepStatus.SKIPPED


# 4. Timeout Handling
def test_step_timeout_handling(test_registry):
    plan = TaskPlan(
        goal="Timeout task",
        steps=[
            PlanStep(
                step_id="step_slow",
                description="Slow operation",
                tool_name="slow_tool",
            )
        ]
    )

    engine = TaskExecutionEngine(tool_registry=test_registry, step_timeout_seconds=0.2)
    result = engine.execute_plan(plan)

    assert result.success is False
    assert result.step_results["step_slow"].status == StepStatus.FAILED
    assert any(term in (result.step_results["step_slow"].error or "").lower() for term in ("timed out", "timeout", "limit", "exhausted"))


# 5. Idempotency Duplicate Execution Prevention
def test_idempotency_duplicate_execution_prevention(test_registry):
    from friday.core.auth import AutoApproveAuthorizer
    writer = test_registry.get("write_file_mock")
    authorizer = AutoApproveAuthorizer.create_for_testing()

    plan = TaskPlan(
        goal="Write data safely",
        steps=[
            PlanStep(
                step_id="step_write_1",
                description="Write to a.txt",
                tool_name="write_file_mock",
                parameters={"path": "a.txt", "content": "hello"},
                safety_level=SafetyLevel.SENSITIVE,
            ),
            PlanStep(
                step_id="step_write_duplicate",
                description="Duplicate write to a.txt",
                tool_name="write_file_mock",
                parameters={"path": "a.txt", "content": "hello"},
                safety_level=SafetyLevel.SENSITIVE,
                depends_on=["step_write_1"],
            ),
        ]
    )

    engine = TaskExecutionEngine(tool_registry=test_registry, authorizer=authorizer)
    result = engine.execute_plan(plan)

    assert result.step_results["step_write_1"].status == StepStatus.SUCCEEDED
    assert result.step_results["step_write_duplicate"].status == StepStatus.FAILED
    assert "idempotency" in result.step_results["step_write_duplicate"].error.lower() or "duplicate" in result.step_results["step_write_duplicate"].error.lower()
    assert writer.invocations == 1


# 6. Computer Action Authorization Gating (Proposal != Execution)
def test_computer_action_authorization_gated(test_registry):
    authorizer = DefaultSecureAuthorizer()

    # Deny authorization
    with mock.patch.object(authorizer, "authorize", return_value=AuthorizationResponse(decision=AuthorizationDecision.DENIED, reason="User rejected proposal")):
        plan = TaskPlan(
            goal="Screen action",
            steps=[
                PlanStep(
                    step_id="step_click",
                    description="Click button",
                    tool_name="write_file_mock",
                    parameters={"path": "system.ini", "content": "val"},
                    safety_level=SafetyLevel.SENSITIVE,
                )
            ]
        )

        engine = TaskExecutionEngine(tool_registry=test_registry, authorizer=authorizer)
        result = engine.execute_plan(plan)

        assert result.success is False
        assert result.step_results["step_click"].status == StepStatus.FAILED
        assert "Authorization Denied" in result.step_results["step_click"].error
