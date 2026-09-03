"""Central Jarvis / HuggingGPT Orchestrator for FRIDAY.

Brings together:
1. Dynamic Task Planning (Decomposition into DAG)
2. Model & Executor Routing (Selection based on capabilities, modality, cost)
3. Concurrent Topological Execution (Parallel wave execution & data passing)
4. Dynamic Replanning (Failure diagnosis, retries, fallback executors, sub-graph repair)
5. Result Synthesis (Multimodal consolidation into human-friendly answer)
"""

from __future__ import annotations

import threading
from typing import Any

from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
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


class JarvisOrchestrator:
    """Unified controller orchestrating Microsoft JARVIS / HuggingGPT capabilities natively inside FRIDAY."""

    def __init__(
        self,
        tool_registry: ToolRegistry | None = None,
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
        self.registry = ExecutorRegistry()
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
        """Execute a user goal through the full Microsoft JARVIS 4-stage pipeline."""
        logger.info(f"JarvisOrchestrator processing goal: '{goal[:80]}...'")

        # Stage 1: Dynamic Task Planning
        graph = self.planner.plan(goal, context=context)

        # Stage 2: Model & Executor Routing
        for task in graph.list_tasks():
            self.router.route_task(task)

        # Stage 3: Topological Execution with Concurrency & Dynamic Replanning
        executed_graph = self.scheduler.execute_graph(graph, cancellation_token=cancellation_token)

        # Stage 4: Result Synthesis
        response = self.synthesizer.synthesize(executed_graph)
        return response
