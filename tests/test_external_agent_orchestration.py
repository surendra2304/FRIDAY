"""Tests for multi-executor orchestration across Browser Use, mini-SWE, and native tools."""

import pytest
from friday.planning.executors import ExecutorRegistry, LLMExecutor, ToolExecutor
from friday.planning.orchestrator import JarvisOrchestrator
from friday.planning.router import ModelRouter
from friday.planning.types import TaskDataType, TaskGraph, TaskStatus, TaskStep
from friday.tools.registry import ToolRegistry
from friday.tools.builtin.calculator import CalculatorTool
from friday.integrations.browser_use.executor import BrowserUseExecutor
from friday.integrations.mini_swe.executor import MiniSWEAgentExecutor


def test_executor_registry_contains_default_specialists():
    registry = ExecutorRegistry()
    names = [e.name for e in registry.list_executors()]
    assert "browser_use" in names
    assert "mini_swe_agent" in names
    assert "vision_analyzer" in names


def test_model_router_scores_browser_and_swe_tasks():
    registry = ExecutorRegistry()
    router = ModelRouter(registry=registry)

    # Task for browser
    browser_task = TaskStep(
        id="task_b",
        description="Navigate to website and extract application deadline",
        objective="Extract web info",
        input_types=[TaskDataType.URL],
        output_type=TaskDataType.TEXT,
    )
    b_route = router.route_task(browser_task)
    assert b_route is not None
    assert b_route.primary_executor.name == "browser_use"

    # Task for SWE
    swe_task = TaskStep(
        id="task_s",
        description="Inspect repository git status and test suite failure",
        objective="Debug test failure",
        input_types=[TaskDataType.TEXT],
        output_type=TaskDataType.TEXT,
    )
    s_route = router.route_task(swe_task)
    assert s_route is not None
    assert s_route.primary_executor.name == "mini_swe_agent"


def test_orchestrator_parallel_multi_executor_pipeline():
    registry = ExecutorRegistry()
    # Add calculator tool
    calc_tool = CalculatorTool()
    registry.register(ToolExecutor(calc_tool))

    orchestrator = JarvisOrchestrator(executor_registry=registry)

    # Wave 1: Browser inspection + SWE git inspection in parallel
    t1 = TaskStep(
        id="task_1",
        description="Inspect git repository status",
        objective="Inspect repo",
        selected_executor="mini_swe_agent",
        parameters={"task_type": "inspect_repo"},
        inputs={"task_type": "inspect_repo"},
    )
    t2 = TaskStep(
        id="task_2",
        description="Calculate resource requirements",
        objective="Calculate",
        selected_executor="calculator",
        parameters={"expression": "100 * 4"},
        inputs={"expression": "100 * 4"},
    )
    # Wave 2: Synthesis dependent on both
    t3 = TaskStep(
        id="task_3",
        description="Synthesize repo status with calculated resources",
        objective="Synthesize",
        dependencies=["task_1", "task_2"],
        selected_executor="calculator",
        parameters={"expression": "400 + 50"},
        inputs={"expression": "400 + 50"},
    )

    graph = TaskGraph(goal="Inspect repo and calculate resources", tasks=[t1, t2, t3])
    executed = orchestrator.execute_graph(graph)

    assert executed.is_successful() is True
    assert executed.get_task("task_1").status == TaskStatus.COMPLETED
    assert executed.get_task("task_2").status == TaskStatus.COMPLETED
    assert executed.get_task("task_3").status == TaskStatus.COMPLETED
