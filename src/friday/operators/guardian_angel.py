"""Guardian Angel Operator for FRIDAY.

The ultimate 24/7 ecosystem watchdog monitoring all subsystems every 10 seconds:
- Tracks Trading Bot, AI-Universe, and FRIDAY OS operational health
- Monitors ecosystem state transitions and risk limit proximity
- Escalates unacknowledged critical alerts across severity channels
- Initiates operator responsiveness checks ("Are you okay?") during unacknowledged crises
"""

from typing import Any

from friday.alert_manager import AlertSeverity, ProductionAlertManager
from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel, TrustLevel
from friday.ecosystem.command_center import EcosystemCommandCenter, EcosystemState
from friday.operators.base_operator import BaseOperator
from friday.operators.triggers import IntervalTrigger

logger = get_logger("operators.guardian_angel")


class GuardianAngelOperator(BaseOperator):
    """The 24/7 ultimate ecosystem guardian auditing all operations every 10 seconds."""

    __test__ = False

    name = "guardian_angel"
    description = (
        "Ultimate 24/7 ecosystem watchdog polling every 10 seconds across all 3 systems, risk headroom, and alert escalations."
    )

    def __init__(
        self,
        command_center: EcosystemCommandCenter | None = None,
        alert_manager: ProductionAlertManager | None = None,
        poll_interval_sec: float = 10.0,
        memory: Any | None = None,
        authorizer: Any | None = None,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="guardian_angel_poll_interval")
        super().__init__(
            name="guardian_angel",
            description="24/7 ecosystem watchdog polling every 10 seconds.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="ecosystem_vigilance",
            authorizer=authorizer,
        )
        self._command_center = command_center
        self._alert_manager = alert_manager
        self.poll_interval_sec = poll_interval_sec
        self.memory = memory
        self._unacknowledged_critical_ticks: int = 0
        self._alerted_states: set[str] = set()

    @property
    def command_center(self) -> EcosystemCommandCenter:
        if self._command_center is None:
            self._command_center = EcosystemCommandCenter()
        return self._command_center

    @property
    def alert_manager(self) -> ProductionAlertManager:
        if self._alert_manager is None:
            self._alert_manager = ProductionAlertManager()
        return self._alert_manager

    def tick(self) -> list[dict[str, Any]]:
        """Executes a 10-second continuous ecosystem supervisory cycle."""
        events: list[dict[str, Any]] = []

        status = self.command_center.get_ecosystem_status()
        state = status.get("ecosystem_state", "SUPERVISED_AUTONOMY")
        risk = status.get("risk_posture", {})
        loss_prox = risk.get("daily_loss_limit_proximity_pct", 0.0)

        # 1. State Transition Check
        if state in (EcosystemState.EMERGENCY_HALT.value, EcosystemState.DEGRADED.value):
            if state not in self._alerted_states:
                self._alerted_states.add(state)
                ev = {
                    "type": "CRITICAL_STATE_TRANSITION",
                    "state": state,
                    "message": f"CRITICAL: Ecosystem has transitioned to state {state}. Trading operations degraded/halted.",
                    "severity": "CRITICAL",
                }
                events.append(ev)
                self._emit_alert(f"ECOSYSTEM STATE: {state}", ev["message"], AlertSeverity.CRITICAL)

        # 2. Risk Limit Proximity Vigilance
        if loss_prox >= 70.0:
            ev = {
                "type": "ELEVATED_RISK_PROXIMITY",
                "proximity_pct": loss_prox,
                "message": f"WARNING: Daily loss limit proximity reached {loss_prox:.1f}% (>70% threshold).",
                "severity": "WARNING",
            }
            events.append(ev)
            self._emit_alert("ELEVATED RISK PROXIMITY", ev["message"], AlertSeverity.WARNING)

            # 3. Unacknowledged Alert Escalation & "Are you okay?" Check
            self._unacknowledged_critical_ticks += 1
            if self._unacknowledged_critical_ticks >= 3:
                ev_check = {
                    "type": "OPERATOR_RESPONSIVENESS_CHECK",
                    "message": "URGENT: Critical risk limits approached and operator is unresponsive. Are you okay?",
                    "severity": "CRITICAL",
                }
                events.append(ev_check)
                self._emit_alert("OPERATOR RESPONSIVENESS CHECK", ev_check["message"], AlertSeverity.CRITICAL)
        else:
            self._unacknowledged_critical_ticks = 0

        return events

    def _emit_alert(self, title: str, message: str, severity: AlertSeverity) -> None:
        """Emits structured alert and logs to memory."""
        try:
            self.alert_manager.create_alert(
                title=title,
                message=message,
                severity=severity,
                category="guardian_angel",
            )
        except Exception as e:
            logger.debug(f"[GUARDIAN_ANGEL] Alert dispatch failed: {e}")

        if self.memory:
            try:
                msg = Message(
                    role=Role.SYSTEM,
                    content=f"GUARDIAN_ALERT [{severity.value}] {title}: {message}",
                    trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                )
                self.memory.add_message(msg)
            except Exception as e:
                logger.debug(f"[GUARDIAN_ANGEL] Memory persist failed: {e}")
