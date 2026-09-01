"""AI Universe Client and Tool Integration (AI Universe Integration).

Communicates asynchronously with the external AI Universe multi-agent debate API
hosted locally at http://localhost:8000 (or configured via FRIDAY_UNIVERSE_API_URL).
"""

import json
from typing import Any

import httpx
from pydantic import BaseModel, Field

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.core.verification import evaluate_ai_universe_response
from friday.tools.base import BaseTool

logger = get_logger("tools.ai_universe")


class AIAgentInfo(BaseModel):
    """Information for a single specialist agent registered in AI Universe."""

    id: str = Field(default="", description="Unique identifier for the agent")
    name: str = Field(default="", description="Human-readable agent name")
    role: str = Field(default="", description="Specialist role")
    purpose: str = Field(default="", description="Core mission or directive")
    provider: str = Field(default="", description="Cloud or local LLM provider")
    model: str = Field(default="", description="Live assigned model")
    strengths: list[str] = Field(default_factory=list, description="Key domain strengths")
    status: str = Field(default="active", description="Agent availability status")


class AIUniverseResponse(BaseModel):
    """Pydantic model for responses received from the AI Universe API."""

    answer: str = Field(default="", description="Synthesized debate conclusion or answer")
    confidence: float = Field(default=0.0, description="Confidence score between 0.0 and 1.0")
    unresolved_disagreements: list[str] = Field(default_factory=list, description="List of lingering agent disagreements")
    key_evidence: list[str] = Field(default_factory=list, description="Key citations and evidence points")
    run_id: str = Field(default="", description="Unique debate run execution identifier")
    agents_used: list[str] = Field(default_factory=list, description="List of participating agent IDs")
    models_used: list[str] = Field(default_factory=list, description="List of active models evaluated")
    mode_used: str | None = Field(default=None, description="Mode utilized (e.g. 'consensus' or 'debate')")
    provenance: dict[str, Any] = Field(default_factory=dict, description="Execution provenance and audit metadata")


class AIUniverseClient:
    """HTTP Client for interacting with the AI Universe API."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float = 45.0,
    ) -> None:
        import os
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = (
                os.getenv("INFERENCE_URL")
                or os.getenv("FRIDAY_UNIVERSE_API_URL")
                or "https://inference-3i2b.onrender.com"
            ).rstrip("/")

        if api_key is not None:
            self.api_key = api_key.strip()
        else:
            self.api_key = (
                os.getenv("INFERENCE_API_KEY")
                or os.getenv("FRIDAY_UNIVERSE_API_KEY")
                or "inference_api"
            ).strip()
        self.timeout = timeout

    def _get_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-FRIDAY-API-Key"] = self.api_key
            headers["X-INFERENCE-API-KEY"] = self.api_key
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def get_status(self) -> dict[str, Any]:
        """Fetch AI Universe status and agents configuration from GET /v1/friday/status."""
        url = f"{self.base_url}/v1/friday/status"
        headers = self._get_headers()
        key_preview = f"{self.api_key[:4]}..." if self.api_key else "(none)"
        print(f"[DEBUG] Sending to {url} with key {key_preview}")
        logger.info(f"Sending to {url} with key {key_preview}...")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def get_agents(self) -> list[AIAgentInfo]:
        """Discover live roster of all specialist agents from GET /v1/friday/agents."""
        url = f"{self.base_url}/v1/friday/agents"
        headers = self._get_headers()
        key_preview = f"{self.api_key[:4]}..." if self.api_key else "(none)"
        print(f"[DEBUG] Sending to {url} with key {key_preview}")
        logger.info(f"Sending to {url} with key {key_preview}...")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list):
                return [AIAgentInfo(**item) for item in data]
            return []

    async def get_info(self) -> dict[str, Any]:
        """Fetch AI Universe platform info from GET /v1/friday/info."""
        url = f"{self.base_url}/v1/friday/info"
        headers = self._get_headers()
        key_preview = f"{self.api_key[:4]}..." if self.api_key else "(none)"
        print(f"[DEBUG] Sending to {url} with key {key_preview}")
        logger.info(f"Sending to {url} with key {key_preview}...")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def ask(self, question: str, mode: str = "auto") -> AIUniverseResponse:
        """Query AI Universe via POST /v1/friday/ask."""
        url = f"{self.base_url}/v1/friday/ask"
        payload = {"question": question, "mode": mode}
        headers = self._get_headers()

        key_preview = f"{self.api_key[:4]}..." if self.api_key else "(none)"
        print(f"[DEBUG] Sending to {url} with key {key_preview}")
        logger.info(f"Sending to {url} with key {key_preview}...")

        timeout_obj = httpx.Timeout(self.timeout, connect=15.0, read=self.timeout, write=15.0)
        async with httpx.AsyncClient(timeout=timeout_obj) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            return AIUniverseResponse(**data)

    async def debate(self, question: str, max_agents: int = 5) -> AIUniverseResponse:
        """Trigger an in-depth multi-agent debate via POST /v1/friday/debate."""
        url = f"{self.base_url}/v1/friday/debate"
        payload = {"question": question, "max_agents": max_agents}
        headers = self._get_headers()

        key_preview = f"{self.api_key[:4]}..." if self.api_key else "(none)"
        print(f"[DEBUG] Sending to {url} with key {key_preview}")
        logger.info(f"Sending AI Universe debate request to {url} with key {key_preview}")

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
                "description": "The complex problem, strategic decision, or architecture to debate. Can be omitted or set to 'list' when querying agents.",
                "default": "",
            },
            "mode": {
                "type": "string",
                "enum": ["ask", "debate", "agents", "info"],
                "description": "Mode: 'debate' (multi-agent deliberation), 'ask' (fast consensus), 'agents' (discover registered specialist agents and their live models), or 'info' (system status).",
                "default": "debate",
            },
            "max_agents": {
                "type": "integer",
                "description": "Maximum debating agents when mode is 'debate' (default 5).",
                "default": 5,
            },
        },
        "required": [],
    }

    def __init__(self, client: AIUniverseClient | None = None, memory: Any | None = None) -> None:
        super().__init__()
        self.client = client or AIUniverseClient()
        self.memory = memory

    def execute(self, question: str = "", mode: str = "debate", max_agents: int = 5, **kwargs: Any) -> ToolResult:
        """Execute query synchronously by running the async client call."""
        import asyncio

        clean_q = (question or "").strip()

        # Handle agent discovery and system info queries directly
        if mode == "agents" or clean_q.lower() in ("agents", "list agents", "show agents", "roster", "who are you"):
            try:
                try:
                    loop = asyncio.get_running_loop()
                    agents_list = loop.run_until_complete(self.client.get_agents())
                except RuntimeError:
                    agents_list = asyncio.run(self.client.get_agents())

                if not agents_list:
                    return ToolResult(
                        name=self.name,
                        content="AI Universe returned an empty agent roster.",
                        is_error=False,
                        safety_level=self.safety_level,
                    )

                lines = ["### AI Universe Active Specialist Agents & Models Roster:"]
                for a in agents_list:
                    lines.append(f"- **{a.name}** (`{a.id}`) — **Role**: {a.role} | **Provider**: {a.provider} | **Model**: `{a.model}`\n  *Purpose*: {a.purpose}")
                return ToolResult(
                    name=self.name,
                    content="\n".join(lines),
                    is_error=False,
                    safety_level=self.safety_level,
                    metadata={"agents": [a.model_dump() for a in agents_list]},
                )
            except Exception as ex:
                return ToolResult(
                    name=self.name,
                    content=f"Failed to fetch AI Universe agents roster: {ex}",
                    is_error=True,
                    safety_level=self.safety_level,
                )

        if mode == "info":
            try:
                try:
                    loop = asyncio.get_running_loop()
                    info_data = loop.run_until_complete(self.client.get_info())
                except RuntimeError:
                    info_data = asyncio.run(self.client.get_info())

                return ToolResult(
                    name=self.name,
                    content=f"### AI Universe Platform Info:\n```json\n{json.dumps(info_data, indent=2)}\n```",
                    is_error=False,
                    safety_level=self.safety_level,
                    metadata=info_data,
                )
            except Exception as ex:
                return ToolResult(
                    name=self.name,
                    content=f"Failed to fetch AI Universe platform info: {ex}",
                    is_error=True,
                    safety_level=self.safety_level,
                )

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
                                "agents_used": resp.agents_used,
                                "models_used": resp.models_used,
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
            agents_str = ", ".join(resp.agents_used) if resp.agents_used else "Auto-selected ensemble"
            models_str = ", ".join(resp.models_used) if resp.models_used else "Multi-provider pool"

            content = (
                f"### AI Universe Consensus (Run ID: {resp.run_id})\n"
                f"**Confidence**: {resp.confidence * 100:.1f}%\n"
                f"**Participating Agents**: {agents_str}\n"
                f"**Evaluated Models**: {models_str}\n\n"
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
                content=f"AI Universe connection failed: {ex!s}. Ensure AI Universe is running at {self.client.base_url}.",
                is_error=True,
                safety_level=self.safety_level,
            )


class GetAIUniverseStatusTool(BaseTool):
    """SAFE tool to inspect the live status, agents configuration, and active models of the AI Universe."""

    name = "get_ai_universe_status"
    description = (
        "Retrieve the live internal configuration, platform status, registered specialist agents, "
        "and active model pool from the AI Universe system (/v1/friday/status)."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, client: AIUniverseClient | None = None) -> None:
        super().__init__()
        self.client = client or AIUniverseClient()

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute status check synchronously against the AI Universe API."""
        import asyncio
        import json

        try:
            try:
                loop = asyncio.get_running_loop()
                status_data = loop.run_until_complete(self.client.get_status())
            except RuntimeError:
                status_data = asyncio.run(self.client.get_status())

            return ToolResult(
                name=self.name,
                content=f"### AI Universe Status & Internal Configuration:\n```json\n{json.dumps(status_data, indent=2)}\n```",
                is_error=False,
                safety_level=self.safety_level,
                metadata=status_data,
            )
        except Exception as ex:
            # Fallback to agents list if status endpoint differs
            try:
                try:
                    loop = asyncio.get_running_loop()
                    agents = loop.run_until_complete(self.client.get_agents())
                except RuntimeError:
                    agents = asyncio.run(self.client.get_agents())

                if agents:
                    lines = ["### AI Universe Active Specialist Agents & Models:"]
                    for a in agents:
                        lines.append(f"- **{a.name}** (`{a.id}`) — Role: {a.role} | Provider: {a.provider} | Model: `{a.model}`")
                    return ToolResult(
                        name=self.name,
                        content="\n".join(lines),
                        is_error=False,
                        safety_level=self.safety_level,
                        metadata={"agents": [a.model_dump() for a in agents]},
                    )
            except Exception:
                pass

            return ToolResult(
                name=self.name,
                content=f"Failed to query AI Universe status: {ex!s}. Ensure AI Universe is running at {self.client.base_url}.",
                is_error=True,
                safety_level=self.safety_level,
            )

