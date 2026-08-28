# -*- coding: utf-8 -*-
"""Proactive Forecasting Workflow for FRIDAY.

Proactively requests and compiles Futuris probabilistic forecasts based on ecosystem state:
1. Daily Capacity Forecast: Load projections across all active subsystems
2. Weekly Risk Forecast: Holistic security threat trajectory, portfolio drawdown risk, business growth
3. Event-Triggered Forecasts:
   - Nexus reports traffic anomaly -> Requests targeted QPS & conversion forecast
   - Sentinel detects critical CVE -> Requests active exploitation risk forecast
- Invariant: All predictions carry TrustLevel.UNTRUSTED_EXTERNAL and explicit confidence intervals.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import TrustLevel
from friday.skills.futuris_manager import FuturisManagerSkill

logger = get_logger("workflows.proactive_forecasting")


@dataclass
class ProactiveForecastSummary:
    """Summary of proactive forecasts compiled across subsystems."""
    summary_type: str  # DAILY_CAPACITY, WEEKLY_RISK, EVENT_TRIGGERED
    forecasts: List[Dict[str, Any]]
    key_findings: List[str]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    trust_level: str = TrustLevel.UNTRUSTED_EXTERNAL.value


class ProactiveForecastingWorkflow:
    """Orchestrates proactive forecast requests across the ecosystem."""

    def __init__(self, futuris_skill: Optional[FuturisManagerSkill] = None) -> None:
        self.futuris = futuris_skill or FuturisManagerSkill()
        self._history: List[ProactiveForecastSummary] = []
        self._lock = threading.RLock()

    def generate_daily_capacity_forecast(self) -> ProactiveForecastSummary:
        """Generates proactive 24-hour capacity forecasts across all managed subsystems."""
        with self._lock:
            targets = [
                ("Forge Compiler Node Utilization", "24 hours"),
                ("Trading Bot Order Pipeline Latency", "24 hours"),
                ("Nexus Web Server Ingress QPS", "24 hours"),
                ("Sentinel Security Assessment Queue", "24 hours"),
            ]
            fcs = []
            findings = []

            for metric, hor in targets:
                fc = self.futuris.request_forecast(target=metric, horizon=hor, confidence_level=0.90)
                fcs.append(fc)
                findings.append(
                    f"• **{metric}**: `{fc['point_estimate']}` [{fc['confidence_interval'][0]} - {fc['confidence_interval'][1]} @ 90% CI]"
                )

            summary = ProactiveForecastSummary(
                summary_type="DAILY_CAPACITY",
                forecasts=fcs,
                key_findings=findings,
            )
            self._history.append(summary)
            logger.info(f"[PROACTIVE_FORECAST] Generated Daily Capacity Forecast ({len(fcs)} metrics)")
            return summary

    def compile_weekly_risk_forecast(self) -> ProactiveForecastSummary:
        """Compiles proactive 7-day multi-domain risk assessment."""
        with self._lock:
            targets = [
                ("7-Day Security Threat & Attack Surface Trajectory", "7 days"),
                ("7-Day Portfolio Maximum Drawdown Probability", "7 days"),
                ("7-Day Nexus Conversion Rate Volatility", "7 days"),
            ]
            fcs = []
            findings = []

            for metric, hor in targets:
                fc = self.futuris.request_forecast(target=metric, horizon=hor, confidence_level=0.90)
                fcs.append(fc)
                findings.append(
                    f"• **{metric}**: `{fc['point_estimate']}` [{fc['confidence_interval'][0]} - {fc['confidence_interval'][1]} @ 90% CI]"
                )

            summary = ProactiveForecastSummary(
                summary_type="WEEKLY_RISK",
                forecasts=fcs,
                key_findings=findings,
            )
            self._history.append(summary)
            logger.info(f"[PROACTIVE_FORECAST] Compiled Weekly Risk Forecast ({len(fcs)} pillars)")
            return summary

    def trigger_nexus_anomaly_forecast(self, anomaly_data: Dict[str, Any]) -> Dict[str, Any]:
        """Triggered when Nexus detects an unusual visitor pattern -> requests targeted forecast."""
        metric = f"Traffic Ingress Spike ({anomaly_data.get('source', 'Organic')})"
        fc = self.futuris.request_forecast(target=metric, horizon="12 hours", confidence_level=0.90)
        logger.info(f"[PROACTIVE_FORECAST] Triggered Nexus Anomaly Forecast: {metric}")
        return fc

    def trigger_sentinel_vulnerability_forecast(self, cve_data: Dict[str, Any]) -> Dict[str, Any]:
        """Triggered when Sentinel discovers a critical vulnerability -> requests exploitation probability forecast."""
        cve_id = cve_data.get("cve_id", "CVE-2026-UNKNOWN")
        metric = f"Exploitation Risk & In-The-Wild Threat for {cve_id}"
        fc = self.futuris.request_forecast(target=metric, horizon="48 hours", confidence_level=0.90)
        logger.info(f"[PROACTIVE_FORECAST] Triggered Sentinel CVE Forecast: {metric}")
        return fc
