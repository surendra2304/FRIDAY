"""Unit tests for ModelRouter and ExecutorRegistry."""

from friday.core.types import SafetyLevel
from friday.planning.executors import (
    BaseExecutor,
    ExecutorRegistry,
    ExecutorResult,
    LLMExecutor,
    ToolExecutor,
    VisionExecutor,
)
from friday.planning.router import ModelRouter
from friday.planning.types import TaskDataType, TaskStep
from friday.tools.builtin import CalculatorTool, ScreenSnapshotTool, SystemInfoTool


class MockSearchExecutor(BaseExecutor):
    def __init__(self):
        super().__init__(
            name="mock_search",
            capability="web_search",
            description="Searches the web for facts and information",
            input_types=[TaskDataType.TEXT],
            output_types=[TaskDataType.TEXT, TaskDataType.JSON],
            is_local=False,
            cost_profile="low",
            latency_profile="medium",
            safety_level=SafetyLevel.SAFE,
        )

    def execute(self, inputs: dict, context=None) -> ExecutorResult:
        return ExecutorResult(success=True, output="Search results for: " + str(inputs))


class MockDangerousExecutor(BaseExecutor):
    def __init__(self):
        super().__init__(
            name="format_disk",
            capability="system_format",
            description="Formats disk partition",
            safety_level=SafetyLevel.DANGEROUS,
        )

    def execute(self, inputs: dict, context=None) -> ExecutorResult:
        return ExecutorResult(success=True, output="Disk formatted")


def test_model_router_exact_match():
    reg = ExecutorRegistry()
    reg.register(ToolExecutor(CalculatorTool()))
    reg.register(ToolExecutor(SystemInfoTool()))
    reg.register(MockSearchExecutor())

    router = ModelRouter(reg)
    task = TaskStep(id="t1", description="Calculate something", tool_name="calculator")
    res = router.route_task(task)

    assert res is not None
    assert res.primary_executor.name == "calculator"
    assert res.score >= 40.0


def test_model_router_capability_and_type_scoring():
    reg = ExecutorRegistry()
    reg.register(ToolExecutor(CalculatorTool()))
    reg.register(MockSearchExecutor())
    reg.register(VisionExecutor())

    router = ModelRouter(reg)

    # Task requiring web search
    search_task = TaskStep(
        id="t1",
        description="Search the web for python release notes",
        objective="web_search",
        input_types=[TaskDataType.TEXT],
        output_type=TaskDataType.TEXT,
    )
    res = router.route_task(search_task)
    assert res is not None
    assert res.primary_executor.name == "mock_search"

    # Task requiring vision analysis
    vision_task = TaskStep(
        id="t2",
        description="Inspect image for text errors",
        objective="visual_analysis",
        input_types=[TaskDataType.SCREENSHOT],
        output_type=TaskDataType.TEXT,
    )
    res_v = router.route_task(vision_task)
    assert res_v is not None
    assert res_v.primary_executor.name == "vision_analyzer"


def test_model_router_safety_escalation():
    reg = ExecutorRegistry()
    reg.register(MockDangerousExecutor())

    router = ModelRouter(reg)
    task = TaskStep(id="t_danger", description="Format disk partition", tool_name="format_disk")
    assert task.safety_level == SafetyLevel.SAFE

    router.route_task(task)
    assert task.safety_level == SafetyLevel.DANGEROUS
    assert task.requires_confirmation is True


def test_model_router_fallback_population():
    reg = ExecutorRegistry()
    calc1 = ToolExecutor(CalculatorTool())
    calc2 = LLMExecutor(name="llm_math")
    reg.register(calc1)
    reg.register(calc2)

    router = ModelRouter(reg)
    task = TaskStep(id="t1", description="Compute mathematical expression", objective="math")
    res = router.route_task(task)

    assert res is not None
    assert task.selected_executor is not None
    assert len(task.fallback_executors) >= 1
