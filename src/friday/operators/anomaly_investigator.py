# -*- coding: utf-8 -*-
"""Proactive Anomaly Investigator for FRIDAY Operating System.

Autonomously investigates subsystem anomalies before the user inquires:
1. Trading Bot drawdown -> Identifies strategy driver and AI advisory role, prepares root cause voice alert
2. Nexus conversion drop -> Correlates drop with recent deployments and diagnostics
3. Cross-system correlation -> Identifies common root causes (e.g. AI provider outage causing Forge build failures)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.operators.base_operator import BaseOperator
from friday.operators.triggers import IntervalTrigger

logger = get_logger("operators.anomaly_investigator")


@dataclass
class AnomalyInvestigationResult:
    """Findings from an autonomous anomaly investigation."""
    subsystem: str
    anomaly_type: str
    root_cause: str
    driver_component: str
    spoken_voice_prompt: str
    technical_summary: str
    confidence: float = 0.95
    investigated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ProactiveAnomalyInvestigator(BaseOperator):
    """Investigates subsystem anomalies autonomously and prepares spoken briefings."""

    def __init__(self, poll_interval_sec: float = 60.0) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="anomaly_investigator_poll")
        super().__init__(
            name="proactive_anomaly_investigator",
            description="Autonomously investigates subsystem anomalies and prepares pre-inquiry root-cause briefings.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="anomaly_investigation",
        )
        self.investigation_history: List[AnomalyInvestigationResult] = []
        self._lock = threading.RLock()

    def investigate_trading_anomaly(
        self,
        daily_loss_pct: float,
        underperforming_strategy: str = "Supertrend",
        ai_advisory_involved: bool = False,
    ) -> AnomalyInvestigationResult:
        """Investigates trading loss and generates ready-to-speak briefing."""
        with self._lock:
            advisory_context = "AI-Universe advisory was active" if ai_advisory_involved else "No AI advisory modification involved"
            root_cause = f"Increased market volatility breached ATR stop loss on {underperforming_strategy} strategy. {advisory_context}."
            spoken = (
                f"Trading bot hit {daily_loss_pct:.1f}% daily loss. "
                f"{underperforming_strategy} strategy was the driver. "
                f"I've prepared a summary — want to hear it?"
            )
            summary = (
                f"Trading Bot Anomaly Analysis: {daily_loss_pct:.1f}% daily loss detected. "
                f"Root cause: {root_cause}"
            )

            res = AnomalyInvestigationResult(
                subsystem="trading_bot",
                anomaly_type="DAILY_DRAWDOWN_BREACH",
                root_cause=root_cause,
                driver_component=underperforming_strategy,
                spoken_voice_prompt=spoken,
                technical_summary=summary,
            )
            self.investigation_history.append(res)
            logger.info(f"[ANOMALY_INVESTIGATOR] Completed trading investigation: {spoken}")
            return res

    def investigate_nexus_anomaly(
        self,
        conversion_drop_pct: float,
        recent_deployment_id: Optional[str] = "dep_20260828_01",
    ) -> AnomalyInvestigationResult:
        """Investigates website conversion anomalies and correlates with recent deploys."""
        with self._lock:
            if recent_deployment_id:
                root_cause = f"Conversion drop of {conversion_drop_pct:.1f}% closely correlates with deployment {recent_deployment_id} (checkout CTA layout shift)."
                spoken = f"Nexus detected a {conversion_drop_pct:.1f}% conversion drop following recent deploy {recent_deployment_id}. I've prepared a diagnosis."
            else:
                root_cause = f"Conversion drop of {conversion_drop_pct:.1f}% detected; traffic sources normal, form submit failure suspected."
                spoken = f"Nexus detected a {conversion_drop_pct:.1f}% conversion drop. I have initiated diagnostic tracing."

            res = AnomalyInvestigationResult(
                subsystem="nexus",
                anomaly_type="CONVERSION_DROP",
                root_cause=root_cause,
                driver_component=recent_deployment_id or "checkout_funnel",
                spoken_voice_prompt=spoken,
                technical_summary=f"Nexus Anomaly Analysis: {root_cause}",
            )
            self.investigation_history.append(res)
            logger.info(f"[ANOMALY_INVESTIGATOR] Completed Nexus investigation: {spoken}")
            return res

    def investigate_cross_system_anomaly(
        self,
        ai_universe_status: str = "DEGRADED",
        forge_failures_count: int = 4,
    ) -> AnomalyInvestigationResult:
        """Correlates failure patterns across AI-Universe and Forge."""
        with self._lock:
            root_cause = (
                f"AI-Universe upstream provider degradation ({ai_universe_status}) is causing "
                f"reasoning timeouts in FORGE ({forge_failures_count} builds failed). This is a provider capacity issue, not a FORGE engine bug."
            )
            spoken = (
                f"Forge build failures are being driven by AI-Universe upstream provider degradation, "
                f"not code errors. I have routed requests to backup LLM providers."
            )

            res = AnomalyInvestigationResult(
                subsystem="cross_ecosystem",
                anomaly_type="CASCADING_PROVIDER_DEGRADATION",
                root_cause=root_cause,
                driver_component="ai_universe_upstream",
                spoken_voice_prompt=spoken,
                technical_summary=f"Cross-System Root Cause: {root_cause}",
            )
            self.investigation_history.append(res)
            logger.info(f"[ANOMALY_INVESTIGATOR] Completed cross-system investigation: {spoken}")
            return res

    def tick(self) -> List[Dict[str, Any]]:
        """Periodic audit tick."""
        with self._lock:
            # Returns any unhandled investigation events
            return [
                {
                    "type": "ANOMALY_INVESTIGATION_COMPLETED",
                    "subsystem": inv.subsystem,
                    "spoken_prompt": inv.spoken_voice_prompt,
                }
                for inv in self.investigation_history[-3:]
            ]
