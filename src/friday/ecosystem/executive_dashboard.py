"""Executive Dashboard Renderer for FRIDAY Ecosystem.

Generates a single-pane-of-glass Markdown dashboard summarizing overall ecosystem health,
tri-system status, portfolio metrics, active predictions, decisions, and governance policies.
"""

from typing import Any
from datetime import datetime, timezone

from friday.ecosystem.command_center import EcosystemCommandCenter
from friday.ecosystem.policy_interface import HumanPolicyInterface
from friday.trading.intelligence_engine import IntelligenceEngine
from friday.trading.strategy_portfolio import StrategyPortfolioManager


class ExecutiveDashboardRenderer:
    """Renders comprehensive executive ecosystem status reports."""

    def __init__(
        self,
        command_center: EcosystemCommandCenter | None = None,
        policy_interface: HumanPolicyInterface | None = None,
        portfolio_manager: StrategyPortfolioManager | None = None,
        intelligence_engine: IntelligenceEngine | None = None,
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
        # "Zero active critical alerts" was printed whenever the alert list was
        # empty - including when the engine had never been asked anything. The
        # empty state now distinguishes "nothing was raised" from "all clear".
        alert_lines = [f"- **[{a.severity}] {a.alert_type}:** {a.message}" for a in alerts] or [
            "- *No alert has been raised. That is not the same as every limit having been measured.*"
        ]
        dec_lines = [
            f"- **`{d.action_type}`** by `{d.operator_id}`: `{d.details}` (Sig: `{d.signature[:10]}...`)"
            for d in decisions
        ] or ["- *No autonomous decision has been recorded.*"]

        from friday.core.readings import UNKNOWN_LABEL, read_number, read_text

        def health_badge(reading: dict[str, Any]) -> str:
            """A traffic light only when a status was actually reported."""
            if not reading.get("available"):
                return f"⚪ {UNKNOWN_LABEL}"
            status_text = str(reading.get("status", "UNKNOWN")).upper()
            badge = {"HEALTHY": "🟢", "OK": "🟢", "ONLINE": "🟢"}.get(status_text, "🔴")
            return f"{badge} {status_text}"

        # Every number below used to be interpolated with a format spec that
        # crashed on None (``TypeError: unsupported format string passed to
        # NoneType.__format__``) or a hardcoded literal: venues were always
        # "Binance, Bybit, OKX", P&L was always prefixed "+", and every system
        # got a green circle regardless of what it reported.
        latency = read_number(bot, "api_latency_ms", source="trading bot")
        ai_latency = read_number(ai, "latency_ms", source="ai universe")
        capital = read_number(bot, "active_capital_usdt", source="trading bot")
        pnl = read_number(bot, "daily_pnl_usdt", source="trading bot")
        confidence = read_number(ai, "model_confidence", source="ai universe")
        venues = bot.get("connected_venues")
        venue_text = ", ".join(venues) if isinstance(venues, (list, tuple)) and venues else UNKNOWN_LABEL
        leverage = read_number(risk, "aggregate_leverage", source="risk posture")
        proximity = read_number(risk, "daily_loss_limit_proximity_pct", source="risk posture")
        concentration = read_number(risk, "single_asset_max_exposure_pct", source="risk posture")

        return (
            f"# 🌐 FRIDAY Trading Ecosystem — Executive Command\n\n"
            f"**Timestamp:** `{now_iso[:19]} UTC` | **Ecosystem State:** `{state}` | **Autonomy:** `{autonomy}`\n"
            f"**Data provenance:** {status.get('data_provenance', 'unknown')}\n\n"
            f"## 🏛️ Tri-System Health Matrix\n"
            f"| System Subsystem | Operational Health | Primary Telemetry / Latency | Key Subsystems |\n"
            f"| :--- | :---: | :---: | :--- |\n"
            f"| **Algorithmic Trading Bot** | {health_badge(bot)} | `{latency.number(1, ' ms')}` "
            f"(Venues: {venue_text}) | Capital: `{capital.currency()}` USDT, Daily P&L: `{pnl.currency()}` |\n"
            f"| **AI-Universe Core** | {health_badge(ai)} | `{ai_latency.number(1, ' ms')}` "
            f"(Confidence: `{confidence.percent(0)}`) | Multi-Agent Debate, Directional Predictor, Alt-Data NLP |\n"
            f"| **FRIDAY Autonomous OS** | {health_badge(friday)} | "
            f"`{read_text(friday, 'guardian_vigilance')}` | Cognitive Engine, Voice Input, Local Tool Layer |\n\n"
            f"## 📊 Portfolio Risk & Capital Posture\n"
            f"- **Aggregate Deployed Capital:** `{capital.currency()} USDT`\n"
            f"- **Aggregate Leverage:** `{leverage.number(2, 'x')}`\n"
            f"- **Daily Loss Limit Proximity:** `{proximity.percent()}` of maximum limit\n"
            f"- **Single Asset Max Concentration:** `{concentration.percent()}`\n\n"
            f"## 📜 Active Human Governance Policies\n" + "\n".join(policy_lines) + "\n\n"
            "## 🚨 Active Vigilance & Market Alerts\n" + "\n".join(alert_lines) + "\n\n"
            "## 📝 Autonomous Decisions Audit Log\n" + "\n".join(dec_lines) + "\n\n"
            "---\n"
            "### ⚡ Quick Voice Command Reference\n"
            "- `\"Ecosystem status\"` → Conversational tri-system status\n"
            "- `\"Set autonomy to level 2\"` → Adjust autonomy mode (Biometric Auth)\n"
            "- `\"What decisions did the system make today?\"` → Autonomous decision log\n"
            "- `\"What are my current policies?\"` → Human policy audit review\n"
        )
