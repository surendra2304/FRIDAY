"""Event System and Telemetry for FRIDAY Planning & Execution Architecture.

Provides pub/sub decoupling so the Desktop Overlay UI, Voice session, CLI,
and API servers can observe real-time task graph progress.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("planning.events")


class TaskEventType(str, Enum):
    """Lifecycle event types emitted during task planning and execution."""

    PLAN_CREATED = "PLAN_CREATED"
    TASK_READY = "TASK_READY"
    TASK_STARTED = "TASK_STARTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_RETRYING = "TASK_RETRYING"
    TASK_SKIPPED = "TASK_SKIPPED"
    TASK_CANCELLED = "TASK_CANCELLED"
    EXECUTOR_SELECTED = "EXECUTOR_SELECTED"
    EXECUTION_REPLANNED = "EXECUTION_REPLANNED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"


@dataclass
class TaskProgressEvent:
    """Telemetry event recording a state change in the planning engine."""

    event_type: TaskEventType
    graph_id: str
    task_id: str | None = None
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "graph_id": self.graph_id,
            "task_id": self.task_id,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp.isoformat(),
        }


class TaskEventBus:
    """Thread-safe publish/subscribe event bus for planning and execution telemetry."""

    def __init__(self) -> None:
        self._subscribers: list[Callable[[TaskProgressEvent], None]] = []

    def subscribe(self, callback: Callable[[TaskProgressEvent], None]) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[TaskProgressEvent], None]) -> None:
        if callback in self._subscribers:
            self._subscribers.remove(callback)

    def publish(self, event: TaskProgressEvent) -> None:
        for cb in list(self._subscribers):
            try:
                cb(event)
            except Exception as e:
                logger.debug(f"Event subscriber exception: {e}")


# Global singleton event bus
global_task_event_bus = TaskEventBus()
