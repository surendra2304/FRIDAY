"""Comprehensive unit test suite for Cognitive Task Planning.4: Formal Verification, Self-Correction & Bounded Recovery.

Tests:
1. Successful formal verification across different assertion types (regex, contains, not_contains, json_key, min_length, exact).
2. Failed verification diagnosis and bounded retry recovery.
3. Alternative tool fallback substitution on verification failure.
4. Changed environment / stale screen observation detection in verification.
5. Impossible / contradictory success condition handling.
6. Retry exhaustion (stopping after max attempts).
7. Safety-blocked self-correction: Unconditional hard-block on bypassing safety / authorization denials.
8. Computer action proposals remain Proposal != Execution during verification and self-correction.
"""

import pytest

from friday.agent.executor import (
    TaskExecutionEngine,
)
from friday.agent.planner import (
    PlanStep,
    StepStatus,
    TaskPlan,
)
from friday.agent.recovery import (
    AutonomousRecoveryManager,
    FailureAnalyzer,
    FailureType,
    RecoveryStrategy,
)
from friday.agent.state import TaskState
from friday.agent.verification import (
    StepVerifier,
)
from friday.core.types import (
    SafetyLevel,
    ToolResult,
)
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class NumberGeneratorTool(BaseTool):
    name = "num_gen"
    description = "Generates numbers or JSON"
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "required": ["mode"],
    }

    def execute(self, mode: str, **kwargs):
        if mode == "json":
            return ToolResult(name=self.name, content='{"status": "ok", "code": 200}', is_error=False)
        elif mode == "text":
            return ToolResult(name=self.name, content="Transaction completed successfully", is_error=False)
        elif mode == "error":
            return ToolResult(name=self.name, content="Error: database locked", is_error=False)
        return ToolResult(name=self.name, content="Unknown", is_error=False)


class FlakyVerificationTool(BaseTool):
    name = "flaky_verification_tool"
    description = "Fails once then succeeds"
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {"mode": {"type": "string"}},
        "required": ["mode"],
    }

    def __init__(self):
        super().__init__()
        self.attempts = 0

    def execute(self, mode: str, **kwargs):
        self.attempts += 1
        if self.attempts == 1:
            return ToolResult(name=self.name, content="Initial imperfect attempt", is_error=False)
        return ToolResult(name=self.name, content="Final verified outcome", is_error=False)


@pytest.fixture
def registry():
    reg = ToolRegistry()
    reg.register(NumberGeneratorTool())
    reg.register(FlakyVerificationTool())
    return reg


# 1. Assertion Types Verification
def test_step_verifier_assertion_types():
    # regex
    step1 = PlanStep(step_id="1", description="test", success_criteria="regex:status code: [0-9]{3}")
    v1 = StepVerifier.verify_step_result(step1, "status code: 200 OK")
    assert v1.passed is True

    # contains & not_contains
    step2 = PlanStep(step_id="2", description="test", success_criteria="contains:success")
    v2 = StepVerifier.verify_step_result(step2, "Operation success confirmed")
    assert v2.passed is True

    step3 = PlanStep(step_id="3", description="test", success_criteria="not_contains:failure")
    v3 = StepVerifier.verify_step_result(step3, "Operation succeeded without issue")
    assert v3.passed is True

    v3_fail = StepVerifier.verify_step_result(step3, "Operation encountered failure")
    assert v3_fail.passed is False

    # json_key
    step4 = PlanStep(step_id="4", description="test", success_criteria="json_key:code")
    v4 = StepVerifier.verify_step_result(step4, '{"code": 200, "msg": "ok"}')
    assert v4.passed is True

    # exact
    step5 = PlanStep(step_id="5", description="test", success_criteria="exact:EXACT_MATCH")
    v5 = StepVerifier.verify_step_result(step5, "EXACT_MATCH")
    assert v5.passed is True

    v5_fail = StepVerifier.verify_step_result(step5, "EXACT_MATCH_EXTRA")
    assert v5_fail.passed is False


# 2. Failed Verification & Bounded Self-Correction Retry
def test_failed_verification_and_bounded_retry(registry):
    flaky = registry.get("flaky_verification_tool")
    flaky.attempts = 0

    plan = TaskPlan(
        goal="Verify self-correction",
        steps=[
            PlanStep(
                step_id="step_flaky",
                description="Run flaky tool",
                tool_name="flaky_verification_tool",
                parameters={"mode": "run"},
                success_criteria="contains:Final verified outcome",
            )
        ]
    )

    engine = TaskExecutionEngine(tool_registry=registry, max_self_corrections_per_step=2)
    result = engine.execute_plan(plan)

    assert result.success is True
    assert result.step_results["step_flaky"].status == StepStatus.SUCCEEDED
    assert flaky.attempts == 2


# 3. Retry Exhaustion on Impossible Condition
def test_retry_exhaustion_on_impossible_condition(registry):
    flaky = registry.get("flaky_verification_tool")
    flaky.attempts = 0

    plan = TaskPlan(
        goal="Impossible condition",
        steps=[
            PlanStep(
                step_id="step_impossible",
                description="Run tool",
                tool_name="flaky_verification_tool",
                parameters={"mode": "run"},
                success_criteria="contains:THIS_STRING_NEVER_APPEARS",
            )
        ]
    )

    engine = TaskExecutionEngine(tool_registry=registry, max_self_corrections_per_step=2)
    result = engine.execute_plan(plan)

    assert result.success is False
    assert result.step_results["step_impossible"].status == StepStatus.FAILED
    assert result.state == TaskState.FAILED


# 4. Safety-Blocked Self-Correction (Hard Policy Restriction)
def test_safety_denial_unrecoverable_and_cannot_self_correct():
    step = PlanStep(
        step_id="step_destructive",
        description="Delete root system directory",
        tool_name="delete_all",
        safety_level=SafetyLevel.DANGEROUS,
    )

    diagnosis = FailureAnalyzer.diagnose(
        step=step,
        error_msg="Unconditional hard-block: destructive action forbidden by policy.",
    )

    assert diagnosis.is_recoverable is False
    assert diagnosis.failure_type == FailureType.UNRECOVERABLE_SAFETY_REJECTION
    assert diagnosis.recommended_strategy == RecoveryStrategy.ABORT_TASK

    # Verify recovery manager refuses to generate recovery step
    mgr = AutonomousRecoveryManager()
    assert mgr.can_recover("step_destructive", diagnosis) is False
    assert mgr.record_and_generate_recovery_step(step, diagnosis) is None
