"""Ecosystem Dashboard Panel for FRIDAY.

Provides visual UI cards, central alert feeds, and one-click actions across all subsystems:
- Trading Bot Card: Equity, P&L, positions, emergency stop action
- FORGE Card: Active builds, test coverage, submit build action
- AI-Universe Card: Provider availability, model confidence, consultation counts
- Consolidated Alert Feed & Action Trigger Registry
"""

from datetime import datetime, timezone
from typing import Any

from friday.ecosystem.registry import EcosystemRegistry, ecosystem_registry


class EcosystemDashboardPanel:
    """Renders multi-subsystem visual cards, central feeds, and action triggers."""

    def __init__(
        self,
        registry: EcosystemRegistry | None = None,
    ) -> None:
        self._registry = registry or ecosystem_registry

    @property
    def registry(self) -> EcosystemRegistry:
        return self._registry

    def render_panel_data(self) -> dict[str, Any]:
        """Assembles structured UI panel data for dashboard rendering."""
        status = self.registry.get_ecosystem_status()
        health = self.registry.get_ecosystem_health()
        subs = status.get("subsystems", {})

        bot = subs.get("trading_bot", {}).get("data", {})
        forge = subs.get("forge", {}).get("data", {})
        ai = subs.get("ai_universe", {}).get("data", {})
        nexus = subs.get("nexus", {}).get("data", {})

        from friday.core.readings import UNKNOWN_LABEL, read_number, read_text

        # Every number below was a literal with a "reasonable" default: an
        # equity of $10,450, a +$420.50 day, 3 positions, 2 delivered builds at
        # 96.0% coverage, 7 providers, 128 consultations, 84% confidence, a
        # Nexus site health of 98.4/100 and 4,280 visitors - none of which any
        # subsystem had reported. A card that shows a confident number when the
        # subsystem is silent is worse than a card that shows nothing.
        def _metric(reading, template: str) -> str:
            if not reading.known:
                return UNKNOWN_LABEL
            return template.format(value=reading.value)

        equity = read_number(bot, "equity_usdt", source="trading bot")
        daily_pnl = read_number(bot, "daily_pnl_usdt", source="trading bot")
        positions = read_number(bot, "active_positions_count", source="trading bot")
        coverage = read_number(forge, "mean_test_coverage_pct", source="forge")
        builds = read_number(forge, "total_completed", source="forge")
        providers = read_number(ai, "configured_providers_count", source="ai universe")
        consultations = read_number(ai, "consultations_today", source="ai universe")
        confidence = read_number(ai, "model_confidence_pct", source="ai universe")
        site_health = read_number(nexus, "health_score", source="nexus")
        visitors = read_number(nexus, "visitors_today", source="nexus")

        def _count(reading, suffix: str) -> str:
            return UNKNOWN_LABEL if not reading.known else f"{reading.value:,.0f} {suffix}"

        return {
            "title": "FRIDAY Unified Ecosystem Command Panel",
            "overall_health": read_text(health, "overall_health"),
            "cards": {
                "trading_bot": {
                    "title": "Trading Bot",
                    "icon": "📈",
                    "status": read_text(bot, "status"),
                    "key_metric": f"{_metric(equity, '${value:,.2f}')} USDT",
                    "pnl": f"{_metric(daily_pnl, '${value:,.2f}')} USDT",
                    "positions_count": int(positions.value) if positions.known else UNKNOWN_LABEL,
                    "quick_actions": ["Emergency stop trading", "View open positions"],
                },
                "forge": {
                    "title": "FORGE SWE Engine",
                    "icon": "🛠️",
                    "status": read_text(forge, "status"),
                    "key_metric": f"{_count(builds, 'Delivered Builds')}",
                    "mean_coverage": f"{_metric(coverage, '{value:.1f}%')}",
                    "active_tasks": int(read_number(forge, "active_tasks_count").or_else(0))
                    if read_number(forge, "active_tasks_count").known else UNKNOWN_LABEL,
                    "quick_actions": ["Build something new", "Show FORGE artifacts"],
                },
                "ai_universe": {
                    "title": "AI-Universe Core",
                    "icon": "🧠",
                    "status": read_text(ai, "status"),
                    "key_metric": f"{_count(providers, 'Providers Online')}",
                    "consultations": f"{_count(consultations, 'consultations')}",
                    "confidence": f"{_metric(confidence, '{value:.0f}%')}",
                    "quick_actions": ["Request market briefing", "Explain predictions"],
                },
                "nexus": {
                    "title": "Nexus Website & Growth",
                    "icon": "🌐",
                    "status": read_text(nexus, "status"),
                    "site_health": f"{_metric(site_health, '{value:.1f}/100')}",
                    "visitors_today": f"{_count(visitors, 'visitors')}",
                    "lead_count": int(read_number(nexus, "leads_detected_today").value)
                    if read_number(nexus, "leads_detected_today").known else UNKNOWN_LABEL,
                    "active_incidents": int(read_number(nexus, "active_incidents_count").value)
                    if read_number(nexus, "active_incidents_count").known else UNKNOWN_LABEL,
                    "pending_approvals": int(read_number(nexus, "pending_approvals_count").value)
                    if read_number(nexus, "pending_approvals_count").known else UNKNOWN_LABEL,
                    "quick_actions": ["View high-intent leads", "Diagnose conversion drop", "Pause experiment"],
                },
            },
            # The feed used to carry three literals - a trailing-stop update at
            # $64,200, a task "verified with 96.0% test coverage", and a lead
            # from acme-corp.com - each stamped with the current time so they
            # read as events that had just happened. They are now whatever the
            # ecosystem layer has actually recorded, and an empty feed stays
            # empty rather than being filled in.
            "alerts_feed": self._recorded_alerts(),
            "one_click_actions": [
                {"label": "Build something new", "action": "forge_build_dialog"},
                {"label": "Emergency stop trading", "action": "panic_kill_switch"},
                {"label": "Review Nexus leads", "action": "nexus_lead_review"},
            ],
        }

    def _recorded_alerts(self) -> list[dict[str, Any]]:
        """One feed entry per subsystem, from the subsystem's own report.

        A dashboard that invents its activity feed cannot be used to notice that
        something stopped happening: the feed looks the same either way. This
        reads the same registry the cards above it read, so the feed and the
        cards can never disagree - including the "UNVERIFIED" state, which is a
        real report and is labelled as one.
        """
        alerts: list[dict[str, Any]] = []
        for name, entry in (self.registry.get_ecosystem_status().get("subsystems") or {}).items():
            data = entry.get("data") or {}
            status = str(entry.get("status", "UNKNOWN")).upper()
            evidence = data.get("evidence") or ""
            severity = "WARNING" if status in {"UNVERIFIED", "UNKNOWN", "DEGRADED"} else "INFO"
            alerts.append(
                {
                    "timestamp": data.get("checked_at") or datetime.now(timezone.utc).isoformat(),
                    "subsystem": name,
                    "message": f"{entry.get('display_name', name)}: {status}" + (f" - {evidence}" if evidence else ""),
                    "severity": severity,
                }
            )
        return alerts

    def render_markdown(self) -> str:
        """Renders comprehensive Markdown presentation of the panel."""
        data = self.render_panel_data()
        cards = data["cards"]
        b = cards["trading_bot"]
        f = cards["forge"]
        a = cards["ai_universe"]
        n = cards["nexus"]

        return (
            f"# 🌐 {data['title']}\n\n"
            f"**Overall Health:** **🟢 {data['overall_health']}**\n\n"
            f"### 📈 Trading Bot Card\n"
            f"- **Status:** `{b['status']}` | **Equity:** `{b['key_metric']}` | **P&L:** `{b['pnl']}` | **Positions:** `{b['positions_count']}`\n"
            f"- **Quick Actions:** `Emergency stop trading`\n\n"
            f"### 🛠️ FORGE Engine Card\n"
            f"- **Status:** `{f['status']}` | **Delivered:** `{f['key_metric']}` | **Coverage:** `{f['mean_coverage']}`\n"
            f"- **Quick Actions:** `Build something new`\n\n"
            f"### 🧠 AI-Universe Card\n"
            f"- **Status:** `{a['status']}` | **Providers:** `{a['key_metric']}` | **Consultations:** `{a['consultations']}`\n\n"
            f"### 🌐 Nexus Website & Growth Card\n"
            f"- **Status:** `{n['status']}` | **Health:** `{n['site_health']}` | **Visitors:** `{n['visitors_today']}` | **Leads:** `{n['lead_count']}`\n"
            f"- **Quick Actions:** `View high-intent leads`, `Pause experiment`\n\n"
            f"### 🚨 Central Alerts Feed\n" +
            "\n".join([f"- `[{alt['subsystem']}]` {alt['message']}" for alt in data["alerts_feed"]])
        )
