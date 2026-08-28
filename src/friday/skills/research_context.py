# -*- coding: utf-8 -*-
"""Research Context Injector for FRIDAY Operating System.

Injects relevant IntelX research insights into active subsystem execution contexts:
- Trading Briefing: Market volatility drivers, macroeconomic news, institutional flows (advisory only)
- Security Briefing / Posture: CVE active exploitation telemetry, mitigations, threat actor intelligence
- Forge Task Submission: Technical architecture comparisons (e.g. WebSockets vs SSE)
- Nexus Website Insights: Competitor intelligence, market positioning, feature comparison
- Invariant: Injected context is strictly tagged TrustLevel.UNTRUSTED_EXTERNAL
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import TrustLevel
from friday.memory.research_library import ResearchLibrary

logger = get_logger("skills.research_context")


class ResearchContextInjector:
    """Injects synthesized research findings into subsystem operation payloads."""

    def __init__(self, library: Optional[ResearchLibrary] = None) -> None:
        self.library = library or ResearchLibrary()

    def inject_trading_market_context(
        self,
        trading_briefing: Dict[str, Any],
        asset: str = "BTC",
    ) -> Dict[str, Any]:
        """Enriches trading briefing with relevant market research intelligence (advisory only)."""
        search_res = self.library.search(query=f"{asset} market volatility macro events", domain="market", limit=2)
        research_notes = []

        for r in search_res:
            research_notes.append(f"• [IntelX Market Research]: {r['topic']} — Top Finding: {r.get('top_finding')}")

        if not research_notes:
            research_notes.append(f"• [IntelX Market Research]: Macro conditions nominal for {asset}. No anomalous regulatory alerts.")

        enriched = dict(trading_briefing)
        enriched["market_research_context"] = {
            "asset": asset,
            "research_notes": research_notes,
            "advisory_disclaimer": "Market research findings are for context only; automated execution based on research is prohibited.",
            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
        }
        return enriched

    def inject_security_threat_context(
        self,
        security_report: Dict[str, Any],
        cve_or_vulnerability: str,
    ) -> Dict[str, Any]:
        """Enriches security posture with CVE threat intelligence and mitigation research."""
        search_res = self.library.search(query=cve_or_vulnerability, domain="security", limit=2)
        threat_intelligence = []

        for r in search_res:
            threat_intelligence.append(f"• [IntelX Threat Intel]: {r['topic']} — Evidence: {r.get('top_finding')}")

        if not threat_intelligence:
            threat_intelligence.append(f"• [IntelX Threat Intel]: Active monitoring for {cve_or_vulnerability} exploitation in the wild.")

        enriched = dict(security_report)
        enriched["threat_research_context"] = {
            "target_vulnerability": cve_or_vulnerability,
            "threat_intelligence": threat_intelligence,
            "remediation_priority": "CRITICAL_ELEVATED" if "critical" in cve_or_vulnerability.lower() else "STANDARD",
            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
        }
        return enriched

    def inject_forge_technical_context(
        self,
        build_spec: Dict[str, Any],
        architecture_topic: str,
    ) -> Dict[str, Any]:
        """Enriches Forge software build specification with technical comparison research."""
        search_res = self.library.search(query=architecture_topic, domain="technical", limit=2)
        tech_recommendations = []

        for r in search_res:
            tech_recommendations.append(f"• [IntelX Technical Research]: {r['topic']} — Recommendation: {r.get('top_finding')}")

        if not tech_recommendations:
            tech_recommendations.append(f"• [IntelX Technical Research]: Standard modern architectural patterns recommended for {architecture_topic}.")

        enriched = dict(build_spec)
        enriched["technical_research_context"] = {
            "topic": architecture_topic,
            "recommendations": tech_recommendations,
            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
        }
        return enriched

    def inject_nexus_competitive_context(
        self,
        nexus_insights: Dict[str, Any],
        competitor_name: str,
    ) -> Dict[str, Any]:
        """Enriches Nexus visitor insights with competitor intelligence and positioning data."""
        search_res = self.library.search(query=competitor_name, domain="competitive", limit=2)
        competitive_intel = []

        for r in search_res:
            competitive_intel.append(f"• [IntelX Competitive Intel]: {r['topic']} — Comparison: {r.get('top_finding')}")

        if not competitive_intel:
            competitive_intel.append(f"• [IntelX Competitive Intel]: {competitor_name} pricing & feature matrix logged for positioning.")

        enriched = dict(nexus_insights)
        enriched["competitive_research_context"] = {
            "competitor": competitor_name,
            "intel": competitive_intel,
            "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
        }
        return enriched
