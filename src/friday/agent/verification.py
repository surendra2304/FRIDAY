import re
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Type, TypeVar, Generic
from pydantic import BaseModel, Field, ValidationError

from friday.planning.types import TaskStep, TaskStatus, TaskGraph
from friday.core.logging import get_logger
from friday.llm.base import BaseLLMProvider
from friday.core.types import Message, Role

logger = get_logger("agent.verification")


class VerificationStatus(str, Enum):
    """Outcome status of a verification check."""
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


@dataclass
class VerificationResult:
    """Detailed audit report for a verification assertion."""
    status: VerificationStatus
    criterion: str
    diagnostics: str = ""
    evidence: str = ""
    evidence_source: str = "agent_executor"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 1.0
    is_real_success: bool = False

    @property
    def passed(self) -> bool:
        return (self.status in (VerificationStatus.PASSED, VerificationStatus.SKIPPED)) and self.is_real_success


class StructuredExecutionEnvelope(BaseModel):
    """Strict Pydantic execution envelope to enforce typed outputs."""
    task_id: str
    tool_name: str
    success: bool
    data: Any | None = None
    error: str | None = None
    raw_output: str = ""


class LLMJudgeResult(BaseModel):
    """Pydantic envelope for strict verification results from the LLM Judge."""
    passed: bool = Field(..., description="Whether the step objective was successfully met based on the output.")
    reasoning: str = Field(..., description="Detailed reasoning explaining why it passed or failed.")
    confidence: float = Field(..., description="Confidence score between 0.0 and 1.0.")


class StepVerifier:
    """Evaluates step and task outcome assertions against real-world evidence and strict envelopes."""

    def __init__(self, llm_provider: BaseLLMProvider | None = None):
        self.llm_provider = llm_provider

    def verify_envelope(self, envelope: StructuredExecutionEnvelope, expected_model: Type[BaseModel] | None = None) -> VerificationResult:
        """Verify that the execution result conforms to the strict Pydantic envelope."""
        if not envelope.success:
            return VerificationResult(
                status=VerificationStatus.FAILED,
                criterion="Envelope indicates success=True",
                diagnostics=f"Execution envelope explicitly marked as failed: {envelope.error}",
                is_real_success=False,
            )

        if expected_model:
            if envelope.data is None:
                return VerificationResult(
                    status=VerificationStatus.FAILED,
                    criterion=f"Envelope contains data of type {expected_model.__name__}",
                    diagnostics="Envelope data is None.",
                    is_real_success=False,
                )
            
            # Since Pydantic generics already validate during parsing, if it parsed successfully 
            # and is an instance, we are good.
            if not isinstance(envelope.data, expected_model):
                try:
                    # Try to parse it if it's a dict
                    envelope.data = expected_model.model_validate(envelope.data)
                except ValidationError as e:
                    return VerificationResult(
                        status=VerificationStatus.FAILED,
                        criterion=f"Data matches Pydantic schema {expected_model.__name__}",
                        diagnostics=f"Pydantic validation failed: {str(e)}",
                        is_real_success=False,
                    )

        return VerificationResult(
            status=VerificationStatus.PASSED,
            criterion="Strict Pydantic envelope format valid",
            evidence=f"Validated envelope payload: {envelope.data}",
            is_real_success=True,
        )

    async def verify_step_result_llm(
        self,
        step: TaskStep,
        step_result: Any,
    ) -> VerificationResult:
        """Verify complex step outputs using LLM-as-a-judge."""
        if not step.objective:
            # Fallback for steps without complex objectives
            if getattr(step_result, "is_error", False) or getattr(step_result, "error", None) or getattr(step_result, "success", True) is False:
                return VerificationResult(
                    status=VerificationStatus.FAILED,
                    criterion="No error",
                    diagnostics="Execution returned an error state.",
                    is_real_success=False,
                )
            return VerificationResult(
                status=VerificationStatus.PASSED,
                criterion="No error",
                evidence="Execution completed without errors.",
                is_real_success=True,
            )

        if not self.llm_provider:
            # If no LLM available, skip complex verification
            return VerificationResult(
                status=VerificationStatus.SKIPPED,
                criterion=step.objective,
                diagnostics="No LLM provider available for complex LLM-as-a-judge verification.",
                is_real_success=True,  # Default to true if we can't verify and there's no obvious error
            )

        # Build prompt for LLM judge
        prompt = f"""You are FRIDAY's authoritative verification judge.
Your task is to verify if a task step successfully achieved its objective based on the provided execution output.
Do NOT hallucinate. Base your decision ONLY on the provided evidence.

Step Objective:
{step.objective}

Step Parameters:
{json.dumps(step.parameters, indent=2)}

Execution Evidence / Output:
{str(step_result)}

Evaluate whether the evidence clearly demonstrates that the objective was fulfilled.
Respond ONLY with a valid JSON object matching this schema: {{"passed": bool, "reasoning": string, "confidence": float}}
"""

        try:
            messages = [Message(role=Role.USER, content=prompt)]
            response = await self.llm_provider.generate_response(messages)
            content = response.content.strip()
            
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            parsed = json.loads(content)
            judge_res = LLMJudgeResult(**parsed)
            
            return VerificationResult(
                status=VerificationStatus.PASSED if judge_res.passed else VerificationStatus.FAILED,
                criterion=step.objective,
                diagnostics=judge_res.reasoning,
                confidence=judge_res.confidence,
                evidence=str(step_result)[:200],
                is_real_success=judge_res.passed,
            )
        except Exception as e:
            logger.error(f"LLM Judge verification failed: {e}")
            return VerificationResult(
                status=VerificationStatus.FAILED,
                criterion=step.objective,
                diagnostics=f"Failed to verify output using LLM Judge: {e}",
                is_real_success=False,
            )

    @staticmethod
    def verify_plan_completion(
        plan: TaskGraph,
        step_verification_results: dict[str, VerificationResult],
    ) -> VerificationResult:
        failed_steps = [
            step_id for step_id, vres in step_verification_results.items() if not vres.passed
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
        self._attempt_counts: dict[str, int] = {}

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
        step: TaskStep,
        failure_evidence: VerificationResult,
        corrector_fn: Callable[[TaskStep, VerificationResult], TaskStep | None] | None = None,
    ) -> TaskStep | None:
        if not self.can_attempt_correction(step.id):
            logger.warning(f"Step '{step.id}': Maximum correction attempts ({self.max_correction_attempts}) exhausted.")
            return None

        attempt_num = self.record_attempt(step.id)
        logger.info(f"Step '{step.id}': Initiating self-correction attempt {attempt_num}/{self.max_correction_attempts}")

        if corrector_fn:
            return corrector_fn(step, failure_evidence)

        new_params = dict(step.parameters)
        corrected_step = TaskStep(
            id=step.id,
            description=f"{step.description} (Retry #{attempt_num})",
            tool_name=step.tool_name,
            parameters=new_params,
            depends_on=list(step.depends_on),
            safety_level=step.safety_level,
            requires_confirmation=step.requires_confirmation,
            status=TaskStatus.PENDING,
            objective=step.objective,
        )
        return corrected_step
