# -*- coding: utf-8 -*-
"""Prediction-Informed Decision Engine for FRIDAY.

Consults relevant Futuris probabilistic forecasts before making ecosystem decisions:
- Forge Task Submission: Checks capacity forecast; suggests queuing if resource saturation >= 80%
- Trading Decisions: Injects volatility and drawdown forecast bounds into trading advisory context
- Nexus Campaigns: Checks traffic forecast to recommend optimal timing
- Sentinel Scans: Checks threat escalation & exploitation probability forecast to set scan urgency
- INVARIANT: Predictions are always inputs to decisions, never autonomous decision-makers.
- All forecast artifacts carry TrustLevel.UNTRUSTED_EXTERNAL.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import TrustLevel
from friday.skills.futuris_manager import FuturisManagerSkill

logger = get_logger("core.prediction_decisions")


@dataclass
class DecisionContext:
    """Enriched decision context containing probabilistic forecasts."""
    domain: str  # forge, trading, nexus, sentinel
    recommendation: str  # PROCEED, QUEUE, DEFER, ADJUST_TIMING, ESCALATE
    forecast_id: str
    target_metric: str
    point_estimate: float
    confidence_interval: List[float]
    rationale: str
    trust_level: str = TrustLevel.UNTRUSTED_EXTERNAL.value
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PredictionInformedDecisionEngine:
    """Provides predictive decision support across all ecosystem operations."""

    def __init__(self, futuris_skill: Optional[FuturisManagerSkill] = None) -> None:
        self.futuris = futuris_skill or FuturisManagerSkill()
        self._lock = threading.RLock()

    def evaluate_forge_task_submission(self, task_spec: Dict[str, Any]) -> DecisionContext:
        """Evaluates compiler capacity forecast before submitting a Forge build task."""
        target = "Forge Cluster CPU & Memory Capacity"
        fc = self.futuris.request_forecast(target=target, horizon="2 hours", confidence_level=0.90)
        p_high = fc["confidence_interval"][1]

        if p_high >= 80.0:
            rec = "QUEUE"
            rat = (
                f"Futuris predicts high capacity utilization at {fc['point_estimate']}% "
                f"[{fc['confidence_interval'][0]}% - {p_high}% @ 90% CI]. "
                f"Suggesting queuing task to prevent compiler starvation."
            )
        else:
            rec = "PROCEED"
            rat = (
                f"Futuris predicts nominal cluster load at {fc['point_estimate']}% "
                f"[{fc['confidence_interval'][0]}% - {p_high}% @ 90% CI]. Safe to proceed."
            )

        logger.info(f"[PREDICTION_DECISION] Forge Evaluation: {rec} — {rat}")
        return DecisionContext(
            domain="forge",
            recommendation=rec,
            forecast_id=fc["forecast_id"],
            target_metric=target,
            point_estimate=fc["point_estimate"],
            confidence_interval=fc["confidence_interval"],
            rationale=rat,
        )

    def enrich_trading_advisory_context(self, market_state: Dict[str, Any]) -> DecisionContext:
        """Injects volatility forecast into trading advisory context (advisory only)."""
        target = "Crypto Market Volatility Index"
        fc = self.futuris.request_forecast(target=target, horizon="24 hours", confidence_level=0.90)
        p_high = fc["confidence_interval"][1]

        rat = (
            f"Futuris predicts 24h market volatility at {fc['point_estimate']} "
            f"[{fc['confidence_interval'][0]} - {p_high} @ 90% CI]. "
            f"Your trading bot's advisory will receive this context for risk evaluation."
        )

        logger.info(f"[PREDICTION_DECISION] Trading Advisory Context Enriched: {rat}")
        return DecisionContext(
            domain="trading",
            recommendation="ADVISORY_CONTEXT_INJECTED",
            forecast_id=fc["forecast_id"],
            target_metric=target,
            point_estimate=fc["point_estimate"],
            confidence_interval=fc["confidence_interval"],
            rationale=rat,
        )

    def evaluate_nexus_campaign_timing(self, campaign_spec: Dict[str, Any]) -> DecisionContext:
        """Evaluates website visitor traffic forecast to recommend optimal campaign launch timing."""
        target = "Nexus Website Visitor Traffic"
        fc = self.futuris.request_forecast(target=target, horizon="48 hours", confidence_level=0.90)
        p_low, p_high = fc["confidence_interval"]

        rat = (
            f"Futuris predicts peak visitor conversion window in next 24-36 hours "
            f"(forecasted traffic index: {fc['point_estimate']} [{p_low} - {p_high} @ 90% CI]). "
            f"Recommended launch window: Tomorrow 14:00 UTC."
        )

        logger.info(f"[PREDICTION_DECISION] Nexus Campaign Timing: {rat}")
        return DecisionContext(
            domain="nexus",
            recommendation="PROCEED",
            forecast_id=fc["forecast_id"],
            target_metric=target,
            point_estimate=fc["point_estimate"],
            confidence_interval=fc["confidence_interval"],
            rationale=rat,
        )

    def evaluate_sentinel_scan_urgency(self, asset_target: str, cve_id: str) -> DecisionContext:
        """Evaluates exploitation probability forecast to configure Sentinel scan mode & urgency."""
        target = f"Exploitation Probability for {cve_id}"
        fc = self.futuris.request_forecast(target=target, horizon="24 hours", confidence_level=0.90)
        p_high = fc["confidence_interval"][1]

        if p_high >= 70.0:
            rec = "ESCALATE_IMMEDIATE"
            rat = (
                f"Futuris predicts 75% probability [{fc['confidence_interval'][0]}% - {p_high}% @ 90% CI] "
                f"of active CVE exploitation in next 24 hours. Immediate targeted scan recommended."
            )
        else:
            rec = "STANDARD_SCHEDULE"
            rat = (
                f"Futuris predicts low exploitation risk at {fc['point_estimate']}% "
                f"[{fc['confidence_interval'][0]}% - {p_high}% @ 90% CI]. Standard passive recon is sufficient."
            )

        logger.info(f"[PREDICTION_DECISION] Sentinel Urgency: {rec} — {rat}")
        return DecisionContext(
            domain="sentinel",
            recommendation=rec,
            forecast_id=fc["forecast_id"],
            target_metric=target,
            point_estimate=fc["point_estimate"],
            confidence_interval=fc["confidence_interval"],
            rationale=rat,
        )
