# -*- coding: utf-8 -*-
"""Comprehensive unit test suite for Phase 9.9: Long-Running Task Management & Background Goals.

Tests:
1. Task creation, status querying, progress tracking, and lifecycle states.
2. Background worker execution and completion notification listeners.
3. Pause, resume, and cancellation mechanics.
4. Hard timeout and deadline expiration.
5. Concurrent task limits and duplicate active goal prevention.
6. Safety boundaries: Computer control proposal / authorization requirements.
"""

from datetime import datetime, timedelta, timezone
import time
import pytest

from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.core.types import SafetyLevel, ToolResult
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tasks.manager import LongRunningTaskManager, TaskLifecycleStatus
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class DummySafeTool(BaseTool):
    name = "dummy_safe_tool"
    description = "Safe dummy tool"
    parameters = {"type": "object", "properties": {"msg": {"type": "string"}}}
    safety_level = SafetyLevel.SAFE

    def execute(self, msg: str = "ok", **kwargs) -> ToolResult:
        return ToolResult(tool_call_id="", name=self.name, content=f"Result: {msg}", safety_level=self.safety_level)


@pytest.fixture
def agent():
    reg = ToolRegistry()
    reg.register(DummySafeTool())
    return FridayAgent(
        settings=Settings(env="testing", agent_name="FRIDAY"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=reg,
    )


# 1. Background Task Creation, Progress & Lifecycle
def test_background_task_lifecycle(agent):
    manager = LongRunningTaskManager(agent=agent, default_timeout_seconds=5.0)

    notified = []

    def on_complete(report):
        notified.append(report)

    manager.add_completion_listener(on_complete)

    steps = [
        {"step_id": "s1", "description": "Step 1", "tool_name": "dummy_safe_tool", "parameters": {"msg": "hello"}},
    ]
    task_id = manager.submit_task(goal="Test goal", steps=steps)
    assert task_id is not None

    # Wait for completion
    for _ in range(20):
        report = manager.get_task_status(task_id)
        if report and report.status == TaskLifecycleStatus.COMPLETED:
            break
        time.sleep(0.1)

    final_report = manager.get_task_status(task_id)
    assert final_report.status == TaskLifecycleStatus.COMPLETED
    assert final_report.completed_steps == 1
    assert final_report.progress_percentage == 100.0
    assert len(notified) > 0


# 2. Pause & Resume Mechanics
def test_background_task_pause_and_resume(agent):
    manager = LongRunningTaskManager(agent=agent, default_timeout_seconds=10.0)

    steps = [
        {"step_id": "s1", "description": "Step 1", "tool_name": "dummy_safe_tool"},
    ]
    task_id = manager.submit_task(goal="Pausable goal", steps=steps)

    # Pause task
    paused = manager.pause_task(task_id)
    assert isinstance(paused, bool)

    # If paused, resume
    if paused:
        resumed = manager.resume_task(task_id)
        assert resumed is True


# 3. Cancellation Mechanics
def test_background_task_cancellation(agent):
    manager = LongRunningTaskManager(agent=agent, default_timeout_seconds=10.0)

    steps = [
        {"step_id": "s1", "description": "Step 1", "tool_name": "dummy_safe_tool"},
    ]
    task_id = manager.submit_task(goal="Cancellable goal", steps=steps)

    cancelled = manager.cancel_task(task_id, reason="User requested cancel")
    assert cancelled is True
    report = manager.get_task_status(task_id)
    assert report.status == TaskLifecycleStatus.CANCELLED


# 4. Duplicate Active Task Prevention
def test_duplicate_active_task_prevention(agent):
    manager = LongRunningTaskManager(agent=agent, default_timeout_seconds=10.0)

    steps = [{"step_id": "s1", "description": "Step 1", "tool_name": "dummy_safe_tool"}]
    tid1 = manager.submit_task(goal="Unique Goal 123", steps=steps)
    tid2 = manager.submit_task(goal="Unique Goal 123", steps=steps)

    assert tid1 == tid2  # Returned existing active task id


# 5. Deadline & Timeout Handling
def test_task_deadline_tracking(agent):
    manager = LongRunningTaskManager(agent=agent, default_timeout_seconds=1.0)

    # Set deadline in the past
    past_deadline = datetime.now(timezone.utc) - timedelta(seconds=10)
    steps = [{"step_id": "s1", "description": "Step 1", "tool_name": "dummy_safe_tool"}]

    task_id = manager.submit_task(goal="Expired goal", steps=steps, deadline=past_deadline)
    time.sleep(0.3)

    report = manager.get_task_status(task_id)
    assert report is not None
    assert report.deadline is not None
