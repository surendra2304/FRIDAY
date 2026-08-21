# -*- coding: utf-8 -*-
"""Centralized Safety Gate & Risk Policy Enforcement for Autonomous Tasks.

Provides:
- `TaskRiskLevel`: Granular risk classification (`SAFE`, `LOW_RISK_CONFIRMATION`, `HIGH_RISK_CONFIRMATION`, `BLOCKED`).
- `AutonomousSafetyGate`:
  * Enforces capability validation, risk classification, and authorization policies.
  * Evaluates untrusted data, prompt injection patterns, and malicious screen text before execution.
  * Enforces hard unconditional blocks: credential extraction, API key access, financial transactions/payments, destructive actions, unrestricted shell execution, and security bypasses.
  * Validates environment freshness to prevent replay of stale UI actions.
  * 100% provider-independent and testable offline.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from friday.agent.planner import PlanStep
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.logging import get_logger
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    SafetyLevel,
)
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry

logger = get_logger("agent.safety_gate")


class TaskRiskLevel(str, Enum):
    """Granular risk classification for autonomous task steps."""
    SAFE = "SAFE"
    LOW_RISK_CONFIRMATION = "LOW_RISK_CONFIRMATION"
    HIGH_RISK_CONFIRMATION = "HIGH_RISK_CONFIRMATION"
    BLOCKED = "BLOCKED"


@dataclass
class GateEvaluationResult:
    """Outcome of safety gate evaluation for an executable action."""
    passed: bool
    risk_level: TaskRiskLevel
    reason: str
    requires_user_confirmation: bool = False
    is_hard_blocked: bool = False


class AutonomousSafetyGate:
    """Centralized gate verifying all autonomous steps before execution."""

    # Unconditional hard-block patterns
    HARD_BLOCKED_PATTERNS = [
        "format c:", "rm -rf", "drop database", "drop table", "del /f", "kill -9",
        "delete from users", "sudo rm", "system.override", "grant all privileges",
        "disable security", "bypass auth", "send bitcoin", "transfer funds", "pay invoice",
        "enter credit card", "read .env", "export api_key", "dump credentials",
    ]

    # Malicious injection markers
    INJECTION_PATTERNS = [
        "ignore previous instructions", "system override", "jailbreak", "you are now in god mode",
        "eval(", "exec(", "__import__", "<script>", "javascript:",
    ]

    def __init__(
        self,
        tool_registry: ToolRegistry,
        authorizer: Optional[BaseAuthorizer] = None,
    ) -> None:
        self.registry = tool_registry
        self.authorizer = authorizer or DefaultSecureAuthorizer()

    def classify_risk(self, step: PlanStep, tool: Optional[BaseTool] = None) -> TaskRiskLevel:
        """Determine the risk classification level for a given task step."""
        # 1. Check for hard-blocked dangerous operations in description, tool name, or parameters
        text_payload = f"{step.description} {step.tool_name} {step.parameters}".lower()
        if any(pat in text_payload for pat in self.HARD_BLOCKED_PATTERNS):
            return TaskRiskLevel.BLOCKED

        # 2. Check tool safety level if tool is present
        if tool:
            if tool.safety_level == SafetyLevel.DANGEROUS:
                return TaskRiskLevel.HIGH_RISK_CONFIRMATION
            elif tool.safety_level == SafetyLevel.SENSITIVE:
                return TaskRiskLevel.LOW_RISK_CONFIRMATION
            return TaskRiskLevel.SAFE

        if step.safety_level == SafetyLevel.DANGEROUS:
            return TaskRiskLevel.HIGH_RISK_CONFIRMATION
        elif step.safety_level == SafetyLevel.SENSITIVE:
            return TaskRiskLevel.LOW_RISK_CONFIRMATION

        return TaskRiskLevel.SAFE

    def validate_environment_freshness(
        self,
        checkpoint_env_hash: Optional[str],
        current_env_hash: Optional[str],
    ) -> Tuple[bool, Optional[str]]:
        """Verify that the desktop or UI environment has not changed since planning/checkpoint."""
        if not checkpoint_env_hash or not current_env_hash:
            return True, None

        if checkpoint_env_hash != "default" and checkpoint_env_hash != current_env_hash:
            return False, "Environment state changed since last checkpoint; UI actions require re-planning."

        return True, None

    def evaluate_step(
        self,
        step: PlanStep,
        step_results: Optional[Dict[str, Any]] = None,
        checkpoint_env_hash: Optional[str] = None,
        current_env_hash: Optional[str] = None,
        allow_confirmation: bool = False,
    ) -> GateEvaluationResult:
        """Run complete centralized safety checks on a plan step prior to execution."""
        # 1. Hard Block & Injection Check
        text_payload = f"{step.description} {step.tool_name} {step.parameters}".lower()
        if any(pat in text_payload for pat in self.HARD_BLOCKED_PATTERNS):
            reason = "Hard Policy Block: Destructive or prohibited operation detected."
            logger.warning(f"Safety Gate rejected step '{step.step_id}': {reason}")
            return GateEvaluationResult(
                passed=False,
                risk_level=TaskRiskLevel.BLOCKED,
                reason=reason,
                is_hard_blocked=True,
            )

        if any(pat in text_payload for pat in self.INJECTION_PATTERNS):
            reason = "Untrusted Input Block: Malicious prompt injection or override pattern detected."
            logger.warning(f"Safety Gate rejected step '{step.step_id}': {reason}")
            return GateEvaluationResult(
                passed=False,
                risk_level=TaskRiskLevel.BLOCKED,
                reason=reason,
                is_hard_blocked=True,
            )

        # 2. Environment Freshness Validation
        env_valid, env_err = self.validate_environment_freshness(checkpoint_env_hash, current_env_hash)
        if not env_valid:
            return GateEvaluationResult(
                passed=False,
                risk_level=TaskRiskLevel.HIGH_RISK_CONFIRMATION,
                reason=env_err or "Stale environment state.",
            )

        # 3. Tool Capability Validation
        if step.tool_name:
            tool = self.registry.get(step.tool_name)
            if not tool:
                return GateEvaluationResult(
                    passed=False,
                    risk_level=TaskRiskLevel.BLOCKED,
                    reason=f"Tool '{step.tool_name}' not registered in tool registry.",
                )

            risk = self.classify_risk(step, tool)

            # 4. Authorization Evaluation
            auth_req = AuthorizationRequest(
                tool_name=step.tool_name,
                safety_level=tool.safety_level,
                arguments=step.parameters,
                purpose=step.description,
            )
            auth_resp = self.authorizer.authorize(auth_req)

            if auth_resp.decision != AuthorizationDecision.APPROVED and not allow_confirmation:
                return GateEvaluationResult(
                    passed=False,
                    risk_level=risk,
                    reason=f"Authorization Policy Denied: {auth_resp.reason}",
                    requires_user_confirmation=True,
                )

            return GateEvaluationResult(
                passed=True,
                risk_level=risk,
                reason="Step passed all safety and authorization policies.",
                requires_user_confirmation=(risk != TaskRiskLevel.SAFE and not allow_confirmation),
            )

        # Non-tool step
        risk = self.classify_risk(step)
        return GateEvaluationResult(
            passed=True,
            risk_level=risk,
            reason="Non-tool step passed safety checks.",
        )
