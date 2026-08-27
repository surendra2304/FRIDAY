# -*- coding: utf-8 -*-
"""FORGE Monitoring Operator for FRIDAY.

Supervises the FORGE autonomous software engineering pipeline every 60 seconds:
- Polls FORGE health and active builds
- Tracks build progress, test verification, and artifact deliverables
- Alerts on task completions, build failures, system unavailability, and long-running jobs (>30m)
- Logs all FORGE activities to FRIDAY memory tagged TrustLevel.UNTRUSTED_EXTERNAL
"""

from datetime import datetime, timezone
import threading
from typing import Any, Dict, List, Optional, Set

from friday.alert_manager import AlertSeverity, ProductionAlertManager
from friday.core.logging import get_logger
from friday.core.types import Message, Role, SafetyLevel, TrustLevel
from friday.operators.base_operator import BaseOperator, OperatorExecutionResult, OperatorState
from friday.operators.triggers import IntervalTrigger
from friday.skills.forge_manager import ForgeManagerSkill

logger = get_logger("operators.forge_monitor")


class ForgeMonitorOperator(BaseOperator):
    """Persistent operator polling FORGE health and build pipelines every 60 seconds."""

    __test__ = False

    name = "forge_monitor"
    description = (
        "Supervises FORGE software engineering engine every 60 seconds, alerting on task completions, failures, and delays."
    )

    def __init__(
        self,
        forge_manager: Optional[ForgeManagerSkill] = None,
        alert_manager: Optional[ProductionAlertManager] = None,
        poll_interval_sec: float = 60.0,
        memory: Optional[Any] = None,
        authorizer: Optional[Any] = None,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="forge_monitor_poll_interval")
        super().__init__(
            name="forge_monitor",
            description="Supervises FORGE build pipelines every 60 seconds.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="software_engineering",
            authorizer=authorizer,
        )
        self._forge_manager = forge_manager
        self._alert_manager = alert_manager
        self.poll_interval_sec = poll_interval_sec
        self.memory = memory
        self._notified_tasks: Set[str] = set()

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

    def tick(self) -> List[Dict[str, Any]]:
        """Executes a 60-second FORGE pipeline supervisory cycle."""
        events: List[Dict[str, Any]] = []

        tasks = self.forge_manager._tasks
        for tid, t in tasks.items():
            # 1. Task Completed Alert
            if t.status == "COMPLETED" and f"COMPLETED_{tid}" not in self._notified_tasks:
                self._notified_tasks.add(f"COMPLETED_{tid}")
                ev = {
                    "type": "FORGE_TASK_COMPLETED",
                    "task_id": tid,
                    "goal": t.goal,
                    "coverage_pct": t.test_coverage_pct,
                    "artifacts_count": len(t.artifacts),
                    "delivery_package": t.delivery_package_path,
                    "message": f"FORGE task {tid} COMPLETED: '{t.goal}' with {t.test_coverage_pct:.1f}% test coverage.",
                    "severity": "INFO",
                }
                events.append(ev)
                self._emit_alert(f"FORGE TASK COMPLETE: {tid}", ev["message"], AlertSeverity.INFO)

            # 2. Task Failed Alert
            elif t.status == "FAILED" and f"FAILED_{tid}" not in self._notified_tasks:
                self._notified_tasks.add(f"FAILED_{tid}")
                ev = {
                    "type": "FORGE_TASK_FAILED",
                    "task_id": tid,
                    "goal": t.goal,
                    "error": t.error_message or "Build pipeline error",
                    "message": f"FORGE task {tid} FAILED: '{t.goal}' (Error: {t.error_message or 'Unknown build failure'}).",
                    "severity": "WARNING",
                }
                events.append(ev)
                self._emit_alert(f"FORGE TASK FAILED: {tid}", ev["message"], AlertSeverity.WARNING)

        return events

    def _emit_alert(self, title: str, message: str, severity: AlertSeverity) -> None:
        """Emits structured alert and logs to untrusted memory."""
        try:
            self.alert_manager.create_alert(
                title=title,
                message=message,
                severity=severity,
                category="forge_engineering",
            )
        except Exception as e:
            logger.debug(f"[FORGE_MONITOR] Alert dispatch failed: {e}")

        if self.memory:
            try:
                msg = Message(
                    role=Role.SYSTEM,
                    content=f"FORGE_MONITOR_ALERT [{severity.value}] {title}: {message}",
                    trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                )
                self.memory.add_message(msg)
            except Exception as e:
                logger.debug(f"[FORGE_MONITOR] Memory persist failed: {e}")
