# src/friday/observability/manager.py
"""Observability manager – emits structured events to a JSONL log file.
The manager is a singleton accessed via `get_observability_manager()`.
All event fields are sanitized to avoid leaking secrets.
"""

import json
import os
import threading
from datetime import datetime
from typing import Optional, Dict, Any

from friday.core.config import get_settings
from .event import Event, EventType, ErrorCategory, sanitize_metadata

_lock = threading.Lock()
_manager_instance: Optional["ObservabilityManager"] = None


def get_observability_manager() -> "ObservabilityManager":
    """Return a singleton ObservabilityManager instance.
    The instance is lazily created on first call.
    """
    global _manager_instance
    if _manager_instance is None:
        with _lock:
            if _manager_instance is None:
                _manager_instance = ObservabilityManager()
    return _manager_instance


class ObservabilityManager:
    """Core manager for writing observability events.

    Events are written as one JSON object per line to the configured log file.
    The manager also ensures the log directory exists and that writes are thread‑safe.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self.log_path: str = getattr(settings, "observability_log_file", "logs/observability.jsonl")
        # Ensure directory exists
        log_dir = os.path.dirname(self.log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        # Open file in append mode; keep handle for performance
        self._file_handle = open(self.log_path, "a", encoding="utf-8")
        self._write_lock = threading.Lock()

    def emit(self, event: Event) -> None:
        """Emit a single event.
        The event is converted to JSON, sanitized, and appended to the log file.
        """
        # Populate timestamp if not provided
        if not event.timestamp:
            event.timestamp = datetime.utcnow().isoformat() + "Z"
        # Sanitize result payload if present
        if event.result:
            event.result = sanitize_metadata(event.result)
        # Convert to JSON dict
        payload = event.to_json()
        line = json.dumps(payload, ensure_ascii=False)
        with self._write_lock:
            self._file_handle.write(line + "\n")
            self._file_handle.flush()

    def close(self) -> None:
        """Close underlying file handle – called during shutdown."""
        with self._write_lock:
            self._file_handle.close()
