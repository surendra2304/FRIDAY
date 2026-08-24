# -*- coding: utf-8 -*-
"""Notification Queue for FRIDAY Phase 17 Proactive System.

Buffers proactive discoveries and alerts so FRIDAY can surface them during conversation turns.
"""

import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("observability.notifications")


@dataclass
class ProactiveNotification:
    """Represents a proactive insight or event notification."""

    notification_id: str
    message: str
    category: str = "monitoring"  # e.g., 'monitoring', 'health', 'workflow', 'system'
    severity: str = "info"       # 'info', 'warning', 'critical'
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    delivered: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class NotificationManager:
    """Thread-safe queue managing proactive notifications."""

    def __init__(self) -> None:
        self._queue: List[ProactiveNotification] = []
        self._lock = threading.RLock()

    def post_notification(
        self,
        message: str,
        category: str = "monitoring",
        severity: str = "info",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Enqueue a new proactive notification."""
        notif_id = str(uuid.uuid4())
        notif = ProactiveNotification(
            notification_id=notif_id,
            message=message,
            category=category,
            severity=severity,
            metadata=metadata or {},
        )
        with self._lock:
            self._queue.append(notif)
        logger.info(f"Queued proactive notification [{category}/{severity}]: {message}")
        return notif_id

    def fetch_pending_notifications(self, mark_delivered: bool = True) -> List[ProactiveNotification]:
        """Retrieve all unread proactive notifications, optionally marking them delivered."""
        with self._lock:
            pending = [n for n in self._queue if not n.delivered]
            if mark_delivered:
                for n in pending:
                    n.delivered = True
        return pending

    def pop_notifications_summary(self) -> Optional[str]:
        """Fetch unread notifications and format as conversational lead-in."""
        pending = self.fetch_pending_notifications(mark_delivered=True)
        if not pending:
            return None

        if len(pending) == 1:
            return f"I noticed that {pending[0].message} while you were away."

        bullet_lines = [f"- {p.message}" for p in pending]
        return "I noticed the following while you were away:\n" + "\n".join(bullet_lines)

    def clear(self) -> None:
        """Clear all stored notifications."""
        with self._lock:
            self._queue.clear()
