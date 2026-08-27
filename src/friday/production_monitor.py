# -*- coding: utf-8 -*-
"""Production Multi-System Monitor for Trading & AI Supervision.

Polls all three core systems (Trading Bot, AI-Universe, FRIDAY OS) every 30 seconds,
tracks interdependencies, detects cascading failures, monitors resource usage,
predicts emerging risks, and generates unified health reports.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import threading
import time
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import Message, Role, TrustLevel
from friday.skills.trading_bot_operator import TradingBotOperator

logger = get_logger("production_monitor")


@dataclass
class SystemHealthReport:
    """Comprehensive snapshot of all monitored systems."""
    overall_status: str  # HEALTHY, DEGRADED, CRITICAL
    timestamp: str
    trading_bot: Dict[str, Any]
    ai_universe: Dict[str, Any]
    friday_os: Dict[str, Any]
    active_alerts_count: int
    cascading_failures: List[str]
    predictive_warnings: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "timestamp": self.timestamp,
            "trading_bot": self.trading_bot,
            "ai_universe": self.ai_universe,
            "friday_os": self.friday_os,
            "active_alerts_count": self.active_alerts_count,
            "cascading_failures": self.cascading_failures,
            "predictive_warnings": self.predictive_warnings,
        }


class ProductionMonitor:
    """Production monitor supervising multi-system health and interdependencies."""

    def __init__(
        self,
        bot_operator: Optional[TradingBotOperator] = None,
        alert_manager: Optional[Any] = None,
        poll_interval: float = 30.0,
        memory: Optional[Any] = None,
    ) -> None:
        self.bot_operator = bot_operator or TradingBotOperator()
        self.alert_manager = alert_manager
        self.poll_interval = poll_interval
        self.memory = memory
        self._history: List[SystemHealthReport] = []
        self._lock = threading.RLock()

    def poll_all_systems(self) -> SystemHealthReport:
        """Polls Trading Bot, AI-Universe, and FRIDAY OS to generate a unified health report."""
        now_iso = datetime.now(timezone.utc).isoformat()
        cascading_failures: List[str] = []
        predictive_warnings: List[str] = []

        # 1. Inspect Trading Bot Tier
        t0 = time.perf_counter()
        bot_status = "UNKNOWN"
        bot_data: Dict[str, Any] = {}
        try:
            bot_data = self.bot_operator.get_status()
            bot_latency_ms = (time.perf_counter() - t0) * 1000.0
            bot_status = bot_data.get("status", "ACTIVE")
            bot_data["latency_ms"] = round(bot_latency_ms, 1)
        except Exception as e:
            bot_status = "DOWN"
            bot_data = {"status": "DOWN", "error": str(e), "latency_ms": 0.0}

        # 2. Inspect AI-Universe Advisory Tier
        t1 = time.perf_counter()
        ai_data: Dict[str, Any] = {}
        try:
            adv_state = self.bot_operator.get_advisory_state()
            ai_latency_ms = (time.perf_counter() - t1) * 1000.0
            ai_health = str(adv_state.get("ai_universe_health", "HEALTHY")).upper()
            ai_data = {
                "health": ai_health,
                "latency_ms": round(ai_latency_ms, 1),
                "enabled": adv_state.get("ai_universe_enabled", True),
                "last_consult": adv_state.get("last_consult_time", "Recent"),
                "active_overlay": adv_state.get("active_overlay", {}),
            }
        except Exception as e:
            ai_data = {"health": "DOWN", "error": str(e), "latency_ms": 0.0}

        # 3. Inspect FRIDAY OS Tier
        friday_data = {
            "status": "HEALTHY",
            "active_threads": threading.active_count(),
            "pid": os.getpid(),
            "memory_backend": "SQLite (friday.db)" if self.memory else "In-Memory",
            "timestamp": now_iso,
        }

        # 4. Cascading Failure Detection
        if ai_data.get("health") in ("DOWN", "UNREACHABLE") and bot_status in ("DOWN", "PANIC"):
            cascading_failures.append("Simultaneous outage across AI-Universe Advisory and Trading Bot engine.")

        if bot_data.get("latency_ms", 0) > 2000.0 and ai_data.get("latency_ms", 0) > 2000.0:
            cascading_failures.append("Severe network latency degradation (>2000ms) across multiple REST endpoints.")

        # 5. Predictive Risk Forecasting
        drawdown = float(bot_data.get("drawdown_pct", 0.0))
        if drawdown >= 4.0:
            predictive_warnings.append(f"Drawdown ({drawdown:.2f}%) approaching maximum 5.0% testnet threshold.")

        win_rate = float(bot_data.get("win_rate_pct", 60.0))
        if win_rate < 40.0:
            predictive_warnings.append(f"Win rate degraded to {win_rate:.1f}% over recent trade sample.")

        # Determine Overall Status
        active_alerts_count = len(self.alert_manager.get_active_alerts()) if self.alert_manager else 0

        if bot_status == "DOWN" or len(cascading_failures) > 0:
            overall_status = "CRITICAL"
        elif ai_data.get("health") in ("DOWN", "DEGRADED") or len(predictive_warnings) > 0:
            overall_status = "DEGRADED"
        else:
            overall_status = "HEALTHY"

        report = SystemHealthReport(
            overall_status=overall_status,
            timestamp=now_iso,
            trading_bot=bot_data,
            ai_universe=ai_data,
            friday_os=friday_data,
            active_alerts_count=active_alerts_count,
            cascading_failures=cascading_failures,
            predictive_warnings=predictive_warnings,
        )

        with self._lock:
            self._history.append(report)
            if len(self._history) > 100:
                self._history.pop(0)

        # Trigger alerts if cascading failure detected
        if cascading_failures and self.alert_manager:
            from friday.alert_manager import AlertSeverity
            for fail in cascading_failures:
                self.alert_manager.create_alert(
                    title="CASCADING MULTI-SYSTEM FAILURE",
                    message=fail,
                    severity=AlertSeverity.CRITICAL,
                    category="system_health",
                    metadata=report.to_dict(),
                )

        return report

    def get_latest_report(self) -> Optional[SystemHealthReport]:
        """Returns the most recent system health report."""
        with self._lock:
            return self._history[-1] if self._history else self.poll_all_systems()
