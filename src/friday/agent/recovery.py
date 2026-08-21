# -*- coding: utf-8 -*-
"""Autonomous Failure Recovery & Strategy Adaptation for FRIDAY.

Provides:
- Failure Classification (`FailureType`):
  * TRANSIENT_NETWORK (e.g. socket/connect error)
  * QUOTA_EXHAUSTED (e.g. 429, RESOURCE_EXHAUSTED)
  * TOOL_ERROR (e.g. execution runtime error)
  * INVALID_PARAMETERS (e.g. schema validation error)
  * UNAVAILABLE_RESOURCE (e.g. file/process not found)
  * VERIFICATION_FAILURE (e.g. assertions/criteria mismatch)
  * SCREEN_STATE_CHANGED (e.g. target UI element shifted/disappeared)
  * AUTHORIZATION_DENIED (user/policy denied permission)
  * UNRECOVERABLE_SAFETY_REJECTION (hard block on dangerous actions)
  * UNKNOWN_FAILURE

- Recovery Strategy (`RecoveryStrategy`):
  * RETRY (transient hiccups)
  * CREDENTIAL_FAILOVER (switch API key / provider in pool)
  * ALTERNATIVE_TOOL (fallback to secondary tool)
  * ADJUST_PARAMETERS (correct arguments)
  * REQUEST_CLARIFICATION (user guidance needed)
  * ABORT_TASK (unrecoverable or safety hard block)

- `FailureAnalyzer` & `AutonomousRecoveryManager`:
  * Evaluates failure diagnostics and safety levels.
  * Ensures dangerous action denials are NEVER bypassed or auto-retried.
  * Enforces global task retry limits and per-step retry limits to eliminate retry storms and infinite loops.
  * 100% provider-independent and testable offline.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from friday.agent.planner import PlanStep, StepStatus
from friday.agent.verification import VerificationResult
from friday.core.logging import get_logger

logger = get_logger("agent.recovery")


class FailureType(str, Enum):
    """Categorized failure types during multi-step execution."""
    TRANSIENT_NETWORK = "TRANSIENT_NETWORK"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    TOOL_ERROR = "TOOL_ERROR"
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    PLANNING_ERROR = "PLANNING_ERROR"
    INVALID_PARAMETERS = "INVALID_PARAMETERS"
    UNAVAILABLE_RESOURCE = "UNAVAILABLE_RESOURCE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    SCREEN_STATE_CHANGED = "SCREEN_STATE_CHANGED"
    AUTHORIZATION_DENIED = "AUTHORIZATION_DENIED"
    SAFETY_VIOLATION = "SAFETY_VIOLATION"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    UNRECOVERABLE_SAFETY_REJECTION = "UNRECOVERABLE_SAFETY_REJECTION"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class RecoveryStrategy(str, Enum):
    """Autonomous recovery strategies."""
    RETRY = "RETRY"
    CREDENTIAL_FAILOVER = "CREDENTIAL_FAILOVER"
    ALTERNATIVE_TOOL = "ALTERNATIVE_TOOL"
    ADJUST_PARAMETERS = "ADJUST_PARAMETERS"
    REPLAN = "REPLAN"
    REQUEST_CLARIFICATION = "REQUEST_CLARIFICATION"
    ESCALATE_TO_USER = "ESCALATE_TO_USER"
    PAUSE_FOR_AUTHORIZATION = "PAUSE_FOR_AUTHORIZATION"
    ABORT_TASK = "ABORT_TASK"


@dataclass
class FailureDiagnosis:
    """Structured diagnosis of a step or task failure."""
    failure_type: FailureType
    is_recoverable: bool
    recommended_strategy: RecoveryStrategy
    reason: str
    diagnostics: str
    confidence: float = 1.0
    suggested_tool: Optional[str] = None
    suggested_params: Optional[Dict[str, Any]] = None
    requires_user_escalation: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_type": self.failure_type.value,
            "is_recoverable": self.is_recoverable,
            "recommended_strategy": self.recommended_strategy.value,
            "reason": self.reason,
            "diagnostics": self.diagnostics,
            "confidence": self.confidence,
            "suggested_tool": self.suggested_tool,
            "requires_user_escalation": self.requires_user_escalation,
            "timestamp": self.timestamp.isoformat(),
        }


class FailureAnalyzer:
    """Deterministic failure analysis engine."""

    # Unrecoverable security denial patterns
    SECURITY_DENIAL_PATTERNS = [
        "hard block",
        "unconditional hard-block",
        "authorization denied",
        "user denied confirmation",
        "denied by policy",
        "destructive system modification",
        "security constraint",
        "prohibited request",
    ]

    # Quota exhaustion patterns
    QUOTA_PATTERNS = [
        "429",
        "quota",
        "resource_exhausted",
        "rate limit",
        "too many requests",
        "credits exhausted",
    ]

    # Provider / LLM crash patterns
    PROVIDER_PATTERNS = [
        "model unavailable",
        "503 service unavailable",
        "bad gateway",
        "provider connection refused",
        "overloaded",
    ]

    # Transient network patterns
    NETWORK_PATTERNS = [
        "connection reset",
        "connection timed out",
        "socket error",
        "remote end closed",
        "temporary connection timeout",
        "econnrefused",
    ]

    # Stale UI / Environmental patterns
    SCREEN_PATTERNS = [
        "stale screen",
        "element not found",
        "window not focused",
        "ui shifted",
        "screen changed",
    ]

    # Parameter error patterns
    PARAM_PATTERNS = [
        "invalid arguments",
        "missing required parameter",
        "unexpected parameter",
        "schema validation failed",
        "type error",
    ]

    @classmethod
    def diagnose(
        cls,
        step: PlanStep,
        error_msg: str,
        verification: Optional[VerificationResult] = None,
        tool_fallbacks: Optional[Dict[str, str]] = None,
    ) -> FailureDiagnosis:
        """Classify a step failure and determine whether it is safely recoverable."""
        err_lower = (error_msg or "").lower()
        diag_lower = (verification.diagnostics if verification and verification.diagnostics else "").lower()
        combined_err = f"{err_lower} {diag_lower}".strip()

        # 1. Check Unrecoverable Security or Authorization Denials
        for pattern in cls.SECURITY_DENIAL_PATTERNS:
            if pattern in combined_err:
                if "hard-block" in combined_err or "destructive" in combined_err or "prohibited" in combined_err:
                    return FailureDiagnosis(
                        failure_type=FailureType.UNRECOVERABLE_SAFETY_REJECTION,
                        is_recoverable=False,
                        recommended_strategy=RecoveryStrategy.ABORT_TASK,
                        reason="Unrecoverable safety rule triggered: Action is strictly forbidden.",
                        diagnostics=error_msg,
                        confidence=1.0,
                        requires_user_escalation=False,
                    )
                return FailureDiagnosis(
                    failure_type=FailureType.AUTHORIZATION_DENIED,
                    is_recoverable=False,
                    recommended_strategy=RecoveryStrategy.PAUSE_FOR_AUTHORIZATION,
                    reason="Authorization was denied by user or secure policy.",
                    diagnostics=error_msg,
                    confidence=1.0,
                    requires_user_escalation=True,
                )

        # 2. Check Quota Exhaustion
        for pattern in cls.QUOTA_PATTERNS:
            if pattern in combined_err:
                return FailureDiagnosis(
                    failure_type=FailureType.QUOTA_EXHAUSTED,
                    is_recoverable=True,
                    recommended_strategy=RecoveryStrategy.CREDENTIAL_FAILOVER,
                    reason="API quota exhausted on active credential.",
                    diagnostics=error_msg,
                    confidence=0.95,
                )

        # 3. Check Provider Errors
        for pattern in cls.PROVIDER_PATTERNS:
            if pattern in combined_err:
                return FailureDiagnosis(
                    failure_type=FailureType.PROVIDER_ERROR,
                    is_recoverable=True,
                    recommended_strategy=RecoveryStrategy.CREDENTIAL_FAILOVER,
                    reason="Model provider service unavailable or overloaded.",
                    diagnostics=error_msg,
                    confidence=0.9,
                )

        # 4. Check Stale UI / Environmental State
        for pattern in cls.SCREEN_PATTERNS:
            if pattern in combined_err:
                return FailureDiagnosis(
                    failure_type=FailureType.SCREEN_STATE_CHANGED,
                    is_recoverable=True,
                    recommended_strategy=RecoveryStrategy.RETRY,
                    reason="Screen or UI environment changed during execution.",
                    diagnostics=error_msg,
                    confidence=0.85,
                )

        # 5. Check Transient Network / Timeout
        for pattern in cls.NETWORK_PATTERNS:
            if pattern in combined_err:
                return FailureDiagnosis(
                    failure_type=FailureType.TRANSIENT_NETWORK,
                    is_recoverable=True,
                    recommended_strategy=RecoveryStrategy.RETRY,
                    reason="Transient network or connection timeout encountered.",
                    diagnostics=error_msg,
                    confidence=0.9,
                )

        # 6. Check Invalid Parameters
        for pattern in cls.PARAM_PATTERNS:
            if pattern in combined_err:
                return FailureDiagnosis(
                    failure_type=FailureType.INVALID_PARAMETERS,
                    is_recoverable=True,
                    recommended_strategy=RecoveryStrategy.ADJUST_PARAMETERS,
                    reason="Tool arguments violated parameter schema or missing required fields.",
                    diagnostics=error_msg,
                    confidence=0.85,
                )

        # 7. Check Verification Failure
        if verification and not verification.passed:
            fallback_tool = tool_fallbacks.get(step.tool_name) if tool_fallbacks else None
            strategy = RecoveryStrategy.ALTERNATIVE_TOOL if fallback_tool else RecoveryStrategy.RETRY

            return FailureDiagnosis(
                failure_type=FailureType.VERIFICATION_FAILURE,
                is_recoverable=True,
                recommended_strategy=strategy,
                reason=f"Step output failed verification criteria: {verification.criterion}",
                diagnostics=verification.diagnostics or error_msg,
                suggested_tool=fallback_tool,
                confidence=0.8,
            )

        # 8. Fallback Tool Error
        fallback_tool = tool_fallbacks.get(step.tool_name) if tool_fallbacks else None
        if fallback_tool:
            return FailureDiagnosis(
                failure_type=FailureType.TOOL_ERROR,
                is_recoverable=True,
                recommended_strategy=RecoveryStrategy.ALTERNATIVE_TOOL,
                reason=f"Tool '{step.tool_name}' failed. Alternative tool available.",
                diagnostics=error_msg,
                suggested_tool=fallback_tool,
                confidence=0.85,
            )

        return FailureDiagnosis(
            failure_type=FailureType.TOOL_ERROR,
            is_recoverable=True,
            recommended_strategy=RecoveryStrategy.RETRY,
            reason="Tool returned error during execution.",
            diagnostics=error_msg,
            confidence=0.75,
        )


class AutonomousRecoveryManager:
    """Manages bounded recovery cycles across step and task lifecycles."""

    def __init__(
        self,
        max_retries_per_step: int = 2,
        max_global_task_retries: int = 5,
        tool_fallbacks: Optional[Dict[str, str]] = None,
    ) -> None:
        self.max_retries_per_step = max_retries_per_step
        self.max_global_task_retries = max_global_task_retries
        self.tool_fallbacks: Dict[str, str] = tool_fallbacks or {}

        self.step_retry_counts: Dict[str, int] = {}
        self.global_retry_count: int = 0
        self.diagnoses_history: List[FailureDiagnosis] = []

    def can_recover(self, step_id: str, diagnosis: FailureDiagnosis) -> bool:
        """Evaluate whether recovery may be attempted according to budgets and safety rules."""
        if not diagnosis.is_recoverable:
            logger.warning(f"Step '{step_id}': Failure is classified as UNRECOVERABLE ({diagnosis.failure_type.value}).")
            return False

        current_step_retries = self.step_retry_counts.get(step_id, 0)
        if current_step_retries >= self.max_retries_per_step:
            logger.warning(f"Step '{step_id}': Exhausted per-step retry limit ({self.max_retries_per_step}).")
            return False

        if self.global_retry_count >= self.max_global_task_retries:
            logger.warning(f"Task: Exhausted global task retry limit ({self.max_global_task_retries}). Halting retry storm.")
            return False

        return True

    def record_and_generate_recovery_step(
        self,
        step: PlanStep,
        diagnosis: FailureDiagnosis,
    ) -> Optional[PlanStep]:
        """Record attempt in budgets and produce the adapted PlanStep."""
        if not self.can_recover(step.step_id, diagnosis):
            return None

        self.step_retry_counts[step.step_id] = self.step_retry_counts.get(step.step_id, 0) + 1
        self.global_retry_count += 1
        self.diagnoses_history.append(diagnosis)

        step_retry_num = self.step_retry_counts[step.step_id]
        logger.info(
            f"Step '{step.step_id}': Applying recovery strategy '{diagnosis.recommended_strategy.value}' "
            f"(Step retry {step_retry_num}/{self.max_retries_per_step}, Global {self.global_retry_count}/{self.max_global_task_retries})"
        )

        target_tool = diagnosis.suggested_tool or step.tool_name
        new_params = dict(step.parameters)

        recovered_step = PlanStep(
            step_id=step.step_id,
            description=f"{step.description} (Retry #{step_retry_num}: {diagnosis.reason})",
            tool_name=target_tool,
            parameters=new_params,
            depends_on=list(step.depends_on),
            safety_level=step.safety_level,
            requires_confirmation=step.requires_confirmation,
            status=StepStatus.PENDING,
            success_criteria=step.success_criteria,
            preconditions=list(step.preconditions),
            postconditions=list(step.postconditions),
            evidence_source=step.evidence_source,
            confidence=step.confidence,
            recovery_strategy=step.recovery_strategy,
        )
        return recovered_step
