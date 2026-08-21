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
    UNVERIFIED = "UNVERIFIED"
    SKIPPED = "SKIPPED"


@dataclass
class VerificationResult:
    """Detailed audit report for a verification assertion."""

    status: VerificationStatus
    criterion: str
    evidence: Optional[str] = None
    diagnostics: Optional[str] = None
    suggested_correction: Optional[Dict[str, Any]] = None
    evidence_source: Optional[str] = None
    confidence: float = 1.0
    is_real_success: bool = True
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def passed(self) -> bool:
        return self.status == VerificationStatus.PASSED and self.is_real_success

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status.value,
            "criterion": self.criterion,
            "evidence": self.evidence,
            "diagnostics": self.diagnostics,
            "suggested_correction": self.suggested_correction,
            "evidence_source": self.evidence_source,
            "confidence": self.confidence,
            "is_real_success": self.is_real_success,
            "timestamp": self.timestamp.isoformat(),
        }


class StepVerifier:
    """Evaluates step and task outcome assertions against real-world evidence and execution results."""

    @staticmethod
    def verify_step_result(
        step: PlanStep,
        step_result: Any,
        custom_validator: Optional[Callable[[PlanStep, Any], VerificationResult]] = None,
        environment_state: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        """Verify that a step's execution result satisfies its postconditions and real-world evidence."""
        import os
        import json

        if custom_validator:
            return custom_validator(step, step_result)

        # 1. Check for null / empty execution failure
        if step_result is None or (isinstance(step_result, str) and not step_result.strip()):
            return VerificationResult(
                status=VerificationStatus.FAILED,
                criterion=step.success_criteria or "Non-empty step output",
                diagnostics="Step produced empty or null execution result.",
                is_real_success=False,
            )

        result_str = str(step_result).strip()
        lower_res = result_str.lower()

        # Check for unhandled error markers in output
        if lower_res.startswith("error:") or "traceback (most recent call last)" in lower_res or "exception:" in lower_res:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                criterion=step.success_criteria or "Error-free execution",
                evidence=result_str[:200],
                diagnostics="Step execution returned an explicit error message.",
                suggested_correction={"adjust_parameters": True, "error_context": result_str[:200]},
                is_real_success=False,
            )

        evidence_src = step.evidence_source or "tool_output"

        # 2. Evidence Source: Filesystem Verification (prevents false-success where tool reports success but file wasn't written)
        if evidence_src == "filesystem" or (step.tool_name and any(term in step.tool_name for term in ("write_file", "create_file", "delete_file", "save_file"))):
            target_path = step.parameters.get("path") or step.parameters.get("file_path") or step.parameters.get("target_path")
            if target_path and isinstance(target_path, str):
                if "delete" in (step.tool_name or ""):
                    if os.path.exists(target_path):
                        return VerificationResult(
                            status=VerificationStatus.FAILED,
                            criterion=f"file_deleted:{target_path}",
                            evidence=f"File still exists at {target_path}",
                            diagnostics="False success: Tool reported deletion but target file still exists on filesystem.",
                            evidence_source="filesystem",
                            is_real_success=False,
                            suggested_correction={"retry": True},
                        )
                else:
                    if not os.path.exists(target_path):
                        return VerificationResult(
                            status=VerificationStatus.FAILED,
                            criterion=f"file_exists:{target_path}",
                            evidence=f"File not found at {target_path}",
                            diagnostics="False success: Tool reported success but target file was not created on filesystem.",
                            evidence_source="filesystem",
                            is_real_success=False,
                            suggested_correction={"retry": True},
                        )

        # 3. Evidence Source: Screen State Verification
        if evidence_src == "screen":
            screen_data = environment_state.get("screen_state", {}) if environment_state else {}
            expected_element = step.parameters.get("target_element") or step.parameters.get("expected_ui_text")
            if expected_element:
                visible_elements = screen_data.get("elements", [])
                if expected_element not in visible_elements and expected_element not in str(screen_data):
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        criterion=f"ui_element_visible:{expected_element}",
                        evidence=str(screen_data)[:150],
                        diagnostics=f"False success: Tool reported action executed but expected UI element '{expected_element}' was not verified on screen.",
                        evidence_source="screen",
                        is_real_success=False,
                    )
            elif not screen_data and environment_state is not None:
                return VerificationResult(
                    status=VerificationStatus.UNVERIFIED,
                    criterion="screen_state_evidence",
                    diagnostics="Screen state evidence unavailable to confirm visual side effects.",
                    evidence_source="screen",
                    is_real_success=False,
                )

        # 4. Evidence Source: Application State Verification
        if evidence_src == "application" or (step.tool_name and any(term in step.tool_name for term in ("launch_app", "close_app", "focus_window"))):
            app_state = environment_state.get("application_state", {}) if environment_state else {}
            expected_app = step.parameters.get("app_name") or step.parameters.get("process_name") or step.parameters.get("window_title")
            if expected_app:
                running_apps = app_state.get("running_processes", []) or app_state.get("open_windows", [])
                if "close" in (step.tool_name or ""):
                    if expected_app in running_apps or any(expected_app.lower() in str(a).lower() for a in running_apps):
                        return VerificationResult(
                            status=VerificationStatus.FAILED,
                            criterion=f"app_closed:{expected_app}",
                            diagnostics=f"False success: Tool reported app closed but '{expected_app}' is still active.",
                            evidence_source="application",
                            is_real_success=False,
                        )
                else:
                    if running_apps and not any(expected_app.lower() in str(a).lower() for a in running_apps):
                        return VerificationResult(
                            status=VerificationStatus.FAILED,
                            criterion=f"app_running:{expected_app}",
                            diagnostics=f"False success: Tool reported app launched but '{expected_app}' was not found in running processes.",
                            evidence_source="application",
                            is_real_success=False,
                        )

        # 5. Evidence Source: External / Network Service State Verification
        if evidence_src == "external_service" or evidence_src == "network":
            external_state = environment_state.get("external_state", {}) if environment_state else {}
            if not external_state and environment_state is not None:
                # If external verification cannot be performed safely, report UNVERIFIED instead of inventing success
                return VerificationResult(
                    status=VerificationStatus.UNVERIFIED,
                    criterion="external_service_evidence",
                    evidence=result_str[:100],
                    diagnostics="External verification service unreachable or unverified; cannot confirm real-world state.",
                    evidence_source="external_service",
                    is_real_success=False,
                )

        # 6. Evidence Source: Structured Output Verification
        if evidence_src == "structured_output":
            try:
                parsed = json.loads(result_str) if isinstance(step_result, str) else step_result
                if not isinstance(parsed, (dict, list)):
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        criterion="structured_json",
                        evidence=result_str[:150],
                        diagnostics="False success: Output is not valid structured JSON object or array.",
                        evidence_source="structured_output",
                        is_real_success=False,
                    )
            except Exception as e:
                return VerificationResult(
                    status=VerificationStatus.FAILED,
                    criterion="structured_json",
                    evidence=result_str[:150],
                    diagnostics=f"False success: Failed to parse structured JSON: {e}",
                    evidence_source="structured_output",
                    is_real_success=False,
                )

        # 5. Evaluate Explicit Postconditions
        all_conditions = list(step.postconditions)
        if step.success_criteria:
            all_conditions.append(step.success_criteria)

        for crit in all_conditions:
            crit = crit.strip()

            # file_exists:<path>
            if crit.startswith("file_exists:"):
                fpath = crit[12:].strip()
                if not os.path.exists(fpath):
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        criterion=crit,
                        diagnostics=f"Postcondition failed: File does not exist at '{fpath}'.",
                        evidence_source="filesystem",
                        is_real_success=False,
                    )

            # file_contains:<path>:<content>
            elif crit.startswith("file_contains:"):
                parts = crit[14:].rsplit(":", 1)
                if len(parts) == 2:
                    fpath, expected_content = parts[0].strip(), parts[1].strip()
                    if not os.path.exists(fpath):
                        return VerificationResult(
                            status=VerificationStatus.FAILED,
                            criterion=crit,
                            diagnostics=f"Postcondition failed: File '{fpath}' not found.",
                            evidence_source="filesystem",
                            is_real_success=False,
                        )
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        if expected_content not in content:
                            return VerificationResult(
                                status=VerificationStatus.FAILED,
                                criterion=crit,
                                diagnostics=f"Postcondition failed: File '{fpath}' does not contain expected content '{expected_content}'.",
                                evidence_source="filesystem",
                                is_real_success=False,
                            )
                    except Exception as fe:
                        return VerificationResult(
                            status=VerificationStatus.FAILED,
                            criterion=crit,
                            diagnostics=f"Postcondition failed: Error reading file '{fpath}': {fe}",
                            evidence_source="filesystem",
                            is_real_success=False,
                        )

            # file_deleted:<path>
            elif crit.startswith("file_deleted:"):
                fpath = crit[13:].strip()
                if os.path.exists(fpath):
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        criterion=crit,
                        diagnostics=f"Postcondition failed: File '{fpath}' was not deleted.",
                        evidence_source="filesystem",
                        is_real_success=False,
                    )

            # json_key:<key>
            elif crit.startswith("json_key:"):
                key = crit[9:].strip()
                try:
                    parsed = json.loads(result_str) if isinstance(step_result, str) else step_result
                    if not isinstance(parsed, dict) or key not in parsed:
                        return VerificationResult(
                            status=VerificationStatus.FAILED,
                            criterion=crit,
                            diagnostics=f"Postcondition failed: Key '{key}' not found in structured JSON output.",
                            is_real_success=False,
                        )
                except Exception as e:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        criterion=crit,
                        diagnostics=f"Postcondition failed: Failed to parse output as JSON for key check '{key}': {e}",
                        is_real_success=False,
                    )

            # json_field:<key>:<expected_val>
            elif crit.startswith("json_field:"):
                parts = crit[11:].split(":", 1)
                if len(parts) == 2:
                    key, expected_val = parts[0].strip(), parts[1].strip()
                    try:
                        parsed = json.loads(result_str) if isinstance(step_result, str) else step_result
                        val = str(parsed.get(key, ""))
                        if val != expected_val:
                            return VerificationResult(
                                status=VerificationStatus.FAILED,
                                criterion=crit,
                                diagnostics=f"Postcondition failed: JSON field '{key}' value '{val}' != expected '{expected_val}'.",
                                is_real_success=False,
                            )
                    except Exception as e:
                        return VerificationResult(
                            status=VerificationStatus.FAILED,
                            criterion=crit,
                            diagnostics=f"Postcondition failed: Failed to check JSON field '{key}': {e}",
                            is_real_success=False,
                        )

            # regex:<pattern>
            elif crit.startswith("regex:"):
                pattern = crit[6:].strip()
                if not re.search(pattern, result_str, re.IGNORECASE):
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        criterion=crit,
                        evidence=result_str[:150],
                        diagnostics=f"Result failed to match required regex pattern: '{pattern}'",
                        is_real_success=False,
                    )

            # contains:<substr>
            elif crit.startswith("contains:"):
                expected = crit[9:].strip().lower()
                if expected not in lower_res:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        criterion=crit,
                        evidence=result_str[:150],
                        diagnostics=f"Result missing expected substring: '{expected}'",
                        is_real_success=False,
                    )

            # not_contains:<substr>
            elif crit.startswith("not_contains:"):
                forbidden = crit[13:].strip().lower()
                if forbidden in lower_res:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        criterion=crit,
                        evidence=result_str[:150],
                        diagnostics=f"Result unexpectedly contains forbidden substring: '{forbidden}'",
                        is_real_success=False,
                    )

            # exact:<text>
            elif crit.startswith("exact:"):
                expected = crit[6:].strip()
                if result_str != expected:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        criterion=crit,
                        diagnostics=f"Result '{result_str[:50]}' does not exactly match expected '{expected[:50]}'",
                        is_real_success=False,
                    )

            # min_length:<int>
            elif crit.startswith("min_length:"):
                try:
                    min_len = int(crit[11:].strip())
                    if len(result_str) < min_len:
                        return VerificationResult(
                            status=VerificationStatus.FAILED,
                            criterion=crit,
                            diagnostics=f"Output length {len(result_str)} is less than required minimum {min_len}",
                            is_real_success=False,
                        )
                except ValueError:
                    pass

        return VerificationResult(
            status=VerificationStatus.PASSED,
            criterion=step.success_criteria or "Valid execution output and postconditions verified",
            evidence=result_str[:150],
            evidence_source=evidence_src,
            confidence=step.confidence,
            is_real_success=True,
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
                is_real_success=False,
            )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            criterion=f"All {len(plan.steps)} steps verified",
            evidence=f"Successfully verified {len(step_verification_results)} step(s).",
            is_real_success=True,
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
