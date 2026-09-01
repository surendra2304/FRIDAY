"""Advisory Watchdog Operator for Trading Supervision (Inspired by OpenJarvis).

Persistent background operator that monitors the Algorithmic Trading Bot's AI-Universe
advisory log every 15 minutes to identify:
1. Contested advisories (verdict=REJECT with high confidence > 0.70).
2. AI-Universe downtime while enabled on the bot.
3. Trading Bot REST API unreachability.

Safety & Memory Contract:
- All external AI-Universe recommendations and alerts logged to FRIDAY memory
  MUST be tagged with `TrustLevel.UNTRUSTED_EXTERNAL`.
- Precedence hierarchy: Safety Gates > FRIDAY Commands > AI-Universe Recommendations.
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

logger = get_logger("operators.advisory_watchdog")


class AdvisoryWatchdogOperator(BaseOperator):
    """Monitors trading bot advisory health, contested decisions, and connectivity."""

    def __init__(
        self,
        bot_operator: TradingBotOperator | None = None,
        poll_interval: float = 900.0,  # 15 minutes default
        memory: Any | None = None,
        notification_manager: Any | None = None,
        authorizer: Any | None = None,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval, name="advisory_poll_interval")
        super().__init__(
            name="advisory_watchdog",
            description="Monitors trading bot advisory log, contested decisions, and AI-Universe connectivity.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="trading_supervision",
            authorizer=authorizer,
            notification_manager=notification_manager,
        )
        self.bot_operator = bot_operator or TradingBotOperator()
        self.memory = memory
        self.seen_decision_ids: set[str] = set()
        self.poll_interval = poll_interval

    def check_state(self) -> dict[str, Any]:
        """Perform a synchronous inspection of trading bot advisory and connectivity state."""
        alerts: list[dict[str, Any]] = []
        status_info: dict[str, Any] = {"reachable": True}

        # 1. Connectivity Check to Trading Bot
        try:
            bot_status = self.bot_operator.get_bot_status()
            status_info["bot_status"] = bot_status.status
            status_info["equity"] = bot_status.equity
        except Exception as e:
            logger.error(f"[WATCHDOG] Trading bot unreachable: {e}")
            alert = {
                "alert_type": "BOT_UNREACHABLE",
                "severity": "critical",
                "message": f"Trading Bot is UNREACHABLE at {self.bot_operator.base_url}: {e}",
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

        # 2. Check AI-Universe Health in Advisory State
        try:
            state_data = self.bot_operator.get_advisory_state()
            ai_health = str(state_data.get("ai_universe_health", state_data.get("health", "HEALTHY"))).upper()
            ai_enabled = state_data.get("ai_universe_enabled", state_data.get("enabled", True))
            status_info["ai_universe_health"] = ai_health

            if ai_enabled and ai_health in ("DOWN", "UNREACHABLE", "DEGRADED", "ERROR"):
                alert = {
                    "alert_type": "AI_UNIVERSE_DOWN",
                    "severity": "warning",
                    "message": f"AI-Universe advisory service is reporting status '{ai_health}' while enabled on the Trading Bot.",
                    "state": state_data,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                alerts.append(alert)
                self._record_alert(alert)
        except Exception as e:
            logger.warning(f"[WATCHDOG] Could not verify advisory state: {e}")

        # 3. Check for Contested Advisories (REJECT + confidence > 0.70)
        try:
            recent_data = self.bot_operator.get_advisory_recent(limit=25)
            advisories = recent_data.get("advisories", recent_data.get("recent_advisories", []))
            if isinstance(recent_data, list):
                advisories = recent_data

            for a in advisories:
                d_id = str(a.get("decision_id", a.get("id", a.get("run_id", ""))))
                verdict = str(a.get("verdict", "")).upper()
                confidence = float(a.get("confidence", 0.0))

                if verdict == "REJECT" and confidence > 0.70:
                    if d_id and d_id not in self.seen_decision_ids:
                        self.seen_decision_ids.add(d_id)
                        rec = a.get("recommendation", a.get("summary", "Parameter modification"))
                        reason = a.get("rejection_reason", a.get("reason", "Safety gate bounds exceeded"))
                        alert = {
                            "alert_type": "CONTESTED_ADVISORY",
                            "severity": "warning",
                            "decision_id": d_id,
                            "confidence": confidence,
                            "recommendation": rec,
                            "rejection_reason": reason,
                            "message": (
                                f"Contested Advisory [{d_id}] ({int(confidence * 100)}% confidence): "
                                f"AI recommended '{rec}', but bot safety gates rejected it: '{reason}'"
                            ),
                            "raw": a,
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                        alerts.append(alert)
                        self._record_alert(alert)
        except Exception as e:
            logger.warning(f"[WATCHDOG] Could not scan recent advisories: {e}")

        return {
            "status": "HEALTHY" if not alerts else "ALERT",
            "alerts": alerts,
            "status_info": status_info,
            "alert_count": len(alerts),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _record_alert(self, alert: dict[str, Any]) -> None:
        """Surface alert through notification channel and persist to memory tagged UNTRUSTED_EXTERNAL."""
        # 1. Post to Notification Manager
        if self.notification_manager:
            try:
                self.notification_manager.post_notification(
                    message=f"[Trading Watchdog Alert] {alert['message']}",
                    category=self.notification_category,
                    severity=alert.get("severity", "warning"),
                    metadata={
                        "alert": alert,
                        "precedence": tag_trading_command("advisory_alert", CommandPrecedence.FRIDAY_COMMANDS),
                    },
                )
            except Exception as e:
                logger.debug(f"[WATCHDOG] Failed to post notification: {e}")

        # 2. Log to Memory with TrustLevel.UNTRUSTED_EXTERNAL (for AI-generated advisory content)
        if self.memory:
            try:
                msg_content = (
                    f"TRADING_SUPERVISOR_ALERT [{alert.get('alert_type', 'EVENT')}]: {alert['message']}"
                )
                msg = Message(
                    role=Role.SYSTEM,
                    content=msg_content,
                    trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                    metadata={
                        "source": "advisory_watchdog",
                        "alert_type": alert.get("alert_type"),
                        "severity": alert.get("severity"),
                        "decision_id": alert.get("decision_id"),
                        "trust_level": TrustLevel.UNTRUSTED_EXTERNAL.value,
                    },
                )
                self.memory.add_message(msg)
                logger.info("[WATCHDOG] Persisted alert into memory with TrustLevel.UNTRUSTED_EXTERNAL")
            except Exception as e:
                logger.debug(f"[WATCHDOG] Failed to record alert to memory: {e}")

    def execute_action(self, event_data: dict[str, Any]) -> Any:
        """Executes watchdog check cycle when triggered."""
        return self.check_state()
