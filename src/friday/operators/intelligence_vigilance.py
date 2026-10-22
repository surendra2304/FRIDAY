"""Intelligence Vigilance Operator for FRIDAY.

Supervises AI-Universe prediction streams and alternative market data feeds every 15 minutes:
- High-confidence adverse prediction alerts for active portfolio positions (>75% confidence)
- Extreme news or social sentiment spikes and crowd divergences
- Large on-chain whale wallet movements and exchange reserve shifts
- Prediction model accuracy decay detection (<60% directional accuracy)
"""

from typing import Any

from friday.alert_manager import AlertSeverity, ProductionAlertManager
from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel, TrustLevel
from friday.operators.base_operator import BaseOperator
from friday.operators.triggers import IntervalTrigger
from friday.trading.intelligence_engine import IntelligenceEngine

logger = get_logger("operators.intelligence_vigilance")


class IntelligenceVigilanceOperator(BaseOperator):
    """Monitors market predictions, on-chain flows, and sentiment anomalies every 15 minutes."""

    __test__ = False

    name = "intelligence_vigilance"
    description = (
        "Supervises AI predictions, on-chain whale flows, sentiment spikes, and model calibration every 15 minutes."
    )

    def __init__(
        self,
        intelligence_engine: IntelligenceEngine | None = None,
        alert_manager: ProductionAlertManager | None = None,
        poll_interval_sec: float = 900.0,  # 15 minutes default
        memory: Any | None = None,
        authorizer: Any | None = None,
        held_positions: dict[str, Any] | None = None,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="intelligence_vigilance_poll_interval")
        super().__init__(
            name="intelligence_vigilance",
            description="Supervises market predictions, on-chain flows, and sentiment every 15 minutes.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="market_intelligence",
            authorizer=authorizer,
        )
        self._intel_engine = intelligence_engine
        self._alert_manager = alert_manager
        self.poll_interval_sec = poll_interval_sec
        self.memory = memory
        self._alerted_whales: set[str] = set()
        #: Positions actually held, reported by the trading bridge as
        #: ``{"ETHUSDT": {"side": "LONG", "size": 1.5}}``. The adverse-prediction
        #: check used to assume a long ETH position unconditionally - "Simulated
        #: active long position on ETH" - and warned the operator about risk in a
        #: position nobody had said they held. With nothing reported, there is no
        #: position to warn about.
        self.held_positions: dict[str, Any] = dict(held_positions or {})

    @property
    def intel_engine(self) -> IntelligenceEngine:
        if self._intel_engine is None:
            self._intel_engine = IntelligenceEngine()
        return self._intel_engine

    @property
    def alert_manager(self) -> ProductionAlertManager:
        if self._alert_manager is None:
            self._alert_manager = ProductionAlertManager()
        return self._alert_manager

    def tick(self) -> list[dict[str, Any]]:
        """Executes a 15-minute intelligence monitoring cycle."""
        events: list[dict[str, Any]] = []

        report = self.intel_engine.get_market_intelligence_report()
        predictions = report.get("predictions", {})
        sentiment = report.get("sentiment", {})
        on_chain = report.get("on_chain", {})
        accuracy = report.get("accuracy", {})

        from friday.core.readings import read_number

        # 1. High-Confidence Adverse Prediction for Held Assets.
        # Only positions that were actually reported are checked. Each threshold
        # below is compared against a *reading*; a missing probability used to be
        # treated as 0.0 (silently no alert) and then formatted with :.0f, which
        # would have raised if the value had been None rather than absent.
        for symbol, position in sorted(self.held_positions.items()):
            entry = predictions.get(symbol) or {}
            probability = read_number(entry, "direction_probability_pct", source=f"{symbol} prediction")
            direction = str(entry.get("direction") or "").upper()
            side = str((position or {}).get("side", "")).upper() if isinstance(position, dict) else ""
            adverse = (direction == "BEARISH" and side == "LONG") or (direction == "BULLISH" and side == "SHORT")
            if adverse and probability.at_least(55.0):
                ev = {
                    "type": "ADVERSE_PREDICTION_ALERT",
                    "symbol": symbol,
                    "direction": direction,
                    "probability_pct": probability.value,
                    "message": (
                        f"Adverse prediction on {symbol}: model indicates "
                        f"{probability.number(0, '%')} probability of a move against your "
                        f"{side} position."
                    ),
                    "severity": "WARNING",
                }
                events.append(ev)
                self._emit_alert(f"ADVERSE PREDICTION: {symbol}", ev["message"], AlertSeverity.WARNING)

        # 2. Sentiment Spike Alert. The 50 default meant "no reading" was compared
        # as if it were a neutral measurement; a genuinely unknown index now
        # produces no alert, and no claim.
        greed = read_number(sentiment, "fear_and_greed_index", source="sentiment telemetry")
        if greed.at_least(65.0) or sentiment.get("social_volume_spike", False):
            ev = {
                "type": "SENTIMENT_ELEVATION_ALERT",
                "greed_index": greed.value,
                "message": (
                    f"Market sentiment elevated: Fear & Greed index at {greed.number(0)}/100 (Greed regime)."
                    if greed.known
                    else "Social volume spike reported; no Fear & Greed index is available."
                ),
                "severity": "INFO",
            }
            events.append(ev)
            self._emit_alert("SENTIMENT REGIME: GREED", ev["message"], AlertSeverity.INFO)

        # 3. Whale Movement Alert
        net_flow = read_number(on_chain, "net_exchange_flow_btc", source="on-chain telemetry")
        if net_flow.known and net_flow.value <= -5000.0 and "WHALE_ACCUMULATION" not in self._alerted_whales:
            self._alerted_whales.add("WHALE_ACCUMULATION")
            ev = {
                "type": "WHALE_FLOW_ALERT",
                "net_flow_btc": net_flow.value,
                "summary": on_chain.get("largest_whale_transfer_summary"),
                "message": (
                    f"Significant on-chain whale accumulation: {abs(net_flow.value):,.0f} BTC net "
                    f"exchange outflow in 24h."
                ),
                "severity": "INFO",
            }
            events.append(ev)
            self._emit_alert("WHALE ACCUMULATION DETECTED", ev["message"], AlertSeverity.INFO)

        # 4. Prediction Accuracy Decay Alert. The 78.5 default was higher than the
        # 60.0 threshold, so an unmeasured accuracy could never trigger decay - but
        # the value was also reported to the caller as though measured.
        rolling_acc = read_number(accuracy, "rolling_30d_directional_accuracy_pct", source="accuracy report")
        if rolling_acc.known and rolling_acc.value < 60.0:
            ev = {
                "type": "MODEL_ACCURACY_DECAY",
                "accuracy_pct": rolling_acc.value,
                "message": (
                    f"Model prediction accuracy decay: rolling 30d directional accuracy is "
                    f"{rolling_acc.number(1, '%')} (<60% threshold)."
                ),
                "severity": "WARNING",
            }
            events.append(ev)
            self._emit_alert("MODEL ACCURACY DECAY", ev["message"], AlertSeverity.WARNING)

        return events

    def _emit_alert(self, title: str, message: str, severity: AlertSeverity) -> None:
        """Emits alert and logs to untrusted memory."""
        try:
            self.alert_manager.create_alert(
                title=title,
                message=message,
                severity=severity,
                category="market_intelligence",
            )
        except Exception as e:
            logger.debug(f"[INTEL_VIGILANCE] Alert dispatch failed: {e}")

        if self.memory:
            try:
                msg = Message(
                    role=Role.SYSTEM,
                    content=f"INTEL_ALERT [{severity.value}] {title}: {message}",
                    trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                )
                self.memory.add_message(msg)
            except Exception as e:
                logger.debug(f"[INTEL_VIGILANCE] Memory persist failed: {e}")
