import json
from typing import Any

from pydantic import BaseModel, Field

from friday.core.logging import get_logger
from friday.llm.base import BaseLLMProvider
from friday.planning.types import TaskStep
from friday.agent.verification import VerificationResult, VerificationStatus

logger = get_logger("agent.verification.llm_judge")


class LLMJudgeResult(BaseModel):
    """Pydantic envelope for strict verification results from the LLM Judge."""
    passed: bool = Field(..., description="Whether the step objective was successfully met based on the output.")
    reasoning: str = Field(..., description="Detailed reasoning explaining why it passed or failed.")
    confidence: float = Field(..., description="Confidence score between 0.0 and 1.0.")


class LLMJudgeVerifier:
    """Verifies complex execution outputs using an LLM as a judge, strictly enforcing Pydantic envelopes."""

    def __init__(self, llm_provider: BaseLLMProvider):
        self.llm_provider = llm_provider

    async def verify(self, step: TaskStep, step_result: Any) -> VerificationResult:
        """Evaluate if the step's real-world evidence satisfies its objectives."""
        if not step.objective:
            # If no complex objective is specified, default to fast heuristic pass if not error.
            if getattr(step_result, "is_error", False) or getattr(step_result, "error", None):
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
"""

        try:
            # Use structured output parsing if provider supports it, otherwise fallback to JSON block parsing
            # For simplicity in this base implementation, we assume we ask for JSON
            prompt += "\nRespond ONLY with a valid JSON object matching this schema: {\"passed\": bool, \"reasoning\": string, \"confidence\": float}"
            
            from friday.core.types import Message, Role
            messages = [Message(role=Role.USER, content=prompt)]
            
            # Here we would call the LLM provider
            response = await self.llm_provider.generate_response(messages)
            content = response.content.strip()
            
            # Extract JSON block if surrounded by markdown
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
                
            parsed = json.loads(content)
            judge_res = LLMJudgeResult(**parsed)
            
            status = VerificationStatus.PASSED if judge_res.passed else VerificationStatus.FAILED
            
            return VerificationResult(
                status=status,
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
