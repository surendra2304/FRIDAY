# -*- coding: utf-8 -*-
"""Capability Routing Layer for FRIDAY.

Selects the cheapest, safest, and most deterministic valid capability for each request:
- DIRECT_REASONING: Direct conversational response without tools or external APIs.
- MEMORY_RETRIEVAL: Local SQLite/embedding search for past context and preferences.
- LOCAL_COMPUTATION: Instant local deterministic calculation or system time/info.
- LOCAL_SCREEN_INSPECTION: Reuses cached perception / local ROI checks without calling Vision APIs.
- VISION_MODEL: External multimodal vision provider (only when visual state has changed or uncached).
- VOICE_MODEL: Live voice/speech session.
- TOOL_EXECUTION: Registry tool invocation.
- BACKGROUND_TASK: Asynchronous long-running multi-step task.

Invariants:
- Evaluates explicit cost ($), latency (ms), confidence (0-1), risk (SafetyLevel), and freshness.
- Prefers local deterministic capabilities when sufficient.
- Prefers cached perception over repeated vision calls.
- Never calls an external API simply because it exists.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.security.scrubber import redact_secrets

logger = get_logger("routing.capability")


class ExecutionCapabilityType(str, Enum):
    """Available execution modalities."""
    DIRECT_REASONING = "DIRECT_REASONING"
    MEMORY_RETRIEVAL = "MEMORY_RETRIEVAL"
    LOCAL_COMPUTATION = "LOCAL_COMPUTATION"
    LOCAL_SCREEN_INSPECTION = "LOCAL_SCREEN_INSPECTION"
    VISION_MODEL = "VISION_MODEL"
    VOICE_MODEL = "VOICE_MODEL"
    TOOL_EXECUTION = "TOOL_EXECUTION"
    BACKGROUND_TASK = "BACKGROUND_TASK"


@dataclass
class CapabilityMetadata:
    """Telemetry, cost, and safety metadata for a candidate capability."""
    capability_type: ExecutionCapabilityType
    estimated_cost_usd: float = 0.0
    estimated_latency_ms: float = 0.0
    confidence: float = 1.0
    risk_level: SafetyLevel = SafetyLevel.SAFE
    is_local_deterministic: bool = True
    freshness_seconds: Optional[float] = None
    rationale: str = ""

    def compute_selection_score(self) -> float:
        """Lower score is better (cheapest, fastest, safest, highest confidence)."""
        risk_multipliers = {
            SafetyLevel.SAFE: 0.0,
            SafetyLevel.SENSITIVE: 50.0,
            SafetyLevel.DANGEROUS: 200.0,
        }
        cost_penalty = self.estimated_cost_usd * 10000.0
        latency_penalty = self.estimated_latency_ms * 0.01
        risk_penalty = risk_multipliers.get(self.risk_level, 0.0)
        confidence_bonus = (1.0 - self.confidence) * 100.0
        local_bonus = -20.0 if self.is_local_deterministic else 20.0

        return cost_penalty + latency_penalty + risk_penalty + confidence_bonus + local_bonus

    def to_dict(self) -> Dict[str, Any]:
        return {
            "capability_type": self.capability_type.value,
            "estimated_cost_usd": self.estimated_cost_usd,
            "estimated_latency_ms": round(self.estimated_latency_ms, 1),
            "confidence": round(self.confidence, 2),
            "risk_level": self.risk_level.value,
            "is_local_deterministic": self.is_local_deterministic,
            "freshness_seconds": self.freshness_seconds,
            "rationale": self.rationale,
            "score": round(self.compute_selection_score(), 2),
        }


@dataclass
class RoutingDecision:
    """The optimal capability selected by the router."""
    selected_capability: ExecutionCapabilityType
    reason: str
    candidate_evaluations: List[CapabilityMetadata]
    avoided_external_call: bool = False
    estimated_savings_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "selected_capability": self.selected_capability.value,
            "reason": self.reason,
            "avoided_external_call": self.avoided_external_call,
            "estimated_savings_usd": self.estimated_savings_usd,
            "candidates": [c.to_dict() for c in self.candidate_evaluations],
        }


class CapabilityRouter:
    """Evaluates request requirements and routes to the cheapest and safest valid capability."""

    # Keywords signaling visual inspection
    SCREEN_KEYWORDS = {"screen", "window", "button", "ui", "display", "visual", "look at screen", "screenshot"}
    # Keywords signaling memory search
    MEMORY_KEYWORDS = {"remember", "recall", "earlier", "previous conversation", "past", "history", "what did i say"}
    # Keywords signaling simple local math or system info
    LOCAL_CALC_KEYWORDS = {"what time", "current date", "calculate", "2 + 2", "sum of", "timestamp"}
    # Keywords signaling background execution
    BACKGROUND_KEYWORDS = {"in the background", "async", "long running", "monitor continuously", "background task"}

    def __init__(
        self,
        default_vision_cost_usd: float = 0.002,
        default_llm_cost_usd: float = 0.001,
    ) -> None:
        self.default_vision_cost_usd = default_vision_cost_usd
        self.default_llm_cost_usd = default_llm_cost_usd

    def route_request(
        self,
        user_input: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RoutingDecision:
        """Select the optimal execution capability based on cost, latency, safety, and cache state."""
        ctx = context or {}
        clean_input = user_input.strip().lower()
        candidates: List[CapabilityMetadata] = []

        has_cached_screen = bool(ctx.get("cached_screen_observation"))
        screen_unchanged = bool(ctx.get("screen_unchanged", False))
        cache_age_seconds = ctx.get("cache_age_seconds")

        # 1. Evaluate Direct Reasoning (Conversational / General Knowledge)
        # If user asks pure conversational question without real-world tools
        is_conversational = not any(w in clean_input for w in ["file", "click", "run", "execute", "background", "search memory"])
        if is_conversational and not any(kw in clean_input for kw in self.SCREEN_KEYWORDS | self.MEMORY_KEYWORDS | self.LOCAL_CALC_KEYWORDS):
            candidates.append(CapabilityMetadata(
                capability_type=ExecutionCapabilityType.DIRECT_REASONING,
                estimated_cost_usd=0.0,
                estimated_latency_ms=150.0,
                confidence=0.98,
                risk_level=SafetyLevel.SAFE,
                is_local_deterministic=True,
                rationale="Pure conversational query requiring no tools or external API calls.",
            ))

        # 2. Evaluate Memory Retrieval
        if any(kw in clean_input for kw in self.MEMORY_KEYWORDS):
            candidates.append(CapabilityMetadata(
                capability_type=ExecutionCapabilityType.MEMORY_RETRIEVAL,
                estimated_cost_usd=0.0,
                estimated_latency_ms=5.0,
                confidence=0.95,
                risk_level=SafetyLevel.SAFE,
                is_local_deterministic=True,
                rationale="Query references past conversational memory or stored user facts.",
            ))

        # 3. Evaluate Local Computation (e.g. system time or simple arithmetic)
        if any(kw in clean_input for kw in self.LOCAL_CALC_KEYWORDS) or re.match(r"^\d+\s*[\+\-\*\/]\s*\d+$", clean_input):
            candidates.append(CapabilityMetadata(
                capability_type=ExecutionCapabilityType.LOCAL_COMPUTATION,
                estimated_cost_usd=0.0,
                estimated_latency_ms=1.0,
                confidence=1.0,
                risk_level=SafetyLevel.SAFE,
                is_local_deterministic=True,
                rationale="Deterministic local arithmetic or system timestamp calculation.",
            ))

        # 4. Evaluate Screen Perception (Cached vs Vision Model)
        if any(kw in clean_input for kw in self.SCREEN_KEYWORDS):
            if has_cached_screen and (screen_unchanged or (cache_age_seconds is not None and cache_age_seconds < 5.0)):
                candidates.append(CapabilityMetadata(
                    capability_type=ExecutionCapabilityType.LOCAL_SCREEN_INSPECTION,
                    estimated_cost_usd=0.0,
                    estimated_latency_ms=2.0,
                    confidence=0.95,
                    risk_level=SafetyLevel.SAFE,
                    is_local_deterministic=True,
                    freshness_seconds=cache_age_seconds,
                    rationale="Screen state is unchanged; reusing local cached perception observation.",
                ))
            else:
                candidates.append(CapabilityMetadata(
                    capability_type=ExecutionCapabilityType.VISION_MODEL,
                    estimated_cost_usd=self.default_vision_cost_usd,
                    estimated_latency_ms=800.0,
                    confidence=0.92,
                    risk_level=SafetyLevel.SAFE,
                    is_local_deterministic=False,
                    rationale="Screen state has changed or cache is cold; external vision perception required.",
                ))

        # 5. Evaluate Background Task Execution
        if any(kw in clean_input for kw in self.BACKGROUND_KEYWORDS):
            candidates.append(CapabilityMetadata(
                capability_type=ExecutionCapabilityType.BACKGROUND_TASK,
                estimated_cost_usd=0.0,
                estimated_latency_ms=20.0,
                confidence=0.95,
                risk_level=SafetyLevel.SAFE,
                is_local_deterministic=True,
                rationale="Request explicitly specifies background execution.",
            ))

        # 6. Fallback Tool Execution Candidate
        if any(w in clean_input for w in ["write", "read", "delete", "create", "list", "system", "file", "process"]):
            candidates.append(CapabilityMetadata(
                capability_type=ExecutionCapabilityType.TOOL_EXECUTION,
                estimated_cost_usd=0.0,
                estimated_latency_ms=10.0,
                confidence=0.90,
                risk_level=SafetyLevel.SAFE,
                is_local_deterministic=True,
                rationale="Task requires standard tool registry execution.",
            ))

        # Default fallback to direct reasoning if no specific candidate matched
        if not candidates:
            candidates.append(CapabilityMetadata(
                capability_type=ExecutionCapabilityType.DIRECT_REASONING,
                estimated_cost_usd=0.0,
                estimated_latency_ms=100.0,
                confidence=0.90,
                risk_level=SafetyLevel.SAFE,
                is_local_deterministic=True,
                rationale="Defaulting to local direct reasoning.",
            ))

        # Sort candidates by cost/safety/latency score
        candidates.sort(key=lambda c: c.compute_selection_score())
        chosen = candidates[0]

        avoided_external = chosen.is_local_deterministic and chosen.capability_type not in (
            ExecutionCapabilityType.VISION_MODEL,
            ExecutionCapabilityType.VOICE_MODEL,
        )

        savings = self.default_vision_cost_usd if (
            chosen.capability_type == ExecutionCapabilityType.LOCAL_SCREEN_INSPECTION
            and has_cached_screen
        ) else (self.default_llm_cost_usd if chosen.capability_type in (ExecutionCapabilityType.LOCAL_COMPUTATION, ExecutionCapabilityType.MEMORY_RETRIEVAL) else 0.0)

        decision = RoutingDecision(
            selected_capability=chosen.capability_type,
            reason=chosen.rationale,
            candidate_evaluations=candidates,
            avoided_external_call=avoided_external,
            estimated_savings_usd=savings,
        )

        logger.info(
            f"Routed query '{redact_secrets(user_input[:40])}' to '{chosen.capability_type.value}' "
            f"(Score: {chosen.compute_selection_score():.1f}, Avoided External: {avoided_external})"
        )
        return decision
