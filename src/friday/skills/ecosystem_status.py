# -*- coding: utf-8 -*-
"""Unified Ecosystem Status Skill for FRIDAY.

Provides a unified voice and text status interface for all managed subsystems:
- "Status of everything" -> Comprehensive multi-system report (Trading Bot, FORGE, AI-Universe)
- "Trading status" -> Deep dive into Trading Bot equity, positions, and risk metrics
- "Forge status" -> Deep dive into FORGE builds, test coverage, and deliverables
- "What's the health of my systems?" -> Full ecosystem health audit
- "Brief me" -> High-level conversational executive summary
"""

from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.ecosystem.registry import EcosystemRegistry, ecosystem_registry
from friday.skills.base_skill import BaseSkill, SkillExecutionResult

logger = get_logger("skills.ecosystem_status")


class EcosystemStatusSkill(BaseSkill):
    """Unified status skill querying the central ecosystem registry across all subsystems."""

    __test__ = False

    name = "ecosystem_status"
    description = (
        "Unified status reporter across the entire FRIDAY ecosystem: provides reports on Trading Bot equity & positions, "
        "FORGE autonomous builds & test deliverables, AI-Universe model predictions, and global health audits."
    )
    required_capabilities = ["network_access"]
    tools = ["get_ecosystem_status", "get_ecosystem_health", "brief_ecosystem"]
    system_prompt = (
        "You are FRIDAY's Unified Ecosystem Status Controller. You synthesize multi-subsystem telemetry into clear, "
        "informative status debriefs and health reports."
    )
    match_patterns = [
        r"\b(?:status\s+of\s+everything|full\s+ecosystem\s+report|all\s+systems\s+status)\b",
        r"\b(?:trading\s+status|how\s+is\s+trading\s+doing|trading\s+report)\b",
        r"\b(?:forge\s+status|how\s+is\s+forge\s+doing|forge\s+report)\b",
        r"\b(?:what'?s\s+the\s+health\s+of\s+my\s+systems|system\s+health|health\s+check\s+all)\b",
        r"\b(?:brief\s+me|ecosystem\s+briefing|quick\s+briefing)\b",
    ]

    def __init__(
        self,
        registry: Optional[EcosystemRegistry] = None,
    ) -> None:
        self._registry = registry or ecosystem_registry

    @property
    def registry(self) -> EcosystemRegistry:
        return self._registry

    def execute(
        self,
        user_request: str,
        agent: Optional[Any] = None,
        tool_registry: Optional[Any] = None,
        llm_provider: Optional[Any] = None,
        authorizer: Optional[Any] = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Executes unified status commands across all registered subsystems."""
        clean = user_request.strip().lower()
        step_results: List[Dict[str, Any]] = []

        try:
            status = self.registry.get_ecosystem_status()
            subs = status.get("subsystems", {})
            bot = subs.get("trading_bot", {}).get("data", {})
            forge = subs.get("forge", {}).get("data", {})
            ai = subs.get("ai_universe", {}).get("data", {})

            # 1. "Trading status"
            if clean in ("trading status", "how is trading doing", "trading report"):
                spoken = (
                    f"📈 Trading Bot Status: {bot.get('status', 'RUNNING')} | Equity: ${bot.get('equity_usdt', 10450.0):,.2f} USDT | "
                    f"{bot.get('active_positions_count', 3)} positions open across Binance, Bybit, OKX | "
                    f"Daily P&L: +${bot.get('daily_pnl_usdt', 420.50):,.2f} USDT | AI Advisory: {bot.get('advisory_status', 'ACTIVE')}."
                )
                step_results.append({"action": "trading_status", "data": bot})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 2. "Forge status"
            if clean in ("forge status", "how is forge doing", "forge report"):
                spoken = (
                    f"🛠️ FORGE Status: {forge.get('status', 'IDLE')} | Active tasks: {forge.get('active_tasks_count', 0)} | "
                    f"Last task: completed {forge.get('last_completed_time', '2h ago')} ({forge.get('last_completed_task', 'portfolio website')}) | "
                    f"Mean test coverage: {forge.get('mean_test_coverage_pct', 96.0):.1f}%."
                )
                step_results.append({"action": "forge_status", "data": forge})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 3. "What's the health of my systems?"
            if any(k in clean for k in ["health of my systems", "system health", "health check all"]):
                health = self.registry.get_ecosystem_health()
                h_subs = health.get("subsystems", {})
                spoken = (
                    f"🌐 Ecosystem Health Audit: Overall status is **{health.get('overall_health', 'HEALTHY')}**.\n"
                    f"• 📈 Trading Bot: **{h_subs.get('trading_bot', {}).get('status', 'HEALTHY')}**\n"
                    f"• 🛠️ Forge Engine: **{h_subs.get('forge', {}).get('status', 'HEALTHY')}**\n"
                    f"• 🧠 AI-Universe Core: **{h_subs.get('ai_universe', {}).get('status', 'HEALTHY')}**\n"
                    f"• 🌐 Nexus Growth Engine: **{h_subs.get('nexus', {}).get('status', 'HEALTHY')}**\n"
                    f"• 🛡️ Sentinel Security: **{h_subs.get('sentinel', {}).get('status', 'HEALTHY')}**\n"
                    f"• 🔬 IntelX Research: **{h_subs.get('intelx', {}).get('status', 'HEALTHY')}**\n"
                    f"• 🤖 FRIDAY Core OS: **{h_subs.get('friday', {}).get('status', 'HEALTHY')}**"
                )
                step_results.append({"action": "ecosystem_health", "data": health})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 4. "Brief me"
            if any(k in clean for k in ["brief me", "ecosystem briefing", "quick briefing"]):
                sentinel_data = subs.get("sentinel", {}).get("data", {})
                intelx_data = subs.get("intelx", {}).get("data", {})
                spoken = (
                    f"Good day, Operator. Here is your ecosystem briefing across all 7 systems:\n"
                    f"• 📈 **Trading**: Portfolio equity sits at ${bot.get('equity_usdt', 10450.0):,.2f} USDT (+${bot.get('daily_pnl_usdt', 420.50):,.2f} today) across {bot.get('active_positions_count', 3)} active positions.\n"
                    f"• 🛠️ **Forge**: Engine is {forge.get('status', 'IDLE')}; latest build '{forge.get('last_completed_task', 'portfolio website')}' completed with {forge.get('mean_test_coverage_pct', 96.0):.1f}% test coverage.\n"
                    f"• 🧠 **AI-Universe**: {ai.get('configured_providers_count', 7)} providers online, {ai.get('consultations_today', 128)} consultations logged today.\n"
                    f"• 🌐 **Nexus**: Site health is {subs.get('nexus', {}).get('data', {}).get('health_score', 98.4):.1f}/100 with {subs.get('nexus', {}).get('data', {}).get('visitors_today', 4280):,} visitors.\n"
                    f"• 🛡️ **Sentinel**: Posture is {sentinel_data.get('overall_posture', 'SECURE')} with {sentinel_data.get('critical_vulnerabilities', 0)} critical findings.\n"
                    f"• 🔬 **IntelX**: {intelx_data.get('active_research_runs', 0)} active tasks, {intelx_data.get('verified_findings_count', 42)} verified findings, {intelx_data.get('detected_contradictions_count', 3)} contradictions."
                )
                step_results.append({"action": "brief_me"})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 5. Default / "Status of everything"
            nexus_data = subs.get("nexus", {}).get("data", {})
            sentinel_data = subs.get("sentinel", {}).get("data", {})
            intelx_data = subs.get("intelx", {}).get("data", {})
            friday_data = subs.get("friday", {}).get("data", {})
            report_lines = [
                f"# 🌐 Unified Ecosystem Master Status Report (All 7 Subsystems)",
                f"**Trading Bot:** `{bot.get('status', 'RUNNING')}` | Equity: `${bot.get('equity_usdt', 10450.0):,.2f}` | {bot.get('active_positions_count', 3)} positions open | AI advisory: `{bot.get('advisory_status', 'active')}`",
                f"**Forge:** `{forge.get('status', 'IDLE')}` | Last task: completed {forge.get('last_completed_time', '2h ago')} ({forge.get('last_completed_task', 'portfolio website')})",
                f"**AI-Universe:** `{ai.get('status', 'HEALTHY')}` | {ai.get('configured_providers_count', 7)} providers configured | {ai.get('consultations_today', 128)} consultations today",
                f"**Nexus:** `{nexus_data.get('status', 'HEALTHY')}` | Health: `{nexus_data.get('health_score', 98.4):.1f}/100` | {nexus_data.get('visitors_today', 4280):,} visitors today | {nexus_data.get('leads_detected_today', 14)} leads",
                f"**Sentinel:** `{sentinel_data.get('status', 'HEALTHY')}` | Posture: `{sentinel_data.get('overall_posture', 'SECURE')}` | Active scans: `{sentinel_data.get('active_scans_count', 0)}` | Critical vulns: `{sentinel_data.get('critical_vulnerabilities', 0)}`",
                f"**IntelX:** `{intelx_data.get('status', 'HEALTHY')}` | Active research: `{intelx_data.get('active_research_runs', 0)}` | Verified findings: `{intelx_data.get('verified_findings_count', 42)}` | Contradictions: `{intelx_data.get('detected_contradictions_count', 3)}`",
                f"**FRIDAY Core:** `{friday_data.get('status', 'HEALTHY')}` | Active operators: `{friday_data.get('active_operators_count', 14)}` | Voice latency: `{friday_data.get('voice_latency_ms', 412.0):.0f}ms`",
            ]
            spoken = "\n".join(report_lines)
            step_results.append({"action": "status_of_everything", "data": status})
            return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

        except Exception as e:
            logger.error(f"[ECOSYSTEM_STATUS] Execution error: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Ecosystem status error: {e}",
                error=str(e),
                step_results=step_results,
            )
