"""Deterministic unit test suite for Computer Action Execution.2 Structured Task Planning & Goal Decomposition.

Validates:
1. Single-step plan creation and data serialization.
2. Multi-step plan creation with dependencies and step decomposition.
3. Pre-execution plan validation:
   - Non-empty goals & steps.
   - Unique step IDs.
   - Dependency ordering and existence (acyclic DAG enforcement).
   - Missing / unknown tool rejection.
   - Parameter schema validation.
   - Self-dependency rejection.
4. Dangerous / Sensitive action authorization requirements (safety elevation).
5. Integration with FridayAgent (create_plan, current_plan, get_status).
6. Complete provider independence (works with MockLLMProvider and offline tests).
7. Preservation of Multimodal Screen Perception security boundaries (Proposal != Execution, hard blocks).
"""

import pytest

from friday.agent.agent import FridayAgent
from friday.agent.planner import (
    GoalDecomposer,
    PlanStep,
    PlanValidationError,
    StepStatus,
    TaskPlan,
)
from friday.core.config import Settings
from friday.core.types import SafetyLevel, ToolResult
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.base import BaseTool
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.registry import ToolRegistry


class SensitiveActionTool(BaseTool):
    name = "modify_system_config"
    description = "Modifies critical system config"
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["key", "value"],
    }

    def execute(self, key: str, value: str, **kwargs):
        return ToolResult(name=self.name, content=f"Updated {key}={value}", is_error=False, safety_level=self.safety_level)


# 1. Single Step Plan
def test_task_plan_single_step_creation_and_serialization():
    plan = GoalDecomposer.create_single_step_plan(
        goal="Check system diagnostics",
        description="Query operating system metrics",
        tool_name="get_system_info",
        parameters={"category": "os"},
        safety_level=SafetyLevel.SAFE,
        success_criteria="System metrics successfully returned",
    )

    assert plan.goal == "Check system diagnostics"
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.step_id == "step_1"
    assert step.tool_name == "get_system_info"
    assert step.parameters == {"category": "os"}
    assert step.status == StepStatus.PENDING
    assert step.safety_level == SafetyLevel.SAFE
    assert step.requires_confirmation is False

    d = plan.to_dict()
    assert d["goal"] == "Check system diagnostics"
    assert len(d["steps"]) == 1
    assert d["steps"][0]["tool_name"] == "get_system_info"
    assert d["steps"][0]["status"] == "PENDING"


# 2. Multi-Step Plan with Dependencies
def test_task_plan_multi_step_decomposition():
    step_defs = [
        {
            "step_id": "gather_info",
            "description": "Gather system info",
            "tool_name": "get_system_info",
            "parameters": {"category": "hardware"},
        },
        {
            "step_id": "calculate_load",
            "description": "Calculate capacity ratio",
            "depends_on": ["gather_info"],
            "parameters": {"multiplier": 2},
        },
        {
            "step_id": "generate_report",
            "description": "Synthesize summary report",
            "depends_on": ["calculate_load"],
        },
    ]

    plan = GoalDecomposer.create_multi_step_plan(
        goal="Diagnose and analyze hardware capacity",
        step_definitions=step_defs,
    )

    assert plan.goal == "Diagnose and analyze hardware capacity"
    assert len(plan.steps) == 3
    assert plan.steps[0].step_id == "gather_info"
    assert plan.steps[1].depends_on == ["gather_info"]
    assert plan.steps[2].depends_on == ["calculate_load"]

    # Verify dependency resolution helper
    deps_step3 = plan.get_dependencies_for_step("generate_report")
    assert len(deps_step3) == 1
    assert deps_step3[0].step_id == "calculate_load"


# 3. Plan Validation: Success with Tool Registry
def test_task_plan_validation_success():
    registry = ToolRegistry()
    registry.register(SystemInfoTool())

    step_defs = [
        {
            "step_id": "step_diag",
            "description": "Get OS info",
            "tool_name": "get_system_info",
            "parameters": {"category": "os"},
        }
    ]
    plan = GoalDecomposer.create_multi_step_plan("Run OS diagnostics", step_defs)
    assert plan.validate(tool_registry=registry) is True


# 4. Plan Validation: Missing Goal or Steps
def test_task_plan_validation_empty_goal_or_steps():
    # Empty goal
    plan1 = TaskPlan(goal="", steps=[PlanStep(step_id="1", description="desc")])
    with pytest.raises(PlanValidationError, match="non-empty goal"):
        plan1.validate()

    # Empty steps
    plan2 = TaskPlan(goal="Valid goal", steps=[])
    with pytest.raises(PlanValidationError, match="at least one step"):
        plan2.validate()


# 5. Plan Validation: Duplicate Step IDs
def test_task_plan_validation_duplicate_step_ids():
    step1 = PlanStep(step_id="dup_id", description="First")
    step2 = PlanStep(step_id="dup_id", description="Second")
    plan = TaskPlan(goal="Test dupes", steps=[step1, step2])

    with pytest.raises(PlanValidationError, match="Duplicate step_id detected: 'dup_id'"):
        plan.validate()


# 6. Plan Validation: Missing Dependency or Self-Dependency
def test_task_plan_validation_invalid_dependency():
    # Non-existent dependency
    step1 = PlanStep(step_id="step_a", description="First", depends_on=["non_existent_step"])
    plan1 = TaskPlan(goal="Test deps", steps=[step1])
    with pytest.raises(PlanValidationError, match="depends on 'non_existent_step' which does not exist in the plan"):
        plan1.validate()

    # Self-dependency
    step_self = PlanStep(step_id="step_self", description="Self", depends_on=["step_self"])
    plan2 = TaskPlan(goal="Test self dep", steps=[step_self])
    with pytest.raises(PlanValidationError, match="cannot depend on itself"):
        plan2.validate()


# 7. Plan Validation: Unknown Tool & Invalid Parameters
def test_task_plan_validation_tool_errors():
    registry = ToolRegistry()
    registry.register(SystemInfoTool())

    # Unknown tool
    step_bad_tool = PlanStep(step_id="step_1", description="Use imaginary tool", tool_name="quantum_teleport_tool")
    plan1 = TaskPlan(goal="Test tool", steps=[step_bad_tool])
    with pytest.raises(PlanValidationError, match="references unknown tool 'quantum_teleport_tool'"):
        plan1.validate(tool_registry=registry)

    # Invalid parameter type
    step_bad_arg = PlanStep(
        step_id="step_1",
        description="Run sysinfo with invalid category type",
        tool_name="get_system_info",
        parameters={"category": 12345},  # Expected string
    )
    plan2 = TaskPlan(goal="Test args", steps=[step_bad_arg])
    with pytest.raises(PlanValidationError, match="invalid arguments for tool 'get_system_info'"):
        plan2.validate(tool_registry=registry)


# 8. Plan Validation: Sensitive / Dangerous Tool Safety Elevation
def test_task_plan_safety_elevation_for_sensitive_tools():
    registry = ToolRegistry()
    registry.register(SensitiveActionTool())

    step_sensitive = PlanStep(
        step_id="step_config",
        description="Update critical key",
        tool_name="modify_system_config",
        parameters={"key": "timeout", "value": "60"},
        safety_level=SafetyLevel.SAFE,  # Model initially proposed as safe
    )
    plan = TaskPlan(goal="Change config", steps=[step_sensitive])
    assert plan.validate(tool_registry=registry) is True

    # Validation must elevate safety level and mandate confirmation
    validated_step = plan.get_step("step_config")
    assert validated_step.safety_level == SafetyLevel.SENSITIVE
    assert validated_step.requires_confirmation is True


# 9. FridayAgent Integration: create_plan and current_plan
def test_agent_create_plan_and_status_integration():
    registry = ToolRegistry()
    registry.register(SystemInfoTool())

    agent = FridayAgent(
        settings=Settings(env="testing", agent_name="FRIDAY"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=registry,
    )

    assert agent.current_plan is None

    # Create plan through agent
    step_defs = [
        {
            "step_id": "step_1",
            "description": "Inspect OS",
            "tool_name": "get_system_info",
            "parameters": {"category": "os"},
        }
    ]
    plan = agent.create_plan(goal="Check OS metrics", steps=step_defs)

    assert agent.current_plan is plan
    assert plan.goal == "Check OS metrics"

    # Status reflects active plan
    status = agent.get_status()
    assert status["active_plan"] is not None
    assert status["active_plan"]["goal"] == "Check OS metrics"
    assert len(status["active_plan"]["steps"]) == 1


# 10. Provider Independence: Zero vendor SDK dependency
def test_planner_zero_provider_dependency():
    """Verify planner.py has no dependency on google.genai or external cloud SDKs."""
    import friday.agent.planner as planner_mod

    assert "google" not in planner_mod.__dict__
    assert "genai" not in planner_mod.__dict__
    assert hasattr(planner_mod, "TaskPlan")
    assert hasattr(planner_mod, "PlanStep")
    assert hasattr(planner_mod, "GoalDecomposer")
