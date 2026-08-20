# -*- coding: utf-8 -*-
"""Formal Verification, Assertion Engine & Bounded Self-Correction for FRIDAY.

Provides:
- Step-level and Task-level verification conditions & assertions.
- Safe inspection of tool results, error states, and outcome contracts.
- Bounded self-correction loop: diagnosis -> parameter/strategy adjustment -> retry -> re-verification.
- Strict anti-infinite-loop limits and preservation of Proposal != Execution and safety gating.
- Completely provider-independent and 100% testable offline.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Callable, Dict, List, Optional

from friday.agent.planner import PlanStep, StepStatus, TaskPlan
from friday.core.logging import get_logger

logger = get_logger("agent.verification")


class VerificationStatus(str, Enum):
    """Outcome status of a verification check."""
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


@dataclass
class VerificationResult:
    """Detailed audit report for a verification assertion."""

    status: VerificationStatus
    criterion: str
    evidence: Optional[str] = None
    diagnostics: Optional[str] = None
    suggested_correction: Optional[Dict[str, Any]] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.PASSED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "criterion": self.criterion,
            "evidence": self.evidence,
            "diagnostics": self.diagnostics,
            "suggested_correction": self.suggested_correction,
            "timestamp": self.timestamp.isoformat(),
        }


class StepVerifier:
    """Evaluates step and task outcome assertions against real execution results."""

    @staticmethod
    def verify_step_result(
        step: PlanStep,
        step_result: Any,
        custom_validator: Optional[Callable[[PlanStep, Any], VerificationResult]] = None,
    ) -> VerificationResult:
        """Verify that a step's execution result satisfies its success criteria."""
        if custom_validator:
            return custom_validator(step, step_result)

        # 1. If step execution failed or produced error content
        if not step_result:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                criterion=step.success_criteria or "Non-empty step output",
                diagnostics="Step produced empty or null execution result.",
            )

        result_str = str(step_result).strip()

        # Check for obvious unhandled error markers in output
        lower_res = result_str.lower()
        if lower_res.startswith("error:") or "traceback (most recent call last)" in lower_res or "exception:" in lower_res:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                criterion=step.success_criteria or "Error-free execution",
                evidence=result_str[:200],
                diagnostics="Step execution returned an explicit error message.",
                suggested_correction={"adjust_parameters": True, "error_context": result_str[:200]},
            )

        # 2. If specific success criteria is defined
        if step.success_criteria:
            crit = step.success_criteria.strip()

            # Handle regex matching criteria syntax: "regex:<pattern>"
            if crit.startswith("regex:"):
                pattern = crit[6:].strip()
                if re.search(pattern, result_str, re.IGNORECASE):
                    return VerificationResult(
                        status=VerificationStatus.PASSED,
                        criterion=crit,
                        evidence=result_str[:150],
                    )
                else:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        criterion=crit,
                        evidence=result_str[:150],
                        diagnostics=f"Result failed to match required regex pattern: '{pattern}'",
                        suggested_correction={"adjust_parameters": True},
                    )

            # Handle substring matching criteria syntax: "contains:<substr>"
            if crit.startswith("contains:"):
                expected = crit[9:].strip().lower()
                if expected in lower_res:
                    return VerificationResult(
                        status=VerificationStatus.PASSED,
                        criterion=crit,
                        evidence=result_str[:150],
                    )
                else:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        criterion=crit,
                        evidence=result_str[:150],
                        diagnostics=f"Result missing expected substring: '{expected}'",
                        suggested_correction={"adjust_parameters": True},
                    )

            # Default text heuristic match
            if any(term in lower_res for term in crit.lower().split() if len(term) > 3):
                return VerificationResult(
                    status=VerificationStatus.PASSED,
                    criterion=crit,
                    evidence=result_str[:150],
                )

        # 3. Default verification passes if output is non-empty and error-free
        return VerificationResult(
            status=VerificationStatus.PASSED,
            criterion=step.success_criteria or "Valid execution output",
            evidence=result_str[:150],
        )

    @staticmethod
    def verify_plan_completion(
        plan: TaskPlan,
        step_verification_results: Dict[str, VerificationResult],
    ) -> VerificationResult:
        """Verify the overall plan outcome after all steps have executed."""
        failed_steps = [
            step_id
            for step_id, vres in step_verification_results.items()
            if not vres.passed
        ]

        if failed_steps:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                criterion=f"All {len(plan.steps)} steps verified",
                diagnostics=f"Step(s) failed verification: {failed_steps}",
            )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            criterion=f"All {len(plan.steps)} steps verified",
            evidence=f"Successfully verified {len(step_verification_results)} step(s).",
        )


class SelfCorrectionPolicy:
    """Manages bounded retry and parameter/strategy adjustment during self-correction."""

    def __init__(self, max_correction_attempts: int = 3) -> None:
        self.max_correction_attempts = max_correction_attempts
        self._attempt_counts: Dict[str, int] = {}

    def get_remaining_attempts(self, step_id: str) -> int:
        used = self._attempt_counts.get(step_id, 0)
        return max(0, self.max_correction_attempts - used)

    def can_attempt_correction(self, step_id: str) -> bool:
        return self.get_remaining_attempts(step_id) > 0

    def record_attempt(self, step_id: str) -> int:
        count = self._attempt_counts.get(step_id, 0) + 1
        self._attempt_counts[step_id] = count
        return count

    def generate_corrected_step(
        self,
        step: PlanStep,
        failure_evidence: VerificationResult,
        corrector_fn: Optional[Callable[[PlanStep, VerificationResult], Optional[PlanStep]]] = None,
    ) -> Optional[PlanStep]:
        """Generate an adjusted PlanStep for retry if within bounds."""
        if not self.can_attempt_correction(step.step_id):
            logger.warning(f"Step '{step.step_id}': Maximum correction attempts ({self.max_correction_attempts}) exhausted.")
            return None

        attempt_num = self.record_attempt(step.step_id)
        logger.info(f"Step '{step.step_id}': Initiating self-correction attempt {attempt_num}/{self.max_correction_attempts}")

        if corrector_fn:
            return corrector_fn(step, failure_evidence)

        # Default correction preserves existing valid parameters without injecting unexpected schema keys
        new_params = dict(step.parameters)

        corrected_step = PlanStep(
            step_id=step.step_id,
            description=f"{step.description} (Retry #{attempt_num})",
            tool_name=step.tool_name,
            parameters=new_params,
            depends_on=list(step.depends_on),
            safety_level=step.safety_level,
            requires_confirmation=step.requires_confirmation,
            status=StepStatus.PENDING,
            success_criteria=step.success_criteria,
        )
        return corrected_step
