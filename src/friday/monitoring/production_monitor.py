"""Comprehensive Production Monitoring & Alerting for FRIDAY.

Supervises real-time system performance, resource utilization, trading-specific risk metrics,
and multi-channel priority alert dispatching (Voice, SMS, Email, Dashboard).
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("monitoring.production_monitor")


@dataclass
class ResourceMetrics:
    """System resource usage statistics."""
    cpu_percent: float
    memory_mb: float
    active_threads: int
    open_connections: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class MonitoringSnapshot:
    """Complete multi-tier monitoring state."""
    system_status: str  # HEALTHY, DEGRADED, CRITICAL
    resources: ResourceMetrics
    trading_risk: dict[str, Any]
    dependencies: dict[str, str]
    unacknowledged_alerts_count: int
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ComprehensiveProductionMonitor:
    """Production monitor tracking system resources, trading risk, and alert escalation."""

    def __init__(
        self,
        alert_manager: Any | None = None,
        risk_dashboard: Any | None = None,
        bot_operator: Any | None = None,
    ) -> None:
        self._alert_manager = alert_manager
        self._risk_dashboard = risk_dashboard
        self._bot_operator = bot_operator
        self._snapshots: list[MonitoringSnapshot] = []
        self._lock = threading.RLock()

    @property
    def alert_manager(self) -> Any:
        if self._alert_manager is None:
            from friday.alert_manager import ProductionAlertManager
            self._alert_manager = ProductionAlertManager()
        return self._alert_manager

    @property
    def risk_dashboard(self) -> Any:
        if self._risk_dashboard is None:
            from friday.trading.risk_dashboard import RiskManagementDashboard
            self._risk_dashboard = RiskManagementDashboard()
        return self._risk_dashboard

    @property
    def bot_operator(self) -> Any:
        if self._bot_operator is None:
            from friday.skills.trading_bot_operator import TradingBotOperator
            self._bot_operator = TradingBotOperator()
        return self._bot_operator

    def capture_snapshot(self) -> MonitoringSnapshot:
        """Captures a real-time system and trading risk monitoring snapshot.

        Every field here was previously either a literal or a green light:

        * ``cpu_percent=1.5``, ``memory_mb=185.0``, ``open_connections=4`` and
          ``active_threads`` (the one real measurement) sat next to each other, so
          a reader could not tell which were measured;
        * all three dependencies were hardcoded ``ONLINE`` - including the trading
          bot REST API, which was simultaneously refusing connections;
        * the dashboard rendered "Portfolio Equity: $10,540.25" and "Effective
          Leverage: 0.43x" from its own defaults when ``evaluate_risk`` had
          nothing, while ``status`` defaulted to HEALTHY.

        A monitor that reports HEALTHY while the thing it monitors is down is
        worse than no monitor, because the green light is what gets believed.
        """
        import os

        import psutil

        # 1. System Resources - measured here, not asserted.
        process = psutil.Process(os.getpid())
        with process.oneshot():
            cpu_percent = process.cpu_percent(interval=None)
            memory_mb = process.memory_info().rss / (1024 * 1024)
            open_connections = len(process.net_connections(kind="inet"))
        resources = ResourceMetrics(
            cpu_percent=round(cpu_percent, 1),
            memory_mb=round(memory_mb, 1),
            active_threads=threading.active_count(),
            open_connections=open_connections,
        )

        # 2. Dependencies - probed, and reported as UNVERIFIED when not probed.
        deps: dict[str, str] = {}
        try:
            deps["TRADING_BOT_REST_API"] = self._probe_bot_api()
        except Exception as exc:  # pragma: no cover - depends on the deployment
            deps["TRADING_BOT_REST_API"] = f"PROBE FAILED ({type(exc).__name__})"
        deps["AI_UNIVERSE_ADVISORY"] = "NOT PROBED"
        deps["SQLITE_MEMORY_STORE"] = "NOT PROBED"

        # 3. Trading Risk - whatever the risk dashboard can attest to.
        try:
            risk = self.risk_dashboard.evaluate_risk()
            risk_dict = {
                "total_equity": risk.total_portfolio_equity,
                "exposure": risk.total_exposure_usdt,
                "leverage": risk.effective_leverage,
                "var_95": risk.var_95_usdt,
                "concentration": risk.concentration_rating,
            }
        except Exception as e:
            risk_dict = {"error": str(e)}

        # Active Alerts
        active_alerts = self.alert_manager.get_active_alerts()
        unack_count = len(active_alerts)

        # 4. Status - a dependency that could not be reached is not HEALTHY, and a
        # dependency that was never probed is not HEALTHY either.
        status = "HEALTHY"
        if unack_count > 0:
            if any(a.severity.value == "CRITICAL" for a in active_alerts):
                status = "CRITICAL"
            elif any(a.severity.value == "ERROR" for a in active_alerts):
                status = "DEGRADED"
        unhealthy = [k for k, v in deps.items() if v not in ("ONLINE", "NOT PROBED")]
        unverified = [k for k, v in deps.items() if v == "NOT PROBED"]
        if unhealthy:
            status = "CRITICAL" if status != "CRITICAL" else status
        elif unverified and status == "HEALTHY":
            status = "UNVERIFIED"

        snapshot = MonitoringSnapshot(
            system_status=status,
            resources=resources,
            trading_risk=risk_dict,
            dependencies=deps,
            unacknowledged_alerts_count=unack_count,
        )

        with self._lock:
            self._snapshots.append(snapshot)
            if len(self._snapshots) > 200:
                self._snapshots.pop(0)

        return snapshot

    def _probe_bot_api(self) -> str:
        """One short HTTP probe of the trading bot's status endpoint."""
        import json
        import urllib.request

        from friday.skills.trading_bot_operator import TradingBotOperator

        base = getattr(self.bot_operator, "base_url", None) or TradingBotOperator.base_url
        url = f"{base}/api/status"
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:  # noqa: S310
                payload = json.loads(response.read().decode() or "{}")
            return "ONLINE" if isinstance(payload, dict) else "UNEXPECTED RESPONSE"
        except Exception as exc:
            return f"UNREACHABLE ({type(exc).__name__})"

    def render_health_dashboard(self) -> str:
        """Renders comprehensive monitoring metrics in Markdown."""
        snap = self.capture_snapshot()
        res = snap.resources
        risk = snap.trading_risk

        # The three risk lines below used to fall back to $10,540.25 / 0.43x /
        # $189.72 - a portfolio that does not exist, rendered under a live
        # timestamp. A missing value now says it is missing.
        def _money(value: Any) -> str:
            return f"${float(value):,.2f}" if isinstance(value, (int, float)) else "unknown (not reported)"

        def _number(value: Any, digits: int, suffix: str = "") -> str:
            return f"{float(value):.{digits}f}{suffix}" if isinstance(value, (int, float)) else "unknown (not reported)"

        def _dep_badge(value: str) -> str:
            # ONLINE is the only green state. A dependency that was never probed
            # is grey, never green: that is the whole difference between "fine"
            # and "unknown", and this table used to print green for both.
            if value == "ONLINE":
                return "\U0001f7e2 ONLINE"
            if value == "NOT PROBED":
                return "\u26aa NOT PROBED"
            return f"\U0001f534 {value}"

        status_badge = {
            "HEALTHY": "🟢 HEALTHY",
            "DEGRADED": "⚠️ DEGRADED",
            "UNVERIFIED": "⚪ UNVERIFIED",
            "CRITICAL": "🚨 CRITICAL",
        }.get(snap.system_status, f"⚪ {snap.system_status}")

        return (
            f"# 🖥️ FRIDAY Comprehensive Production Monitoring Dashboard\n\n"
            f"**System Status:** **{status_badge}** | **Time:** `{snap.timestamp[:19]} UTC`\n\n"
            f"## ⚙️ Resource Utilization\n"
            f"- **Active Threads:** `{res.active_threads}`\n"
            f"- **Memory Usage:** `{res.memory_mb:.1f} MB`\n"
            f"- **CPU Usage:** `{res.cpu_percent:.1f}%`\n\n"
            f"## 🌐 Dependencies Health\n"
            f"| Dependency | Status |\n"
            + "\n".join(f"| `{k}` | **{_dep_badge(v)}** |" for k, v in snap.dependencies.items()) + "\n\n"
            f"## 📈 Trading Risk Telemetry\n"
            f"- **Portfolio Equity:** **{_money(risk.get('total_equity'))} USDT**\n"
            f"- **Effective Leverage:** `{_number(risk.get('leverage'), 2, 'x')}`\n"
            f"- **1-Day 95% VaR:** **{_money(risk.get('var_95'))} USDT**\n"
            f"- **Unacknowledged Alerts:** `{snap.unacknowledged_alerts_count}`\n"
        )
