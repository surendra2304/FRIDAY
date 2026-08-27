# -*- coding: utf-8 -*-
"""A/B Test Operator for Autonomous Trading Experiment Monitoring.

Persistent background operator that monitors the Algorithmic Trading Bot's
live A/B experiment status every 15 minutes to track progress, evaluate statistical
significance, and trigger proactive alerts.

Alert Conditions:
1. Statistical significance achieved (p < 0.05 / Bayes Factor >= 3.0).
2. Treatment arm outperforming control by significant threshold (>5.0%).
3. Experiment reaches planned duration / completion.
4. Experiment terminated early due to max drawdown violation.
5. System integrity issues or data divergence detected.
"""

from datetime import datetime, timezone
import os
import threading
from typing import Any, Dict, List, Optional, Set

from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel, TrustLevel
from friday.operators.base_operator import BaseOperator, OperatorExecutionResult, OperatorState
from friday.operators.triggers import IntervalTrigger
from friday.skills.trading_bot_operator import TradingBotOperator
from friday.skills.trading_precedence import CommandPrecedence, tag_trading_command

logger = get_logger("operators.ab_test_operator")


class ABTestOperator(BaseOperator):
    """Monitors live A/B test experiments, performance divergence, and statistical outcomes."""

    def __init__(
        self,
        bot_operator: Optional[TradingBotOperator] = None,
        poll_interval: float = 900.0,  # 15 minutes default
        memory: Optional[Any] = None,
        notification_manager: Optional[Any] = None,
        authorizer: Optional[Any] = None,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval, name="ab_test_poll_interval")
        super().__init__(
            name="ab_test_operator",
            description="Monitors live trading A/B experiment status, statistical significance, and drawdown bounds.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="ab_test_supervision",
            authorizer=authorizer,
            notification_manager=notification_manager,
        )
        self.bot_operator = bot_operator or TradingBotOperator()
        self.memory = memory
        self.poll_interval = poll_interval
        self.alerted_events: Set[str] = set()

    def check_state(self) -> Dict[str, Any]:
        """Perform a synchronous inspection of live A/B experiment status and statistical thresholds."""
        alerts: List[Dict[str, Any]] = []

        try:
            raw = self.bot_operator.get_ab_status()
        except Exception as e:
            logger.error(f"[AB_OPERATOR] Trading Bot A/B endpoint unreachable: {e}")
            alert = {
                "alert_type": "BOT_UNREACHABLE",
                "severity": "critical",
                "message": f"Trading Bot A/B monitoring endpoint unreachable: {e}",
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

        if not raw or raw.get("status") in ("NO_ACTIVE_TEST", "INACTIVE"):
            return {
                "status": "INACTIVE",
                "alerts": [],
                "message": "No active A/B test running.",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        status = str(raw.get("status", "RUNNING")).upper()
        test_name = str(raw.get("test_name", "AI_Universe_AB_Test"))
        control = raw.get("control_arm", raw.get("control", {}))
        treatment = raw.get("treatment_arm", raw.get("treatment", {}))
        stats = raw.get("statistics", raw.get("stat_sig", {}))

        c_ret = float(control.get("total_return_pct", control.get("return_pct", 0.0)))
        t_ret = float(treatment.get("total_return_pct", treatment.get("return_pct", 0.0)))
        c_dd = float(control.get("max_drawdown_pct", control.get("drawdown_pct", 0.0)))
        t_dd = float(treatment.get("max_drawdown_pct", treatment.get("drawdown_pct", 0.0)))
        delta_ret = t_ret - c_ret

        p_value = float(stats.get("p_value", 0.10))
        stat_sig = bool(stats.get("stat_sig_achieved", p_value < 0.05))

        # 1. Condition: Drawdown Termination Alert
        if status in ("DRAWDOWN_TERMINATED", "TERMINATED_EARLY", "SAFETY_STOP"):
            event_key = f"{test_name}:DRAWDOWN_TERMINATED"
            if event_key not in self.alerted_events:
                self.alerted_events.add(event_key)
                culprit = "Treatment" if t_dd > c_dd else "Control"
                alert = {
                    "alert_type": "DRAWDOWN_TERMINATED",
                    "severity": "critical",
                    "test_name": test_name,
                    "message": (
                        f"⚠️ A/B Test '{test_name}' terminated early due to drawdown. "
                        f"{culprit} arm exceeded risk limit (Control DD: {c_dd:.2f}%, Treatment DD: {t_dd:.2f}%)."
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                alerts.append(alert)
                self._record_alert(alert)

        # 2. Condition: Statistical Significance Achieved
        if stat_sig:
            event_key = f"{test_name}:STAT_SIG_ACHIEVED"
            if event_key not in self.alerted_events:
                self.alerted_events.add(event_key)
                lead = "Treatment" if delta_ret > 0 else "Control"
                alert = {
                    "alert_type": "STAT_SIG_ACHIEVED",
                    "severity": "info",
                    "test_name": test_name,
                    "p_value": p_value,
                    "message": (
                        f"📊 A/B test '{test_name}' complete with significant results (p={p_value:.3f}). "
                        f"{lead} arm is outperforming with {abs(delta_ret):+.2f}% delta."
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                alerts.append(alert)
                self._record_alert(alert)

        # 3. Condition: Treatment Outperforming Control by > 5%
        if delta_ret >= 5.0 and stat_sig:
            event_key = f"{test_name}:TREATMENT_OUTPERFORM_5PCT"
            if event_key not in self.alerted_events:
                self.alerted_events.add(event_key)
                alert = {
                    "alert_type": "TREATMENT_OUTPERFORMING",
                    "severity": "info",
                    "test_name": test_name,
                    "delta_return_pct": delta_ret,
                    "message": f"🚀 Treatment arm outperforming control by {delta_ret:.2f}% (Treatment: {t_ret:+.2f}%, Control: {c_ret:+.2f}%).",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                alerts.append(alert)
                self._record_alert(alert)

        # 4. Condition: Test Completed (100% progress / duration)
        if status == "COMPLETED":
            event_key = f"{test_name}:EXPERIMENT_COMPLETED"
            if event_key not in self.alerted_events:
                self.alerted_events.add(event_key)
                alert = {
                    "alert_type": "EXPERIMENT_COMPLETED",
                    "severity": "info",
                    "test_name": test_name,
                    "message": f"🏁 A/B experiment '{test_name}' reached planned duration and is now complete.",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                alerts.append(alert)
                self._record_alert(alert)

        # 5. Condition: System Integrity Error
        if raw.get("integrity_error") or raw.get("divergence_error"):
            event_key = f"{test_name}:INTEGRITY_ERROR"
            if event_key not in self.alerted_events:
                self.alerted_events.add(event_key)
                err_text = str(raw.get("integrity_error") or raw.get("divergence_error"))
                alert = {
                    "alert_type": "INTEGRITY_ERROR",
                    "severity": "warning",
                    "test_name": test_name,
                    "message": f"⚠️ A/B Test system integrity anomaly detected: {err_text}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                alerts.append(alert)
                self._record_alert(alert)

        return {
            "status": "ALERT" if alerts else "HEALTHY",
            "test_name": test_name,
            "test_status": status,
            "alerts": alerts,
            "alert_count": len(alerts),
            "delta_return_pct": delta_ret,
            "p_value": p_value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _record_alert(self, alert: Dict[str, Any]) -> None:
        """Surface alert through notification channel and persist to memory tagged UNTRUSTED_EXTERNAL."""
        if self.notification_manager:
            try:
                self.notification_manager.post_notification(
                    message=f"[A/B Test Alert] {alert['message']}",
                    category=self.notification_category,
                    severity=alert.get("severity", "info"),
                    metadata={
                        "alert": alert,
                        "precedence": tag_trading_command("ab_test_alert", CommandPrecedence.FRIDAY_COMMANDS),
                    },
                )
            except Exception as e:
                logger.debug(f"[AB_OPERATOR] Failed to post notification: {e}")

        if self.memory:
            try:
                msg_content = f"AB_TEST_SUPERVISOR_ALERT [{alert.get('alert_type', 'EVENT')}]: {alert['message']}"
                msg = Message(
                    role=Role.SYSTEM,
                    content=msg_content,
                    trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                    metadata={
                        "source": "ab_test_operator",
                        "alert_type": alert.get("alert_type"),
                        "severity": alert.get("severity"),
                        "test_name": alert.get("test_name"),
                        "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                    },
                )
                self.memory.add_message(msg)
                logger.info(f"[AB_OPERATOR] Persisted A/B alert into memory with TrustLevel.UNTRUSTED_EXTERNAL")
            except Exception as e:
                logger.debug(f"[AB_OPERATOR] Failed to record alert to memory: {e}")

    def execute_action(self, event_data: Dict[str, Any]) -> Any:
        """Executes A/B test inspection cycle."""
        return self.check_state()
