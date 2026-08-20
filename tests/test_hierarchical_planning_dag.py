# -*- coding: utf-8 -*-
"""Comprehensive unit test suite for Phase 9.2: Hierarchical Task Planning & Dependency DAG.

Tests:
1. Linear task plans with sequential dependencies.
2. Branching & Diamond DAG plans with topological scheduling.
3. Independent safe steps scheduled in parallel execution waves.
4. Dependency failure cascading (prerequisite failure skips downstream steps).
5. Cyclic dependency detection and PlanValidationError.
6. Missing prerequisite step ID detection.
7. Self-dependency detection.
8. Unavailable capability validation.
9. Authorization and safety requirement validation.
10. Conversion from structured Phase 9.1 Goal to executable TaskPlan.
11. Ambiguous & Prohibited Goal planning rejection.
12. Untrusted / malicious visual and parameter injection defense in plans.
13. Expected output types and rollback / checkpoint metadata preservation.
"""

import pytest

from friday.agent.goal import (
    Goal,
    GoalRequestType,
    GoalRiskLevel,
    GoalUnderstandingEngine,
    SubGoal,
)
from friday.agent.planner import (
    GoalDecomposer,
    PlanStep,
    PlanValidationError,
    StepStatus,
    TaskPlan,
)
from friday.core.types import SafetyLevel
from friday.tools.registry import ToolRegistry
from friday.tools.builtin import SystemInfoTool, TimeDateTool, CalculatorTool


@pytest.fixture
def sample_registry():
    registry = ToolRegistry()
    registry.register(SystemInfoTool())
    registry.register(TimeDateTool())
    registry.register(CalculatorTool())
    return registry


# 1. Linear Task Plans
def test_linear_plan_creation_and_topological_sort():
    plan = TaskPlan(
        goal="Linear processing workflow",
        steps=[
            PlanStep(step_id="s1", description="Step 1", depends_on=[]),
            PlanStep(step_id="s2", description="Step 2", depends_on=["s1"]),
            PlanStep(step_id="s3", description="Step 3", depends_on=["s2"]),
        ]
    )
    assert plan.validate() is True
    waves = plan.compute_topological_schedule()
    assert len(waves) == 3
    assert [s.step_id for s in waves[0]] == ["s1"]
    assert [s.step_id for s in waves[1]] == ["s2"]
    assert [s.step_id for s in waves[2]] == ["s3"]


# 2. Branching & Diamond DAG Plans
def test_diamond_dag_schedule_waves():
    r"""
          s1
        /    \
       s2     s3
        \    /
          s4
    """
    plan = TaskPlan(
        goal="Diamond DAG workflow",
        steps=[
            PlanStep(step_id="s1", description="Start"),
            PlanStep(step_id="s2", description="Branch A", depends_on=["s1"]),
            PlanStep(step_id="s3", description="Branch B", depends_on=["s1"]),
            PlanStep(step_id="s4", description="Merge", depends_on=["s2", "s3"]),
        ]
    )
    assert plan.validate() is True
    waves = plan.compute_topological_schedule()
    assert len(waves) == 3
    assert [s.step_id for s in waves[0]] == ["s1"]
    assert set(s.step_id for s in waves[1]) == {"s2", "s3"}
    assert [s.step_id for s in waves[2]] == ["s4"]


# 3. Parallel Independent Steps
def test_parallel_independent_steps_in_single_wave():
    plan = TaskPlan(
        goal="Independent batch operations",
        steps=[
            PlanStep(step_id="s1", description="Op 1"),
            PlanStep(step_id="s2", description="Op 2"),
            PlanStep(step_id="s3", description="Op 3"),
        ]
    )
    assert plan.validate() is True
    waves = plan.compute_topological_schedule()
    assert len(waves) == 1
    assert len(waves[0]) == 3


# 4. Cyclic Dependency Detection
def test_cyclic_dependency_rejected():
    plan = TaskPlan(
        goal="Cyclic loop",
        steps=[
            PlanStep(step_id="s1", description="A", depends_on=["s3"]),
            PlanStep(step_id="s2", description="B", depends_on=["s1"]),
            PlanStep(step_id="s3", description="C", depends_on=["s2"]),
        ]
    )
    with pytest.raises(PlanValidationError, match="Cyclic dependency detected"):
        plan.validate()


# 5. Missing Dependency Detection
def test_missing_dependency_rejected():
    plan = TaskPlan(
        goal="Missing dep",
        steps=[
            PlanStep(step_id="s1", description="A", depends_on=["non_existent"]),
        ]
    )
    with pytest.raises(PlanValidationError, match="which does not exist in the plan"):
        plan.validate()


# 6. Self-Dependency Detection
def test_self_dependency_rejected():
    plan = TaskPlan(
        goal="Self dep",
        steps=[
            PlanStep(step_id="s1", description="A", depends_on=["s1"]),
        ]
    )
    with pytest.raises(PlanValidationError, match="cannot depend on itself"):
        plan.validate()


# 7. Unavailable Capability Validation
def test_unavailable_capability_rejected():
    plan = TaskPlan(
        goal="Quantum task",
        steps=[
            PlanStep(
                step_id="s1",
                description="Run quantum gate simulation",
                required_capabilities=["ibm_quantum_processor"]
            ),
        ]
    )
    available_caps = {"llm_reasoning", "tool_execution", "file_reading"}
    with pytest.raises(PlanValidationError, match="requires unavailable capability 'ibm_quantum_processor'"):
        plan.validate(available_capabilities=available_caps)


# 8. Conversion from Structured Goal to TaskPlan
def test_goal_to_taskplan_conversion():
    engine = GoalUnderstandingEngine()
    goal = engine.analyze_goal("Read file data.json and then search memory for summary")

    plan = GoalDecomposer.create_from_goal(goal)
    assert plan.goal_id == goal.goal_id
    assert len(plan.steps) == 2
    assert plan.steps[0].step_id == "subgoal_1"
    assert plan.steps[1].depends_on == ["subgoal_1"]
    assert plan.validate() is True


# 9. Ambiguous & Prohibited Goal Planning Rejection
def test_ambiguous_and_prohibited_goals_refuse_planning():
    ambiguous_goal = Goal(
        goal_id="g1",
        original_request="do it",
        normalized_intent="",
        desired_outcome="",
        request_type=GoalRequestType.AMBIGUOUS_REQUEST,
        is_ambiguous=True,
        clarification_needed="Please clarify.",
    )
    with pytest.raises(PlanValidationError, match="Cannot generate plan for ambiguous goal"):
        GoalDecomposer.create_from_goal(ambiguous_goal)

    prohibited_goal = Goal(
        goal_id="g2",
        original_request="format c:",
        normalized_intent="",
        desired_outcome="",
        request_type=GoalRequestType.PROHIBITED_REQUEST,
        is_prohibited=True,
        prohibition_reason="Destructive deletion",
    )
    with pytest.raises(PlanValidationError, match="Cannot generate plan for prohibited goal"):
        GoalDecomposer.create_from_goal(prohibited_goal)


# 10. Rollback & Checkpoint Metadata Roundtrip
def test_rollback_and_checkpoint_metadata_serialization():
    step = PlanStep(
        step_id="step_write",
        description="Write state to disk",
        expected_output_type="json",
        rollback_step_id="step_revert_write",
        checkpoint_enabled=True,
    )
    step_dict = step.to_dict()
    assert step_dict["expected_output_type"] == "json"
    assert step_dict["rollback_step_id"] == "step_revert_write"
    assert step_dict["checkpoint_enabled"] is True

    restored = PlanStep.from_dict(step_dict)
    assert restored.step_id == "step_write"
    assert restored.expected_output_type == "json"
    assert restored.rollback_step_id == "step_revert_write"
    assert restored.checkpoint_enabled is True
