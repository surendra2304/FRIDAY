"""End-to-end unit tests for JarvisOrchestrator, Scheduler, and Replanner."""

import threading
from typing import Any

from friday.core.auth import BaseAuthorizer
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    SafetyLevel,
    ToolResult,
)
from friday.planning.events import TaskEventBus, TaskEventType
from friday.planning.executors import BaseExecutor, ExecutorResult
from friday.planning.orchestrator import JarvisOrchestrator
from friday.planning.types import TaskDataType, TaskGraph, TaskStatus, TaskStep
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class AddTool(BaseTool):
    name = "add_numbers"
    description = "Adds two numbers a and b"
    safety_level = SafetyLevel.SAFE

    def execute(self, a: int = 0, b: int = 0, query: str = "", **kwargs) -> Any:
        import re
        if a == 0 and b == 0 and query:
            nums = [int(n) for n in re.findall(r"\d+", query)]
            if len(nums) >= 2:
                a, b = nums[0], nums[1]
        return ToolResult(name="add_numbers", content=str(int(a) + int(b)))


class FailingExecutor(BaseExecutor):
    def __init__(self, name="failing_exec"):
        super().__init__(
            name=name,
            capability="failing_action",
            description="Always fails",
            safety_level=SafetyLevel.SAFE,
        )

    def execute(self, inputs: dict, context=None) -> ExecutorResult:
        return ExecutorResult(success=False, output=None, error="Primary executor failure")


class SuccessfulFallbackExecutor(BaseExecutor):
    def __init__(self, name="backup_exec"):
        super().__init__(
            name=name,
            capability="failing_action",
            description="Recovers successfully",
            safety_level=SafetyLevel.SAFE,
        )

    def execute(self, inputs: dict, context=None) -> ExecutorResult:
        return ExecutorResult(success=True, output="Recovered value")


class MockDenyingAuthorizer(BaseAuthorizer):
    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        return AuthorizationResponse(
            decision=AuthorizationDecision.DENIED,
            reason="Blocked by test security policy",
        )


def test_orchestrator_single_step():
    registry = ToolRegistry()
    registry.register(AddTool())

    orch = JarvisOrchestrator(tool_registry=registry)
    resp = orch.execute_goal("add_numbers with a=5 and b=10")

    assert resp.is_successful is True
    assert resp.completed_tasks >= 1
    assert "15" in resp.content


def test_orchestrator_multi_step_sequential():
    registry = ToolRegistry()
    registry.register(AddTool())

    orch = JarvisOrchestrator(tool_registry=registry)

    # Manually construct a 2-step pipeline
    t1 = TaskStep(
        id="t1",
        description="Add 10 and 20",
        selected_executor="add_numbers",
        parameters={"a": 10, "b": 20},
    )
    t2 = TaskStep(
        id="t2",
        description="Add result to 5",
        dependencies=["t1"],
        selected_executor="add_numbers",
        parameters={"a": "<t1>", "b": 5},
    )
    graph = TaskGraph(goal="Chained addition", tasks=[t1, t2])

    executed = orch.scheduler.execute_graph(graph)
    assert executed.is_successful() is True
    assert executed.get_task("t1").result == "30"
    assert executed.get_task("t2").result == "35"


def test_orchestrator_parallel_execution():
    registry = ToolRegistry()
    registry.register(AddTool())

    orch = JarvisOrchestrator(tool_registry=registry, max_concurrency=4)

    # 3 independent steps that can run concurrently in wave 0
    t1 = TaskStep(id="t1", description="Add 1+1", selected_executor="add_numbers", parameters={"a": 1, "b": 1})
    t2 = TaskStep(id="t2", description="Add 2+2", selected_executor="add_numbers", parameters={"a": 2, "b": 2})
    t3 = TaskStep(id="t3", description="Add 3+3", selected_executor="add_numbers", parameters={"a": 3, "b": 3})
    graph = TaskGraph(goal="Parallel math", tasks=[t1, t2, t3])

    executed = orch.scheduler.execute_graph(graph)
    assert executed.is_successful() is True
    assert executed.get_task("t1").result == "2"
    assert executed.get_task("t2").result == "4"
    assert executed.get_task("t3").result == "6"


def test_orchestrator_replanning_fallback():
    registry = ToolRegistry()
    orch = JarvisOrchestrator(tool_registry=registry)
    orch.registry.register(FailingExecutor("primary_failing"))
    orch.registry.register(SuccessfulFallbackExecutor("backup_executor"))

    t1 = TaskStep(
        id="t1",
        description="Run action that fails",
        selected_executor="primary_failing",
        fallback_executors=["backup_executor"],
    )
    graph = TaskGraph(goal="Recovery test", tasks=[t1])

    executed = orch.scheduler.execute_graph(graph)
    assert executed.is_successful() is True
    task = executed.get_task("t1")
    assert task.status == TaskStatus.COMPLETED
    assert task.result == "Recovered value"
    assert task.metadata.get("recovered_by_fallback") == "backup_executor"


def test_orchestrator_security_authorization_gating():
    registry = ToolRegistry()
    authorizer = MockDenyingAuthorizer()
    orch = JarvisOrchestrator(tool_registry=registry, authorizer=authorizer)

    t1 = TaskStep(
        id="t_danger",
        description="Format critical partition",
        selected_executor="llm_reasoning",
        safety_level=SafetyLevel.DANGEROUS,
    )
    graph = TaskGraph(goal="Sensitive operation", tasks=[t1])

    executed = orch.scheduler.execute_graph(graph)
    assert executed.is_successful() is False
    assert executed.get_task("t_danger").status == TaskStatus.FAILED
    assert "Security authorization denied" in executed.get_task("t_danger").error


def test_orchestrator_cancellation():
    registry = ToolRegistry()
    orch = JarvisOrchestrator(tool_registry=registry)

    cancel_token = threading.Event()
    cancel_token.set()  # Signal cancellation immediately

    t1 = TaskStep(id="t1", description="Step 1", selected_executor="llm_reasoning")
    graph = TaskGraph(goal="Cancelled goal", tasks=[t1])

    executed = orch.scheduler.execute_graph(graph, cancellation_token=cancel_token)
    assert executed.get_task("t1").status == TaskStatus.CANCELLED
