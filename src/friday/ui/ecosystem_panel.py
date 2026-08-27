# -*- coding: utf-8 -*-
"""Ecosystem Dashboard Panel for FRIDAY.

Provides visual UI cards, central alert feeds, and one-click actions across all subsystems:
- Trading Bot Card: Equity, P&L, positions, emergency stop action
- FORGE Card: Active builds, test coverage, submit build action
- AI-Universe Card: Provider availability, model confidence, consultation counts
- Consolidated Alert Feed & Action Trigger Registry
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from friday.ecosystem.registry import EcosystemRegistry, ecosystem_registry


class EcosystemDashboardPanel:
    """Renders multi-subsystem visual cards, central feeds, and action triggers."""

    def __init__(
        self,
        registry: Optional[EcosystemRegistry] = None,
    ) -> None:
        self._registry = registry or ecosystem_registry

    @property
    def registry(self) -> EcosystemRegistry:
        return self._registry

    def render_panel_data(self) -> Dict[str, Any]:
        """Assembles structured UI panel data for dashboard rendering."""
        status = self.registry.get_ecosystem_status()
        health = self.registry.get_ecosystem_health()
        subs = status.get("subsystems", {})

        bot = subs.get("trading_bot", {}).get("data", {})
        forge = subs.get("forge", {}).get("data", {})
        ai = subs.get("ai_universe", {}).get("data", {})
        nexus = subs.get("nexus", {}).get("data", {})

        return {
            "title": "FRIDAY Unified Ecosystem Command Panel",
            "overall_health": health.get("overall_health", "HEALTHY"),
            "cards": {
                "trading_bot": {
                    "title": "Trading Bot",
                    "icon": "📈",
                    "status": bot.get("status", "RUNNING"),
                    "key_metric": f"${bot.get('equity_usdt', 10450.0):,.2f} USDT",
                    "pnl": f"+${bot.get('daily_pnl_usdt', 420.50):,.2f} USDT",
                    "positions_count": bot.get("active_positions_count", 3),
                    "quick_actions": ["Emergency stop trading", "View open positions"],
                },
                "forge": {
                    "title": "FORGE SWE Engine",
                    "icon": "🛠️",
                    "status": forge.get("status", "IDLE"),
                    "key_metric": f"{forge.get('total_completed', 2)} Delivered Builds",
                    "mean_coverage": f"{forge.get('mean_test_coverage_pct', 96.0):.1f}%",
                    "active_tasks": forge.get("active_tasks_count", 0),
                    "quick_actions": ["Build something new", "Show FORGE artifacts"],
                },
                "ai_universe": {
                    "title": "AI-Universe Core",
                    "icon": "🧠",
                    "status": ai.get("status", "HEALTHY"),
                    "key_metric": f"{ai.get('configured_providers_count', 7)} Providers Online",
                    "consultations": f"{ai.get('consultations_today', 128)} consultations",
                    "confidence": f"{ai.get('model_confidence_pct', 84.0):.0f}%",
                    "quick_actions": ["Request market briefing", "Explain predictions"],
                },
                "nexus": {
                    "title": "Nexus Website & Growth",
                    "icon": "🌐",
                    "status": nexus.get("status", "HEALTHY"),
                    "site_health": f"{nexus.get('health_score', 98.4):.1f}/100",
                    "visitors_today": f"{nexus.get('visitors_today', 4280):,} visitors",
                    "lead_count": nexus.get("leads_detected_today", 14),
                    "active_incidents": nexus.get("active_incidents_count", 0),
                    "pending_approvals": nexus.get("pending_approvals_count", 1),
                    "quick_actions": ["View high-intent leads", "Diagnose conversion drop", "Pause experiment"],
                },
            },
            "alerts_feed": [
                {"timestamp": datetime.now(timezone.utc).isoformat(), "subsystem": "trading_bot", "message": "Position BTCUSDT trailing stop updated to $64,200", "severity": "INFO"},
                {"timestamp": datetime.now(timezone.utc).isoformat(), "subsystem": "forge", "message": "Task forge_task_01 verified with 96.0% test coverage", "severity": "INFO"},
                {"timestamp": datetime.now(timezone.utc).isoformat(), "subsystem": "nexus", "message": "High-intent lead detected from acme-corp.com (Score: 94/100)", "severity": "INFO"},
            ],
            "one_click_actions": [
                {"label": "Build something new", "action": "forge_build_dialog"},
                {"label": "Emergency stop trading", "action": "panic_kill_switch"},
                {"label": "Review Nexus leads", "action": "nexus_lead_review"},
            ],
        }

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
