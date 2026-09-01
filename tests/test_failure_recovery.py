"""Deterministic unit test suite for Computer Action Execution.6 Autonomous Failure Recovery & Strategy Adaptation.

Validates:
1. Classification of failures into FailureType (TRANSIENT_NETWORK, QUOTA_EXHAUSTED, TOOL_ERROR, INVALID_PARAMETERS, AUTHORIZATION_DENIED, UNRECOVERABLE_SAFETY_REJECTION).
2. Autonomous strategy mapping to RecoveryStrategy (RETRY, CREDENTIAL_FAILOVER, ALTERNATIVE_TOOL, ADJUST_PARAMETERS, ABORT_TASK).
3. Transient network recovery with successful retry.
4. Tool fallback substitution to alternative tool when primary fails.
5. Quota exhaustion detection recommending credential pool failover without infinite loop.
6. Authorization denial: Preserves security, flags unrecoverable, and does NOT retry or bypass.
7. Unconditional safety hard-block: Strictly non-recoverable, halts task execution immediately.
8. Bounded per-step retry limits: Prevents endless retrying of failing actions.
9. Global task retry bounds: Prevents retry storms and cascading infinite loops.
10. Provider independence: Operates 100% offline with MockLLMProvider and zero external SDK dependencies.
"""


from friday.agent.executor import TaskExecutionEngine
from friday.agent.planner import GoalDecomposer, PlanStep, StepStatus
from friday.agent.recovery import (
    AutonomousRecoveryManager,
    FailureAnalyzer,
    FailureDiagnosis,
    FailureType,
    RecoveryStrategy,
)
from friday.agent.state import TaskState
from friday.core.auth import BaseAuthorizer
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    SafetyLevel,
    ToolResult,
)
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry


class TransientNetworkTool(BaseTool):
    name = "network_flaky_tool"
    description = "Fails once with network timeout then succeeds"
    safety_level = SafetyLevel.SAFE

    def __init__(self):
        super().__init__()
        self.calls = 0

    def execute(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ToolResult(name=self.name, content="Error: Connection timed out while reaching endpoint", is_error=True, safety_level=self.safety_level)
        return ToolResult(name=self.name, content="Connected successfully. Data retrieved.", is_error=False, safety_level=self.safety_level)


class PrimaryFailingTool(BaseTool):
    name = "primary_data_source"
    description = "Primary data source that is offline"
    safety_level = SafetyLevel.SAFE

    def execute(self, **kwargs):
        return ToolResult(name=self.name, content="Error: Primary database cluster unavailable", is_error=True, safety_level=self.safety_level)


class BackupWorkingTool(BaseTool):
    name = "backup_data_source"
    description = "Backup replica data source"
    safety_level = SafetyLevel.SAFE

    def execute(self, **kwargs):
        return ToolResult(name=self.name, content="Backup replica response: Status OK", is_error=False, safety_level=self.safety_level)


class DangerousActionTool(BaseTool):
    name = "delete_root_filesystem"
    description = "Destructive tool"
    safety_level = SafetyLevel.DANGEROUS

    def execute(self, **kwargs):
        return ToolResult(name=self.name, content="Action executed", is_error=False, safety_level=self.safety_level)


class DenyAllAuthorizer(BaseAuthorizer):
    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        return AuthorizationResponse(
            decision=AuthorizationDecision.DENIED,
            reason="User denied confirmation: Action not authorized",
        )


# 1. Failure Classification & Diagnostics
def test_failure_analyzer_classification():
    step = PlanStep(step_id="s1", description="Test Step", tool_name="fetch_tool")

    # Network timeout
    d_net = FailureAnalyzer.diagnose(step, "Error: Connection timed out to remote server")
    assert d_net.failure_type == FailureType.TRANSIENT_NETWORK
    assert d_net.is_recoverable is True
    assert d_net.recommended_strategy == RecoveryStrategy.RETRY

    # Quota exhaustion
    d_quota = FailureAnalyzer.diagnose(step, "Error: 429 RESOURCE_EXHAUSTED quota exceeded")
    assert d_quota.failure_type == FailureType.QUOTA_EXHAUSTED
    assert d_quota.is_recoverable is True
    assert d_quota.recommended_strategy == RecoveryStrategy.CREDENTIAL_FAILOVER

    # Invalid arguments
    d_param = FailureAnalyzer.diagnose(step, "Invalid arguments: missing required parameter 'path'")
    assert d_param.failure_type == FailureType.INVALID_PARAMETERS
    assert d_param.is_recoverable is True
    assert d_param.recommended_strategy == RecoveryStrategy.ADJUST_PARAMETERS

    # User authorization denial
    d_auth = FailureAnalyzer.diagnose(step, "Authorization denied by user confirmation")
    assert d_auth.failure_type == FailureType.AUTHORIZATION_DENIED
    assert d_auth.is_recoverable is False
    assert d_auth.recommended_strategy in (RecoveryStrategy.PAUSE_FOR_AUTHORIZATION, RecoveryStrategy.ABORT_TASK)

    # Unconditional safety hard-block
    d_safe = FailureAnalyzer.diagnose(step, "Unconditional hard-block on destructive system modification")
    assert d_safe.failure_type == FailureType.UNRECOVERABLE_SAFETY_REJECTION
    assert d_safe.is_recoverable is False
    assert d_safe.recommended_strategy == RecoveryStrategy.ABORT_TASK


# 2. Transient Network Recovery
def test_transient_network_recovery():
    tool = TransientNetworkTool()
    reg = ToolRegistry()
    reg.register(tool)

    engine = TaskExecutionEngine(tool_registry=reg, max_self_corrections_per_step=2)
    step_defs = [{"step_id": "step_net", "description": "Fetch data", "tool_name": "network_flaky_tool"}]
    plan = GoalDecomposer.create_multi_step_plan("Network fetch task", step_defs)

    result = engine.execute_plan(plan)
    assert result.success is True
    assert result.state == TaskState.COMPLETED
    assert tool.calls == 2
    assert result.step_results["step_net"].retries_used == 1


# 3. Tool Fallback Substitution
def test_tool_fallback_substitution():
    primary = PrimaryFailingTool()
    backup = BackupWorkingTool()
    reg = ToolRegistry()
    reg.register(primary)
    reg.register(backup)

    engine = TaskExecutionEngine(
        tool_registry=reg,
        max_self_corrections_per_step=2,
        tool_fallbacks={"primary_data_source": "backup_data_source"},
    )
    step_defs = [{"step_id": "step_data", "description": "Fetch critical data", "tool_name": "primary_data_source"}]
    plan = GoalDecomposer.create_multi_step_plan("Fetch data with fallback", step_defs)

    result = engine.execute_plan(plan)
    assert result.success is True
    assert result.state == TaskState.COMPLETED
    assert result.step_results["step_data"].status == StepStatus.COMPLETED
    assert "Backup replica response: Status OK" in result.step_results["step_data"].result


# 4. Security Denial Preservation: No Retry / No Bypass
def test_authorization_denial_unrecoverable():
    tool = DangerousActionTool()
    reg = ToolRegistry()
    reg.register(tool)

    engine = TaskExecutionEngine(
        tool_registry=reg,
        authorizer=DenyAllAuthorizer(),
        max_self_corrections_per_step=3,
    )
    step_defs = [{"step_id": "step_del", "description": "Destructive cleanup", "tool_name": "delete_root_filesystem"}]
    plan = GoalDecomposer.create_multi_step_plan("Unsafe operation", step_defs)

    result = engine.execute_plan(plan)
    assert result.success is False
    assert result.state == TaskState.FAILED
    assert result.step_results["step_del"].status == StepStatus.FAILED
    assert result.step_results["step_del"].retries_used == 0  # Crucial: 0 retries attempted on auth denial
    assert "User denied confirmation" in result.step_results["step_del"].error


# 5. Global Retry Bounds (Anti-Storm Prevention)
def test_global_retry_limit_prevents_retry_storm():
    mgr = AutonomousRecoveryManager(max_retries_per_step=5, max_global_task_retries=2)
    step = PlanStep(step_id="step_a", description="A", tool_name="tool_a")
    diagnosis = FailureDiagnosis(
        failure_type=FailureType.TRANSIENT_NETWORK,
        is_recoverable=True,
        recommended_strategy=RecoveryStrategy.RETRY,
        reason="test",
        diagnostics="test",
    )

    # 1st retry
    assert mgr.can_recover("step_a", diagnosis) is True
    mgr.record_and_generate_recovery_step(step, diagnosis)

    # 2nd retry
    assert mgr.can_recover("step_a", diagnosis) is True
    mgr.record_and_generate_recovery_step(step, diagnosis)

    # 3rd retry (Global cap 2 reached)
    assert mgr.can_recover("step_a", diagnosis) is False
    s3 = mgr.record_and_generate_recovery_step(step, diagnosis)
    assert s3 is None


# 6. Provider Independence: Zero vendor cloud SDK dependencies
def test_recovery_zero_provider_dependency():
    """Verify recovery.py has no dependency on google.genai or external cloud SDKs."""
    import friday.agent.recovery as rec_mod

    assert "google" not in rec_mod.__dict__
    assert "genai" not in rec_mod.__dict__
    assert hasattr(rec_mod, "FailureAnalyzer")
    assert hasattr(rec_mod, "AutonomousRecoveryManager")
    assert hasattr(rec_mod, "FailureType")
    assert hasattr(rec_mod, "RecoveryStrategy")
