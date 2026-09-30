"""Unified Intelligence Panel for FRIDAY Ecosystem Dashboard.

Renders an integrated multi-subsystem intelligence view:
- Weighted composite ecosystem health gauge
- Trading Bot performance, positions, and drawdown metrics
- Nexus traffic, conversion rates, and high-intent lead pipelines
- FORGE build velocity, verification coverage, and active pipelines
- AI-Universe provider availability and consultation volume
- Real-time cross-system anomaly feeds
"""

from datetime import datetime, timezone
from typing import Any

from friday.ecosystem.intelligence_service import (
    EcosystemIntelligenceService,
    ecosystem_intelligence,
)
from friday.ecosystem.registry import EcosystemRegistry, ecosystem_registry


class UnifiedIntelligencePanel:
    """Dashboard UI component rendering four-system unified intelligence."""

    def __init__(
        self,
        intelligence_service: EcosystemIntelligenceService | None = None,
        registry: EcosystemRegistry | None = None,
    ) -> None:
        self.intelligence_service = intelligence_service or ecosystem_intelligence
        self.registry = registry or ecosystem_registry

    def render_intelligence_data(self) -> dict[str, Any]:
        """Assembles structured intelligence data for web/mobile UI views."""
        status = self.registry.get_ecosystem_status()
        subs = status.get("subsystems", {})
        bot = subs.get("trading_bot", {}).get("data", {})
        forge = subs.get("forge", {}).get("data", {})
        ai = subs.get("ai_universe", {}).get("data", {})
        nexus = subs.get("nexus", {}).get("data", {})

        telemetry = {"trading_bot": bot, "forge": forge, "ai_universe": ai, "nexus": nexus}
        composite_score = self.intelligence_service.compute_composite_health_score(telemetry)
        score_label = f"{composite_score}/100" if composite_score is not None else "UNVERIFIED"

        def observed(data: dict[str, Any], key: str, suffix: str = "") -> str:
            value = data.get(key)
            return f"{value}{suffix}" if value is not None else "Not verified"

        return {
            "title": "FRIDAY Unified Ecosystem Intelligence Dashboard",
            "composite_health_score": composite_score,
            "composite_health_label": score_label,
            "status": "UNVERIFIED" if composite_score is None else "OBSERVED",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "subsystems": {
                "trading": {
                    "equity": observed(bot, "equity_usdt", " USDT"),
                    "daily_pnl": observed(bot, "daily_pnl_usdt", " USDT"),
                    "positions_count": observed(bot, "active_positions_count"),
                    "status": bot.get("status", "UNVERIFIED"),
                },
                "nexus": {
                    "health_score": observed(nexus, "health_score", "/100"),
                    "visitors": observed(nexus, "visitors_today"),
                    "leads": observed(nexus, "leads_detected_today"),
                    "conversion_rate": observed(nexus, "conversion_rate_pct", "%"),
                },
                "forge": {
                    "delivered": observed(forge, "total_completed"),
                    "active_tasks": observed(forge, "active_tasks_count"),
                    "mean_coverage": observed(forge, "mean_test_coverage_pct", "%"),
                    "status": forge.get("status", "UNVERIFIED"),
                },
                "ai_universe": {
                    "providers_online": observed(ai, "configured_providers_count"),
                    "consultations": observed(ai, "consultations_today"),
                    "model_confidence": observed(ai, "model_confidence_pct", "%"),
                },
            },
            "one_click_reports": [
                {"label": "Generate Morning Briefing", "action": "generate_morning_briefing"},
                {"label": "Generate Evening Wrap-Up", "action": "generate_evening_wrapup"},
                {"label": "Generate Weekly Report", "action": "generate_weekly_report"},
            ],
        }

    def render_markdown(self) -> str:
        """Renders comprehensive Markdown presentation of the intelligence view."""
        data = self.render_intelligence_data()
        subs = data["subsystems"]
        t = subs["trading"]
        n = subs["nexus"]
        f = subs["forge"]
        a = subs["ai_universe"]

        return (
            f"# 🧠 {data['title']}\n\n"
            f"**Composite Ecosystem Health:** `{data['composite_health_label']}` (`{data['status']}`)\n\n"
            f"### 📈 Quantitative Trading\n"
            f"- **Equity:** `{t['equity']}` | **P&L:** `{t['daily_pnl']}` | **Positions:** `{t['positions_count']}`\n\n"
            f"### 🌐 Nexus Growth & Website\n"
            f"- **Health:** `{n['health_score']}` | **Visitors:** `{n['visitors']}` | **Leads:** `{n['leads']}` | **CR:** `{n['conversion_rate']}`\n\n"
            f"### 🛠️ FORGE Software Engineering\n"
            f"- **Delivered:** `{f['delivered']}` builds | **Coverage:** `{f['mean_coverage']}` | **Status:** `{f['status']}`\n\n"
            f"### 🧠 AI-Universe Intelligence Core\n"
            f"- **Providers:** `{a['providers_online']}` | **Consultations:** `{a['consultations']}` | **Confidence:** `{a['model_confidence']}`\n"
        )
