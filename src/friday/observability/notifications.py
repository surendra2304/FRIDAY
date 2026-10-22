"""Notification Queue for FRIDAY Proactive Background Monitoring Proactive System.

Buffers proactive discoveries and alerts so FRIDAY can surface them during conversation turns.
"""

import threading
import uuid
import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
    metadata: dict[str, Any] = field(default_factory=dict)


class NotificationManager:
    """Thread-safe queue managing proactive notifications."""

    def __init__(self, storage_path: str | None = None) -> None:
        self._queue: list[ProactiveNotification] = []
        self._lock = threading.RLock()
        self._storage_path: str | None = None
        if storage_path:
            self.enable_persistence(storage_path)

    def enable_persistence(self, storage_path: str) -> None:
        """Enable a SQLite-backed inbox and migrate any notifications already queued."""
        path = str(storage_path).strip()
        if not path:
            raise ValueError("storage_path must not be empty")
        if path != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._storage_path = str(Path(path).expanduser()) if path != ":memory:" else path
            with self._connect() as connection:
                connection.execute(
                    """CREATE TABLE IF NOT EXISTS notifications (
                        notification_id TEXT PRIMARY KEY, message TEXT NOT NULL,
                        category TEXT NOT NULL, severity TEXT NOT NULL,
                        timestamp TEXT NOT NULL, delivered INTEGER NOT NULL DEFAULT 0,
                        metadata_json TEXT NOT NULL DEFAULT '{}'
                    )"""
                )
                for item in self._queue:
                    self._insert(connection, item)
                connection.commit()
            self._queue.clear()

    def _connect(self) -> sqlite3.Connection:
        if self._storage_path is None:
            raise RuntimeError("notification persistence is not enabled")
        return sqlite3.connect(self._storage_path, timeout=5.0)

    @staticmethod
    def _insert(connection: sqlite3.Connection, item: ProactiveNotification) -> None:
        connection.execute(
            """INSERT OR IGNORE INTO notifications
               (notification_id, message, category, severity, timestamp, delivered, metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (item.notification_id, item.message, item.category, item.severity,
             item.timestamp.isoformat(), int(item.delivered),
             json.dumps(item.metadata, sort_keys=True, default=str)),
        )

    def post_notification(
        self,
        message: str,
        category: str = "monitoring",
        severity: str = "info",
        metadata: dict[str, Any] | None = None,
        notification_id: str | None = None,
    ) -> str:
        """Enqueue a new proactive notification."""
        notif_id = notification_id or str(uuid.uuid4())
        notif = ProactiveNotification(
            notification_id=notif_id,
            message=message,
            category=category,
            severity=severity,
            metadata=metadata or {},
        )
        with self._lock:
            if self._storage_path:
                with self._connect() as connection:
                    self._insert(connection, notif)
                    connection.commit()
            else:
                self._queue.append(notif)
        logger.info(f"Queued proactive notification [{category}/{severity}]: {message}")
        return notif_id

    def fetch_pending_notifications(self, mark_delivered: bool = True) -> list[ProactiveNotification]:
        """Retrieve all unread proactive notifications, optionally marking them delivered."""
        with self._lock:
            if self._storage_path:
                with self._connect() as connection:
                    rows = connection.execute(
                        "SELECT notification_id, message, category, severity, timestamp, delivered, metadata_json "
                        "FROM notifications WHERE delivered = 0 ORDER BY timestamp, notification_id"
                    ).fetchall()
                    pending = [ProactiveNotification(
                        notification_id=row[0], message=row[1], category=row[2], severity=row[3],
                        timestamp=datetime.fromisoformat(row[4]), delivered=bool(row[5]),
                        metadata=json.loads(row[6] or "{}"),
                    ) for row in rows]
                    if mark_delivered and pending:
                        connection.executemany(
                            "UPDATE notifications SET delivered = 1 WHERE notification_id = ?",
                            [(item.notification_id,) for item in pending],
                        )
                        connection.commit()
                    return pending
            pending = [n for n in self._queue if not n.delivered]
            if mark_delivered:
                for n in pending:
                    n.delivered = True
        return pending

    def pop_notifications_summary(self) -> str | None:
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
            if self._storage_path:
                with self._connect() as connection:
                    connection.execute("DELETE FROM notifications")
                    connection.commit()
