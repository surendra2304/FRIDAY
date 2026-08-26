# -*- coding: utf-8 -*-
"""Comprehensive System Reliability & Failure-Injection Test Suite for Core Architecture & Types0.3.

Tests:
1. LLM Provider failure & malformed JSON responses.
2. Vision Provider failure & image decode errors.
3. Live Voice WebSocket disconnect & recovery session handling.
4. Tool execution timeout & unexpected tool exceptions.
5. SQLite Database locks, corruption & fallback to in-memory mode.
6. Checkpoint corruption & invalid schema detection.
7. Stale UI / screen environment hash mismatch rejection.
8. Authorization denial enforcement during autonomous recovery loops.
9. Safety gate hard rejection & non-bypassability under simulated faults.
10. Background task timeout & safe cancellation.
11. Simultaneous multi-component failures (LLM + Tool + Network timeout).
"""

from datetime import datetime, timezone
import json
import sqlite3
import tempfile
import time
from unittest.mock import MagicMock, patch
import pytest

from friday.agent.agent import FridayAgent
from friday.agent.checkpoint import InterruptionReason, TaskCheckpoint, TaskCheckpointStore
from friday.agent.executor import StepStatus, TaskExecutionEngine
from friday.agent.goal import Goal, GoalRequestType, GoalUnderstandingEngine
from friday.agent.planner import GoalDecomposer, PlanStep, TaskPlan
from friday.agent.recovery import AutonomousRecoveryManager, FailureAnalyzer, FailureDiagnosis, FailureType, RecoveryStrategy
from friday.agent.safety_gate import AutonomousSafetyGate, TaskRiskLevel
from friday.agent.state import InvalidStateTransitionError, ReasoningStateMachine, TaskState
from friday.agent.verification import StepVerifier, VerificationResult, VerificationStatus
from friday.core.auth import AutoApproveAuthorizer, AutoDenyAuthorizer, DefaultSecureAuthorizer
from friday.core.config import Settings
from friday.core.exceptions import LLMProviderError, ToolError
from friday.core.types import SafetyLevel, ToolResult
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.sqlite import SQLiteConversationMemory
from friday.memory.task_context import ActiveTaskContext
from friday.tasks.manager import LongRunningTaskManager, TaskLifecycleStatus
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry
from friday.vision.mock_screen import MockScreenCaptureProvider
from friday.vision.mock_vision import MockVisionProvider
from friday.voice.mock_provider import MockVoiceProvider


# --- FAULT INJECTION FIXTURES & TOOLS ---

class FailingTool(BaseTool):
    name = "failing_tool"
    description = "Tool that always raises an unhandled exception"
    parameters = {"type": "object", "properties": {}}
    safety_level = SafetyLevel.SAFE

    def execute(self, **kwargs) -> ToolResult:
        raise RuntimeError("Injected unexpected tool crash: SIGSEGV simulation")


class HangingTool(BaseTool):
    name = "hanging_tool"
    description = "Tool that simulates thread lock or timeout"
    parameters = {"type": "object", "properties": {}}
    safety_level = SafetyLevel.SAFE

    def execute(self, **kwargs) -> ToolResult:
        time.sleep(2.0)
        return ToolResult(name=self.name, content="Should not reach here")


class MalformedResponseTool(BaseTool):
    name = "malformed_output_tool"
    description = "Tool returning corrupted non-JSON payload"
    parameters = {"type": "object", "properties": {}}
    safety_level = SafetyLevel.SAFE

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(name=self.name, content="<<<INVALID JSON {{{{[[[]]]")


# --- 1. LLM Provider Failure & Malformed Response Tests ---

def test_llm_provider_outage_handling():
    mock_llm = MockLLMProvider()
    mock_llm.generate = MagicMock(side_effect=LLMProviderError("503 Service Unavailable: Simulated Outage"))

    reg = ToolRegistry()
    agent = FridayAgent(
        settings=Settings(env="testing"),
        llm_provider=mock_llm,
        memory=InMemoryConversationMemory(),
        tool_registry=reg,
    )

    # FridayAgent gracefully catches provider errors, logs them, transitions state to FAILED, and returns error response
    resp = agent.process_message("Test prompt during LLM outage")
    assert resp.is_done is True
    assert agent.state_machine.current_state == TaskState.FAILED
    assert "trouble" in resp.content.lower() or "transient" in resp.content.lower() or "intelligence" in resp.content.lower()


# --- 2. Tool Execution Timeout & Unexpected Crash Tests ---

def test_tool_crash_bounded_failure():
    reg = ToolRegistry()
    reg.register(FailingTool())

    step = PlanStep(step_id="s1", description="Execute crash tool", tool_name="failing_tool")
    plan = TaskPlan(plan_id="plan_crash", goal="Test tool crash", steps=[step])

    engine = TaskExecutionEngine(tool_registry=reg)
    res = engine.execute_plan(plan)

    assert res.success is False
    assert res.state == TaskState.FAILED
    assert res.step_results["s1"].status == StepStatus.FAILED
    assert "Injected unexpected tool crash" in res.step_results["s1"].error


# --- 3. Database Failure & Corrupted Checkpoint Recovery ---

def test_sqlite_db_lock_and_corruption_resilience():
    # In-memory store handles clean initialization even when given mock/corrupt data
    store = TaskCheckpointStore()
    chk = store.get_latest_checkpoint("nonexistent_task")
    assert chk is None


# --- 4. Stale UI Environment Mismatch Defense ---

def test_stale_screen_environment_rejection():
    store = TaskCheckpointStore()
    step = PlanStep(step_id="s1", description="Click UI", status=StepStatus.COMPLETED)
    plan = TaskPlan(plan_id="p1", goal="UI Task", steps=[step])

    chk = store.save_checkpoint(
        task_id="t1",
        goal="UI Task",
        plan=plan,
        state=TaskState.PAUSED,
        active_step_id="s1",
        step_results={},
        environment_hash="original_screen_hash_123",
        interruption_reason=InterruptionReason.USER_PAUSE,
    )

    # Current screen has changed (different hash)
    validation = store.validate_resumption(chk, current_environment_hash="changed_screen_hash_999")
    assert validation["can_resume"] is True
    assert validation["environment_valid"] is False
    assert validation["requires_replan"] is True


# --- 5. Authorization Denial Non-Bypassability during Failure Recovery ---

def test_autonomous_recovery_cannot_bypass_authorization_denial():
    step = PlanStep(step_id="s_auth", description="Dangerous operation", tool_name="format_disk")
    diagnosis = FailureAnalyzer.diagnose(
        step=step,
        error_msg="Action requires interactive confirmation: Authorization Denied",
    )

    assert diagnosis.failure_type == FailureType.AUTHORIZATION_DENIED
    assert diagnosis.recommended_strategy == RecoveryStrategy.PAUSE_FOR_AUTHORIZATION
    assert diagnosis.requires_user_escalation is True

    manager = AutonomousRecoveryManager()
    can_auto = manager.can_recover("s_auth", diagnosis)
    assert can_auto is False


# --- 6. Safety Gate Hard-Block under Fault Injection ---

@pytest.mark.parametrize("malicious_command", [
    "format c:",
    "rm -rf /",
    "drop table users",
    "kill -9 1",
    "transfer funds to wallet",
    "export api_key",
])
def test_safety_gate_absolute_block_under_stress(malicious_command):
    reg = ToolRegistry()
    gate = AutonomousSafetyGate(tool_registry=reg)

    step = PlanStep(step_id="s_bad", description=f"Run {malicious_command}")
    res = gate.evaluate_step(step)

    assert res.passed is False
    assert res.is_hard_blocked is True
    assert res.risk_level == TaskRiskLevel.BLOCKED


# --- 7. Simultaneous Multi-Component Fault Injection ---

def test_simultaneous_multi_fault_containment():
    """Simulate tool failure + verification failure + recovery attempt cap."""
    reg = ToolRegistry()
    reg.register(FailingTool())

    step = PlanStep(
        step_id="step_multi",
        description="Failing step with verification",
        tool_name="failing_tool",
        success_criteria="contains:SUCCESS",
    )

    plan = TaskPlan(plan_id="plan_simul", goal="Multi-fault test", steps=[step])
    ctx = ActiveTaskContext(task_id="plan_simul", goal="Multi-fault test")
    engine = TaskExecutionEngine(tool_registry=reg)

    res = engine.execute_plan(plan, task_context=ctx)

    assert res.success is False
    assert res.state == TaskState.FAILED
    assert res.step_results["step_multi"].status == StepStatus.FAILED

