# -*- coding: utf-8 -*-
"""Executive Dashboard Renderer for FRIDAY Ecosystem.

Generates a single-pane-of-glass Markdown dashboard summarizing overall ecosystem health,
tri-system status, portfolio metrics, active predictions, decisions, and governance policies.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from friday.ecosystem.command_center import EcosystemCommandCenter
from friday.ecosystem.policy_interface import HumanPolicyInterface
from friday.trading.intelligence_engine import IntelligenceEngine
from friday.trading.strategy_portfolio import StrategyPortfolioManager


class ExecutiveDashboardRenderer:
    """Renders comprehensive executive ecosystem status reports."""

    def __init__(
        self,
        command_center: Optional[EcosystemCommandCenter] = None,
        policy_interface: Optional[HumanPolicyInterface] = None,
        portfolio_manager: Optional[StrategyPortfolioManager] = None,
        intelligence_engine: Optional[IntelligenceEngine] = None,
    ) -> None:
        self._command_center = command_center
        self._policy_interface = policy_interface
        self._portfolio_manager = portfolio_manager
        self._intel_engine = intelligence_engine

    @property
    def command_center(self) -> EcosystemCommandCenter:
        if self._command_center is None:
            self._command_center = EcosystemCommandCenter()
        return self._command_center

    @property
    def policy_interface(self) -> HumanPolicyInterface:
        if self._policy_interface is None:
            self._policy_interface = HumanPolicyInterface()
        return self._policy_interface

    @property
    def portfolio_manager(self) -> StrategyPortfolioManager:
        if self._portfolio_manager is None:
            self._portfolio_manager = StrategyPortfolioManager()
        return self._portfolio_manager

    @property
    def intel_engine(self) -> IntelligenceEngine:
        if self._intel_engine is None:
            self._intel_engine = IntelligenceEngine()
        return self._intel_engine

    def render_markdown(self) -> str:
        """Renders executive single-pane-of-glass dashboard."""
        now_iso = datetime.now(timezone.utc).isoformat()
        status = self.command_center.get_ecosystem_status()
        state = status.get("ecosystem_state", "SUPERVISED_AUTONOMY")
        autonomy = status.get("autonomy_name", "LEVEL_2_SUPERVISED")
        systems = status.get("systems", {})
        bot = systems.get("trading_bot", {})
        ai = systems.get("ai_universe", {})
        friday = systems.get("friday_os", {})
        risk = status.get("risk_posture", {})

        policies = self.policy_interface.get_active_policies()
        decisions = self.command_center.get_recent_decisions()
        alerts = self.intel_engine.get_active_alerts()

        policy_lines = [f"- **{p.name}:** `{p.natural_language_rule}` (v{p.version})" for p in policies]
        alert_lines = [f"- **[{a.severity}] {a.alert_type}:** {a.message}" for a in alerts] or ["- *Zero active critical alerts.*"]
        dec_lines = [f"- **`{d.action_type}`** by `{d.operator_id}`: `{d.details}` (Sig: `{d.signature[:10]}...`)" for d in decisions]

        return (
            f"# 🌐 FRIDAY Autonomous Trading Ecosystem — Executive Command\n\n"
            f"**Timestamp:** `{now_iso[:19]} UTC` | **Ecosystem State:** **🟢 {state}** | **Autonomy:** `{autonomy}`\n\n"
            f"## 🏛️ Tri-System Health Matrix\n"
            f"| System Subsystem | Operational Health | Primary Telemetry / Latency | Key Subsystems |\n"
            f"| :--- | :---: | :---: | :--- |\n"
            f"| **Algorithmic Trading Bot** | **🟢 {bot.get('status')}** | `{bot.get('api_latency_ms')} ms` (Venues: Binance, Bybit, OKX) | Real Capital (${bot.get('active_capital_usdt'):,.0f} USDT), Daily P&L: `+${bot.get('daily_pnl_usdt'):,.2f}` |\n"
            f"| **AI-Universe Core** | **🟢 {ai.get('status')}** | `{ai.get('latency_ms')} ms` (Confidence: `{ai.get('model_confidence')*100:.0f}%`) | Multi-Agent Debate, Directional Predictor, Alternative Data NLP |\n"
            f"| **FRIDAY Autonomous OS** | **🟢 {friday.get('status')}** | `{friday.get('guardian_vigilance')}` | Cognitive Engine, Voice Biometrics, Guardian Angel 24/7 |\n\n"
            f"## 📊 Portfolio Risk & Capital Posture\n"
            f"- **Aggregate Deployed Capital:** `${bot.get('active_capital_usdt'):,.2f} USDT`\n"
            f"- **Aggregate Leverage:** `{risk.get('aggregate_leverage'):.2f}x`\n"
            f"- **Daily Loss Limit Proximity:** `{risk.get('daily_loss_limit_proximity_pct'):.1f}%` of maximum limit\n"
            f"- **Single Asset Max Concentration:** `{risk.get('single_asset_max_exposure_pct'):.1f}%` (BTC Ceiling: 50%)\n\n"
            f"## 📜 Active Human Governance Policies\n" + "\n".join(policy_lines) + "\n\n"
            f"## 🚨 Active Vigilance & Market Alerts\n" + "\n".join(alert_lines) + "\n\n"
            f"## 📝 Autonomous Decisions Audit Log\n" + "\n".join(dec_lines) + "\n\n"
            f"---\n"
            f"### ⚡ Quick Voice Command Reference\n"
            f"- `\"Ecosystem status\"` → Conversational tri-system status\n"
            f"- `\"Set autonomy to level 2\"` → Adjust autonomy mode (Biometric Auth)\n"
            f"- `\"What decisions did the system make today?\"` → Autonomous decision log\n"
            f"- `\"What are my current policies?\"` → Human policy audit review\n"
        )
