"""
FRIDAY/apps/core/src/friday_core/decision_synthesis_engine.py — FRIDAY Decision Synthesis Engine.

Combines outputs from multiple agents into unified decisions with conflict
resolution, confidence weighting, and consensus building.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class AgentRecommendation:
    """A recommendation from an agent."""
    agent_name: str
    recommendation_id: str
    action: str
    rationale: str
    confidence: float = 0.5
    expected_value: float = 0.0
    risk_level: str = "low"
    timestamp: float = field(default_factory=time.time)


@dataclass
class SynthesizedDecision:
    """A synthesized decision from multiple agents."""
    decision_id: str
    action: str
    contributing_agents: list[str]
    conflicts_resolved: list[str]
    confidence: float
    rationale: str
    expected_value: float
    risk_level: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConflictRecord:
    """Record of a conflict between agent recommendations."""
    conflict_id: str
    decision_id: str
    agents_involved: list[str]
    conflict_type: str
    resolution: str
    resolution_rationale: str


class DecisionSynthesisEngine:
    """Engine for synthesizing decisions from multiple agent recommendations."""

    def __init__(self) -> None:
        self._recommendations: dict[str, list[AgentRecommendation]] = {}
        self._decisions: dict[str, SynthesizedDecision] = {}
        self._conflicts: dict[str, ConflictRecord] = {}

    def submit_recommendation(self, agent_name: str, action: str, rationale: str,
                              confidence: float = 0.5, expected_value: float = 0.0,
                              risk_level: str = "low") -> str:
        """Submit a recommendation from an agent."""
        recommendation = AgentRecommendation(
            agent_name=agent_name,
            recommendation_id=f"rec_{uuid.uuid4().hex[:12]}",
            action=action,
            rationale=rationale,
            confidence=confidence,
            expected_value=expected_value,
            risk_level=risk_level,
        )
        self._recommendations.setdefault("default", []).append(recommendation)
        return recommendation.recommendation_id

    def synthesize_decision(self, recommendation_group: str = "default") -> SynthesizedDecision:
        """Synthesize a decision from all recommendations in a group."""
        recs = self._recommendations.get(recommendation_group, [])
        if not recs:
            raise HTTPException(status_code=400, detail="No recommendations to synthesize")

        # Group by action
        action_groups: dict[str, list[AgentRecommendation]] = {}
        for rec in recs:
            action_groups.setdefault(rec.action, []).append(rec)

        # Find the action with highest aggregated confidence
        best_action = max(action_groups, key=lambda a: sum(r.confidence for r in action_groups[a]))
        best_recs = action_groups[best_action]

        # Detect conflicts
        conflicts = []
        for action, group in action_groups.items():
            if action != best_action:
                conflict = ConflictRecord(
                    conflict_id=f"conf_{uuid.uuid4().hex[:12]}",
                    decision_id="",
                    agents_involved=[r.agent_name for r in group],
                    conflict_type="action_mismatch",
                    resolution=f"Selected action '{best_action}' with higher aggregated confidence",
                    resolution_rationale=f"Action '{action}' had lower aggregated confidence",
                )
                conflicts.append(conflict)

        # Calculate aggregated metrics
        total_confidence = sum(r.confidence for r in best_recs) / len(best_recs)
        total_value = sum(r.expected_value for r in best_recs) / len(best_recs)
        risk_levels = [r.risk_level for r in best_recs]
        risk = "high" if "high" in risk_levels else "medium" if "medium" in risk_levels else "low"

        decision = SynthesizedDecision(
            decision_id=f"dec_{uuid.uuid4().hex[:12]}",
            action=best_action,
            contributing_agents=[r.agent_name for r in best_recs],
            conflicts_resolved=[c.conflict_id for c in conflicts],
            confidence=total_confidence,
            rationale=f"Selected '{best_action}' from {len(best_recs)} agents with avg confidence {total_confidence:.2f}",
            expected_value=total_value,
            risk_level=risk,
        )
        for c in conflicts:
            c.decision_id = decision.decision_id
            self._conflicts[c.conflict_id] = c
        self._decisions[decision.decision_id] = decision
        return decision

    def get_decision(self, decision_id: str) -> dict[str, Any]:
        """Get a decision by ID."""
        dec = self._decisions.get(decision_id)
        if not dec:
            raise HTTPException(status_code=404, detail="Decision not found")
        return {
            "decision_id": dec.decision_id,
            "action": dec.action,
            "contributing_agents": dec.contributing_agents,
            "conflicts_resolved": dec.conflicts_resolved,
            "confidence": dec.confidence,
            "rationale": dec.rationale,
            "expected_value": dec.expected_value,
            "risk_level": dec.risk_level,
        }

    def get_all_decisions(self) -> list[dict[str, Any]]:
        """Get all synthesized decisions."""
        return [
            {
                "decision_id": d.decision_id,
                "action": d.action,
                "agents": d.contributing_agents,
                "confidence": d.confidence,
                "risk_level": d.risk_level,
            }
            for d in self._decisions.values()
        ]

    def get_report(self) -> dict[str, Any]:
        """Get engine report."""
        return {
            "total_recommendations": sum(len(v) for v in self._recommendations.values()),
            "total_decisions": len(self._decisions),
            "total_conflicts": len(self._conflicts),
            "engine_status": "operational",
        }


engine = DecisionSynthesisEngine()


@router.post("/synthesis/recommend")
async def submit_recommendation(agent_name: str, action: str, rationale: str,
                                confidence: float = 0.5, expected_value: float = 0.0,
                                risk_level: str = "low"):
    """Submit an agent recommendation for synthesis."""
    rec_id = engine.submit_recommendation(agent_name, action, rationale, confidence, expected_value, risk_level)
    return {"recommendation_id": rec_id, "status": "received"}


@router.post("/synthesis/decide")
async def synthesize_decision(group: str = "default"):
    """Synthesize a decision from all agent recommendations."""
    decision = engine.synthesize_decision(group)
    return {
        "decision_id": decision.decision_id,
        "action": decision.action,
        "contributing_agents": decision.contributing_agents,
        "confidence": decision.confidence,
        "risk_level": decision.risk_level,
        "rationale": decision.rationale,
    }


@router.get("/synthesis/decisions/{decision_id}")
async def get_decision(decision_id: str):
    """Get a synthesized decision by ID."""
    return engine.get_decision(decision_id)


@router.get("/synthesis/decisions")
async def list_decisions():
    """List all synthesized decisions."""
    return {"decisions": engine.get_all_decisions()}


@router.get("/synthesis/report")
async def synthesis_report():
    """Get decision synthesis report."""
    return engine.get_report()
