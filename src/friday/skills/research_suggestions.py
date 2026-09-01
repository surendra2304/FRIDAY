"""Proactive Research Suggestion Engine for FRIDAY.

Monitors live multi-subsystem ecosystem telemetry and proposes contextual deep research:
- Trading Bot State: Heavy allocation / volatility surge -> "Your trading bot is heavily positioned in BTC — want me to research regulatory risks?"
- Sentinel Security State: Discovered auth vulnerabilities -> "Sentinel found vulnerabilities in your auth stack — want me to research best-practice auth patterns?"
- Nexus Growth State: New visitor geography / traffic surge -> "Nexus shows visitors from a new geography — want competitive research on that market?"
- Forge Build State: Unfamiliar technology stack -> "Forge is building a real-time service — want technical research on WebSocket vs SSE?"
- Invariant: Suggestions are non-intrusive and tagged TrustLevel.UNTRUSTED_EXTERNAL
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import TrustLevel

logger = get_logger("skills.research_suggestions")


@dataclass
class ResearchSuggestion:
    """Individual contextual research proposal."""
    suggestion_id: str
    subsystem: str  # trading_bot, sentinel, nexus, forge
    prompt: str
    suggested_topic: str
    domain_hint: str
    depth: str
    rationale: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "PENDING"  # PENDING, ACCEPTED, DISMISSED
    trust_level: str = TrustLevel.UNTRUSTED_EXTERNAL.value


class ResearchSuggestionEngine:
    """Analyzes ecosystem conditions to generate intelligent research recommendations."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._suggestions: dict[str, ResearchSuggestion] = {}
        self._init_defaults()

    def _init_defaults(self) -> None:
        """Seeds standard proactive research proposals based on nominal state."""
        self.generate_suggestions_from_ecosystem({
            "trading_bot": {"top_asset": "ETH", "allocation_pct": 42.0},
            "sentinel": {"open_vulnerabilities": ["JWT Algorithm Confusion", "CORS Wildcard"]},
            "nexus": {"new_geography": "DACH Region (Germany/Austria)", "traffic_growth_pct": 28.0},
            "forge": {"active_stack": "Distributed WebSockets"},
        })

    def generate_suggestions_from_ecosystem(
        self,
        ecosystem_state: dict[str, Any],
    ) -> list[ResearchSuggestion]:
        """Evaluates ecosystem telemetry across all 4 operational subsystems."""
        with self._lock:
            new_suggestions: list[ResearchSuggestion] = []

            # 1. Trading Bot Evaluation
            trade = ecosystem_state.get("trading_bot", {})
            top_asset = trade.get("top_asset", "BTC")
            alloc = trade.get("allocation_pct", 0.0)
            if alloc >= 30.0 or top_asset:
                sid = f"sug-trade-{top_asset.lower()}"
                sug = ResearchSuggestion(
                    suggestion_id=sid,
                    subsystem="trading_bot",
                    prompt=f"Your trading bot is heavily positioned in {top_asset} ({alloc:.0f}% allocation) — want me to research regulatory risks and institutional ETF flows?",
                    suggested_topic=f"{top_asset} institutional liquidity drivers and regulatory risk outlook",
                    domain_hint="market",
                    depth="standard",
                    rationale=f"High portfolio exposure ({alloc:.0f}%) in {top_asset}.",
                )
                self._suggestions[sid] = sug
                new_suggestions.append(sug)

            # 2. Sentinel Security Evaluation
            sec = ecosystem_state.get("sentinel", {})
            vulns = sec.get("open_vulnerabilities", [])
            if vulns:
                top_vuln = vulns[0]
                sid = "sug-sec-auth"
                sug = ResearchSuggestion(
                    suggestion_id=sid,
                    subsystem="sentinel",
                    prompt=f"Sentinel found {len(vulns)} vulnerabilities in your auth perimeter (including {top_vuln}) — want me to research industry best-practice mitigation patterns?",
                    suggested_topic=f"Zero-trust authentication and {top_vuln} mitigation best practices",
                    domain_hint="security",
                    depth="deep_dive",
                    rationale="Active security findings in authentication stack.",
                )
                self._suggestions[sid] = sug
                new_suggestions.append(sug)

            # 3. Nexus Website Evaluation
            nexus = ecosystem_state.get("nexus", {})
            geo = nexus.get("new_geography")
            if geo:
                sid = "sug-nexus-geo"
                sug = ResearchSuggestion(
                    suggestion_id=sid,
                    subsystem="nexus",
                    prompt=f"Nexus shows a 28% traffic surge from {geo} — want competitive research on competitors and conversion tactics in that market?",
                    suggested_topic=f"Enterprise SaaS competitor landscape and localization in {geo}",
                    domain_hint="competitive",
                    depth="standard",
                    rationale="Regional visitor traffic spike detected.",
                )
                self._suggestions[sid] = sug
                new_suggestions.append(sug)

            # 4. Forge Engineering Evaluation
            forge = ecosystem_state.get("forge", {})
            stack = forge.get("active_stack")
            if stack:
                sid = "sug-forge-arch"
                sug = ResearchSuggestion(
                    suggestion_id=sid,
                    subsystem="forge",
                    prompt=f"Forge is building services with {stack} — want technical research on latency, reliability tradeoffs, and benchmark comparisons?",
                    suggested_topic=f"{stack} scalability benchmarks and engineering tradeoffs",
                    domain_hint="technical",
                    depth="standard",
                    rationale="New architectural deliverable queued in Forge.",
                )
                self._suggestions[sid] = sug
                new_suggestions.append(sug)

            return new_suggestions

    def get_pending_suggestions(self) -> list[dict[str, Any]]:
        """Retrieves pending research proposals formatted for UI or conversational injection."""
        with self._lock:
            return [
                {
                    "suggestion_id": s.suggestion_id,
                    "subsystem": s.subsystem,
                    "prompt": s.prompt,
                    "suggested_topic": s.suggested_topic,
                    "domain_hint": s.domain_hint,
                    "depth": s.depth,
                    "rationale": s.rationale,
                    "created_at": s.created_at,
                    "status": s.status,
                    "trust_level": s.trust_level,
                }
                for s in self._suggestions.values()
                if s.status == "PENDING"
            ]

    def accept_suggestion(self, suggestion_id: str) -> dict[str, Any] | None:
        """Accepts a proposal and returns parameters for IntelX delegation."""
        with self._lock:
            sug = self._suggestions.get(suggestion_id)
            if not sug:
                return None
            sug.status = "ACCEPTED"
            return {
                "suggestion_id": sug.suggestion_id,
                "topic": sug.suggested_topic,
                "domain_hint": sug.domain_hint,
                "depth": sug.depth,
                "status": "ACCEPTED",
                "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
            }
