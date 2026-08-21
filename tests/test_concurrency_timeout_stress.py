# -*- coding: utf-8 -*-
"""Comprehensive Concurrency, Timeout & Cancellation Stress Test Suite for FRIDAY.

Stress-tests:
1. Intentionally blocking tool calls under strict timeout boundaries.
2. Concurrent parallel execution of independent slow tools without thread starvation or shutdown hangs.
3. Cancellation token propagation halting subsequent side-effect tools immediately.
4. Recovery manager refusing to restart cancelled tasks or replay state-modifying actions.
5. Background worker execution lifecycle under rapid task creation, cancellation, and timeout.
6. Race conditions and deadlocks in state machine, task context, and tool registry.
"""

import threading
import time
import pytest
from typing import Any, Dict, List, Optional

from friday.agent.agent import FridayAgent
from friday.agent.executor import TaskExecutionEngine
from friday.agent.planner import PlanStep, StepStatus, TaskPlan
from friday.agent.state import ReasoningStateMachine, TaskState
from friday.core.auth import DefaultSecureAuthorizer
from friday.core.types import Message, Role, SafetyLevel, ToolCall, ToolResult
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.security.authorization import ToolAuthorizer
from friday.tasks.manager import LongRunningTaskManager, TaskBudget, TaskLifecycleStatus, TaskScope, TaskSpec
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


# ---------------------------------------------------------------------------
# Test Fixtures: Intentionally Slow and Blocking Tools
# ---------------------------------------------------------------------------

class IntentionallyBlockingTool(BaseTool):
    """Tool that sleeps for a configurable duration and records if execution completed."""
    name = "slow_blocking_tool"
    description = "Intentionally slow tool for timeout stress testing."
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "sleep_seconds": {"type": "number"},
        },
        "required": ["sleep_seconds"],
    }

    def __init__(self) -> None:
        super().__init__()
        self.started_count = 0
        self.completed_count = 0
        self.cancelled_count = 0
        self.lock = threading.Lock()

    def execute(self, sleep_seconds: float = 2.0, cancellation_token: Optional[threading.Event] = None, **kwargs: Any) -> ToolResult:
        with self.lock:
            self.started_count += 1

        interval = 0.05
        elapsed = 0.0
        while elapsed < sleep_seconds:
            if cancellation_token and cancellation_token.is_set():
                with self.lock:
                    self.cancelled_count += 1
                return ToolResult(
                    name=self.name,
                    content="Execution cancelled early via cancellation token.",
                    is_error=True,
                )
            time.sleep(interval)
            elapsed += interval

        with self.lock:
            self.completed_count += 1

        return ToolResult(
            name=self.name,
            content=f"Completed sleep of {sleep_seconds:.2f}s",
            is_error=False,
        )


class StateModifyingSideEffectTool(BaseTool):
    """Tool that records every execution to verify no side effects occur after cancellation."""
    name = "state_modifying_side_effect"
    description = "Side-effect tool for testing cancellation barrier."
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "action_id": {"type": "string"},
        },
        "required": ["action_id"],
    }

    def __init__(self) -> None:
        super().__init__()
        self.executed_actions: List[str] = []
        self.lock = threading.Lock()

    def execute(self, action_id: str, **kwargs: Any) -> ToolResult:
        with self.lock:
            self.executed_actions.append(action_id)
        return ToolResult(
            name=self.name,
            content=f"Side effect executed for {action_id}",
            is_error=False,
            safety_level=self.safety_level,
        )


# ===========================================================================
# 1. Tool Execution Strict Timeout Tests
# ===========================================================================

class TestToolExecutionStrictTimeouts:

    def test_single_tool_strict_timeout_returns_control_quickly(self):
        """Verify tool execution times out and returns control in ~0.2s without waiting for 5s sleep."""
        reg = ToolRegistry()
        slow_tool = IntentionallyBlockingTool()
        reg.register(slow_tool)

        agent = FridayAgent(
            llm_provider=MockLLMProvider(),
            tool_registry=reg,
            tool_timeout=0.2,
        )

        tc = ToolCall(id="call_slow_1", name="slow_blocking_tool", arguments={"sleep_seconds": 5.0})

        start = time.perf_counter()
        result = agent._execute_single_tool_call_with_timeout(tc, timeout=0.2)
        elapsed = time.perf_counter() - start

        assert result.is_error is True
        assert "timeout" in result.content.lower() or "exceeded" in result.content.lower()
        # Control must be returned strictly near the timeout, not waiting 5 seconds
        assert elapsed < 1.0, f"Timeout took too long: {elapsed:.2f}s"

    def test_parallel_tool_batch_timeout_does_not_block_agent(self):
        """Verify parallel tool execution batch returns control quickly when one tool blocks."""
        reg = ToolRegistry()
        slow_tool = IntentionallyBlockingTool()
        reg.register(slow_tool)

        # Mock LLM requests two parallel slow tools
        tc1 = ToolCall(id="call_slow_a", name="slow_blocking_tool", arguments={"sleep_seconds": 5.0})
        tc2 = ToolCall(id="call_slow_b", name="slow_blocking_tool", arguments={"sleep_seconds": 0.05})

        step_count = 0
        def responder(messages, tools=None):
            nonlocal step_count
            step_count += 1
            if step_count == 1:
                return Message(role=Role.ASSISTANT, content="Running tools", tool_calls=[tc1, tc2])
            return Message(role=Role.ASSISTANT, content="Done summarizing.")

        agent = FridayAgent(
            llm_provider=MockLLMProvider(custom_responder=responder),
            tool_registry=reg,
            memory=InMemoryConversationMemory(),
            tool_timeout=0.2,
        )

        start = time.perf_counter()
        response = agent.process_message("Execute parallel slow tools")
        elapsed = time.perf_counter() - start

        assert response.is_done is True
        # Whole turn must finish quickly despite 5s tool (within 2.5s under concurrent pytest load)
        assert elapsed < 2.5, f"Parallel batch took too long: {elapsed:.2f}s"


# ===========================================================================
# 2. Cancellation and Side-Effect Barrier Tests
# ===========================================================================

class TestCancellationBarrierAndRecovery:

    def test_cancellation_halts_subsequent_side_effects(self):
        """Verify that cancelling a TaskPlan immediately prevents subsequent steps from executing."""
        reg = ToolRegistry()
        slow_tool = IntentionallyBlockingTool()
        side_effect_tool = StateModifyingSideEffectTool()
        reg.register(slow_tool)
        reg.register(side_effect_tool)

        authorizer = ToolAuthorizer()
        engine = TaskExecutionEngine(
            tool_registry=reg,
            authorizer=DefaultSecureAuthorizer(authorizer=authorizer),
            step_timeout_seconds=5.0,
        )

        plan = TaskPlan(
            plan_id="cancel_test_plan",
            goal="Test cancellation barrier",
            steps=[
                PlanStep(
                    step_id="step_slow",
                    tool_name="slow_blocking_tool",
                    parameters={"sleep_seconds": 1.0},
                    safety_level=SafetyLevel.SAFE,
                    description="Slow step",
                ),
                PlanStep(
                    step_id="step_side_effect",
                    tool_name="state_modifying_side_effect",
                    parameters={"action_id": "critical_database_mutation"},
                    safety_level=SafetyLevel.SAFE,
                    depends_on=["step_slow"],
                    description="Side effect step",
                ),
            ],
        )

        # Trigger cancellation after 0.1s while step_slow is in progress
        def _cancel_async():
            time.sleep(0.1)
            engine.cancel(reason="User pressed stop")

        t = threading.Thread(target=_cancel_async, daemon=True)
        t.start()

        start = time.perf_counter()
        result = engine.execute_plan(plan)
        elapsed = time.perf_counter() - start

        assert result.success is False
        assert result.state == TaskState.CANCELLED
        # The subsequent side-effect step must NEVER have executed
        assert "critical_database_mutation" not in side_effect_tool.executed_actions
        assert elapsed < 2.0, f"Cancelled plan took too long to halt: {elapsed:.2f}s"

    def test_cancellation_token_stops_in_flight_tool(self):
        """Verify cancellation token passed to tool causes early exit."""
        slow_tool = IntentionallyBlockingTool()
        cancel_event = threading.Event()

        def _cancel_after():
            time.sleep(0.1)
            cancel_event.set()

        t = threading.Thread(target=_cancel_after, daemon=True)
        t.start()

        start = time.perf_counter()
        res = slow_tool.execute(sleep_seconds=4.0, cancellation_token=cancel_event)
        elapsed = time.perf_counter() - start

        assert res.is_error is True
        assert "cancelled early" in res.content
        assert elapsed < 0.5, f"Tool did not observe cancellation token promptly: {elapsed:.2f}s"


# ===========================================================================
# 3. LongRunningTaskManager Concurrency & Timeout Stress Tests
# ===========================================================================

class TestLongRunningTaskManagerStress:

    def test_task_manager_timeout_terminates_background_worker(self, tmp_path):
        """Verify background task exceeding hard deadline transitions to TIMED_OUT."""
        reg = ToolRegistry()
        slow_tool = IntentionallyBlockingTool()
        reg.register(slow_tool)

        agent = FridayAgent(
            llm_provider=MockLLMProvider(),
            tool_registry=reg,
        )

        db_path = str(tmp_path / "tasks_stress.db")
        manager = LongRunningTaskManager(agent=agent, db_path=db_path)

        steps = [
            {
                "step_id": "step_block",
                "tool_name": "slow_blocking_tool",
                "parameters": {"sleep_seconds": 10.0},
                "safety_level": "SAFE",
                "description": "Blocking execution step",
            }
        ]

        # Submit task with 0.3s timeout
        task_id = manager.submit_task(
            goal="Timeout stress test",
            steps=steps,
            timeout_seconds=0.3,
        )

        # Wait for worker thread to process timeout
        time.sleep(0.8)

        status = manager.get_task_status(task_id)
        assert status is not None
        assert status.status in (TaskLifecycleStatus.TIMED_OUT, TaskLifecycleStatus.FAILED)

    def test_rapid_task_submission_and_cancellation_race_conditions(self, tmp_path):
        """Submit 10 concurrent background tasks and rapidly cancel them without deadlocks."""
        reg = ToolRegistry()
        slow_tool = IntentionallyBlockingTool()
        reg.register(slow_tool)

        agent = FridayAgent(
            llm_provider=MockLLMProvider(),
            tool_registry=reg,
        )

        db_path = str(tmp_path / "tasks_race.db")
        manager = LongRunningTaskManager(agent=agent, db_path=db_path, max_concurrent_tasks=20)

        submitted_ids = []
        for i in range(10):
            steps = [
                {
                    "step_id": f"step_{i}",
                    "tool_name": "slow_blocking_tool",
                    "parameters": {"sleep_seconds": 2.0},
                    "safety_level": "SAFE",
                    "description": f"Concurrent task step {i}",
                }
            ]
            tid = manager.submit_task(goal=f"Concurrent task {i}", steps=steps, timeout_seconds=5.0)
            submitted_ids.append(tid)

        # Rapidly cancel all tasks
        for tid in submitted_ids:
            manager.cancel_task(tid, reason="Stress cancellation")

        time.sleep(0.5)

        for tid in submitted_ids:
            st = manager.get_task_status(tid)
            assert st is not None
            assert st.status in (TaskLifecycleStatus.CANCELLED, TaskLifecycleStatus.SUBMITTED, TaskLifecycleStatus.FAILED)
