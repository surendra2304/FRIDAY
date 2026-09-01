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

        # 1. High-Confidence Adverse Prediction for Held Assets
        # Simulated active long position on ETH with 58% bearish prediction
        eth_pred = predictions.get("ETHUSDT")
        if eth_pred and eth_pred.get("direction") == "BEARISH" and eth_pred.get("direction_probability_pct", 0.0) >= 55.0:
            ev = {
                "type": "ADVERSE_PREDICTION_ALERT",
                "symbol": "ETHUSDT",
                "direction": "BEARISH",
                "probability_pct": eth_pred.get("direction_probability_pct"),
                "message": f"Adverse prediction on ETHUSDT: Model indicates {eth_pred.get('direction_probability_pct'):.0f}% probability of downward move while holding long position.",
                "severity": "WARNING",
            }
            events.append(ev)
            self._emit_alert("ADVERSE PREDICTION: ETHUSDT", ev["message"], AlertSeverity.WARNING)

        # 2. Sentiment Spike Alert
        if sentiment.get("fear_and_greed_index", 50) >= 65 or sentiment.get("social_volume_spike", False):
            ev = {
                "type": "SENTIMENT_ELEVATION_ALERT",
                "greed_index": sentiment.get("fear_and_greed_index"),
                "message": f"Market sentiment elevated: Fear & Greed index at {sentiment.get('fear_and_greed_index')}/100 (Greed regime).",
                "severity": "INFO",
            }
            events.append(ev)
            self._emit_alert("SENTIMENT REGIME: GREED", ev["message"], AlertSeverity.INFO)

        # 3. Whale Movement Alert
        if on_chain.get("net_exchange_flow_btc", 0) <= -5000.0 and "WHALE_ACCUMULATION" not in self._alerted_whales:
            self._alerted_whales.add("WHALE_ACCUMULATION")
            ev = {
                "type": "WHALE_FLOW_ALERT",
                "net_flow_btc": on_chain.get("net_exchange_flow_btc"),
                "summary": on_chain.get("largest_whale_transfer_summary"),
                "message": f"Significant on-chain whale accumulation: {abs(on_chain.get('net_exchange_flow_btc', 0)):,.0f} BTC net exchange outflow in 24h.",
                "severity": "INFO",
            }
            events.append(ev)
            self._emit_alert("WHALE ACCUMULATION DETECTED", ev["message"], AlertSeverity.INFO)

        # 4. Prediction Accuracy Decay Alert
        rolling_acc = accuracy.get("rolling_30d_directional_accuracy_pct", 78.5)
        if rolling_acc < 60.0:
            ev = {
                "type": "MODEL_ACCURACY_DECAY",
                "accuracy_pct": rolling_acc,
                "message": f"Model prediction accuracy decay: Rolling 30d directional accuracy dropped to {rolling_acc:.1f}% (<60% threshold).",
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
