"""Testnet Advisory Operator for Live Binance Futures Execution Supervision.

Persistent background operator that monitors live Binance Futures Testnet
AI advisory state every 15 minutes, tracking SHADOW vs APPLY mode transitions,
detecting critical drawdown threshold breaches, and alerting on AI-Universe downtime.

Alert Conditions:
1. Mode Transition: Testnet advisory mode changed to APPLY.
2. Drawdown Threshold: Testnet drawdown exceeds maximum limit (e.g. >5.0%).
3. AI Health Degradation: AI-Universe health down or unreachable while testnet advisory is enabled.
4. Bot Unreachable: Trading bot REST API fails to respond.
"""

from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel, TrustLevel
from friday.operators.base_operator import (
    BaseOperator,
)
from friday.operators.triggers import IntervalTrigger
from friday.skills.trading_bot_operator import TradingBotOperator
from friday.skills.trading_precedence import CommandPrecedence, tag_trading_command

logger = get_logger("operators.testnet_advisory_operator")


class TestnetAdvisoryOperator(BaseOperator):
    """Monitors live Binance Futures Testnet AI advisory operations and safety boundaries."""

    __test__ = False

    def __init__(
        self,
        bot_operator: TradingBotOperator | None = None,
        poll_interval: float = 900.0,  # 15 minutes default
        memory: Any | None = None,
        notification_manager: Any | None = None,
        authorizer: Any | None = None,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval, name="testnet_advisory_poll_interval")
        super().__init__(
            name="testnet_advisory_operator",
            description="Monitors live Binance Futures Testnet AI advisory mode, drawdowns, and health.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="testnet_supervision",
            authorizer=authorizer,
            notification_manager=notification_manager,
        )
        self.bot_operator = bot_operator or TradingBotOperator()
        self.memory = memory
        self.poll_interval = poll_interval
        self.last_mode: str | None = None
        self.alerted_events: set[str] = set()

    def check_state(self) -> dict[str, Any]:
        """Performs a synchronous inspection of live testnet advisory metrics and safety limits."""
        alerts: list[dict[str, Any]] = []

        try:
            raw = self.bot_operator.get_testnet_advisory_status()
        except Exception as e:
            logger.error(f"[TESTNET_OPERATOR] Trading Bot testnet endpoint unreachable: {e}")
            alert = {
                "alert_type": "BOT_UNREACHABLE",
                "severity": "critical",
                "message": f"Testnet bot unreachable: {e}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            alerts.append(alert)
            self._record_alert(alert)
            return {
                "status": "UNREACHABLE",
                "alerts": alerts,
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        if not raw:
            return {
                "status": "INACTIVE",
                "alerts": [],
                "message": "No testnet advisory data available.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        enabled = bool(raw.get("enabled", True))
        mode = str(raw.get("mode", "SHADOW")).upper()
        health = str(raw.get("ai_universe_health", "HEALTHY")).upper()
        drawdown_pct = float(raw.get("drawdown_pct", 0.0))
        max_drawdown_limit = float(raw.get("max_drawdown_limit", 5.0))
        equity = float(raw.get("equity", 10000.0))

        # 1. Condition: Mode transition to APPLY
        if mode == "APPLY" and self.last_mode is not None and self.last_mode != "APPLY":
            event_key = f"MODE_CHANGE:APPLY:{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
            if event_key not in self.alerted_events:
                self.alerted_events.add(event_key)
                alert = {
                    "alert_type": "MODE_CHANGED_APPLY",
                    "severity": "warning",
                    "mode": mode,
                    "message": "⚠️ Testnet advisory mode changed to APPLY. AI-Universe parameter overlays are now live on Binance Futures Testnet orders.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                alerts.append(alert)
                self._record_alert(alert)

        self.last_mode = mode

        # 2. Condition: Testnet Drawdown Threshold Exceeded
        if drawdown_pct >= max_drawdown_limit and enabled:
            event_key = f"DRAWDOWN_CRITICAL:{drawdown_pct:.1f}"
            if event_key not in self.alerted_events:
                self.alerted_events.add(event_key)
                alert = {
                    "alert_type": "DRAWDOWN_CRITICAL",
                    "severity": "critical",
                    "drawdown_pct": drawdown_pct,
                    "max_limit": max_drawdown_limit,
                    "message": f"🚨 Testnet drawdown critical: {drawdown_pct:.2f}% (threshold: {max_drawdown_limit:.2f}%). Emergency parameter rollback recommended.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                alerts.append(alert)
                self._record_alert(alert)

        # 3. Condition: AI-Universe Health Issue
        if health in ("DOWN", "UNREACHABLE", "DEGRADED") and enabled:
            event_key = f"AI_HEALTH:{health}"
            if event_key not in self.alerted_events:
                self.alerted_events.add(event_key)
                alert = {
                    "alert_type": "AI_HEALTH_DOWN",
                    "severity": "warning",
                    "health": health,
                    "message": f"⚠️ AI-Universe health issue affecting testnet advisory: Service reports status '{health}'.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                alerts.append(alert)
                self._record_alert(alert)

        return {
            "status": "ALERT" if alerts else "HEALTHY",
            "enabled": enabled,
            "mode": mode,
            "health": health,
            "equity": equity,
            "drawdown_pct": drawdown_pct,
            "alerts": alerts,
            "alert_count": len(alerts),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _record_alert(self, alert: dict[str, Any]) -> None:
        """Surface alert through notification channels and log to memory with TrustLevel.UNTRUSTED_EXTERNAL."""
        if self.notification_manager:
            try:
                self.notification_manager.post_notification(
                    message=f"[Testnet Advisory Alert] {alert['message']}",
                    category=self.notification_category,
                    severity=alert.get("severity", "info"),
                    metadata={
                        "alert": alert,
                        "precedence": tag_trading_command("testnet_advisory_alert", CommandPrecedence.FRIDAY_COMMANDS),
                    },
                )
            except Exception as e:
                logger.debug(f"[TESTNET_OPERATOR] Failed to post notification: {e}")

        if self.memory:
            try:
                msg_content = f"TESTNET_ADVISORY_ALERT [{alert.get('alert_type', 'EVENT')}]: {alert['message']}"
                msg = Message(
                    role=Role.SYSTEM,
                    content=msg_content,
                    trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                    metadata={
                        "source": "testnet_advisory_operator",
                        "alert_type": alert.get("alert_type"),
                        "severity": alert.get("severity"),
                        "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                    },
                )
                self.memory.add_message(msg)
                logger.info("[TESTNET_OPERATOR] Persisted testnet alert into memory with TrustLevel.UNTRUSTED_EXTERNAL")
            except Exception as e:
                logger.debug(f"[TESTNET_OPERATOR] Failed to record alert to memory: {e}")

    def execute_action(self, event_data: dict[str, Any]) -> Any:
        """Executes testnet advisory inspection cycle."""
        return self.check_state()
