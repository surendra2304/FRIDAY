# -*- coding: utf-8 -*-
"""Verification tests for FRIDAY's Unified Planning Architecture & Dependency-Aware Scheduling."""

import threading
import time
import pytest
from typing import List

from friday.agent.goal import Goal, GoalRequestType, GoalRiskLevel, SubGoal
from friday.agent.planner import GoalDecomposer, PlanStep, PlanValidationError, StepStatus, TaskPlan
from friday.agent.executor import TaskExecutionEngine, StepExecutionResult
from friday.agent.state import ReasoningStateMachine, TaskState
from friday.core.auth import AutoApproveAuthorizer
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class ConcurrentSafeReadTool(BaseTool):
    name = "safe_read_tool"
    description = "A safe read-only tool that sleeps briefly to simulate work"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"item_id": {"type": "string"}}}

    def __init__(self):
        super().__init__()
        self.active_threads = set()
        self.max_concurrency = 0
        self._lock = threading.Lock()

    def execute(self, item_id: str = "", **kwargs) -> ToolResult:
        t_id = threading.get_ident()
        with self._lock:
            self.active_threads.add(t_id)
            if len(self.active_threads) > self.max_concurrency:
                self.max_concurrency = len(self.active_threads)

        time.sleep(0.2)  # Simulate I/O

        with self._lock:
            self.active_threads.discard(t_id)

        return ToolResult(
            name=self.name,
            content=f"Read item {item_id}",
            is_error=False,
            safety_level=self.safety_level,
        )


class SensitiveWriteTool(BaseTool):
    name = "sensitive_write_tool"
    description = "A sensitive state-modifying action"
    safety_level = SafetyLevel.SENSITIVE
    parameters = {"type": "object", "properties": {"data": {"type": "string"}}}

    def __init__(self):
        super().__init__()
        self.active_count = 0
        self.max_concurrency = 0
        self._lock = threading.Lock()

    def execute(self, data: str = "", **kwargs) -> ToolResult:
        with self._lock:
            self.active_count += 1
            if self.active_count > self.max_concurrency:
                self.max_concurrency = self.active_count

        time.sleep(0.1)

        with self._lock:
            self.active_count -= 1

        return ToolResult(
            name=self.name,
            content=f"Written: {data}",
            is_error=False,
            safety_level=self.safety_level,
        )


# ============================================================================
# 1. Canonical Planning Flow & DAG Correctness Tests
# ============================================================================

def test_canonical_planning_flow_from_goal():
    """Verify conversion from Goal -> GoalDecomposer -> TaskPlan -> DAG validation."""
    goal = Goal(
        goal_id="goal_100",
        original_request="Analyze system and list documents",
        normalized_intent="Analyze system configuration and list files",
        desired_outcome="System analyzed and documents listed",
        request_type=GoalRequestType.MULTI_STEP_TASK,
        risk_level=GoalRiskLevel.LOW,
        subgoals=[
            SubGoal(
                subgoal_id="sg_1",
                description="Get system information",
                desired_outcome="System info retrieved",
                required_capabilities=["system_info"],
            ),
            SubGoal(
                subgoal_id="sg_2",
                description="List project files",
                desired_outcome="Files listed",
                required_capabilities=["file_listing"],
                dependencies=["sg_1"],
            ),
        ]
    )

    plan = GoalDecomposer.create_from_goal(goal)
    assert plan.goal_id == "goal_100"
    assert len(plan.steps) == 2
    assert plan.steps[0].tool_name == "get_system_info"
    assert plan.steps[1].tool_name == "list_files"
    assert plan.steps[1].depends_on == ["sg_1"]

    # Compute topological waves
    waves = plan.compute_topological_schedule()
    assert len(waves) == 2
    assert [s.step_id for s in waves[0]] == ["sg_1"]
    assert [s.step_id for s in waves[1]] == ["sg_2"]


def test_diamond_dag_wave_computation():
    """Verify diamond dependency DAG (A -> B, A -> C, B & C -> D) schedules in 3 waves."""
    plan = TaskPlan(
        goal="Diamond DAG test",
        steps=[
            PlanStep(step_id="A", description="Step A"),
            PlanStep(step_id="B", description="Step B", depends_on=["A"]),
            PlanStep(step_id="C", description="Step C", depends_on=["A"]),
            PlanStep(step_id="D", description="Step D", depends_on=["B", "C"]),
        ]
    )

    waves = plan.compute_topological_schedule()
    assert len(waves) == 3
    assert [s.step_id for s in waves[0]] == ["A"]
    assert set(s.step_id for s in waves[1]) == {"B", "C"}
    assert [s.step_id for s in waves[2]] == ["D"]


def test_cycle_detection_in_dag():
    """Verify cycle detection in TaskPlan raises PlanValidationError."""
    plan = TaskPlan(
        goal="Cyclic plan",
        steps=[
            PlanStep(step_id="A", description="Step A", depends_on=["B"]),
            PlanStep(step_id="B", description="Step B", depends_on=["A"]),
        ]
    )

    with pytest.raises(PlanValidationError):
        plan.compute_topological_schedule()


# ============================================================================
# 2. Concurrency for Independent SAFE Work Tests
# ============================================================================

def test_independent_safe_steps_execute_concurrently():
    """Verify that independent SAFE read-only steps in the same wave execute concurrently."""
    registry = ToolRegistry()
    safe_tool = ConcurrentSafeReadTool()
    registry.register(safe_tool)
    authorizer = AutoApproveAuthorizer.create_for_testing()
    engine = TaskExecutionEngine(tool_registry=registry, authorizer=authorizer, allow_concurrent_safe_steps=True)

    # 3 independent safe steps in the same initial wave
    plan = TaskPlan(
        goal="Concurrent safe reads",
        steps=[
            PlanStep(step_id="read_1", description="Read 1", tool_name="safe_read_tool", parameters={"item_id": "1"}),
            PlanStep(step_id="read_2", description="Read 2", tool_name="safe_read_tool", parameters={"item_id": "2"}),
            PlanStep(step_id="read_3", description="Read 3", tool_name="safe_read_tool", parameters={"item_id": "3"}),
        ]
    )

    start = time.perf_counter()
    res = engine.execute_plan(plan)
    elapsed = time.perf_counter() - start

    assert res.success
    assert res.state == TaskState.COMPLETED
    assert len(res.step_results) == 3

    # If executed concurrently, 3 x 0.2s sleeps should complete in ~0.25 - 0.4s, NOT 0.6s+
    assert elapsed < 0.5, f"Expected concurrent execution under 0.5s, took {elapsed:.2f}s"
    assert safe_tool.max_concurrency >= 2, f"Expected concurrency >= 2, got {safe_tool.max_concurrency}"


# ============================================================================
# 3. Serialization for Sensitive/Unsafe Work Tests
# ============================================================================

def test_sensitive_steps_remain_serialized():
    """Verify that sensitive state-changing steps in the same wave remain serialized."""
    registry = ToolRegistry()
    write_tool = SensitiveWriteTool()
    registry.register(write_tool)
    authorizer = AutoApproveAuthorizer.create_for_testing()
    engine = TaskExecutionEngine(tool_registry=registry, authorizer=authorizer, allow_concurrent_safe_steps=True)

    # 3 independent sensitive steps in the same wave
    plan = TaskPlan(
        goal="Serialized sensitive writes",
        steps=[
            PlanStep(
                step_id="write_1",
                description="Write 1",
                tool_name="sensitive_write_tool",
                parameters={"data": "A"},
                safety_level=SafetyLevel.SENSITIVE,
            ),
            PlanStep(
                step_id="write_2",
                description="Write 2",
                tool_name="sensitive_write_tool",
                parameters={"data": "B"},
                safety_level=SafetyLevel.SENSITIVE,
            ),
        ]
    )

    res = engine.execute_plan(plan)
    assert res.success
    assert write_tool.max_concurrency == 1, f"Sensitive tool executed concurrently! max_concurrency={write_tool.max_concurrency}"


# ============================================================================
# 4. Deterministic Ordering & Dependency Cascading Tests
# ============================================================================

def test_deterministic_ordering_of_results():
    """Verify results dictionary maintains original step order."""
    registry = ToolRegistry()
    safe_tool = ConcurrentSafeReadTool()
    registry.register(safe_tool)
    authorizer = AutoApproveAuthorizer.create_for_testing()
    engine = TaskExecutionEngine(tool_registry=registry, authorizer=authorizer)

    plan = TaskPlan(
        goal="Order test",
        steps=[
            PlanStep(step_id="first", description="1st", tool_name="safe_read_tool", parameters={"item_id": "1"}),
            PlanStep(step_id="second", description="2nd", tool_name="safe_read_tool", parameters={"item_id": "2"}),
            PlanStep(step_id="third", description="3rd", tool_name="safe_read_tool", parameters={"item_id": "3"}),
        ]
    )

    res = engine.execute_plan(plan)
    assert list(res.step_results.keys()) == ["first", "second", "third"]


def test_failure_cascades_and_skips_downstream_dependents():
    """Verify that when an upstream step fails, dependent steps are SKIPPED."""
    registry = ToolRegistry()
    safe_tool = ConcurrentSafeReadTool()
    registry.register(safe_tool)
    authorizer = AutoApproveAuthorizer.create_for_testing()
    engine = TaskExecutionEngine(tool_registry=registry, authorizer=authorizer)

    plan = TaskPlan(
        goal="Cascading failure test",
        steps=[
            PlanStep(
                step_id="step_fail",
                description="Fails verification",
                tool_name="safe_read_tool",
                parameters={"item_id": "1"},
                success_criteria="contains:impossible_token_value",
            ),
            PlanStep(
                step_id="step_dependent",
                description="Should be skipped",
                tool_name="safe_read_tool",
                parameters={"item_id": "2"},
                depends_on=["step_fail"],
            ),
        ]
    )

    res = engine.execute_plan(plan)
    assert not res.success
    assert res.step_results["step_fail"].status == StepStatus.FAILED
    assert res.step_results["step_dependent"].status == StepStatus.SKIPPED
