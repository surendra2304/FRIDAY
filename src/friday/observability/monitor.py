# -*- coding: utf-8 -*-
"""Background Monitoring Service for FRIDAY Phase 17 Proactive System.

Executes continuous bounded checks (e.g. web page diffing, file modifications) and alerts NotificationManager.
"""

import hashlib
import threading
from typing import Any, Callable, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.observability.notifications import NotificationManager
from friday.workflows.scheduler import WorkflowScheduler

logger = get_logger("observability.monitor")


class BackgroundMonitorService:
    """Service that coordinates background monitoring checks and emits proactive notifications."""

    def __init__(
        self,
        scheduler: WorkflowScheduler,
        notifications: NotificationManager,
    ) -> None:
        self.scheduler = scheduler
        self.notifications = notifications
        self._monitored_targets: Dict[str, Any] = {}
        self._lock = threading.RLock()

    def monitor_webpage_change(
        self,
        name: str,
        url: str,
        fetch_fn: Callable[[str], str],
        interval_seconds: float = 60.0,
    ) -> str:
        """Schedule a periodic background check on a webpage URL. Notifies when content hash changes."""
        target_id = f"web_{name}"
        last_hash_container = {"hash": None}

        def check_page():
            try:
                content = fetch_fn(url)
                curr_hash = hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
                if last_hash_container["hash"] is None:
                    last_hash_container["hash"] = curr_hash
                    logger.debug(f"Baseline established for '{name}' ({url})")
                elif last_hash_container["hash"] != curr_hash:
                    last_hash_container["hash"] = curr_hash
                    self.notifications.post_notification(
                        message=f"the content at '{url}' ({name}) has changed",
                        category="web_monitor",
                        severity="info",
                        metadata={"url": url, "target": name},
                    )
            except Exception as e:
                logger.error(f"Error checking webpage '{url}': {e}")

        job_id = self.scheduler.register_interval_job(
            name=f"MonitorWeb_{name}",
            interval_seconds=interval_seconds,
            action_fn=check_page,
            safety_level=SafetyLevel.SAFE,
        )
        with self._lock:
            self._monitored_targets[target_id] = job_id
        return job_id

    def monitor_file_modification(
        self,
        name: str,
        file_path: str,
    ) -> str:
        """Schedule a background watch for file modifications."""
        target_id = f"file_{name}"

        def on_modified():
            self.notifications.post_notification(
                message=f"file '{file_path}' ({name}) was modified",
                category="file_monitor",
                severity="info",
                metadata={"file_path": file_path, "target": name},
            )

        job_id = self.scheduler.register_file_watch_job(
            name=f"WatchFile_{name}",
            file_path=file_path,
            action_fn=on_modified,
            safety_level=SafetyLevel.SAFE,
        )
        with self._lock:
            self._monitored_targets[target_id] = job_id
        return job_id
