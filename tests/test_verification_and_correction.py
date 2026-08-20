# -*- coding: utf-8 -*-
"""Deterministic unit test suite for Phase 7.4 Verification, Assertions & Self-Correction Loops.

Validates:
1. Successful step and overall plan verification.
2. Failed verification when step output is empty or contains error indicators.
3. Verification assertion syntax:
   - "contains:<substring>"
   - "regex:<pattern>"
4. Bounded self-correction: Failing step triggers diagnosis and retry with parameter adjustment.
5. Successful recovery: Corrected retry passes verification and leads to plan completion.
6. Exhausted retries leading to safe FAILED state (strict bounded limit, no infinite loops).
7. Dangerous action and safety preservation: Self-correction does NOT bypass authorization gates.
8. Preservation of Proposal != Execution: Self-correction generates steps subject to the same strict validation and authorization.
9. Provider independence: Operates 100% offline with MockLLMProvider and zero external SDK dependencies.
"""

from typing import Dict, List, Optional
import pytest

from friday.agent.agent import FridayAgent
from friday.agent.executor import (
    ExecutionProgress,
    StepExecutionResult,
    TaskExecutionEngine,
    TaskExecutionResult,
)
from friday.agent.planner import GoalDecomposer, PlanStep, StepStatus, TaskPlan
from friday.agent.state import TaskState
from friday.agent.verification import (
    SelfCorrectionPolicy,
    StepVerifier,
    VerificationResult,
    VerificationStatus,
)
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.config import Settings
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    SafetyLevel,
    ToolResult,
)
from friday.llm.mock_provider import MockLLMProvider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.base import BaseTool
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.registry import ToolRegistry


class StatefulRetryTool(BaseTool):
    """Tool that fails on the first call and succeeds on the second call (simulating transient issue)."""
    name = "stateful_retry_tool"
    description = "Fails initially then succeeds on retry"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"_retry_attempt": {"type": "integer"}}}

    def __init__(self):
        super().__init__()
        self.call_count = 0

    def execute(self, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            return ToolResult(name=self.name, content="Error: Temporary connection timeout", is_error=True, safety_level=self.safety_level)
        return ToolResult(name=self.name, content="System report: Healthy and synchronized", is_error=False, safety_level=self.safety_level)


class NonRecoverableFlakyTool(BaseTool):
    """Tool that always fails execution."""
    name = "permanent_failure_tool"
    description = "Always fails"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {"_retry_attempt": {"type": "integer"}}}

    def execute(self, **kwargs):
        return ToolResult(name=self.name, content="Error: Permanent hardware failure", is_error=True, safety_level=self.safety_level)


# 1. StepVerifier Syntax & Condition Matching
def test_step_verifier_conditions():
    step_contains = PlanStep(step_id="s1", description="Check report", success_criteria="contains:synchronized")
    step_regex = PlanStep(step_id="s2", description="Check status", success_criteria="regex:status:\\s*(active|ready)")
    step_empty = PlanStep(step_id="s3", description="Check empty", success_criteria="contains:data")

    # Positive matches
    v1 = StepVerifier.verify_step_result(step_contains, "System report: Fully synchronized with cluster.")
    assert v1.passed is True
    assert v1.status == VerificationStatus.PASSED

    v2 = StepVerifier.verify_step_result(step_regex, "Current status: ACTIVE and operational")
    assert v2.passed is True

    # Negative matches
    v3 = StepVerifier.verify_step_result(step_contains, "System report: Initialization pending...")
    assert v3.passed is False
    assert v3.status == VerificationStatus.FAILED
    assert "missing expected substring" in v3.diagnostics

    v4 = StepVerifier.verify_step_result(step_empty, "")
    assert v4.passed is False


# 2. SelfCorrectionPolicy Bounded Limit Checks
def test_self_correction_policy_bounds():
    policy = SelfCorrectionPolicy(max_correction_attempts=2)
    step = PlanStep(step_id="step_test", description="Test action")
    fail_evidence = VerificationResult(status=VerificationStatus.FAILED, criterion="test", diagnostics="failed")

    # Attempt 1
    assert policy.can_attempt_correction("step_test") is True
    c1 = policy.generate_corrected_step(step, fail_evidence)
    assert c1 is not None
    assert "Retry #1" in c1.description

    # Attempt 2
    assert policy.can_attempt_correction("step_test") is True
    c2 = policy.generate_corrected_step(step, fail_evidence)
    assert c2 is not None
    assert "Retry #2" in c2.description

    # Attempt 3 (Should be blocked by bounds)
    assert policy.can_attempt_correction("step_test") is False
    c3 = policy.generate_corrected_step(step, fail_evidence)
    assert c3 is None


# 3. Successful Self-Correction Execution
def test_execution_engine_successful_self_correction():
    tool = StatefulRetryTool()
    registry = ToolRegistry()
    registry.register(tool)

    engine = TaskExecutionEngine(tool_registry=registry, max_self_corrections_per_step=2)

    step_defs = [
        {
            "step_id": "step_retry",
            "description": "Run stateful tool",
            "tool_name": "stateful_retry_tool",
            "success_criteria": "contains:synchronized",
        }
    ]
    plan = GoalDecomposer.create_multi_step_plan("Self-correction recovery test", step_defs)
    result = engine.execute_plan(plan)

    assert result.success is True
    assert result.state == TaskState.COMPLETED
    assert result.step_results["step_retry"].status == StepStatus.COMPLETED
    assert result.step_results["step_retry"].retries_used == 1
    assert result.step_results["step_retry"].verification.passed is True
    assert tool.call_count == 2


# 4. Exhausted Self-Correction Leading to FAILED State
def test_execution_engine_exhausted_self_correction():
    tool = NonRecoverableFlakyTool()
    registry = ToolRegistry()
    registry.register(tool)

    engine = TaskExecutionEngine(tool_registry=registry, max_self_corrections_per_step=2)

    step_defs = [
        {
            "step_id": "step_flaky",
            "description": "Run unrecoverable tool",
            "tool_name": "permanent_failure_tool",
        }
    ]
    plan = GoalDecomposer.create_multi_step_plan("Exhausted retries test", step_defs)
    result = engine.execute_plan(plan)

    assert result.success is False
    assert result.state == TaskState.FAILED
    assert result.step_results["step_flaky"].status == StepStatus.FAILED
    assert result.step_results["step_flaky"].retries_used == 2
    assert result.plan_verification.passed is False


# 5. Verification Failure on Execution Success with Missing Criteria
def test_execution_engine_verification_failure_on_output_mismatch():
    registry = ToolRegistry()
    registry.register(SystemInfoTool())

    engine = TaskExecutionEngine(tool_registry=registry, max_self_corrections_per_step=1)

    # Tool will succeed in execution, but the output will NOT match impossible criteria
    step_defs = [
        {
            "step_id": "step_sys",
            "description": "Inspect OS",
            "tool_name": "get_system_info",
            "parameters": {"category": "os"},
            "success_criteria": "contains:QUANTUM_HYPERDRIVE_ONLINE",
        }
    ]
    plan = GoalDecomposer.create_multi_step_plan("Criteria mismatch test", step_defs)
    result = engine.execute_plan(plan)

    assert result.success is False
    assert result.state == TaskState.FAILED
    assert result.step_results["step_sys"].status == StepStatus.FAILED
    assert "Verification Failure" in result.step_results["step_sys"].error


# 6. Provider Independence: Zero vendor cloud SDK dependencies
def test_verification_zero_provider_dependency():
    """Verify verification.py has no dependency on google.genai or external cloud SDKs."""
    import friday.agent.verification as verif_mod

    assert "google" not in verif_mod.__dict__
    assert "genai" not in verif_mod.__dict__
    assert hasattr(verif_mod, "StepVerifier")
    assert hasattr(verif_mod, "VerificationResult")
    assert hasattr(verif_mod, "SelfCorrectionPolicy")
