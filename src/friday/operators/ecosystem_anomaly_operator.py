"""Cross-System Anomaly Detection Operator for FRIDAY Ecosystem.

Monitors correlations and cascading failure patterns across Trading Bot,
Nexus Website, FORGE SWE Engine, and AI-Universe Core on a 60-second cycle:
- Market/Nexus correlation anomalies (trading drawdown during web traffic surge)
- Correlated build failures (FORGE errors coinciding with AI-Universe provider degradation)
- Cascading multi-system outages
- Unusual cross-system quietness (zero activity across all four components)
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.ecosystem.registry import EcosystemRegistry, ecosystem_registry
from friday.operators.base_operator import BaseOperator
from friday.operators.triggers import IntervalTrigger

logger = get_logger("operators.ecosystem_anomaly")


@dataclass
class AnomalyEvent:
    """Record of a detected cross-subsystem anomaly."""
    anomaly_type: str  # CASCADING_FAILURE, CORRELATED_BUILD_AI_FAILURE, MARKET_WEB_ANOMALY, UNUSUAL_QUIETNESS
    severity: str  # CRITICAL, HIGH, MEDIUM, LOW
    description: str
    affected_subsystems: list[str]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class EcosystemAnomalyDetection(BaseOperator):
    """Persistent 60-second anomaly detection operator evaluating cross-system correlation rules."""

    def __init__(
        self,
        registry: EcosystemRegistry | None = None,
        poll_interval_sec: float = 60.0,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="ecosystem_anomaly_poll_interval")
        super().__init__(
            name="ecosystem_anomaly_operator",
            description="Evaluates cross-system correlation anomalies and cascading failures every 60 seconds.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="ecosystem_anomaly",
        )
        self.registry = registry or ecosystem_registry
        self.poll_interval_sec = poll_interval_sec
        self._lock = threading.RLock()
        self._detected_anomalies: list[AnomalyEvent] = []

    def tick(self) -> list[dict[str, Any]]:
        """Executes 60-second cross-subsystem anomaly evaluation."""
        with self._lock:
            now = datetime.now(timezone.utc)
            events: list[dict[str, Any]] = []

            try:
                status = self.registry.get_ecosystem_status()
                subs = status.get("subsystems", {})
                bot = subs.get("trading_bot", {}).get("data", {})
                forge = subs.get("forge", {}).get("data", {})
                ai = subs.get("ai_universe", {}).get("data", {})
                nexus = subs.get("nexus", {}).get("data", {})

                # 1. Cascading Failure Rule: > 1 subsystem degraded/unavailable
                degraded_subs = [
                    name for name, data in subs.items()
                    if data.get("status") in ("DEGRADED", "UNAVAILABLE", "ERROR", "CRITICAL")
                ]
                if len(degraded_subs) >= 2:
                    evt = {
                        "type": "CASCADING_FAILURE",
                        "severity": "CRITICAL",
                        "affected_subsystems": degraded_subs,
                        "message": f"🚨 [CASCADING OUTAGE] Multiple subsystems degraded simultaneously: {', '.join(degraded_subs)}.",
                        "timestamp": now.isoformat(),
                        "trust_level": "UNTRUSTED_EXTERNAL",
                    }
                    events.append(evt)
                    logger.critical(f"[ECOSYSTEM_ANOMALY] {evt['message']}")

                # 2. Correlated Build / AI-Universe Failure
                forge_status = forge.get("status", "IDLE")
                ai_status = ai.get("status", "HEALTHY")
                if (forge_status in ("FAILED", "BLOCKED")) and (ai_status in ("DEGRADED", "UNAVAILABLE")):
                    evt = {
                        "type": "CORRELATED_BUILD_AI_FAILURE",
                        "severity": "HIGH",
                        "affected_subsystems": ["forge", "ai_universe"],
                        "message": "⚠️ [CORRELATED ANOMALY] FORGE build pipeline failure correlated with AI-Universe provider degradation.",
                        "timestamp": now.isoformat(),
                        "trust_level": "UNTRUSTED_EXTERNAL",
                    }
                    events.append(evt)
                    logger.warning(f"[ECOSYSTEM_ANOMALY] {evt['message']}")

                # 3. Market / Web Spike Anomaly
                bot_loss = bot.get("daily_loss_pct", 0.0)
                nexus_visitors = nexus.get("visitors_today", 4280)
                if bot_loss >= 3.5 and nexus_visitors >= 8000:
                    evt = {
                        "type": "MARKET_WEB_ANOMALY",
                        "severity": "MEDIUM",
                        "affected_subsystems": ["trading_bot", "nexus"],
                        "message": "📈 [MARKET CORRELATION] High trading drawdown coinciding with surge in website traffic.",
                        "timestamp": now.isoformat(),
                        "trust_level": "UNTRUSTED_EXTERNAL",
                    }
                    events.append(evt)
                    logger.info(f"[ECOSYSTEM_ANOMALY] {evt['message']}")

                # 4. Unusual Quietness Rule (0 across all systems)
                if (
                    bot.get("active_positions_count", 0) == 0
                    and nexus.get("visitors_today", 0) == 0
                    and forge.get("active_tasks_count", 0) == 0
                    and ai.get("consultations_today", 0) == 0
                ):
                    evt = {
                        "type": "UNUSUAL_QUIETNESS",
                        "severity": "LOW",
                        "affected_subsystems": ["trading_bot", "nexus", "forge", "ai_universe"],
                        "message": "💤 [UNUSUAL QUIETNESS] Zero activity recorded across all four subsystems.",
                        "timestamp": now.isoformat(),
                        "trust_level": "UNTRUSTED_EXTERNAL",
                    }
                    events.append(evt)
                    logger.info(f"[ECOSYSTEM_ANOMALY] {evt['message']}")

            except Exception as e:
                logger.error(f"[ECOSYSTEM_ANOMALY] Error evaluating anomaly rules: {e}")

            for evt in events:
                self._detected_anomalies.append(
                    AnomalyEvent(
                        anomaly_type=evt["type"],
                        severity=evt["severity"],
                        description=evt["message"],
                        affected_subsystems=evt.get("affected_subsystems", []),
                    )
                )

            return events

    def get_detected_anomalies(self) -> list[AnomalyEvent]:
        """Returns log of all detected cross-system anomalies."""
        with self._lock:
            return list(self._detected_anomalies)
