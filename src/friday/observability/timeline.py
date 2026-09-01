"""Timeline logger and execution replay for Observability UI Observability."""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("observability.timeline")


@dataclass
class TimelineEvent:
    """Individual lifecycle event or state transition in the task timeline."""

    timestamp: str
    event_type: str  # e.g., 'state_transition', 'cognitive_phase', 'tool_start', 'tool_end', 'agent_routed'
    description: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float | None = None


class ExecutionTimeline:
    """Thread-safe event logger capturing granular task execution transitions."""

    def __init__(self, max_events: int = 200) -> None:
        self.max_events = max(1, max_events)
        self._events: list[TimelineEvent] = []
        self._lock = threading.RLock()
        self._active_status: dict[str, Any] = {
            "cognitive_phase": "IDLE",
            "active_agent": "General",
            "selected_provider": "Default",
            "active_tool": "None",
            "last_latency_ms": 0.0,
        }

    def record_event(
        self,
        event_type: str,
        description: str,
        details: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> TimelineEvent:
        """Record an execution transition in the active timeline."""
        now = datetime.now(timezone.utc).isoformat()
        evt = TimelineEvent(
            timestamp=now,
            event_type=event_type,
            description=description,
            details=details or {},
            duration_ms=duration_ms,
        )
        with self._lock:
            self._events.append(evt)
            if len(self._events) > self.max_events:
                self._events.pop(0)

        logger.debug(f"Timeline event [{event_type}]: {description}")
        return evt

    def update_status(
        self,
        cognitive_phase: str | None = None,
        active_agent: str | None = None,
        selected_provider: str | None = None,
        active_tool: str | None = None,
        last_latency_ms: float | None = None,
    ) -> None:
        """Update live status panel metadata."""
        with self._lock:
            if cognitive_phase is not None:
                self._active_status["cognitive_phase"] = cognitive_phase
            if active_agent is not None:
                self._active_status["active_agent"] = active_agent
            if selected_provider is not None:
                self._active_status["selected_provider"] = selected_provider
            if active_tool is not None:
                self._active_status["active_tool"] = active_tool
            if last_latency_ms is not None:
                self._active_status["last_latency_ms"] = last_latency_ms

    def get_status(self) -> dict[str, Any]:
        """Retrieve copy of current status metadata."""
        with self._lock:
            return dict(self._active_status)

    def get_events(self, limit: int = 50) -> list[TimelineEvent]:
        """Return chronological events up to limit."""
        with self._lock:
            return list(self._events[-limit:])

    def clear(self) -> None:
        """Clear recorded events."""
        with self._lock:
            self._events.clear()

    def format_replay(self, limit: int = 20) -> str:
        """Render a readable chronological replay of past execution steps."""
        events = self.get_events(limit=limit)
        if not events:
            return "No recent execution steps recorded in timeline."

        lines = [
            "==================================================",
            "           TASK EXECUTION TIMELINE REPLAY         ",
            "==================================================",
        ]
        for idx, e in enumerate(events, 1):
            time_part = e.timestamp.split("T")[-1][:8] if "T" in e.timestamp else e.timestamp
            dur_str = f" ({e.duration_ms:.1f}ms)" if e.duration_ms is not None else ""
            lines.append(f"  {idx:02d}. [{time_part}] [{e.event_type.upper()}] {e.description}{dur_str}")
        lines.append("==================================================")
        return "\n".join(lines)


# Global singleton instance for easy cross-module observability
global_timeline = ExecutionTimeline()
