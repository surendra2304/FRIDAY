"""Production Multi-System Monitor for Trading & AI Supervision.

Polls all three core systems (Trading Bot, AI-Universe, FRIDAY OS) every 30 seconds,
tracks interdependencies, detects cascading failures, monitors resource usage,
predicts emerging risks, and generates unified health reports.
"""

import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.skills.trading_bot_operator import TradingBotOperator

logger = get_logger("production_monitor")


@dataclass
class SystemHealthReport:
    """Comprehensive snapshot of all monitored systems."""
    overall_status: str  # HEALTHY, DEGRADED, CRITICAL
    timestamp: str
    trading_bot: dict[str, Any]
    ai_universe: dict[str, Any]
    friday_os: dict[str, Any]
    active_alerts_count: int
    cascading_failures: list[str]
    predictive_warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
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
        bot_operator: TradingBotOperator | None = None,
        alert_manager: Any | None = None,
        poll_interval: float = 30.0,
        memory: Any | None = None,
    ) -> None:
        self.bot_operator = bot_operator or TradingBotOperator()
        self.alert_manager = alert_manager
        self.poll_interval = poll_interval
        self.memory = memory
        self._history: list[SystemHealthReport] = []
        self._lock = threading.RLock()

    def poll_all_systems(self) -> SystemHealthReport:
        """Polls Trading Bot, AI-Universe, and FRIDAY OS to generate a unified health report."""
        now_iso = datetime.now(timezone.utc).isoformat()
        cascading_failures: list[str] = []
        predictive_warnings: list[str] = []

        # 1. Inspect Trading Bot Tier. `bot_data.get("status", "ACTIVE")` meant an
        # operator that reported no status was displayed as an active one, and
        # `float(bot_data.get("win_rate_pct", 60.0))` below fabricated a win rate
        # for the same reason. An unreported value stays unreported.
        t0 = time.perf_counter()
        bot_status = "UNKNOWN"
        bot_data: dict[str, Any] = {}
        try:
            bot_data = self.bot_operator.get_status()
            bot_latency_ms = (time.perf_counter() - t0) * 1000.0
            bot_status = str(bot_data.get("status") or "UNREPORTED").upper()
            bot_data["latency_ms"] = round(bot_latency_ms, 1)
        except Exception as e:
            bot_status = "DOWN"
            bot_data = {"status": "DOWN", "error": str(e), "latency_ms": 0.0}

        # 2. Inspect AI-Universe Advisory Tier
        t1 = time.perf_counter()
        ai_data: dict[str, Any] = {}
        try:
            adv_state = self.bot_operator.get_advisory_state()
            ai_latency_ms = (time.perf_counter() - t1) * 1000.0
            # The default was "HEALTHY": an advisory tier that said nothing was
            # rendered as a healthy one on a health dashboard.
            ai_health = str(adv_state.get("ai_universe_health") or "UNREPORTED").upper()
            ai_data = {
                "health": ai_health,
                "latency_ms": round(ai_latency_ms, 1),
                "enabled": adv_state.get("ai_universe_enabled", True),
                "last_consult": adv_state.get("last_consult_time", "Recent"),
                "active_overlay": adv_state.get("active_overlay", {}),
            }
        except Exception as e:
            ai_data = {"health": "DOWN", "error": str(e), "latency_ms": 0.0}

        # 3. Inspect FRIDAY OS Tier. The process can attest to facts about itself -
        # its thread count, its pid, and which memory object it holds - and nothing
        # more. "HEALTHY" and "SQLite (friday.db)" were assertions about the
        # deployment, not measurements.
        memory_backend = type(self.memory).__name__ if self.memory is not None else "none configured"
        friday_data = {
            "status": "RUNNING (this process); no health probe has been run",
            "active_threads": threading.active_count(),
            "pid": os.getpid(),
            "memory_backend": memory_backend,
            "timestamp": now_iso,
        }

        # 4. Cascading Failure Detection
        if ai_data.get("health") in ("DOWN", "UNREACHABLE") and bot_status in ("DOWN", "PANIC"):
            cascading_failures.append("Simultaneous outage across AI-Universe Advisory and Trading Bot engine.")

        if bot_data.get("latency_ms", 0) > 2000.0 and ai_data.get("latency_ms", 0) > 2000.0:
            cascading_failures.append("Severe network latency degradation (>2000ms) across multiple REST endpoints.")

        # 5. Predictive Risk Forecasting
        raw_drawdown = bot_data.get("drawdown_pct")
        drawdown = float(raw_drawdown) if isinstance(raw_drawdown, (int, float)) else 0.0
        if isinstance(raw_drawdown, (int, float)) and drawdown >= 4.0:
            predictive_warnings.append(f"Drawdown ({drawdown:.2f}%) approaching maximum 5.0% testnet threshold.")

        win_rate = bot_data.get("win_rate_pct")
        if isinstance(win_rate, (int, float)) and win_rate < 40.0:
            predictive_warnings.append(
                f"Win rate degraded to {float(win_rate):.1f}% over recent trade sample."
            )

        # Determine Overall Status
        active_alerts_count = len(self.alert_manager.get_active_alerts()) if self.alert_manager else 0

        # The else-branch used to be HEALTHY, which is what an operator with no
        # readings produced: silence reported as the best case.
        unreported = [
            name
            for name, reading in (("trading_bot", bot_status), ("ai_universe", ai_data.get("health")))
            if reading in (None, "", "UNREPORTED", "UNKNOWN")
        ]
        if bot_status == "DOWN" or len(cascading_failures) > 0:
            overall_status = "CRITICAL"
        elif ai_data.get("health") in ("DOWN", "DEGRADED") or len(predictive_warnings) > 0:
            overall_status = "DEGRADED"
        elif unreported:
            overall_status = "UNVERIFIED"
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

    def get_latest_report(self) -> SystemHealthReport | None:
        """Returns the most recent system health report."""
        with self._lock:
            return self._history[-1] if self._history else self.poll_all_systems()
