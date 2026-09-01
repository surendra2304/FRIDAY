"""Comprehensive Test Suite for FRIDAY's Structured Cognitive Intelligence Loop.

Test Type: UNIT / INTEGRATION / SECURITY

Validates:
1. 10-Phase Cognitive Loop: UNDERSTAND -> CLARIFY -> PLAN -> CHECK PLAN -> AUTHORIZE -> EXECUTE -> OBSERVE -> VERIFY -> LEARN -> COMPLETE.
2. Confidence estimation calibration across understanding, planning, perception, tool selection, and verification.
3. Low confidence triggers CLARIFY with targeted questions instead of hallucinated certainty.
4. Active heuristics: Accurately identifies when information is lacking, perception is needed, memory is useful, and tools are necessary.
5. Security Invariant: High confidence NEVER bypasses authorization gating for sensitive/dangerous actions.
6. Verification & learning: Verification failures reduce confidence and trigger bounded correction rather than false success.
"""

import pytest

# Explicit test markers
pytestmark = [pytest.mark.unit, pytest.mark.integration, pytest.mark.security]

from friday.agent.cognitive import (
    CognitiveIntelligenceEngine,
    CognitivePhase,
)
from friday.agent.planner import PlanStep, TaskPlan
from friday.agent.verification import VerificationResult, VerificationStatus
from friday.core.auth import DefaultSecureAuthorizer, SafetyLevel
from friday.core.types import ToolResult
from friday.llm.mock_provider import MockLLMProvider

# ============================================================================
# 1. UNDERSTAND & CLARIFY on Low Confidence / Missing Info
# ============================================================================

def test_underspecified_goal_triggers_clarify_with_low_confidence():
    """Verify that ambiguous or underspecified input yields low confidence and triggers CLARIFY."""
    engine = CognitiveIntelligenceEngine(llm_provider=MockLLMProvider())

    decision = engine.evaluate_request("do it")

    assert decision.current_phase == CognitivePhase.CLARIFY
    assert decision.lacks_information is True
    assert decision.confidence.understanding_confidence < 0.65
    assert decision.clarification_prompt is not None
    assert decision.should_continue_autonomously is False


def test_clear_goal_yields_high_confidence_and_proceeds_to_plan():
    """Verify unambiguous goal yields high confidence and moves directly to PLAN phase."""
    engine = CognitiveIntelligenceEngine(llm_provider=MockLLMProvider())

    decision = engine.evaluate_request(
        "Calculate 15 * 34 and save the result to output.txt",
        available_tools=["calculator", "write_file"]
    )

    assert decision.current_phase == CognitivePhase.PLAN
    assert decision.lacks_information is False
    assert decision.confidence.understanding_confidence >= 0.8
    assert decision.tool_necessary is True
    assert decision.should_continue_autonomously is True


# ============================================================================
# 2. Perception & Memory Detection Heuristics
# ============================================================================

def test_visual_and_memory_heuristics_activation():
    """Verify engine detects when perception is required and when memory is useful."""
    engine = CognitiveIntelligenceEngine(llm_provider=MockLLMProvider())

    # Visual perception request
    vis_decision = engine.evaluate_request("Look at the screen and click the submit button")
    assert vis_decision.perception_required is True
    assert vis_decision.confidence.perception_confidence > 0.8

    # Memory recall request
    mem_decision = engine.evaluate_request("Remember what file we edited earlier today")
    assert mem_decision.memory_useful is True


# ============================================================================
# 3. CHECK_PLAN & Authorization Invariant (Confidence != Authorization Bypass)
# ============================================================================

def test_high_confidence_never_bypasses_authorization():
    """CRITICAL SECURITY INVARIANT: Even 1.0 confidence cannot bypass authorizer on sensitive/dangerous steps."""
    engine = CognitiveIntelligenceEngine(llm_provider=MockLLMProvider(), authorizer=DefaultSecureAuthorizer())

    sensitive_plan = TaskPlan(
        goal="Delete system database",
        steps=[
            PlanStep(
                step_id="s1",
                description="Drop production database",
                tool_name="database_admin",
                parameters={"action": "drop_all"},
                safety_level=SafetyLevel.DANGEROUS,
            )
        ]
    )

    decision = engine.check_plan_safety_and_confidence(sensitive_plan)

    assert decision.current_phase == CognitivePhase.AUTHORIZE
    assert decision.plan_unsafe is True
    assert decision.requires_user_confirmation is True
    # Must NOT continue autonomously without human approval
    assert decision.should_continue_autonomously is False


def test_safe_plan_proceeds_autonomously():
    """Verify safe read-only plans execute autonomously without interrupting user."""
    engine = CognitiveIntelligenceEngine(llm_provider=MockLLMProvider(), authorizer=DefaultSecureAuthorizer())

    safe_plan = TaskPlan(
        goal="Check system time and date",
        steps=[
            PlanStep(
                step_id="s1",
                description="Get current time",
                tool_name="get_time_date",
                parameters={"timezone": "UTC"},
                safety_level=SafetyLevel.SAFE,
            )
        ]
    )

    decision = engine.check_plan_safety_and_confidence(safe_plan)

    assert decision.current_phase == CognitivePhase.EXECUTE
    assert decision.plan_unsafe is False
    assert decision.requires_user_confirmation is False
    assert decision.should_continue_autonomously is True


# ============================================================================
# 4. OBSERVE, VERIFY, & LEARN Calibration
# ============================================================================

def test_verification_failure_reduces_confidence_and_halts_learning():
    """Verify that failed step verification reduces verification confidence and blocks false progression."""
    engine = CognitiveIntelligenceEngine(llm_provider=MockLLMProvider())

    step = PlanStep(step_id="s1", description="Write file", tool_name="write_file")
    tool_res = ToolResult(name="write_file", content="Success", is_error=False)
    failed_verif = VerificationResult(
        status=VerificationStatus.FAILED,
        criterion="File exists on disk",
        evidence="File not found at destination path",
        confidence=0.0,
        is_real_success=False,
    )

    decision = engine.evaluate_verification_and_learning(
        step=step,
        step_result=tool_res,
        verification=failed_verif,
    )

    assert decision.current_phase == CognitivePhase.OBSERVE
    assert decision.confidence.verification_confidence < 0.5
    assert decision.should_continue_autonomously is False


def test_verification_success_advances_to_learning_phase():
    """Verify that verified outcomes advance to the LEARN phase with high confidence."""
    engine = CognitiveIntelligenceEngine(llm_provider=MockLLMProvider())

    step = PlanStep(step_id="s1", description="Calculate sum", tool_name="calculator")
    tool_res = ToolResult(name="calculator", content="42", is_error=False)
    passed_verif = VerificationResult(
        status=VerificationStatus.PASSED,
        criterion="Arithmetic matches output",
        evidence="42 matches expression",
        confidence=1.0,
        is_real_success=True,
    )

    decision = engine.evaluate_verification_and_learning(
        step=step,
        step_result=tool_res,
        verification=passed_verif,
    )

    assert decision.current_phase == CognitivePhase.LEARN
    assert decision.confidence.verification_confidence == 1.0
    assert decision.should_continue_autonomously is True
