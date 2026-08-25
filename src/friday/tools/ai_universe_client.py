# -*- coding: utf-8 -*-
"""AI Universe Client and Tool Integration (Phase 20).

Communicates asynchronously with the external AI Universe multi-agent debate API
hosted locally at http://localhost:8000 (or configured via FRIDAY_UNIVERSE_API_URL).
"""

from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.core.verification import evaluate_ai_universe_response
from friday.tools.base import BaseTool

logger = get_logger("tools.ai_universe")


class AIUniverseResponse(BaseModel):
    """Pydantic model for responses received from the AI Universe API."""

    answer: str = Field(default="", description="Synthesized debate conclusion or answer")
    confidence: float = Field(default=0.0, description="Confidence score between 0.0 and 1.0")
    unresolved_disagreements: List[str] = Field(default_factory=list, description="List of lingering agent disagreements")
    key_evidence: List[str] = Field(default_factory=list, description="Key citations and evidence points")
    run_id: str = Field(default="", description="Unique debate run execution identifier")


class AIUniverseClient:
    """HTTP Client for interacting with the AI Universe API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 45.0,
    ) -> None:
        settings = get_settings()
        self.base_url = (
            base_url
            or getattr(settings, "universe_api_url", None)
            or getattr(settings, "ai_universe_api_url", "http://localhost:8000")
        ).rstrip("/")
        self.api_key = api_key or getattr(settings, "api_key", None) or getattr(settings, "friday_api_key", "") or ""
        self.timeout = timeout

    def _get_headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-FRIDAY-API-Key"] = self.api_key
        return headers

    async def ask(self, question: str, mode: str = "auto") -> AIUniverseResponse:
        """Query AI Universe via POST /v1/friday/ask."""
        url = f"{self.base_url}/v1/friday/ask"
        payload = {"question": question, "mode": mode}
        headers = self._get_headers()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return AIUniverseResponse(**data)

    async def debate(self, question: str, max_agents: int = 5) -> AIUniverseResponse:
        """Trigger an in-depth multi-agent debate via POST /v1/friday/debate."""
        url = f"{self.base_url}/v1/friday/debate"
        payload = {"question": question, "max_agents": max_agents}
        headers = self._get_headers()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return AIUniverseResponse(**data)


class AIUniverseTool(BaseTool):
    """SAFE tool allowing FRIDAY to request second opinions or architecture debates from AI Universe."""

    name = "ai_universe_query"
    description = (
        "Consult the external AI Universe multi-agent debate system for complex questions, "
        "strategic dilemmas, architectural second opinions, or comprehensive validation debates."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The complex problem, strategic decision, or architecture to debate.",
            },
            "mode": {
                "type": "string",
                "enum": ["ask", "debate"],
                "description": "Mode of query: 'ask' (fast consensus) or 'debate' (multi-agent deliberation).",
                "default": "debate",
            },
            "max_agents": {
                "type": "integer",
                "description": "Maximum debating agents when mode is 'debate' (default 5).",
                "default": 5,
            },
        },
        "required": ["question"],
    }

    def __init__(self, client: Optional[AIUniverseClient] = None, memory: Optional[Any] = None) -> None:
        super().__init__()
        self.client = client or AIUniverseClient()
        self.memory = memory

    def execute(self, question: str, mode: str = "debate", max_agents: int = 5, **kwargs: Any) -> ToolResult:
        """Execute query synchronously by running the async client call."""
        import asyncio

        clean_q = (question or "").strip()
        if not clean_q:
            return ToolResult(
                name=self.name,
                content="Error: Question cannot be empty.",
                is_error=True,
                safety_level=self.safety_level,
            )

        try:
            try:
                loop = asyncio.get_running_loop()
                if mode == "ask":
                    resp = loop.run_until_complete(self.client.ask(clean_q))
                else:
                    resp = loop.run_until_complete(self.client.debate(clean_q, max_agents=max_agents))
            except RuntimeError:
                if mode == "ask":
                    resp = asyncio.run(self.client.ask(clean_q))
                else:
                    resp = asyncio.run(self.client.debate(clean_q, max_agents=max_agents))

            # Run verification pipeline
            resp_dict = resp.model_dump()
            is_valid, status_msg, extracted = evaluate_ai_universe_response(resp_dict)

            # Store in Memory if verified
            if is_valid and self.memory is not None:
                try:
                    from friday.core.types import Message, Role, TrustLevel
                    validated_content = f"[AI Universe Validated Fact | Run: {resp.run_id} | Conf: {resp.confidence:.2f}]\n{resp.answer}"
                    self.memory.add_message(
                        Message(
                            role=Role.ASSISTANT,
                            content=validated_content,
                            trust_level=TrustLevel.MODEL_OUTPUT,
                            metadata={
                                "type": "validated_fact",
                                "run_id": resp.run_id,
                                "confidence": resp.confidence,
                                "source": "ai_universe",
                            },
                        )
                    )
                except Exception as mem_err:
                    logger.warning(f"Could not persist AI Universe response to memory: {mem_err}")

            if not is_valid:
                if extracted.get("requires_user_authorization"):
                    flags = ", ".join(extracted.get("security_flags", []))
                    return ToolResult(
                        name=self.name,
                        content=f"AI Universe Warning (Run ID: {resp.run_id}): Lingering security/safety disagreements detected ({flags}). Explicit user authorization required before proceeding.\nSummary: {resp.answer}",
                        is_error=False,
                        safety_level=SafetyLevel.SENSITIVE,
                        metadata=resp_dict,
                    )
                return ToolResult(
                    name=self.name,
                    content=f"AI Universe Verification Result: {status_msg} (Confidence: {resp.confidence:.2f} < 0.70 threshold for Run ID: {resp.run_id}). Answer rejected.",
                    is_error=True,
                    safety_level=self.safety_level,
                    metadata=resp_dict,
                )

            evidence_str = "\n".join(f"- {e}" for e in resp.key_evidence) if resp.key_evidence else "None"
            disagreements_str = "\n".join(f"- {d}" for d in resp.unresolved_disagreements) if resp.unresolved_disagreements else "None"

            content = (
                f"### AI Universe Consensus (Run ID: {resp.run_id})\n"
                f"**Confidence**: {resp.confidence * 100:.1f}%\n\n"
                f"**Synthesized Conclusion**:\n{resp.answer}\n\n"
                f"**Key Evidence**:\n{evidence_str}\n\n"
                f"**Unresolved Disagreements**:\n{disagreements_str}"
            )

            return ToolResult(
                name=self.name,
                content=content,
                is_error=False,
                safety_level=self.safety_level,
                metadata=resp_dict,
            )

        except Exception as ex:
            logger.error(f"AI Universe communication failed: {ex}")
            return ToolResult(
                name=self.name,
                content=f"AI Universe connection failed: {str(ex)}. Ensure AI Universe is running at {self.client.base_url}.",
                is_error=True,
                safety_level=self.safety_level,
            )
