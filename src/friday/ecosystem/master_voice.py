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
        # The default here used to be 0.0, which reads "no reported risk" and
        # "risk is zero" identically - so the calm tone was chosen on the
        # strength of a number nobody had measured. The reading is taken as it
        # is and .at_least() answers False for anything unknown.
        from friday.core.readings import read_number

        loss_prox = read_number(status.get("risk_posture"), "daily_loss_limit_proximity_pct")

        if state in (EcosystemState.EMERGENCY_HALT.value, EcosystemState.DEGRADED.value) or loss_prox.at_least(70.0):
            return VoiceToneContext.CRISIS
        return VoiceToneContext.CALM

    def answer_how_is_everything(self) -> str:
        """Answers: 'How is everything doing?'"""
        tone = self.determine_tone()
        status = self.command_center.get_ecosystem_status()
        state = status.get("ecosystem_state")
        systems = status.get("systems", {})
        bot = systems.get("trading_bot", {})
        # Every clause that follows used to be a claim this method could not
        # support: "All three systems are in HEALTHY status", "3 active
        # positions", "up $X today", "on-chain whale accumulation remain strongly
        # favorable". The numbers came from defaults; the health adjectives came
        # from nowhere at all. Each part is now printed from the reported
        # reading, or named as unreported.
        from friday.core.readings import read_number

        pnl = read_number(bot, "daily_pnl_usdt", source="trading bot")
        positions = read_number(bot, "active_positions_count", source="trading bot")
        unreported = [name for name, reading in systems.items() if not reading.get("available")]

        if tone == VoiceToneContext.CRISIS:
            return (
                f"Attention Operator: Ecosystem state is currently {state}. "
                f"Trading bot P&L is {pnl.currency()} USDT with elevated risk proximity. "
                f"Guardian Angel is monitoring the safety gates it can read. Say 'Ecosystem status' for a breakdown."
            )

        if unreported:
            names = ", ".join(unreported)
            return (
                f"I will not claim everything is running smoothly, Operator: I have no reading for {names}, "
                f"so I cannot speak for them. Ecosystem state is {state}. "
                f"Trading P&L is {pnl.currency()} USDT across {positions.number(0)} positions."
            )

        return (
            f"Ecosystem state is {state}, with every system having reported. "
            f"Trading P&L is {pnl.currency()} USDT today across {positions.number(0)} positions. "
            f"Ask me for the risk posture if you want the limits and leverage."
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
                f"That is a count of actions, not an assessment of your safety thresholds."
            )

        # "All risk limits, venue latencies, and candidate validations are
        # operating normally with zero active emergency alerts" asserted three
        # things this class never checks. An empty alert list means no alert was
        # raised; it does not mean the limits were measured.
        return (
            "Nothing is in the alert queue, Operator - which means no alert was raised, not that "
            "everything was checked. Ask me for the risk posture if you want the numbers."
        )

    def answer_should_i_be_worried(self) -> str:
        """Answers: 'Should I be worried about anything?'"""
        status = self.command_center.get_ecosystem_status()
        risk = status.get("risk_posture", {})
        from friday.core.readings import read_number

        prox = read_number(risk, "daily_loss_limit_proximity_pct", source="trading bot risk posture")
        lev = read_number(risk, "aggregate_leverage", source="trading bot risk posture")

        # The old answer invented a leaverage, a loss-limit utilisation and an
        # ETH position with ATR stops "fully protecting" it. There was no ETH
        # position; there was no reading. "I cannot see your risk" is a less
        # comfortable answer and the only true one.
        if not prox.known and not lev.known:
            return (
                "I cannot answer that honestly, Operator: no risk reading has been reported, so I have no "
                "view of your loss limits or leverage. I am not going to describe a position I cannot see. "
                "Connect the trading bridge and ask me again."
            )

        parts = []
        if prox.known:
            parts.append(f"daily loss limit utilisation is {prox.percent()}")
        else:
            parts.append("daily loss limit utilisation is unknown")
        if lev.known:
            parts.append(f"aggregate leverage is {lev.number(2, 'x')}")
        else:
            parts.append("aggregate leverage is unknown")
        return "From what has been reported: " + "; ".join(parts) + "."

    def answer_what_did_you_learn(self) -> str:
        """Answers: 'What did you learn this week?'"""
        return self.history_tracker.get_spoken_learning_summary()
