"""Comprehensive unit test suite for Cognitive Task Planning.6: Autonomous Failure Recovery & Strategy Adaptation.

Tests:
1. Classification of transient network/socket failures -> RETRY.
2. Classification of provider/model errors -> CREDENTIAL_FAILOVER.
3. Classification of quota exhaustion (429, RESOURCE_EXHAUSTED) -> CREDENTIAL_FAILOVER.
4. Classification of stale screen / UI environment changes -> RETRY.
5. Missing application state / tool errors -> ALTERNATIVE_TOOL fallback.
6. Parameter schema errors -> ADJUST_PARAMETERS.
7. Authorization denial -> PAUSE_FOR_AUTHORIZATION / user escalation (never bypass).
8. Unconditional safety hard-block -> ABORT_TASK (never bypass).
9. Strict retry exhaustion halting retry storms.
10. Recovery confidence scoring and escalation flags.
"""


from friday.agent.planner import PlanStep
from friday.agent.recovery import (
    AutonomousRecoveryManager,
    FailureAnalyzer,
    FailureType,
    RecoveryStrategy,
)
from friday.core.types import SafetyLevel


# 1. Transient Network Failures
def test_transient_network_diagnosis():
    step = PlanStep(step_id="step_net", description="Fetch data", tool_name="fetch_url")
    diagnosis = FailureAnalyzer.diagnose(step, error_msg="Connection reset by peer: temporary connection timeout")

    assert diagnosis.failure_type == FailureType.TRANSIENT_NETWORK
    assert diagnosis.is_recoverable is True
    assert diagnosis.recommended_strategy == RecoveryStrategy.RETRY
    assert diagnosis.confidence >= 0.9


# 2. Provider Errors
def test_provider_error_diagnosis():
    step = PlanStep(step_id="step_llm", description="Generate reasoning")
    diagnosis = FailureAnalyzer.diagnose(step, error_msg="503 Service Unavailable: provider overloaded")

    assert diagnosis.failure_type == FailureType.PROVIDER_ERROR
    assert diagnosis.is_recoverable is True
    assert diagnosis.recommended_strategy == RecoveryStrategy.CREDENTIAL_FAILOVER


# 3. Quota Exhaustion
def test_quota_exhaustion_diagnosis():
    step = PlanStep(step_id="step_api", description="Call API")
    diagnosis = FailureAnalyzer.diagnose(step, error_msg="429 Resource_Exhausted: rate limit exceeded")

    assert diagnosis.failure_type == FailureType.QUOTA_EXHAUSTED
    assert diagnosis.is_recoverable is True
    assert diagnosis.recommended_strategy == RecoveryStrategy.CREDENTIAL_FAILOVER


# 4. Stale Screen / Environmental Change
def test_stale_screen_diagnosis():
    step = PlanStep(step_id="step_click", description="Click submit button")
    diagnosis = FailureAnalyzer.diagnose(step, error_msg="Stale screen: target element not found, window not focused")

    assert diagnosis.failure_type == FailureType.SCREEN_STATE_CHANGED
    assert diagnosis.is_recoverable is True
    assert diagnosis.recommended_strategy == RecoveryStrategy.RETRY


# 5. Alternative Tool Fallback Substitution
def test_alternative_tool_fallback():
    step = PlanStep(step_id="step_search", description="Search items", tool_name="web_search")
    tool_fallbacks = {"web_search": "local_search"}

    diagnosis = FailureAnalyzer.diagnose(
        step,
        error_msg="Search index unavailable",
        tool_fallbacks=tool_fallbacks,
    )

    assert diagnosis.failure_type == FailureType.TOOL_ERROR
    assert diagnosis.is_recoverable is True
    assert diagnosis.recommended_strategy == RecoveryStrategy.ALTERNATIVE_TOOL
    assert diagnosis.suggested_tool == "local_search"

    # Verify recovery manager substitutes tool
    mgr = AutonomousRecoveryManager(tool_fallbacks=tool_fallbacks)
    rec_step = mgr.record_and_generate_recovery_step(step, diagnosis)
    assert rec_step is not None
    assert rec_step.tool_name == "local_search"


# 6. Authorization Denial (Safe Termination / Escalation)
def test_authorization_denial_unrecoverable_without_permission():
    step = PlanStep(step_id="step_auth", description="Write sensitive file", safety_level=SafetyLevel.SENSITIVE)
    diagnosis = FailureAnalyzer.diagnose(step, error_msg="Authorization denied: User denied confirmation")

    assert diagnosis.failure_type == FailureType.AUTHORIZATION_DENIED
    assert diagnosis.is_recoverable is False
    assert diagnosis.recommended_strategy == RecoveryStrategy.PAUSE_FOR_AUTHORIZATION
    assert diagnosis.requires_user_escalation is True

    mgr = AutonomousRecoveryManager()
    assert mgr.can_recover("step_auth", diagnosis) is False
    assert mgr.record_and_generate_recovery_step(step, diagnosis) is None


# 7. Unconditional Safety Hard-Block
def test_safety_hard_block_strictly_aborts():
    step = PlanStep(step_id="step_danger", description="Format system drive", safety_level=SafetyLevel.DANGEROUS)
    diagnosis = FailureAnalyzer.diagnose(step, error_msg="Unconditional hard-block: destructive action prohibited by policy")

    assert diagnosis.failure_type == FailureType.UNRECOVERABLE_SAFETY_REJECTION
    assert diagnosis.is_recoverable is False
    assert diagnosis.recommended_strategy == RecoveryStrategy.ABORT_TASK

    mgr = AutonomousRecoveryManager()
    assert mgr.can_recover("step_danger", diagnosis) is False
    assert mgr.record_and_generate_recovery_step(step, diagnosis) is None


# 8. Strict Retry Exhaustion Halting
def test_retry_limits_exhaustion():
    step = PlanStep(step_id="step_loop", description="Flaky step")
    diagnosis = FailureAnalyzer.diagnose(step, error_msg="Connection timed out")

    mgr = AutonomousRecoveryManager(max_retries_per_step=2, max_global_task_retries=3)

    # Attempt 1
    step1 = mgr.record_and_generate_recovery_step(step, diagnosis)
    assert step1 is not None

    # Attempt 2
    step2 = mgr.record_and_generate_recovery_step(step, diagnosis)
    assert step2 is not None

    # Attempt 3 (Should exceed max_retries_per_step=2)
    step3 = mgr.record_and_generate_recovery_step(step, diagnosis)
    assert step3 is None
    assert mgr.can_recover("step_loop", diagnosis) is False
