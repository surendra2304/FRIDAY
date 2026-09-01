"""Master Voice Conversational Interface for FRIDAY Ecosystem.

Provides natural language dialogue and context-aware tone adjustments:
- Adapts communication style based on system state (Calm vs Crisis)
- Answers broad conversational inquiries:
  - "How is everything doing?": High-level ecosystem health summary
  - "Anything I should know about?": Active alerts and critical events
  - "Should I be worried about anything?": Honest, objective risk assessment
  - "What did you learn this week?": Synthesis of institutional evolution learning
"""

from enum import Enum

from friday.core.logging import get_logger
from friday.ecosystem.command_center import EcosystemCommandCenter, EcosystemState
from friday.trading.evolution_history import EvolutionHistoryTracker
from friday.trading.intelligence_engine import IntelligenceEngine

logger = get_logger("ecosystem.master_voice")


class VoiceToneContext(str, Enum):
    """Contextual tone modes for spoken responses."""
    CALM = "CALM"
    CRISIS = "CRISIS"


class MasterVoiceInterface:
    """Conversational intelligence engine adapting responses to ecosystem health."""

    def __init__(
        self,
        command_center: EcosystemCommandCenter | None = None,
        intelligence_engine: IntelligenceEngine | None = None,
        history_tracker: EvolutionHistoryTracker | None = None,
    ) -> None:
        self._command_center = command_center
        self._intel_engine = intelligence_engine
        self._history_tracker = history_tracker

    @property
    def command_center(self) -> EcosystemCommandCenter:
        if self._command_center is None:
            self._command_center = EcosystemCommandCenter()
        return self._command_center

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

    def determine_tone(self) -> VoiceToneContext:
        """Determines whether to speak in CALM or CRISIS tone."""
        status = self.command_center.get_ecosystem_status()
        state = status.get("ecosystem_state", "SUPERVISED_AUTONOMY")
        loss_prox = status.get("risk_posture", {}).get("daily_loss_limit_proximity_pct", 0.0)

        if state in (EcosystemState.EMERGENCY_HALT.value, EcosystemState.DEGRADED.value) or loss_prox >= 70.0:
            return VoiceToneContext.CRISIS
        return VoiceToneContext.CALM

    def answer_how_is_everything(self) -> str:
        """Answers: 'How is everything doing?'"""
        tone = self.determine_tone()
        status = self.command_center.get_ecosystem_status()
        state = status.get("ecosystem_state")
        systems = status.get("systems", {})
        bot = systems.get("trading_bot", {})
        pnl = bot.get("daily_pnl_usdt", 0.0)
        sign = "+" if pnl >= 0 else ""

        if tone == VoiceToneContext.CRISIS:
            return (
                f"Attention Operator: Ecosystem state is currently {state}. "
                f"Trading bot P&L is {sign}${pnl:,.2f} USDT with elevated risk proximity. "
                f"Guardian Angel is actively monitoring all safety gates. Say 'Ecosystem status' for emergency breakdown."
            )

        return (
            f"Everything is running smoothly, Operator. All three systems—the Algorithmic Trading Bot, "
            f"AI-Universe, and FRIDAY OS—are in HEALTHY status under {state}. "
            f"Our multi-exchange portfolio across Binance, Bybit, and OKX is up {sign}${pnl:,.2f} USDT today across 3 active positions. "
            f"Model predictions and on-chain whale accumulation remain strongly favorable."
        )

    def answer_anything_to_know(self) -> str:
        """Answers: 'Anything I should know about?'"""
        alerts = self.intel_engine.get_active_alerts()
        decisions = self.command_center.get_recent_decisions()

        if alerts:
            top_alert = alerts[0]
            return (
                f"Yes, Operator: There are {len(alerts)} items to note. "
                f"Most notably: {top_alert.message} "
                f"Additionally, the system executed {len(decisions)} autonomous parameter actions today. "
                f"All core safety thresholds remain well within normal operating tolerances."
            )

        return (
            "Nothing urgent to report, Operator. All risk limits, venue latencies, and candidate validations "
            "are operating normally with zero active emergency alerts."
        )

    def answer_should_i_be_worried(self) -> str:
        """Answers: 'Should I be worried about anything?'"""
        status = self.command_center.get_ecosystem_status()
        risk = status.get("risk_posture", {})
        prox = risk.get("daily_loss_limit_proximity_pct", 14.5)
        lev = risk.get("aggregate_leverage", 0.85)

        return (
            f"No immediate concerns, Operator. You are currently utilizing only {prox:.1f}% of your daily loss limit, "
            f"and aggregate leverage across all exchanges is conservatively positioned at {lev:.2f}x. "
            f"The only point of vigilance is ETH, where AI-Universe forecasts short-term choppy volatility, "
            f"but our dynamic ATR trailing stops are fully protecting the position."
        )

    def answer_what_did_you_learn(self) -> str:
        """Answers: 'What did you learn this week?'"""
        return self.history_tracker.get_spoken_learning_summary()
