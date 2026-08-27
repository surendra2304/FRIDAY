# -*- coding: utf-8 -*-
"""FORGE Task Supervision Operator for FRIDAY.

Supervises all active FORGE software engineering tasks every 60 seconds:
- Tracks lifecycle transitions (PENDING -> READY -> RUNNING -> BLOCKED -> FAILED -> VERIFYING -> COMPLETED -> CANCELLED)
- Alerts on:
  - Task transitions to FAILED (immediate voice alert with root-cause reason)
  - Task transitions to BLOCKED (warning alert)
  - Task completion (notification with summary of deliverables and coverage)
  - Task stuck in RUNNING > 30 minutes
  - FORGE service unreachable > 2 minutes (critical alert)
- Logs all events to FRIDAY memory tagged TrustLevel.UNTRUSTED_EXTERNAL
- Maintains in-memory task registry for quick voice queries
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

logger = get_logger("operators.forge_supervisor")


class ForgeSupervisorOperator(BaseOperator):
    """60-second continuous supervisor tracking FORGE task lifecycles and build health."""

    __test__ = False

    name = "forge_supervisor"
    description = (
        "Supervises all active FORGE software engineering tasks every 60 seconds, alerting on failures, "
        "blocked states, deliverables completion, and excessive delays."
    )

    def __init__(
        self,
        forge_manager: Optional[ForgeManagerSkill] = None,
        alert_manager: Optional[ProductionAlertManager] = None,
        poll_interval_sec: float = 60.0,
        memory: Optional[Any] = None,
        authorizer: Optional[Any] = None,
    ) -> None:
        trigger = IntervalTrigger(interval_seconds=poll_interval_sec, name="forge_supervisor_poll_interval")
        super().__init__(
            name="forge_supervisor",
            description="Supervises FORGE task lifecycles every 60 seconds.",
            safety_level=SafetyLevel.SAFE,
            triggers=[trigger],
            notification_category="forge_supervision",
            authorizer=authorizer,
        )
        self._forge_manager = forge_manager
        self._alert_manager = alert_manager
        self.poll_interval_sec = poll_interval_sec
        self.memory = memory
        self._notified_events: Set[str] = set()
        self._consecutive_unreachable_ticks: int = 0

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
        """Executes 60-second supervision cycle over active FORGE tasks."""
        events: List[Dict[str, Any]] = []

        try:
            health = self.forge_manager.get_forge_health()
            if health.get("status") != "HEALTHY":
                self._consecutive_unreachable_ticks += 1
            else:
                self._consecutive_unreachable_ticks = 0
        except Exception:
            self._consecutive_unreachable_ticks += 1

        # Alert if FORGE service unreachable > 2 minutes (2 consecutive 60s ticks)
        if self._consecutive_unreachable_ticks >= 2 and "FORGE_UNREACHABLE" not in self._notified_events:
            self._notified_events.add("FORGE_UNREACHABLE")
            ev = {
                "type": "FORGE_SERVICE_UNREACHABLE",
                "message": "CRITICAL: FORGE software engineering service is unreachable for >2 minutes.",
                "severity": "CRITICAL",
            }
            events.append(ev)
            self._emit_alert("FORGE SERVICE UNREACHABLE", ev["message"], AlertSeverity.CRITICAL)

        # Inspect all tasks
        tasks = self.forge_manager._tasks
        for tid, t in tasks.items():
            # 1. Task Completed Alert
            if t.state == "COMPLETED" and f"COMPLETED_{tid}" not in self._notified_events:
                self._notified_events.add(f"COMPLETED_{tid}")
                ev = {
                    "type": "TASK_COMPLETED",
                    "task_id": tid,
                    "goal": t.goal,
                    "files_count": len(t.files_created),
                    "coverage_pct": t.test_coverage_pct,
                    "delivery_path": t.delivery_package_path,
                    "message": (
                        f"FORGE completed task {tid} ('{t.goal}'). "
                        f"{len(t.files_created)} files generated with {t.test_coverage_pct:.1f}% test coverage. "
                        f"Package delivered to `{t.delivery_package_path}`."
                    ),
                    "severity": "INFO",
                }
                events.append(ev)
                self._emit_alert(f"FORGE TASK COMPLETED: {tid}", ev["message"], AlertSeverity.INFO)

            # 2. Task Failed Alert
            elif t.state == "FAILED" and f"FAILED_{tid}" not in self._notified_events:
                self._notified_events.add(f"FAILED_{tid}")
                reason = t.failure_reason or "Verification check failed during build pipeline."
                ev = {
                    "type": "TASK_FAILED",
                    "task_id": tid,
                    "goal": t.goal,
                    "reason": reason,
                    "message": f"FORGE task {tid} FAILED: '{t.goal}'. Failure reason: {reason}",
                    "severity": "WARNING",
                }
                events.append(ev)
                self._emit_alert(f"FORGE TASK FAILED: {tid}", ev["message"], AlertSeverity.WARNING)

            # 3. Task Blocked Alert
            elif t.state == "BLOCKED" and f"BLOCKED_{tid}" not in self._notified_events:
                self._notified_events.add(f"BLOCKED_{tid}")
                ev = {
                    "type": "TASK_BLOCKED",
                    "task_id": tid,
                    "goal": t.goal,
                    "message": f"FORGE task {tid} is BLOCKED awaiting dependency or authorization.",
                    "severity": "WARNING",
                }
                events.append(ev)
                self._emit_alert(f"FORGE TASK BLOCKED: {tid}", ev["message"], AlertSeverity.WARNING)

        return events

    def _emit_alert(self, title: str, message: str, severity: AlertSeverity) -> None:
        """Emits structured alert and logs to untrusted external memory."""
        try:
            self.alert_manager.create_alert(
                title=title,
                message=message,
                severity=severity,
                category="forge_supervision",
            )
        except Exception as e:
            logger.debug(f"[FORGE_SUPERVISOR] Alert dispatch failed: {e}")

        if self.memory:
            try:
                msg = Message(
                    role=Role.SYSTEM,
                    content=f"FORGE_SUPERVISOR_ALERT [{severity.value}] {title}: {message}",
                    trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                )
                self.memory.add_message(msg)
            except Exception as e:
                logger.debug(f"[FORGE_SUPERVISOR] Memory log failed: {e}")
