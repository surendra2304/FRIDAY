"""Conversational Ecosystem Query Skill for FRIDAY.

Enables fluid natural language queries spanning all four managed subsystems
(Trading Bot, Nexus, FORGE, AI-Universe) including cross-domain multi-part queries
(e.g., "Compare website leads to trading profits this week").
"""

from typing import Any

from friday.core.logging import get_logger
from friday.ecosystem.intelligence_service import (
    EcosystemIntelligenceService,
    ecosystem_intelligence,
)
from friday.ecosystem.registry import EcosystemRegistry, ecosystem_registry
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.conversational_ecosystem")


class ConversationalEcosystemQuery(BaseSkill):
    """Answers conversational inquiries across Trading Bot, Nexus, FORGE, and AI-Universe."""

    __test__ = False

    name = "conversational_ecosystem"
    description = (
        "Answers natural language questions about any ecosystem component (Trading Bot, Nexus, FORGE, AI-Universe) "
        "and resolves multi-part cross-subsystem comparisons (e.g. comparing leads to trading profits)."
    )
    required_capabilities = ["network_access"]
    tools = ["query_ecosystem", "compare_subsystems", "check_ecosystem_health"]
    system_prompt = (
        "You are FRIDAY's Unified Ecosystem Analyst. You synthesize telemetry from Trading Bot, Nexus, FORGE, and AI-Universe "
        "into clear conversational answers."
    )
    match_patterns = [
        r"\b(?:how\s+did\s+the\s+website\s+do|website\s+performance|how\s+is\s+the\s+website)\b",
        r"\b(?:what\s+did\s+(?:the\s+)?trading\s+bot\s+decide|trading\s+decisions?)\b",
        r"\b(?:what\s+did\s+forge\s+build|forge\s+builds\s+this\s+week)\b",
        r"\b(?:is\s+everything\s+healthy|are\s+all\s+systems\s+healthy)\b",
        r"\b(?:compare\s+.*to\s+.*|leads\s+to\s+trading\s+profits)\b",
    ]

    def __init__(
        self,
        intelligence_service: EcosystemIntelligenceService | None = None,
        registry: EcosystemRegistry | None = None,
    ) -> None:
        self.intelligence_service = intelligence_service or ecosystem_intelligence
        self.registry = registry or ecosystem_registry

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Executes conversational multi-subsystem inquiries."""
        clean = user_request.strip().lower()
        step_results: list[dict[str, Any]] = []

        try:
            status = self.registry.get_ecosystem_status()
            subs = status.get("subsystems", {})
            bot = subs.get("trading_bot", {}).get("data", {})
            forge = subs.get("forge", {}).get("data", {})
            ai = subs.get("ai_universe", {}).get("data", {})
            nexus = subs.get("nexus", {}).get("data", {})

            def status_line(label: str, data: dict[str, Any]) -> str:
                status_value = str(data.get("status", "UNVERIFIED"))
                evidence = data.get("evidence")
                suffix = f" Evidence: {evidence}" if evidence else ""
                metrics = {
                    key: value for key, value in data.items()
                    if key not in {"status", "evidence", "service", "checked_at"}
                }
                if metrics:
                    suffix += f" Observed metrics: {metrics}."
                return f"{label}: {status_value}.{suffix}"

            # 1. Multi-part Cross-Subsystem Query: "Compare website leads to trading profits this week"
            if "compare" in clean or ("leads" in clean and "profit" in clean):
                spoken = (
                    "Ecosystem comparison: "
                    + status_line("Cortex", nexus) + " "
                    + status_line("Stratex", bot)
                    + " A comparison requires verified lead and trading event data; no totals are inferred."
                )
                step_results.append({"action": "compare_subsystems", "nexus": nexus, "trading_bot": bot})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 2. Nexus Query: "How did the website do today?"
            if any(k in clean for k in ["how did the website do", "website performance", "website do today"]):
                spoken = "🌐 Website status: " + status_line("Cortex", nexus)
                step_results.append({"action": "query_nexus", "data": nexus})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 3. Trading Bot Query: "What did the trading bot decide overnight?"
            if any(k in clean for k in ["trading bot decide", "trading decisions", "decide overnight"]):
                spoken = "📈 Stratex status: " + status_line("Stratex", bot)
                step_results.append({"action": "query_trading", "data": bot})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 4. FORGE Query: "What did Forge build this week?"
            if any(k in clean for k in ["what did forge build", "forge build this week", "forge builds"]):
                spoken = "🛠️ Forge status: " + status_line("Forge", forge)
                step_results.append({"action": "query_forge", "data": forge})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 5. Global Health Check: "Is everything healthy?"
            if any(k in clean for k in ["is everything healthy", "are all systems healthy"]):
                health = self.registry.get_ecosystem_health()
                h_subs = health.get("subsystems", {})
                spoken = (
                    f"🌐 Full Ecosystem Health Audit: **{health.get('overall_health', 'UNVERIFIED')}**.\n"
                    f"• Stratex: **{h_subs.get('trading_bot', {}).get('status', 'UNVERIFIED')}**\n"
                    f"• Cortex: **{h_subs.get('nexus', {}).get('status', 'UNVERIFIED')}**\n"
                    f"• Forge: **{h_subs.get('forge', {}).get('status', 'UNVERIFIED')}**\n"
                    f"• Inference: **{h_subs.get('ai_universe', {}).get('status', 'UNVERIFIED')}**"
                )
                step_results.append({"action": "check_ecosystem_health", "health": health})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # Default
            spoken = "Ecosystem query received. No matching verified telemetry was available for this request."
            step_results.append({"action": "default"})
            return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

        except Exception as e:
            logger.error(f"[CONVERSATIONAL_ECOSYSTEM] Execution error: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Ecosystem query error: {e}",
                error=str(e),
                step_results=step_results,
            )
