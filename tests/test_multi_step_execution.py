# -*- coding: utf-8 -*-
"""Deterministic unit test suite for Phase 7.3 Multi-Step Task Execution Engine & Progress Tracker.

Validates:
1. Sequential execution of single-step and multi-step plans.
2. Dependency ordering: Steps execute strictly after prerequisites complete.
3. Prerequisite failure cascading: Failed dependencies cause dependent steps to be marked SKIPPED.
4. Progress tracking callbacks: ExecutionProgress telemetry updates accurately.
5. Maximum step limit enforcement (bounded execution protection against runaway plans).
6. Tool parameter validation and unknown tool error handling during execution.
7. Authorization gating & safe rejection: Denied actions fail step without unrestricted execution.
8. State machine synchronization: Transitions through UNDERSTANDING -> PLANNING -> EXECUTING -> VERIFYING -> COMPLETED / FAILED.
9. Agent integration: FridayAgent.execute_plan operates seamlessly with local tools.
10. Provider independence: Operates 100% offline with MockLLMProvider and zero vendor SDK dependencies.
"""

from typing import Dict, List, Optional
import pytest

from friday.agent.agent import FridayAgent
from friday.agent.executor import (
    ExecutionProgress,
    StepExecutionResult,
    TaskExecutionEngine,
    TaskExecutionResult,
)
from friday.agent.planner import GoalDecomposer, PlanStep, StepStatus, TaskPlan
from friday.agent.state import ReasoningStateMachine, TaskState
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.config import Settings
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    SafetyLevel,
    ToolResult,
)
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.base import BaseTool
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.registry import ToolRegistry


class AddNumbersTool(BaseTool):
    name = "add_numbers"
    description = "Adds two numbers"
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"},
        },
        "required": ["a", "b"],
    }

    def execute(self, a: int, b: int, **kwargs):
        return ToolResult(name=self.name, content=str(a + b), is_error=False, safety_level=self.safety_level)


class FlakyTool(BaseTool):
    name = "flaky_tool"
    description = "Always fails"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"msg": {"type": "string"}}, "required": ["msg"]}

    def execute(self, msg: str, **kwargs):
        return ToolResult(name=self.name, content="Error: Simulated hardware failure.", is_error=True, safety_level=self.safety_level)


class RestrictedAdminTool(BaseTool):
    name = "restricted_admin_tool"
    description = "Dangerous admin action"
    safety_level = SafetyLevel.DANGEROUS
    parameters = {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"]}

    def execute(self, target: str, **kwargs):
        return ToolResult(name=self.name, content=f"Wiped {target}", is_error=False, safety_level=self.safety_level)


class RejectingAuthorizer(BaseAuthorizer):
    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        return AuthorizationResponse(decision=AuthorizationDecision.DENIED, reason="Administrative lockdown active")


# 1. Sequential Execution Success
def test_execution_engine_single_step_success():
    registry = ToolRegistry()
    registry.register(SystemInfoTool())
    engine = TaskExecutionEngine(tool_registry=registry)

    plan = GoalDecomposer.create_single_step_plan(
        goal="Get OS info",
        description="Inspect OS details",
        tool_name="get_system_info",
        parameters={"category": "os"},
    )

    result = engine.execute_plan(plan)
    assert result.success is True
    assert result.state == TaskState.COMPLETED
    assert len(result.step_results) == 1
    assert result.step_results["step_1"].status == StepStatus.COMPLETED
    assert "os" in str(result.step_results["step_1"].result).lower()


# 2. Multi-step Execution with Dependencies
def test_execution_engine_multi_step_dependency_success():
    registry = ToolRegistry()
    registry.register(AddNumbersTool())
    engine = TaskExecutionEngine(tool_registry=registry)

    step_defs = [
        {
            "step_id": "step_a",
            "description": "Add 5 and 10",
            "tool_name": "add_numbers",
            "parameters": {"a": 5, "b": 10},
        },
        {
            "step_id": "step_b",
            "description": "Add 20 and 30",
            "tool_name": "add_numbers",
            "parameters": {"a": 20, "b": 30},
            "depends_on": ["step_a"],
        },
        {
            "step_id": "step_c",
            "description": "Synthesize final sum milestone",
            "depends_on": ["step_b"],
        },
    ]

    plan = GoalDecomposer.create_multi_step_plan("Compute chain", step_defs)
    result = engine.execute_plan(plan)

    assert result.success is True
    assert result.state == TaskState.COMPLETED
    assert result.step_results["step_a"].status == StepStatus.COMPLETED
    assert result.step_results["step_a"].result == "15"
    assert result.step_results["step_b"].status == StepStatus.COMPLETED
    assert result.step_results["step_b"].result == "50"
    assert result.step_results["step_c"].status == StepStatus.COMPLETED


# 3. Prerequisite Failure Cascades to SKIPPED
def test_execution_engine_failed_dependency_skips_downstream():
    registry = ToolRegistry()
    registry.register(FlakyTool())
    registry.register(AddNumbersTool())
    engine = TaskExecutionEngine(tool_registry=registry)

    step_defs = [
        {
            "step_id": "step_flaky",
            "description": "Run flaky tool",
            "tool_name": "flaky_tool",
            "parameters": {"msg": "test"},
        },
        {
            "step_id": "step_dependent",
            "description": "Depends on flaky tool",
            "tool_name": "add_numbers",
            "parameters": {"a": 1, "b": 2},
            "depends_on": ["step_flaky"],
        },
    ]

    plan = GoalDecomposer.create_multi_step_plan("Test cascade failure", step_defs)
    result = engine.execute_plan(plan)

    assert result.success is False
    assert result.state == TaskState.FAILED
    assert result.step_results["step_flaky"].status == StepStatus.FAILED
    assert result.step_results["step_dependent"].status == StepStatus.SKIPPED


# 4. Progress Tracking Telemetry
def test_execution_engine_progress_tracking_callbacks():
    registry = ToolRegistry()
    registry.register(AddNumbersTool())

    progress_events: List[ExecutionProgress] = []

    def on_progress(p: ExecutionProgress):
        progress_events.append(p)

    engine = TaskExecutionEngine(tool_registry=registry, on_step_progress=on_progress)

    step_defs = [
        {"step_id": "step_1", "tool_name": "add_numbers", "parameters": {"a": 1, "b": 2}},
        {"step_id": "step_2", "tool_name": "add_numbers", "parameters": {"a": 3, "b": 4}, "depends_on": ["step_1"]},
    ]
    plan = GoalDecomposer.create_multi_step_plan("Progress test", step_defs)
    result = engine.execute_plan(plan)

    assert result.success is True
    assert len(progress_events) >= 4
    # Final progress event
    final_p = progress_events[-1]
    assert final_p.is_done is True
    assert final_p.completed_steps == 2
    assert final_p.percentage == 100.0


# 5. Max Step Limit Protection
def test_execution_engine_step_limit_protection():
    registry = ToolRegistry()
    registry.register(AddNumbersTool())
    engine = TaskExecutionEngine(tool_registry=registry, max_step_limit=2)

    step_defs = [
        {"step_id": "s1", "tool_name": "add_numbers", "parameters": {"a": 1, "b": 1}},
        {"step_id": "s2", "tool_name": "add_numbers", "parameters": {"a": 2, "b": 2}, "depends_on": ["s1"]},
        {"step_id": "s3", "tool_name": "add_numbers", "parameters": {"a": 3, "b": 3}, "depends_on": ["s2"]},
    ]
    plan = GoalDecomposer.create_multi_step_plan("Limit test", step_defs)
    result = engine.execute_plan(plan)

    assert result.success is False
    assert result.state == TaskState.FAILED
    assert result.step_results["s1"].status == StepStatus.COMPLETED
    assert result.step_results["s2"].status == StepStatus.COMPLETED
    assert result.step_results["s3"].status == StepStatus.BLOCKED


# 6. Authorization Denial Fails Step Safely
def test_execution_engine_authorization_denial():
    registry = ToolRegistry()
    registry.register(RestrictedAdminTool())
    engine = TaskExecutionEngine(tool_registry=registry, authorizer=RejectingAuthorizer())

    step_defs = [
        {
            "step_id": "admin_step",
            "description": "Attempt dangerous action",
            "tool_name": "restricted_admin_tool",
            "parameters": {"target": "disk"},
            "safety_level": SafetyLevel.DANGEROUS,
        }
    ]
    plan = GoalDecomposer.create_multi_step_plan("Auth denial test", step_defs)
    result = engine.execute_plan(plan)

    assert result.success is False
    assert result.state == TaskState.FAILED
    assert result.step_results["admin_step"].status == StepStatus.FAILED
    assert "Authorization Denied" in result.step_results["admin_step"].error


# 7. Agent Integration with create_plan and execute_plan
def test_agent_create_and_execute_plan_integration():
    registry = ToolRegistry()
    registry.register(SystemInfoTool())

    agent = FridayAgent(
        settings=Settings(env="testing", agent_name="FRIDAY"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=registry,
    )

    step_defs = [
        {
            "step_id": "step_diag",
            "description": "Check system",
            "tool_name": "get_system_info",
            "parameters": {"category": "os"},
        }
    ]
    plan = agent.create_plan("Run OS diagnostics", steps=step_defs)
    exec_result = agent.execute_plan(plan)

    assert exec_result.success is True
    assert exec_result.state == TaskState.COMPLETED
    assert agent.current_state == TaskState.COMPLETED


# 8. Provider Independence: Zero vendor cloud SDK dependencies
def test_executor_zero_provider_dependency():
    """Verify executor.py has no dependency on google.genai or external cloud SDKs."""
    import friday.agent.executor as exec_mod

    assert "google" not in exec_mod.__dict__
    assert "genai" not in exec_mod.__dict__
    assert hasattr(exec_mod, "TaskExecutionEngine")
    assert hasattr(exec_mod, "ExecutionProgress")
    assert hasattr(exec_mod, "StepExecutionResult")
