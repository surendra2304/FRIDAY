"""Market Intelligence Briefing Skill for FRIDAY.

Provides interactive voice-driven market intelligence reports and prediction audits:
- "Market intelligence report": Full summary of asset predictions, news/social sentiment, on-chain whale flows, and model accuracy
- "What does the model predict for BTC/ETH?": Asset-specific deep predictions, probability, expected moves, and key drivers
- "How accurate have predictions been?": 30-day directional accuracy, Brier calibration scores, and asset breakdowns
- "Any intelligence alerts?": Active whale transfers, sentiment regime shifts, and adverse prediction warnings
"""

import re
from typing import Any

from friday.core.logging import get_logger
from friday.skills.base_skill import BaseSkill, SkillExecutionResult
from friday.trading.intelligence_engine import IntelligenceEngine

logger = get_logger("skills.intelligence_briefing")


class IntelligenceBriefingSkill(BaseSkill):
    """Voice market intelligence and prediction oversight skill."""

    __test__ = False

    name = "intelligence_briefing"
    description = (
        "Delivers comprehensive market intelligence briefings: deep directional predictions, "
        "NLP news/social sentiment, on-chain whale tracking, and prediction accuracy calibration reports."
    )
    required_capabilities = ["network_access"]
    tools = ["prediction_model_query", "sentiment_feed_query", "onchain_analytics_query"]
    system_prompt = (
        "You are FRIDAY's Market Intelligence and Prediction Specialist. You analyze deep forecasts from AI-Universe, "
        "synthesize alternative on-chain and sentiment data, evaluate prediction accuracy calibration, and alert on market anomalies."
    )
    match_patterns = [
        r"\b(?:market\s+intelligence\s+report|intelligence\s+briefing|intel\s+report)\b",
        r"\b(?:what\s+does\s+the\s+model\s+predict\s+for\s+[a-z0-9]+|model\s+prediction|predict\s+for\s+[a-z0-9]+)\b",
        r"\b(?:how\s+accurate\s+have\s+predictions\s+been|prediction\s+accuracy|model\s+accuracy)\b",
        r"\b(?:any\s+intelligence\s+alerts|intel\s+alerts|whale\s+alerts)\b",
    ]

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

    def execute(
        self,
        user_request: str,
        agent: Any | None = None,
        tool_registry: Any | None = None,
        llm_provider: Any | None = None,
        authorizer: Any | None = None,
        **kwargs: Any,
    ) -> SkillExecutionResult:
        """Dispatches voice intelligence queries."""
        clean = user_request.strip().lower()
        step_results: list[dict[str, Any]] = []

        try:
            from friday.core.readings import UNKNOWN_LABEL, read_number, read_text

            # 1. "What does the model predict for BTC / ETH / SOL?"
            match_pred = re.search(r"predict\s+for\s+([a-z0-9]+)", clean)
            if match_pred:
                symbol = match_pred.group(1).upper()
                pred = self.intel_engine.get_prediction(symbol)
                if pred is None:
                    spoken = (
                        f"I have no recorded prediction for {symbol}. I will not read you one that "
                        f"does not exist."
                    )
                    step_results.append({"action": "asset_prediction", "symbol": symbol, "found": False})
                    return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

                entry = pred.__dict__ if hasattr(pred, "__dict__") else {}
                probability = read_number(entry, "direction_probability_pct", source=pred.symbol)
                move = read_number(entry, "expected_move_24h_pct", source=pred.symbol)
                confidence = read_number(entry, "model_confidence", source=pred.symbol)
                support = read_number(entry, "support_level", source=pred.symbol)
                resistance = read_number(entry, "resistance_level", source=pred.symbol)
                spoken = (
                    f"Prediction for {pred.symbol}: The model is {probability.number(0, '%')} {pred.direction} "
                    f"with an expected 24-hour move of {move.number(1, '%')} "
                    f"(confidence: {confidence.percent(0)}). "
                    f"Key drivers: {', '.join(pred.key_drivers[:2]) or 'none recorded'}. "
                    f"Key support sits at ${support.number(0)} with resistance at ${resistance.number(0)}."
                )
                step_results.append({"action": "asset_prediction", "symbol": pred.symbol})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 2. "How accurate have predictions been?"
            if any(k in clean for k in ["accurate have predictions been", "prediction accuracy", "model accuracy"]):
                acc = self.intel_engine.get_accuracy_report()
                if acc is None:
                    # The fallback used to be AccuracyReport(78.5, 0.142, 120,
                    # {"BTCUSDT": 82.5}, "WELL_CALIBRATED") - invented and then
                    # spoken as a measurement.
                    spoken = (
                        "No accuracy history has been recorded, so I cannot tell you how accurate the "
                        "predictions have been. I will not quote a number I do not have."
                    )
                    step_results.append({"action": "accuracy_report", "recorded": False})
                    return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

                entry = acc.__dict__ if hasattr(acc, "__dict__") else {}
                per_asset = acc.asset_accuracies or {}
                breakdown = ", ".join(
                    f"{symbol} at {value:.1f}%" for symbol, value in sorted(per_asset.items())
                ) or "no per-asset breakdown recorded"
                spoken = (
                    f"Prediction accuracy report: Over the last 30 days ({acc.total_predictions_evaluated} evaluated forecasts), "
                    f"the model achieved {acc.rolling_30d_directional_accuracy_pct:.1f}% directional accuracy with a Brier calibration score of {acc.brier_score:.3f}. "
                    f"Asset breakdown: {breakdown}. "
                    f"Overall calibration status is {acc.calibration_status}."
                )
                step_results.append({"action": "accuracy_report", "accuracy_pct": acc.rolling_30d_directional_accuracy_pct})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 3. "Any intelligence alerts?"
            if any(k in clean for k in ["intelligence alerts", "intel alerts", "whale alerts"]):
                alerts = self.intel_engine.get_active_alerts()
                if alerts:
                    lines = [f"There are currently {len(alerts)} active market intelligence alerts:"]
                    for a in alerts:
                        lines.append(f"• **[{a.severity}] {a.alert_type}** ({a.symbol}): {a.message}")
                    spoken = "\n".join(lines)
                else:
                    # "No anomalous alerts active" was a claim about the market.
                    # Nothing here observes the market; it only knows its own list.
                    spoken = (
                        "No intelligence alert has been recorded. That is not the same as no anomaly "
                        "having occurred - nothing here is watching the market."
                    )

                step_results.append({"action": "intelligence_alerts", "count": len(alerts)})
                return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

            # 4. Default: "Market intelligence report". Every number in the old
            # sentence had a plausible default (BULLISH, 68, -6,500 BTC, 76%/65%/
            # 58%, 78.5%), so an engine with nothing to report recited a complete
            # market view.
            report = self.intel_engine.get_market_intelligence_report()
            sent = report.get("sentiment", {})
            onchain = report.get("on_chain", {})
            acc = report.get("accuracy", {})

            if not (sent or onchain or acc):
                spoken = (
                    "The intelligence engine has no market data on record: no sentiment, no on-chain "
                    "telemetry and no accuracy history. I have no market intelligence summary to give."
                )
            else:
                parts = []
                if sent:
                    parts.append(
                        f"News sentiment is {read_text(sent, 'news_sentiment_label')} with a Fear & Greed "
                        f"index of {read_number(sent, 'fear_and_greed_index', source='sentiment telemetry').number(0)}."
                    )
                if onchain:
                    parts.append(
                        f"On-chain telemetry reports a net exchange flow of "
                        f"{read_number(onchain, 'net_exchange_flow_btc', source='on-chain telemetry').number(0, ' BTC')} "
                        f"({read_text(onchain, 'exchange_reserve_trend')})."
                    )
                if acc:
                    parts.append(
                        f"Rolling 30-day directional prediction accuracy stands at "
                        f"{read_number(acc, 'rolling_30d_directional_accuracy_pct', source='accuracy report').percent()}."
                    )
                    forecasts = []
                    for symbol in ("BTCUSDT", "SOLUSDT", "ETHUSDT"):
                        pred = self.intel_engine.get_prediction(symbol)
                        if pred is not None:
                            entry = pred.__dict__
                            forecasts.append(
                                f"{symbol} {read_number(entry, 'direction_probability_pct', source=symbol).number(0, '%')} "
                                f"{pred.direction}"
                            )
                    if forecasts:
                        parts.append("Forecasts: " + "; ".join(forecasts) + ".")
                spoken = "Market intelligence summary: " + " ".join(parts)

            step_results.append({"action": "market_intelligence_report"})
            return SkillExecutionResult(skill_name=self.name, success=True, output=spoken, step_results=step_results)

        except Exception as e:
            logger.error(f"[INTELLIGENCE_BRIEFING] Execution error: {e}", exc_info=True)
            return SkillExecutionResult(
                skill_name=self.name,
                success=False,
                output=f"Market intelligence briefing query encountered an error: {e}",
                error=str(e),
                step_results=step_results,
            )
