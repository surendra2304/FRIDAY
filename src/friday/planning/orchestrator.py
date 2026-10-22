"""Central HuggingGPT-Style Orchestrator for FRIDAY.

Brings together:
1. Dynamic Task Planning (Decomposition into DAG)
2. Model & Executor Routing (Selection based on capabilities, modality, cost)
3. Concurrent Topological Execution (Parallel wave execution & data passing)
4. Dynamic Replanning (Failure diagnosis, retries, fallback executors, sub-graph repair)
5. Result Synthesis (Multimodal consolidation into human-friendly answer)
"""

from __future__ import annotations

import threading
import re
from typing import Any

from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.types import Message, Role, ToolCall, ToolResult
from friday.core.logging import get_logger
from friday.planning.events import TaskEventBus, global_task_event_bus
from friday.planning.executors import (
    ExecutorRegistry,
    LLMExecutor,
    VisionExecutor,
)
from friday.planning.planner import DynamicTaskPlanner
from friday.planning.replanner import DynamicReplanner
from friday.planning.router import ModelRouter
from friday.planning.scheduler import TaskGraphScheduler
from friday.planning.synthesizer import ResultSynthesizer, SynthesizedResponse
from friday.planning.types import TaskGraph
from friday.tools.registry import ToolRegistry

logger = get_logger("planning.orchestrator")


class FridayOrchestrator:
    """Unified controller orchestrating Microsoft HuggingGPT capabilities natively inside FRIDAY."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
        executor_registry: ExecutorRegistry | None = None,
        llm_provider: Any = None,
        authorizer: BaseAuthorizer | None = None,
        max_concurrency: int = 5,
        default_timeout_seconds: float = 60.0,
        event_bus: TaskEventBus | None = None,
    ) -> None:
        self.event_bus = event_bus or global_task_event_bus
        self.llm = llm_provider
        self.authorizer = authorizer or DefaultSecureAuthorizer()

        # 1. Initialize Executor Registry & Catalog
        self.registry = executor_registry or ExecutorRegistry()
        if tool_registry:
            self.registry.register_tool_registry(tool_registry)

        # Register foundational cognitive & vision executors
        self.registry.register(LLMExecutor(name="llm_reasoning", llm_provider=self.llm))
        self.registry.register(VisionExecutor(name="vision_analyzer", llm_provider=self.llm))

        # 2. Model Router
        self.router = ModelRouter(self.registry)

        # 3. Dynamic Planner
        self.planner = DynamicTaskPlanner(
            executor_registry=self.registry,
            llm_provider=self.llm,
            model_router=self.router,
        )

        # 4. Dynamic Replanner
        self.replanner = DynamicReplanner(
            executor_registry=self.registry,
            llm_provider=self.llm,
            event_bus=self.event_bus,
        )

        # 5. Task Graph Scheduler
        self.scheduler = TaskGraphScheduler(
            executor_registry=self.registry,
            authorizer=self.authorizer,
            max_concurrency=max_concurrency,
            default_timeout_seconds=default_timeout_seconds,
            replanner=self.replanner,
            event_bus=self.event_bus,
        )

        # 6. Result Synthesizer
        self.synthesizer = ResultSynthesizer(llm_provider=self.llm)

    def register_specialist_agent(self, agent: Any, role_name: str) -> None:
        """Register a specialist agent into the executor catalog."""
        from friday.planning.executors import SpecialistAgentExecutor

        self.registry.register(SpecialistAgentExecutor(agent=agent, role_name=role_name))

    def execute_goal(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        cancellation_token: threading.Event | None = None,
    ) -> SynthesizedResponse:
        """Execute a user goal through the full Microsoft HuggingGPT 4-stage pipeline."""
        logger.info(f"FridayOrchestrator processing goal: '{goal[:80]}...'")

        # Stage 1: Dynamic Task Planning
        graph = self.planner.plan(goal, context=context)

        # Stage 2: Model & Executor Routing
        for task in graph.list_tasks():
            self.router.route_task(task)

        # Model tool calls form an interactive loop: execute, report verified
        # results, and allow the model to choose the next action or recover.
        if graph.metadata.get("interactive_tool_plan"):
            return self._execute_interactive_tool_plan(
                goal=goal,
                graph=graph,
                cancellation_token=cancellation_token,
            )

        # Stage 3: Topological Execution with Concurrency & Dynamic Replanning
        executed_graph = self.scheduler.execute_graph(graph, cancellation_token=cancellation_token)

        # Stage 4: Result Synthesis
        response = self.synthesizer.synthesize(executed_graph)
        return response

    def _execute_interactive_tool_plan(
        self,
        goal: str,
        graph: TaskGraph,
        cancellation_token: threading.Event | None = None,
    ) -> SynthesizedResponse:
        """Run bounded tool-call turns until the model returns a final answer."""
        messages = [Message(role=Role.USER, content=goal)]
        all_results: list[ToolResult] = []
        last_error = ""

        for _ in range(4):
            replanner = self.scheduler.replanner
            self.scheduler.replanner = None
            try:
                executed = self.scheduler.execute_graph(graph, cancellation_token=cancellation_token)
            finally:
                self.scheduler.replanner = replanner
            current_results = self._tool_results_from_graph(executed)
            all_results.extend(current_results)
            failed = [result for result in current_results if result.is_error]

            if failed:
                last_error = failed[-1].content
                messages.append(
                    Message(
                        role=Role.SYSTEM,
                        content=(
                            f"Your previous tool call '{failed[-1].name}' failed with this error: "
                            f"{last_error}. Choose a safe recovery action or report the failure."
                        ),
                    )
                )
            else:
                messages.append(Message(role=Role.SYSTEM, content="The previous tool call completed successfully. Continue or summarize."))

            for result in current_results:
                messages.append(Message(role=Role.TOOL, name=result.name, tool_call_id=result.tool_call_id, content=result.content))

            response = self.llm.generate(messages) if self.llm and hasattr(self.llm, "generate") else None
            if response is None:
                break
            if not response.tool_calls:
                content = self._clean_model_text(response.content)
                if content:
                    return self._response_from_results(content, goal, graph, all_results, executed)
                break

            next_tasks = []
            for index, tool_call in enumerate(response.tool_calls, start=1):
                next_tasks.append(
                    self._task_from_tool_call(tool_call, index=index, dependency=None)
                )
            graph = TaskGraph(
                goal=goal,
                tasks=next_tasks,
                metadata={"interactive_tool_plan": True},
            )
            for task in graph.list_tasks():
                self.router.route_task(task)

        fallback = f"I could not complete the request: {last_error}" if last_error else "I could not complete the request within the action limit."
        return self._response_from_results(fallback, goal, graph, all_results, executed if 'executed' in locals() else graph)

    @staticmethod
    def _task_from_tool_call(tool_call: ToolCall, index: int, dependency: str | None):
        from friday.planning.types import TaskStep

        return TaskStep(
            id=f"tool_step_{index}_{tool_call.id or index}",
            description=f"Execute tool {tool_call.name}",
            tool_name=tool_call.name,
            parameters=tool_call.arguments if isinstance(tool_call.arguments, dict) else {},
            dependencies=[dependency] if dependency else [],
        )

    @staticmethod
    def _tool_results_from_graph(graph: TaskGraph) -> list[ToolResult]:
        results: list[ToolResult] = []
        for task in graph.list_tasks():
            raw = task.outputs.get("raw_result") if task.outputs else None
            if isinstance(raw, ToolResult):
                results.append(raw)
            elif isinstance(task.result, ToolResult):
                results.append(task.result)
            elif task.error:
                results.append(ToolResult(name=task.tool_name or task.id, content=task.error, is_error=True))
        return results

    @staticmethod
    def _clean_model_text(content: str | None) -> str:
        cleaned = re.sub(r"<thought>.*?</thought>", "", content or "", flags=re.IGNORECASE | re.DOTALL).strip()
        return cleaned

    @staticmethod
    def _response_from_results(content: str, goal: str, graph: TaskGraph, results: list[ToolResult], executed: TaskGraph) -> SynthesizedResponse:
        tasks = executed.list_tasks()
        completed = sum(1 for task in tasks if task.status.value == "COMPLETED")
        failed = sum(1 for task in tasks if task.status.value == "FAILED")
        return SynthesizedResponse(
            content=content,
            goal=goal,
            graph_id=graph.graph_id,
            is_successful=failed == 0 and bool(content),
            total_tasks=len(tasks),
            completed_tasks=completed,
            failed_tasks=failed,
            tool_results=results,
        )

    def execute_graph(
        self,
        graph: TaskGraph,
        cancellation_token: threading.Event | None = None,
    ) -> TaskGraph:
        """Execute a pre-constructed TaskGraph directly through the scheduler."""
        return self.scheduler.execute_graph(graph, cancellation_token=cancellation_token)
