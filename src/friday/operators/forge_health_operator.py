"""FORGE Health Monitoring Operator for FRIDAY.

Monitors FORGE service availability and AI-Universe backend connectivity every 5 minutes:
- Polls FORGE health endpoint
- Tracks availability uptime history
- Alerts if FORGE becomes unreachable
- Alerts if AI-Universe bridge from FORGE degrades or fails
"""

from typing import Any

from friday.alert_manager import AlertSeverity, ProductionAlertManager
from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel, TrustLevel
from friday.operators.base_operator import BaseOperator
from friday.operators.triggers import IntervalTrigger
from friday.skills.forge_manager import ForgeManagerSkill

logger = get_logger("operators.forge_health")


class ForgeHealthOperator(BaseOperator):
    """5-minute continuous operator monitoring FORGE availability and AI-Universe bridges."""

    __test__ = False

    name = "forge_health"
    description = (
        "Monitors FORGE software engineering engine health and AI-Universe connectivity every 5 minutes."
    )

    def __init__(
        self,
        forge_manager: ForgeManagerSkill | None = None,
        alert_manager: ProductionAlertManager | None = None,
        poll_interval_sec: float = 300.0,
        memory: Any | None = None,
        authorizer: Any | None = None,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="forge_health_poll_interval")
        super().__init__(
            name="forge_health",
            description="Monitors FORGE service health every 5 minutes.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="forge_health",
            authorizer=authorizer,
        )
        self._forge_manager = forge_manager
        self._alert_manager = alert_manager
        self.poll_interval_sec = poll_interval_sec
        self.memory = memory
        self._uptime_checks_total: int = 0
        self._uptime_checks_successful: int = 0
        self._notified_failures: set[str] = set()

    @property
    def forge_manager(self) -> ForgeManagerSkill:
        if self._forge_manager is None:
            self._forge_manager = ForgeManagerSkill()
        return self._forge_manager

    @property
    def alert_manager(self) -> ProductionAlertManager:
        if self._alert_manager is None:
            self._alert_manager = ProductionAlertManager()
        return self._alert_manager

    def tick(self) -> list[dict[str, Any]]:
        """Executes 5-minute health check cycle."""
        events: list[dict[str, Any]] = []
        self._uptime_checks_total += 1

        try:
            health = self.forge_manager.get_forge_health()
            status = health.get("status")
            ai_bridge = health.get("ai_universe_connection")

            if status == "HEALTHY":
                self._uptime_checks_successful += 1
            else:
                ev = {
                    "type": "FORGE_HEALTH_DEGRADED",
                    "status": status,
                    "message": f"FORGE health degraded: Service reported status '{status}'.",
                    "severity": "WARNING",
                }
                events.append(ev)
                self._emit_alert("FORGE HEALTH DEGRADED", ev["message"], AlertSeverity.WARNING)

            if ai_bridge != "CONNECTED" and "AI_BRIDGE_FAIL" not in self._notified_failures:
                self._notified_failures.add("AI_BRIDGE_FAIL")
                ev = {
                    "type": "FORGE_AI_UNIVERSE_BRIDGE_FAILED",
                    "bridge_status": ai_bridge,
                    "message": "WARNING: FORGE connection to AI-Universe is failing. Agent capabilities degraded.",
                    "severity": "WARNING",
                }
                events.append(ev)
                self._emit_alert("FORGE AI-UNIVERSE BRIDGE FAILED", ev["message"], AlertSeverity.WARNING)

        except Exception as e:
            ev = {
                "type": "FORGE_HEALTH_POLL_EXCEPTION",
                "error": str(e),
                "message": f"CRITICAL: Could not reach FORGE health endpoint: {e}",
                "severity": "CRITICAL",
            }
            events.append(ev)
            self._emit_alert("FORGE HEALTH UNREACHABLE", ev["message"], AlertSeverity.CRITICAL)

        return events

    def get_uptime_ratio(self) -> float:
        """Returns uptime percentage."""
        if self._uptime_checks_total == 0:
            return 100.0
        return (self._uptime_checks_successful / self._uptime_checks_total) * 100.0

    def _emit_alert(self, title: str, message: str, severity: AlertSeverity) -> None:
        """Emits alert and logs to memory."""
        try:
            self.alert_manager.create_alert(
                title=title,
                message=message,
                severity=severity,
                category="forge_health",
            )
        except Exception as e:
            logger.debug(f"[FORGE_HEALTH] Alert dispatch failed: {e}")

        if self.memory:
            try:
                msg = Message(
                    role=Role.SYSTEM,
                    content=f"FORGE_HEALTH_ALERT [{severity.value}] {title}: {message}",
                    trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                )
                self.memory.add_message(msg)
            except Exception as e:
                logger.debug(f"[FORGE_HEALTH] Memory log failed: {e}")
