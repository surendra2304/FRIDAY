"""Morning Intelligence Briefing Workflow for FRIDAY.

Synthesizes deep market intelligence into the morning briefing:
- Overnight NLP news sentiment impact
- Directional and volatility forecasts for active portfolio assets
- Overnight on-chain whale transactions and reserve movements
- Model confidence and calibration health
- Produces conversational spoken briefings and detailed Markdown reports
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from friday.core.logging import get_logger
from friday.trading.intelligence_engine import IntelligenceEngine

logger = get_logger("workflows.intel_briefing")


@dataclass
class MorningIntelligenceSnapshot:
    """Snapshot containing morning intelligence debrief data."""
    timestamp: str
    overall_sentiment: str
    fear_and_greed_index: int | None
    overnight_news_impact: str
    btc_forecast_direction: str
    btc_probability_pct: float | None
    eth_forecast_direction: str
    eth_probability_pct: float | None
    on_chain_whale_summary: str
    model_calibration_status: str
    spoken_briefing: str
    markdown_report: str
    # True when at least one of the fields above carries a reported value. A
    # consumer that needs "did anything actually report?" must not have to infer
    # it from a sentinel.
    has_any_reading: bool = False


class MorningIntelligenceBriefingWorkflow:
    """Delivers enriched morning intelligence briefings."""

    def __init__(
        self,
        intelligence_engine: IntelligenceEngine | None = None,
    ) -> None:
        self._intel_engine = intelligence_engine

    @property
    def intel_engine(self) -> IntelligenceEngine:
        if self._intel_engine is None:
            self._intel_engine = IntelligenceEngine()
        return self._intel_engine

    def can_handle(self, user_request: str) -> bool:
        """Determines if the request is for a morning intelligence briefing."""
        clean = user_request.strip().lower()
        return any(k in clean for k in ["morning intelligence briefing", "morning intel briefing", "morning intelligence", "intelligence briefing"])

    def generate_briefing(self) -> MorningIntelligenceSnapshot:
        """Generates unified morning intelligence briefing snapshot."""
        now_iso = datetime.now(timezone.utc).isoformat()
        report = self.intel_engine.get_market_intelligence_report()

        preds = report.get("predictions", {})
        btc_pred = preds.get("BTCUSDT", {})
        eth_pred = preds.get("ETHUSDT", {})
        sol_pred = preds.get("SOLUSDT", {})

        sent = report.get("sentiment", {})
        onchain = report.get("on_chain", {})
        acc = report.get("accuracy", {})

        from friday.core.readings import UNKNOWN_LABEL, read_number, read_text

        # The spoken paragraph this replaces described a market move that had not
        # been measured: "news sentiment turned cautious on ETH, with the model
        # predicting a 58% probability of downward volatility", "-6,500 BTC in net
        # exchange outflows reinforcing our 76% bullish forecast", Fear & Greed
        # 68, "models remain WELL_CALIBRATED at 78.5% accuracy". Every number came
        # from a default chosen on the spot, and the causal claims ("reinforcing",
        # "due to elevated funding rates") were invented to explain them. A
        # briefing that invents a market and then explains it is worse than a
        # briefing that says it has nothing.
        def _reading(container: dict, key: str, source: str):
            return read_number(container, key, source=source)

        def spoken_prediction(label: str, entry: dict) -> str:
            if not entry:
                return f"{label}: no prediction on record."
            probability = _reading(entry, "direction_probability_pct", label)
            direction = str(entry.get("direction") or UNKNOWN_LABEL)
            return f"{label} is a {probability.number(0, '%')} {direction} forecast."

        has_prediction = bool(btc_pred or eth_pred or sol_pred)
        has_sentiment = bool(sent)
        has_onchain = bool(onchain)
        has_accuracy = bool(acc)

        spoken_parts = [
            f"Good morning Operator Surendra. Here is your morning market intelligence briefing "
            f"for {datetime.now(timezone.utc).strftime('%A, %B %d')}."
        ]
        if has_prediction:
            spoken_parts.append(
                " ".join(
                    spoken_prediction(label, entry)
                    for label, entry in (("Bitcoin", btc_pred), ("Ethereum", eth_pred), ("Solana", sol_pred))
                )
            )
        if has_sentiment:
            spoken_parts.append(
                f"Overall market sentiment is {read_text(sent, 'news_sentiment_label')} "
                f"with a Fear and Greed index of {_reading(sent, 'fear_and_greed_index', 'sentiment telemetry').number(0)}."
            )
        if has_onchain:
            flow = _reading(onchain, "net_exchange_flow_btc", "on-chain telemetry")
            spoken_parts.append(
                f"On-chain telemetry reports a net exchange flow of {flow.number(0, ' BTC')} "
                f"({read_text(onchain, 'exchange_reserve_trend')})."
            )
        if has_accuracy:
            spoken_parts.append(
                f"Directional models are {read_text(acc, 'calibration_status')} at "
                f"{_reading(acc, 'rolling_30d_directional_accuracy_pct', 'accuracy report').percent()}."
            )
        if not (has_prediction or has_sentiment or has_onchain or has_accuracy):
            spoken_parts.append(
                "No market intelligence has been reported to me: no forecasts, no sentiment, no "
                "on-chain telemetry and no accuracy history. I have nothing to brief you on, and I "
                "will not read out numbers I do not have."
            )
        spoken = " ".join(spoken_parts)

        # 2. Markdown Visual Report. Every cell is either a reported value or an
        # explicit unknown; the old table formatted absent values with :.0f/:.0f%
        # and crashed with "TypeError: unsupported format string passed to
        # NoneType.__format__" the moment its defaults were removed - which is the
        # proof that the numbers had never come from a feed.
        def prediction_row(label: str, entry: dict) -> str:
            if not entry:
                return f"| **{label}** | no prediction recorded | - | - | - | - |"
            probability = _reading(entry, "direction_probability_pct", label)
            move = _reading(entry, "expected_move_24h_pct", label)
            support = _reading(entry, "support_level", label)
            resistance = _reading(entry, "resistance_level", label)
            confidence = _reading(entry, "model_confidence", label)
            direction = str(entry.get("direction") or UNKNOWN_LABEL)
            return (
                f"| **{label}** | **{direction}** ({probability.number(0, '%')}) | "
                f"`{move.number(2, '%')}` | `${support.number(0)}` | `${resistance.number(0)}` | "
                f"`{confidence.percent(0)}` |"
            )

        pred_rows = [
            prediction_row("BTC/USDT", btc_pred),
            prediction_row("ETH/USDT", eth_pred),
            prediction_row("SOL/USDT", sol_pred),
        ]

        provider_note = (
            "Sample data - no feed produced these forecasts."
            if getattr(self.intel_engine, "demo_data", False)
            else "Reported by the intelligence engine; absent values are unknown."
        )

        md = (
            f"# 🧠 FRIDAY Morning Market Intelligence Briefing\n\n"
            f"**Generated:** `{now_iso[:19]} UTC` | "
            f"**Sentiment:** **{read_text(sent, 'news_sentiment_label')}** "
            f"(Fear & Greed: `{_reading(sent, 'fear_and_greed_index', 'sentiment telemetry').number(0)}/100`)\n"
            f"**Provenance:** {provider_note}\n\n"
            f"## 🔮 24-Hour AI-Universe Directional Forecasts\n"
            f"| Asset | Directional Bias | Expected Move | Key Support | Key Resistance | Confidence |\n"
            f"| :--- | :---: | :---: | :---: | :---: | :---: |\n" + "\n".join(pred_rows) + "\n\n"
            f"## 📰 Overnight News & Sentiment Summary\n"
            f"- **NLP Sentiment Score:** `{_reading(sent, 'news_sentiment_score', 'sentiment telemetry').number(2)}` "
            f"({read_text(sent, 'news_sentiment_label')})\n"
            f"- **Dominant Narrative:** {read_text(sent, 'news_headline_summary')}\n\n"
            f"## 🐋 On-Chain Whale & Reserve Activity\n"
            f"- **Net Exchange Flow:** `{_reading(onchain, 'net_exchange_flow_btc', 'on-chain telemetry').number(0, ' BTC')}` "
            f"({read_text(onchain, 'exchange_reserve_trend')})\n"
            f"- **Large Whale Transfers (>1k BTC):** "
            f"`{_reading(onchain, 'whale_transactions_count_24h', 'on-chain telemetry').number(0)}` transactions\n"
            f"- **Key Movement:** {read_text(onchain, 'largest_whale_transfer_summary')}\n\n"
            f"## 🎯 Model Accuracy & Calibration Health\n"
            f"- **30-Day Directional Accuracy:** "
            f"**{_reading(acc, 'rolling_30d_directional_accuracy_pct', 'accuracy report').percent()}** "
            f"({_reading(acc, 'total_predictions_evaluated', 'accuracy report').number(0)} forecasts evaluated)\n"
            f"- **Brier Score:** `{_reading(acc, 'brier_score', 'accuracy report').number(3)}` "
            f"(**{read_text(acc, 'calibration_status')}**)\n"
        )

        # ``sent.get(...)`` used to fall back to literals like 68 and "BULLISH" in
        # the snapshot itself, so even a caller that checked for missing data was
        # handed an invented value. The snapshot now carries what was measured or
        # an explicit unknown.
        #: Sentinel for a snapshot field with no reading behind it. ``None`` is
        #: used rather than a plausible number: a consumer that formats it will
        #: raise, which is the correct outcome for "not measured".
        def _snapshot_number(container: dict, key: str):
            reading = read_number(container, key, source="snapshot")
            return reading.value if reading.known else None

        return MorningIntelligenceSnapshot(
            timestamp=now_iso,
            overall_sentiment=read_text(sent, "news_sentiment_label"),
            fear_and_greed_index=_snapshot_number(sent, "fear_and_greed_index"),
            overnight_news_impact=read_text(sent, "news_headline_summary"),
            btc_forecast_direction=read_text(btc_pred, "direction"),
            btc_probability_pct=_snapshot_number(btc_pred, "direction_probability_pct"),
            eth_forecast_direction=read_text(eth_pred, "direction"),
            eth_probability_pct=_snapshot_number(eth_pred, "direction_probability_pct"),
            on_chain_whale_summary=read_text(onchain, "largest_whale_transfer_summary"),
            model_calibration_status=read_text(acc, "calibration_status"),
            spoken_briefing=spoken,
            markdown_report=md,
            has_any_reading=bool(has_prediction or has_sentiment or has_onchain or has_accuracy),
        )
