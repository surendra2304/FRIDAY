"""Production Alert Manager for Multi-System Supervision.

Handles alert prioritization (INFO, WARNING, ERROR, CRITICAL), multi-channel routing,
alert aggregation and correlation, escalation policies, acknowledgment lifecycles,
and automatic resolution detection.
"""

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import Message, Role, TrustLevel

logger = get_logger("alert_manager")


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class AlertStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


@dataclass
class Alert:
    """Represents a structured production alert."""
    id: str
    title: str
    message: str
    category: str
    severity: AlertSeverity
    status: AlertStatus = AlertStatus.PENDING
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    acknowledged_at: str | None = None
    acknowledged_by: str | None = None
    resolved_at: str | None = None
    resolution_note: str | None = None
    correlation_key: str | None = None
    escalation_level: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "message": self.message,
            "category": self.category,
            "severity": self.severity.value,
            "status": self.status.value,
            "created_at": self.created_at,
            "acknowledged_at": self.acknowledged_at,
            "acknowledged_by": self.acknowledged_by,
            "resolved_at": self.resolved_at,
            "resolution_note": self.resolution_note,
            "correlation_key": self.correlation_key,
            "escalation_level": self.escalation_level,
            "metadata": self.metadata,
        }


class ProductionAlertManager:
    """Comprehensive alert management engine for FRIDAY production operations."""

    def __init__(
        self,
        memory: Any | None = None,
        notification_manager: Any | None = None,
        escalation_timeout_sec: float = 300.0,  # 5 minutes default
    ) -> None:
        self.memory = memory
        self.notification_manager = notification_manager
        self.escalation_timeout_sec = escalation_timeout_sec
        self._alerts: dict[str, Alert] = {}
        self._correlated_events: dict[str, list[str]] = {}
        self._lock = threading.RLock()
        self._channel_handlers: dict[str, list[Callable[[Alert], None]]] = {
            "email": [],
            "sms": [],
            "voice": [],
            "dashboard": [],
        }

    def register_channel_handler(self, channel: str, handler: Callable[[Alert], None]) -> None:
        """Register a custom callback handler for specific delivery channels."""
        with self._lock:
            if channel in self._channel_handlers:
                self._channel_handlers[channel].append(handler)

    def create_alert(
        self,
        title: str,
        message: str,
        severity: AlertSeverity = AlertSeverity.INFO,
        category: str = "general",
        metadata: dict[str, Any] | None = None,
        correlation_key: str | None = None,
    ) -> Alert:
        """Creates, correlates, routes, and records a new production alert."""
        metadata = metadata or {}
        now_iso = datetime.now(timezone.utc).isoformat()

        # Generate deterministic or unique alert ID
        seed = f"{category}:{title}:{message}:{now_iso}"
        alert_id = "alt_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]

        # Automatic correlation key fallback
        corr_key = correlation_key or f"{category}:{title}"

        with self._lock:
            # Check for duplicate pending alert within correlation group
            existing_ids = self._correlated_events.get(corr_key, [])
            for eid in existing_ids:
                existing = self._alerts.get(eid)
                if existing and existing.status == AlertStatus.PENDING:
                    # Update metadata and timestamp of existing alert rather than spamming duplicates
                    existing.metadata.update(metadata)
                    existing.metadata["occurrence_count"] = existing.metadata.get("occurrence_count", 1) + 1
                    logger.debug(f"[ALERT_MGR] Aggregated duplicate alert {eid} (count={existing.metadata['occurrence_count']})")
                    return existing

            alert = Alert(
                id=alert_id,
                title=title,
                message=message,
                category=category,
                severity=severity,
                created_at=now_iso,
                correlation_key=corr_key,
                metadata=metadata,
            )
            self._alerts[alert_id] = alert
            if corr_key not in self._correlated_events:
                self._correlated_events[corr_key] = []
            self._correlated_events[corr_key].append(alert_id)

        # Route alert to all notification channels
        self._route_alert(alert)
        return alert

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str = "Surendra") -> bool:
        """Marks an alert as acknowledged."""
        with self._lock:
            alert = self._alerts.get(alert_id)
            if not alert:
                logger.warning(f"[ALERT_MGR] Cannot acknowledge unknown alert ID: {alert_id}")
                return False

            alert.status = AlertStatus.ACKNOWLEDGED
            alert.acknowledged_at = datetime.now(timezone.utc).isoformat()
            alert.acknowledged_by = acknowledged_by
            logger.info(f"[ALERT_MGR] Alert {alert_id} acknowledged by {acknowledged_by}")
            return True

    def resolve_alert(self, alert_id: str, resolution_note: str = "Condition cleared") -> bool:
        """Marks an alert as resolved."""
        with self._lock:
            alert = self._alerts.get(alert_id)
            if not alert:
                logger.warning(f"[ALERT_MGR] Cannot resolve unknown alert ID: {alert_id}")
                return False

            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = datetime.now(timezone.utc).isoformat()
            alert.resolution_note = resolution_note
            logger.info(f"[ALERT_MGR] Alert {alert_id} resolved: {resolution_note}")
            return True

    def auto_resolve_category(self, category: str, note: str = "Service healthy") -> int:
        """Automatically resolves all pending alerts in a category upon recovery."""
        count = 0
        with self._lock:
            for alert in self._alerts.values():
                if alert.category == category and alert.status in (AlertStatus.PENDING, AlertStatus.ESCALATED):
                    alert.status = AlertStatus.RESOLVED
                    alert.resolved_at = datetime.now(timezone.utc).isoformat()
                    alert.resolution_note = note
                    count += 1
        if count > 0:
            logger.info(f"[ALERT_MGR] Auto-resolved {count} alerts in category '{category}'")
        return count

    def check_escalations(self) -> list[Alert]:
        """Inspects pending critical/error alerts and escalates unacknowledged ones exceeding timeout."""
        escalated: list[Alert] = []
        now = datetime.now(timezone.utc)

        with self._lock:
            for alert in self._alerts.values():
                if alert.status == AlertStatus.PENDING and alert.severity in (AlertSeverity.CRITICAL, AlertSeverity.ERROR):
                    try:
                        created = datetime.fromisoformat(alert.created_at)
                        elapsed = (now - created).total_seconds()
                        if elapsed >= self.escalation_timeout_sec:
                            alert.status = AlertStatus.ESCALATED
                            alert.escalation_level += 1
                            escalated.append(alert)
                            logger.warning(f"[ALERT_MGR] Escalated alert {alert.id} (Level {alert.escalation_level}) after {elapsed:.0f}s")
                            # Trigger emergency notification escalation
                            self._route_alert(alert, is_escalation=True)
                    except Exception as e:
                        logger.debug(f"[ALERT_MGR] Failed checking escalation for {alert.id}: {e}")

        return escalated

    def get_active_alerts(self, min_severity: AlertSeverity | None = None) -> list[Alert]:
        """Returns all currently active (PENDING or ESCALATED) alerts."""
        severity_order = [AlertSeverity.INFO, AlertSeverity.WARNING, AlertSeverity.ERROR, AlertSeverity.CRITICAL]
        min_idx = severity_order.index(min_severity) if min_severity else 0

        with self._lock:
            active = [
                a for a in self._alerts.values()
                if a.status in (AlertStatus.PENDING, AlertStatus.ESCALATED)
                and severity_order.index(a.severity) >= min_idx
            ]
            # Sort newest and highest severity first
            return sorted(
                active,
                key=lambda x: (severity_order.index(x.severity), x.created_at),
                reverse=True,
            )

    def get_alert_history(self, limit: int = 50) -> list[Alert]:
        """Returns the chronological history of all alerts."""
        with self._lock:
            all_alerts = list(self._alerts.values())
            return sorted(all_alerts, key=lambda x: x.created_at, reverse=True)[:limit]

    def _route_alert(self, alert: Alert, is_escalation: bool = False) -> None:
        """Dispatches alert to notification manager, memory, and channel handlers."""
        prefix = "[ESCALATION] " if is_escalation else ""
        notif_msg = f"{prefix}[{alert.severity.value}] {alert.title}: {alert.message}"

        # 1. Dispatch to NotificationManager
        if self.notification_manager:
            try:
                self.notification_manager.post_notification(
                    message=notif_msg,
                    category=alert.category,
                    severity=alert.severity.value.lower(),
                    metadata=alert.to_dict(),
                )
            except Exception as e:
                logger.debug(f"[ALERT_MGR] Failed posting to notification manager: {e}")

        # 2. Persist to FRIDAY Memory with UNTRUSTED_EXTERNAL
        if self.memory:
            try:
                msg = Message(
                    role=Role.SYSTEM,
                    content=f"PRODUCTION_ALERT [{alert.severity.value}] {alert.title} (ID: {alert.id}): {alert.message}",
                    trust_level=TrustLevel.UNTRUSTED_EXTERNAL,
                    metadata=alert.to_dict(),
                )
                self.memory.add_message(msg)
            except Exception as e:
                logger.debug(f"[ALERT_MGR] Failed persisting alert to memory: {e}")

        # 3. Channel callbacks (email, sms, voice, dashboard)
        for channel, handlers in self._channel_handlers.items():
            for handler in handlers:
                try:
                    handler(alert)
                except Exception as e:
                    logger.debug(f"[ALERT_MGR] Failed executing channel handler for {channel}: {e}")
