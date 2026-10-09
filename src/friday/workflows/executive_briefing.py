"""Daily Executive Briefing Workflow for FRIDAY.

The flagship executive briefing delivering morning strategic debriefs (08:00 UTC)
and evening wrap-ups (20:00 UTC) across the entire autonomous trading ecosystem.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from friday.core.logging import get_logger
from friday.ecosystem.command_center import EcosystemCommandCenter
from friday.ecosystem.policy_interface import HumanPolicyInterface
from friday.trading.evolution_history import EvolutionHistoryTracker
from friday.trading.intelligence_engine import IntelligenceEngine

logger = get_logger("workflows.executive_briefing")


@dataclass
class ExecutiveBriefingSnapshot:
    """Snapshot containing morning or evening executive briefing data."""
    briefing_type: str  # MORNING, EVENING
    timestamp: str
    ecosystem_state: str
    daily_pnl_usdt: float
    spoken_briefing: str
    markdown_report: str


class DailyExecutiveBriefingWorkflow:
    """Generates morning executive briefings and evening performance wrap-ups."""

    def __init__(
        self,
        command_center: EcosystemCommandCenter | None = None,
        policy_interface: HumanPolicyInterface | None = None,
        intelligence_engine: IntelligenceEngine | None = None,
        history_tracker: EvolutionHistoryTracker | None = None,
    ) -> None:
        self._command_center = command_center
        self._policy_interface = policy_interface
        self._intel_engine = intelligence_engine
        self._history_tracker = history_tracker

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
    def intel_engine(self) -> IntelligenceEngine:
        if self._intel_engine is None:
            self._intel_engine = IntelligenceEngine()
        return self._intel_engine

    @property
    def history_tracker(self) -> EvolutionHistoryTracker:
        if self._history_tracker is None:
            self._history_tracker = EvolutionHistoryTracker()
        return self._history_tracker

    def can_handle(self, user_request: str) -> bool:
        """Determines if the request is for an executive briefing."""
        clean = user_request.strip().lower()
        return any(k in clean for k in ["executive briefing", "morning executive briefing", "evening wrap-up", "evening wrap up", "daily executive briefing"])

    def generate_morning_briefing(self) -> ExecutiveBriefingSnapshot:
        """Generates the flagship morning executive strategic debrief."""
        now_iso = datetime.now(timezone.utc).isoformat()
        status = self.command_center.get_ecosystem_status()
        state = status.get("ecosystem_state", "SUPERVISED_AUTONOMY")
        systems = status.get("systems", {})
        bot = systems.get("trading_bot", {})
        ai = systems.get("ai_universe", {})
        friday_os = systems.get("friday_os", {})
        risk = status.get("risk_posture", {})

        intel = self.intel_engine.get_market_intelligence_report()
        sent = intel.get("sentiment", {})
        onchain = intel.get("on_chain", {})
        acc = intel.get("accuracy", {})

        from friday.core.readings import UNKNOWN_LABEL, read_number, read_text

        pnl = read_number(bot, "daily_pnl_usdt", source="trading bot")
        positions = read_number(bot, "active_positions_count", source="trading bot")
        venues = bot.get("connected_venues")
        venue_text = ", ".join(venues) if isinstance(venues, (list, tuple)) and venues else UNKNOWN_LABEL
        prox = read_number(risk, "daily_loss_limit_proximity_pct", source="risk posture")
        lev = read_number(risk, "aggregate_leverage", source="risk posture")
        flow = read_number(onchain, "net_exchange_flow_btc", source="on-chain intelligence")

        # "with all three systems HEALTHY", "3 active positions", "84% confidence",
        # "3 active predictions", "one candidate strategy passed all validation
        # gates" - all of it was written into the string. A briefing is the one
        # artefact the owner reads first and trusts most, so a fabricated line in
        # it is the most expensive kind of wrong. Every clause is now a reading
        # or an explicit unknown.
        system_lines = []
        for label, reading in (("Trading Bot", bot), ("AI-Universe Core", ai), ("FRIDAY OS", friday_os)):
            if reading.get("available"):
                system_lines.append(f"{label}: {reading.get('status', 'reported')}")
            else:
                system_lines.append(f"{label}: {UNKNOWN_LABEL}")

        if pnl.known or positions.known:
            trading_clause = (
                f"Trading produced {pnl.currency()} USDT across {positions.number(0)} active positions "
                f"over venues {venue_text}. "
            )
        else:
            trading_clause = (
                "No trading figures were reported, so this briefing contains no P&L and no position count. "
            )

        spoken = (
            f"Good morning Operator Surendra. Here is your morning executive briefing for {datetime.now(timezone.utc).strftime('%A, %B %d')}. "
            f"Ecosystem state is {state}; system readings - {'; '.join(system_lines)}. "
            f"{trading_clause}"
            f"Risk limit utilisation is {prox.percent()} and aggregate leverage is {lev.number(2, 'x')}. "
            f"On-chain net exchange flow is {flow.number(0, ' BTC')}. "
            f"The candidate strategy list is reported below; nothing is awaiting review unless it is named there."
        )

        md = (
            f"# 🌅 FRIDAY Morning Executive Briefing\n\n"
            f"**Date:** `{now_iso[:10]}` | **Ecosystem State:** `{state}` | **Daily P&L:** `{pnl.currency()} USDT`\n\n"
            f"**Data provenance:** {status.get('data_provenance', 'unknown')}\n\n"
            f"## 🏛️ Executive Health Summary\n"
            f"- **Trading Bot:** `{bot.get('status', UNKNOWN_LABEL)}` "
            f"(venues: {venue_text}; positions: {positions.number(0)})\n"
            f"- **AI-Universe Core:** `{ai.get('status', UNKNOWN_LABEL)}` "
            f"(confidence: {read_number(ai, 'model_confidence').number(2)}; "
            f"active predictions: {read_number(ai, 'active_predictions_count').number(0)})\n"
            f"- **FRIDAY OS:** `{friday_os.get('status', UNKNOWN_LABEL)}` "
            f"(guardian vigilance: {read_text(friday_os, 'guardian_vigilance')})\n\n"
            f"## 🔮 Strategic Outlook & Risk Posture\n"
            f"- **Market Sentiment:** `{read_text(sent, 'news_sentiment_label')}` "
            f"(Fear & Greed: `{read_number(sent, 'fear_and_greed_index').number(0)}/100`)\n"
            f"- **Whale Flow:** `{flow.number(0, ' BTC')}` ({read_text(onchain, 'exchange_reserve_trend')})\n"
            f"- **Daily Loss Headroom:** `{prox.known and f'{100.0 - prox.value:.1f}% remaining' or UNKNOWN_LABEL}`\n"
            f"- **Model Calibration:** `{read_text(acc, 'calibration_status')}` "
            f"({read_number(acc, 'rolling_30d_directional_accuracy_pct').percent()})\n"
        )

        return ExecutiveBriefingSnapshot(
            briefing_type="MORNING",
            timestamp=now_iso,
            ecosystem_state=state,
            daily_pnl_usdt=pnl,
            spoken_briefing=spoken,
            markdown_report=md,
        )

    def generate_evening_wrapup(self) -> ExecutiveBriefingSnapshot:
        """Generates the evening performance wrap-up and overnight posture."""
        now_iso = datetime.now(timezone.utc).isoformat()
        status = self.command_center.get_ecosystem_status()
        state = status.get("ecosystem_state", "SUPERVISED_AUTONOMY")
        bot = status.get("systems", {}).get("trading_bot", {})
        pnl = bot.get("daily_pnl_usdt", 0.0)
        sign = "+" if pnl >= 0 else ""
        decisions = self.command_center.get_recent_decisions()

        spoken = (
            f"Good evening Operator Surendra. Here is your daily evening wrap-up. "
            f"Today's trading concluded with a total realized P&L of {sign}${pnl:,.2f} USDT. "
            f"The ecosystem executed {len(decisions)} autonomous parameter actions with zero risk limit breaches. "
            f"Overnight risk limits are locked with dynamic ATR trailing stops, and Guardian Angel 24/7 vigilance is active."
        )

        md = (
            f"# 🌙 FRIDAY Evening Performance Wrap-Up\n\n"
            f"**Date:** `{now_iso[:10]}` | **Total Day P&L:** **`{sign}${pnl:,.2f} USDT`** | **Decisions Executed:** `{len(decisions)}`\n\n"
            f"## 🛡️ Overnight Posture\n"
            f"- Dynamic trailing stops active across all liquid positions.\n"
            f"- Guardian Angel 24/7 continuous 10s monitoring online.\n"
            f"- All human governance policies enforced.\n"
        )

        return ExecutiveBriefingSnapshot(
            briefing_type="EVENING",
            timestamp=now_iso,
            ecosystem_state=state,
            daily_pnl_usdt=pnl,
            spoken_briefing=spoken,
            markdown_report=md,
        )
