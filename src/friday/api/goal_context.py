"""Validated request models for versioned FRIDAY agent execution context."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class FridayAgentPrivateContext(BaseModel):
    """Private memories and verified repair lessons for one specialist."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    private_memories: list[Annotated[str, Field(max_length=800)]] = Field(
        default_factory=list,
        max_length=8,
    )
    verified_repair_lessons: list[Annotated[str, Field(max_length=800)]] = Field(
        default_factory=list,
        max_length=3,
    )


class FridayAgentExecutionContext(BaseModel):
    """Versioned, per-agent context accepted from FRIDAY Universe."""

    model_config = ConfigDict(extra="forbid")

    contract: Literal["friday-agent-context/v1"]
    by_agent: dict[str, FridayAgentPrivateContext] = Field(max_length=9)
    handoff_policy: Literal["verified_predecessor_result_and_evidence_only"]
