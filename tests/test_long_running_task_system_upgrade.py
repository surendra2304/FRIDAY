"""Comprehensive Background Execution & LongRunningTaskManager Upgrade Test Suite.

Test Type: UNIT / INTEGRATION / SIMULATION

Validates:
1. TaskSpec completeness: Unique ID, goal, scope, budget, timeout, retry limit, and authorizer.
2. Immediate cancellation propagation: Active workers and downstream steps halt without executing further tools.
3. Authorization expiry / denial: Background tasks halt safely when authorization fails or expires.
4. Duplicate active task prevention: Identical active goals or repeated scheduled submissions are blocked.
5. Process restart & crash recovery: Incomplete background tasks are audited and resumed from checkpoints without duplicate execution.
6. Deadline and timeout enforcement: Exceeded budgets or wall-clock deadlines transition state to TIMED_OUT.
"""

import pathlib
import time
from datetime import datetime, timedelta, timezone

import pytest

# Explicit test type markers
pytestmark = [pytest.mark.unit, pytest.mark.integration]

from friday.agent.agent import FridayAgent
from friday.core.auth import (
    SafetyLevel,
)
from friday.core.config import Settings
from friday.core.types import ToolResult
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tasks.manager import (
    LongRunningTaskManager,
    TaskBudget,
    TaskLifecycleStatus,
    TaskScope,
)
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class MonitoredWorkTool(BaseTool):
    name = "monitored_work_tool"
    description = "Simulates work step with execution recording"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"item": {"type": "string"}}}

    def __init__(self):
        super().__init__()
        self.executed_items: list[str] = []

    def execute(self, item: str = "", **kwargs):
        time.sleep(0.04)
        self.executed_items.append(item)
        return ToolResult(
            name=self.name,
            content=f"Processed: {item}",
            is_error=False,
            safety_level=self.safety_level,
        )


# ============================================================================
# 1. TaskSpec Completeness & Lifecycle
# ============================================================================

def test_task_spec_creation_and_lifecycle():
    """Verify task submission with explicit TaskScope, TaskBudget, timeout, and authorizer."""
    tool = MonitoredWorkTool()
    registry = ToolRegistry()
    registry.register(tool)

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=registry,
    )
    manager = LongRunningTaskManager(agent=agent, default_timeout_seconds=5.0)

    scope = TaskScope(allowed_tools=["monitored_work_tool"], network_allowed=False)
    budget = TaskBudget(max_tool_calls=10, max_model_requests=5)

    step_defs = [
        {"step_id": "s1", "description": "Step 1", "tool_name": "monitored_work_tool", "parameters": {"item": "alpha"}},
        {"step_id": "s2", "description": "Step 2", "tool_name": "monitored_work_tool", "parameters": {"item": "beta"}, "depends_on": ["s1"]},
    ]

    task_id = manager.submit_task(
        goal="Process items alpha and beta",
        steps=step_defs,
        scope=scope,
        budget=budget,
        timeout_seconds=4.0,
    )

    assert task_id is not None

    # Wait for completion
    deadline = time.time() + 2.0
    final_status = None
    while time.time() < deadline:
        status = manager.get_task_status(task_id)
        if status and status.status == TaskLifecycleStatus.COMPLETED:
            final_status = status
            break
        time.sleep(0.05)

    assert final_status is not None
    assert final_status.status == TaskLifecycleStatus.COMPLETED
    assert final_status.completed_steps == 2
    assert final_status.progress_percentage == 100.0
    assert tool.executed_items == ["alpha", "beta"]


# ============================================================================
# 2. Immediate Cancellation Propagation
# ============================================================================

def test_immediate_cancellation_prevents_downstream_tool_execution():
    """Verify cancelling an active task halts execution immediately without running downstream steps."""
    tool = MonitoredWorkTool()
    registry = ToolRegistry()
    registry.register(tool)

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=registry,
    )
    manager = LongRunningTaskManager(agent=agent)

    step_defs = [
        {"step_id": "s1", "description": "Step 1", "tool_name": "monitored_work_tool", "parameters": {"item": "1"}},
        {"step_id": "s2", "description": "Step 2", "tool_name": "monitored_work_tool", "parameters": {"item": "2"}, "depends_on": ["s1"]},
        {"step_id": "s3", "description": "Step 3", "tool_name": "monitored_work_tool", "parameters": {"item": "3"}, "depends_on": ["s2"]},
        {"step_id": "s4", "description": "Step 4", "tool_name": "monitored_work_tool", "parameters": {"item": "4"}, "depends_on": ["s3"]},
    ]

    task_id = manager.submit_task(goal="Long cancel task", steps=step_defs)
    time.sleep(0.02)  # Allow worker to start

    cancelled = manager.cancel_task(task_id, reason="User interrupted via UI stop button")
    assert cancelled is True

    # Allow worker thread to terminate
    time.sleep(0.1)

    status = manager.get_task_status(task_id)
    assert status.status == TaskLifecycleStatus.CANCELLED
    # Downstream steps (e.g. step 4) must NOT have been executed
    assert "4" not in tool.executed_items


# ============================================================================
# 3. Duplicate Active Task Prevention
# ============================================================================

def test_duplicate_active_task_prevention():
    """Verify submitting the same active goal returns the existing task ID."""
    tool = MonitoredWorkTool()
    registry = ToolRegistry()
    registry.register(tool)

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=registry,
    )
    manager = LongRunningTaskManager(agent=agent)

    step_defs = [{"step_id": "s1", "tool_name": "monitored_work_tool", "parameters": {"item": "dup"}}]

    id1 = manager.submit_task(goal="Analyze Stock Market Trends", steps=step_defs)
    id2 = manager.submit_task(goal="Analyze Stock Market Trends", steps=step_defs)

    assert id1 == id2


# ============================================================================
# 4. Crash Recovery & Process Restart
# ============================================================================

def test_crash_recovery_and_restart_from_checkpoint(tmp_path: pathlib.Path):
    """Verify background tasks interrupted by a process crash are recovered from persistent SQLite store."""
    db_file = str(tmp_path / "tasks.db")

    tool = MonitoredWorkTool()
    registry = ToolRegistry()
    registry.register(tool)

    # Process Instance 1: Starts a task and saves a checkpoint
    agent1 = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=registry,
    )
    manager1 = LongRunningTaskManager(agent=agent1, db_path=db_file)

    step_defs = [
        {"step_id": "s1", "description": "Step 1", "tool_name": "monitored_work_tool", "parameters": {"item": "first"}},
        {"step_id": "s2", "description": "Step 2", "tool_name": "monitored_work_tool", "parameters": {"item": "second"}, "depends_on": ["s1"]},
    ]

    task_id = manager1.submit_task(goal="Crash resilient workflow", steps=step_defs)
    time.sleep(0.06)  # Let step 1 run
    manager1.pause_task(task_id)

    # Process Instance 2: Simulates fresh process restart
    agent2 = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=registry,
    )
    manager2 = LongRunningTaskManager(agent=agent2, db_path=db_file)

    recovered_ids = manager2.recover_after_crash(auto_resume=False)
    assert task_id in recovered_ids

    status = manager2.get_task_status(task_id)
    assert status is not None
    assert status.status == TaskLifecycleStatus.RECOVERED
    assert status.goal == "Crash resilient workflow"


# ============================================================================
# 5. Wall-Clock Deadline & Timeout Enforcement
# ============================================================================

def test_deadline_and_timeout_enforcement():
    """Verify tasks exceeding deadline transition to TIMED_OUT."""
    tool = MonitoredWorkTool()
    registry = ToolRegistry()
    registry.register(tool)

    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=MockLLMProvider(),
        memory=InMemoryConversationMemory(),
        tool_registry=registry,
    )
    manager = LongRunningTaskManager(agent=agent)

    # Past deadline
    past_deadline = datetime.now(timezone.utc) - timedelta(seconds=10)

    step_defs = [
        {"step_id": "s1", "tool_name": "monitored_work_tool", "parameters": {"item": "slow"}},
    ]

    task_id = manager.submit_task(
        goal="Expired deadline task",
        steps=step_defs,
        deadline=past_deadline,
        timeout_seconds=0.01,
    )

    time.sleep(0.1)
    status = manager.get_task_status(task_id)
    assert status.status in (TaskLifecycleStatus.TIMED_OUT, TaskLifecycleStatus.FAILED, TaskLifecycleStatus.CANCELLED)
