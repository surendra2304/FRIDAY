# -*- coding: utf-8 -*-
"""Smart Notification Router for FRIDAY Operating System.

Delivers intelligent notification routing and quiet hours management:
1. Urgency classification:
   - CRITICAL: Immediate voice + push + dashboard + all channels (bypasses quiet hours)
   - HIGH: Voice if user active, push + dashboard otherwise
   - MEDIUM: Batched into next scheduled briefing
   - LOW: Dashboard silently
2. Quiet hours respect: Strict silence (22:00 - 07:00) unless CRITICAL
3. User response learning: Automatically batches weekend MEDIUM alerts until Monday
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import threading
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger

logger = get_logger("core.notification_router")


class UrgencyTier(str, Enum):
    """Urgency classification tiers for ecosystem events."""
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class NotificationItem:
    """Routed notification event."""
    notification_id: str
    tier: UrgencyTier
    title: str
    message: str
    subsystem: str
    target_channels: List[str]  # voice, push, dashboard, briefing_queue
    is_quiet_hours_muted: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class SmartNotificationRouter:
    """Classifies urgency, enforces quiet hours, and learns delivery preferences."""

    def __init__(self, quiet_hours_start: int = 0, quiet_hours_end: int = 8) -> None:
        self.quiet_start = quiet_hours_start
        self.quiet_end = quiet_hours_end
        self.briefing_batch_queue: List[NotificationItem] = []
        self.dispatched_history: List[NotificationItem] = []
        self.weekend_ignore_count = 0
        self._lock = threading.RLock()

    def is_quiet_hours(self, current_time: Optional[datetime] = None) -> bool:
        """Determines if current timestamp falls within quiet hours (22:00 - 07:00)."""
        now = current_time or datetime.now(timezone.utc)
        hour = now.hour
        if self.quiet_start > self.quiet_end:
            # e.g. 22:00 to 07:00
            return hour >= self.quiet_start or hour < self.quiet_end
        return self.quiet_start <= hour < self.quiet_end

    def route_notification(
        self,
        tier: UrgencyTier,
        title: str,
        message: str,
        subsystem: str = "ecosystem",
        is_user_active: bool = True,
        current_time: Optional[datetime] = None,
    ) -> NotificationItem:
        """Routes notification through appropriate channels based on urgency and context."""
        with self._lock:
            now = current_time or datetime.now(timezone.utc)
            in_quiet_hours = self.is_quiet_hours(now)
            is_weekend = now.weekday() in (5, 6)

            channels: List[str] = []
            muted = False
            nid = f"notif_{int(now.timestamp())}_{len(self.dispatched_history)}"

            # 1. Weekend Medium Alert Learning Check
            if is_weekend and tier == UrgencyTier.MEDIUM and self.weekend_ignore_count >= 2:
                # Batch until Monday morning
                channels = ["briefing_queue"]
            elif tier == UrgencyTier.CRITICAL:
                # CRITICAL: Voice + All Channels (Always, even during quiet hours)
                channels = ["voice", "push", "dashboard"]
            elif tier == UrgencyTier.HIGH:
                if in_quiet_hours:
                    channels = ["push", "dashboard"]
                    muted = True
                else:
                    channels = ["voice", "push", "dashboard"] if is_user_active else ["push", "dashboard"]
            elif tier == UrgencyTier.MEDIUM:
                channels = ["briefing_queue", "dashboard"]
            else:  # LOW
                channels = ["dashboard"]

            item = NotificationItem(
                notification_id=nid,
                tier=tier,
                title=title,
                message=message,
                subsystem=subsystem,
                target_channels=channels,
                is_quiet_hours_muted=muted,
            )

            if "briefing_queue" in channels:
                self.briefing_batch_queue.append(item)

            self.dispatched_history.append(item)
            logger.info(f"[NOTIFICATION_ROUTER] Dispatched {tier.value} notification -> {channels} (muted={muted})")
            return item

    def record_user_feedback(self, was_ignored_on_weekend: bool) -> None:
        """Learns when user ignores weekend medium notifications."""
        with self._lock:
            if was_ignored_on_weekend:
                self.weekend_ignore_count += 1

    def drain_briefing_queue(self) -> List[NotificationItem]:
        """Returns and empties the accumulated briefing queue."""
        with self._lock:
            items = list(self.briefing_batch_queue)
            self.briefing_batch_queue.clear()
            return items


# Default singleton instance
smart_notification_router = SmartNotificationRouter()
