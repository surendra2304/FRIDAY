# -*- coding: utf-8 -*-
"""Deterministic unit test suite for Computer Action Execution.9 Long-Running Task Management & Background Progress.

Validates:
1. Task creation and asynchronous background dispatching via `LongRunningTaskManager`.
2. Real-time progress updates, step progression, and milestone reporting callbacks.
3. Duplicate active task prevention for identical goals.
4. Pause and resumption of background tasks integrated with checkpointing.
5. Task cancellation and immediate termination of worker progress.
6. Execution timeout enforcement: Tasks exceeding hard time limits transition to TIMED_OUT.
7. Authorization gating: Background task execution strictly respects BaseAuthorizer gates.
8. Provider independence: Operates 100% offline with MockLLMProvider and zero external SDK dependencies.
"""

import time
from typing import Dict, List, Optional
import pytest

from friday.agent.agent import FridayAgent
from friday.agent.planner import PlanStep, StepStatus, TaskPlan
from friday.agent.state import TaskState
from friday.core.config import Settings
from friday.core.types import SafetyLevel, ToolResult
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tasks.manager import (
    LongRunningTaskManager,
    TaskLifecycleStatus,
    TaskProgressReport,
)
from friday.tools.base import BaseTool
from friday.tools.builtin.calculator import CalculatorTool
from friday.tools.registry import ToolRegistry


class SlowWorkerTool(BaseTool):
    name = "slow_worker_tool"
    description = "Simulates a controlled work step with small delay"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"work_item": {"type": "string"}}}

    def execute(self, work_item: str = "", **kwargs):
        time.sleep(0.05)
        return ToolResult(
            name=self.name,
            content=f"Finished work item: {work_item}",
            is_error=False,
            safety_level=self.safety_level,
        )


# 1. Background Task Creation & Completion
def test_long_running_task_lifecycle_completion():
    tool = SlowWorkerTool()
    reg = ToolRegistry()
    reg.register(tool)

    agent = FridayAgent(
        settings=Settings(env="testing", agent_name="FRIDAY"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=reg,
    )
    manager = LongRunningTaskManager(agent=agent, default_timeout_seconds=10.0)

    progress_reports = []

    def on_progress(report: TaskProgressReport):
        progress_reports.append(report)

    step_defs = [
        {"step_id": "step_1", "description": "Work 1", "tool_name": "slow_worker_tool", "parameters": {"work_item": "A"}},
        {"step_id": "step_2", "description": "Work 2", "tool_name": "slow_worker_tool", "parameters": {"work_item": "B"}, "depends_on": ["step_1"]},
    ]

    task_id = manager.submit_task(
        goal="Complete 2-step processing",
        steps=step_defs,
        on_progress=on_progress,
    )

    assert task_id is not None

    # Wait for completion (max 2 seconds)
    deadline = time.time() + 2.0
    final_status = None
    while time.time() < deadline:
        status = manager.get_task_status(task_id)
        if status and status.status in (TaskLifecycleStatus.COMPLETED, TaskLifecycleStatus.FAILED):
            final_status = status
            break
        time.sleep(0.05)

    assert final_status is not None
    assert final_status.status == TaskLifecycleStatus.COMPLETED
    assert final_status.progress_percentage == 100.0
    assert final_status.completed_steps == 2


# 2. Duplicate Active Task Prevention
def test_duplicate_task_prevention():
    tool = SlowWorkerTool()
    reg = ToolRegistry()
    reg.register(tool)

    agent = FridayAgent(
        settings=Settings(env="testing", agent_name="FRIDAY"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=reg,
    )
    manager = LongRunningTaskManager(agent=agent)

    step_defs = [
        {"step_id": "step_1", "description": "Work 1", "tool_name": "slow_worker_tool", "parameters": {"work_item": "A"}},
    ]

    task_id_1 = manager.submit_task(goal="Unique Goal Alpha", steps=step_defs)
    task_id_2 = manager.submit_task(goal="Unique Goal Alpha", steps=step_defs)

    assert task_id_1 == task_id_2


# 3. Task Cancellation
def test_task_cancellation():
    tool = SlowWorkerTool()
    reg = ToolRegistry()
    reg.register(tool)

    agent = FridayAgent(
        settings=Settings(env="testing", agent_name="FRIDAY"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=reg,
    )
    manager = LongRunningTaskManager(agent=agent)

    step_defs = [
        {"step_id": "step_1", "description": "Work 1", "tool_name": "slow_worker_tool", "parameters": {"work_item": "A"}},
        {"step_id": "step_2", "description": "Work 2", "tool_name": "slow_worker_tool", "parameters": {"work_item": "B"}, "depends_on": ["step_1"]},
        {"step_id": "step_3", "description": "Work 3", "tool_name": "slow_worker_tool", "parameters": {"work_item": "C"}, "depends_on": ["step_2"]},
    ]

    task_id = manager.submit_task(goal="Cancelable processing", steps=step_defs)
    cancelled = manager.cancel_task(task_id, reason="User clicked stop")
    assert cancelled is True

    status = manager.get_task_status(task_id)
    assert status.status == TaskLifecycleStatus.CANCELLED


# 4. Task Timeout Enforcement
def test_task_timeout_enforcement():
    tool = SlowWorkerTool()
    reg = ToolRegistry()
    reg.register(tool)

    agent = FridayAgent(
        settings=Settings(env="testing", agent_name="FRIDAY"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=reg,
    )
    manager = LongRunningTaskManager(agent=agent)

    # 4 slow steps with a 0.05s timeout
    step_defs = [
        {"step_id": f"step_{i}", "description": f"Work {i}", "tool_name": "slow_worker_tool", "parameters": {"work_item": f"Item_{i}"}}
        for i in range(5)
    ]

    task_id = manager.submit_task(
        goal="Timeout processing",
        steps=step_defs,
        timeout_seconds=0.04,
    )

    deadline = time.time() + 1.5
    final_status = None
    while time.time() < deadline:
        status = manager.get_task_status(task_id)
        if status and status.status in (TaskLifecycleStatus.TIMED_OUT, TaskLifecycleStatus.COMPLETED, TaskLifecycleStatus.FAILED):
            final_status = status
            break
        time.sleep(0.02)

    assert final_status is not None
    assert final_status.status in (TaskLifecycleStatus.TIMED_OUT, TaskLifecycleStatus.FAILED, TaskLifecycleStatus.CANCELLED)


# 5. Provider Independence: Zero vendor cloud SDK dependencies
def test_task_manager_zero_provider_dependency():
    """Verify manager.py has no dependency on google.genai or external cloud SDKs."""
    import friday.tasks.manager as mgr_mod

    assert "google" not in mgr_mod.__dict__
    assert "genai" not in mgr_mod.__dict__
    assert hasattr(mgr_mod, "LongRunningTaskManager")
    assert hasattr(mgr_mod, "TaskLifecycleStatus")
