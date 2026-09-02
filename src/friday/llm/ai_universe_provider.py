"""AI Universe LLM Provider (AI Universe Integration Fallback Integration).

Provides ultimate fallback in FRIDAY's reasoning chain by routing user prompts
to the external AI Universe multi-agent deliberation API when cloud LLM providers
experience outages or rate limits.
"""

import asyncio
from typing import Any

from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.core.types import Message, Role, TrustLevel
from friday.core.verification import evaluate_ai_universe_response
from friday.llm.base import BaseLLMProvider
from friday.tools.ai_universe_client import AIUniverseClient, AIUniverseResponse

logger = get_logger("llm.ai_universe")


class AIUniverseLLMProvider(BaseLLMProvider):
    """LLM Provider backed by the external AI Universe multi-agent debate system."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        min_confidence: float = 0.70,
        mode: str = "auto",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            model="ai-universe-debate",
            temperature=temperature,
            max_tokens=max_tokens,
        )
        import os
        final_url = base_url or os.getenv("FRIDAY_INFERENCE_URL") or "http://localhost:8001"
        final_key = api_key or os.getenv("FRIDAY_INFERENCE_API_KEY") or ""
        self.api_key = final_key
        self.client = AIUniverseClient(base_url=final_url, api_key=final_key)
        self.min_confidence = min_confidence
        self.mode = mode

    @property
    def provider_name(self) -> str:
        return "ai_universe"

    def _extract_user_query(self, messages: list[Message]) -> str:
        """Extract the most relevant user query or instruction from conversation messages."""
        for msg in reversed(messages):
            if msg.role == Role.USER and msg.content and msg.content.strip():
                return msg.content.strip()
        # If no user message, concatenate non-system content
        non_system = [m.content for m in messages if m.role != Role.SYSTEM and m.content]
        if non_system:
            return "\n".join(non_system)
        return "Provide reasoning and solution for current task."

    def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> Message:
        """Generate response by querying AI Universe consensus."""
        query = self._extract_user_query(messages)
        logger.info(f"Routing query to AI Universe fallback provider (URL: {self.client.base_url})")

        try:
            try:
                loop = asyncio.get_running_loop()
                resp = loop.run_until_complete(
                    self.client.ask(query, mode=self.mode)
                )
            except RuntimeError:
                resp = asyncio.run(
                    self.client.ask(query, mode=self.mode)
                )
        except Exception as ex:
            logger.error(f"AI Universe provider request failed: {ex}")
            raise LLMProviderError(f"AI Universe communication error: {ex}") from ex

        resp_dict = resp.model_dump()
        is_verified, status_msg, extracted = evaluate_ai_universe_response(resp_dict)

        if not is_verified or resp.confidence < self.min_confidence:
            err_msg = f"AI Universe response below verification threshold ({resp.confidence:.2f} < {self.min_confidence:.2f}): {status_msg}"
            logger.warning(err_msg)
            raise LLMProviderError(err_msg)

        # Format clean answer for FRIDAY cognitive loop
        answer_text = resp.answer.strip()
        if not answer_text:
            raise LLMProviderError("AI Universe returned empty answer.")

        return Message(
            role=Role.ASSISTANT,
            content=answer_text,
            trust_level=TrustLevel.MODEL_OUTPUT,
            metadata={
                "provider": "ai_universe",
                "run_id": resp.run_id,
                "confidence": resp.confidence,
                "key_evidence": resp.key_evidence,
                "unresolved_disagreements": resp.unresolved_disagreements,
            },
        )
