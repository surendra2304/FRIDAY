# src/friday/observability/event.py
"""Observability event model and enums for FRIDAY.

All events are emitted as JSON lines via the ObservabilityManager.
The schema intentionally avoids logging any sensitive data.
"""

import enum
from dataclasses import asdict, dataclass
from typing import Any


class EventType(str, enum.Enum):
    TASK_STARTED = "task_started"
    TASK_PLANNED = "task_planned"
    AUTHORIZATION_REQUESTED = "authorization_requested"
    AUTHORIZATION_GRANTED = "authorization_granted"
    AUTHORIZATION_DENIED = "authorization_denied"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    PROVIDER_SELECTED = "provider_selected"
    PROVIDER_FAILED = "provider_failed"
    CREDENTIAL_ROTATED = "credential_rotated"
    VISION_STARTED = "vision_started"
    VISION_COMPLETED = "vision_completed"
    VOICE_STARTED = "voice_started"
    VOICE_INTERRUPTED = "voice_interrupted"
    VERIFICATION_STARTED = "verification_started"
    VERIFICATION_FAILED = "verification_failed"
    RECOVERY_STARTED = "recovery_started"
    CHECKPOINT_CREATED = "checkpoint_created"
    CHECKPOINT_RESUMED = "checkpoint_resumed"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"


class ErrorCategory(str, enum.Enum):
    USER_ERROR = "USER_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    QUOTA_ERROR = "QUOTA_ERROR"
    TOOL_ERROR = "TOOL_ERROR"
    VISION_ERROR = "VISION_ERROR"
    VOICE_ERROR = "VOICE_ERROR"
    STATE_ERROR = "STATE_ERROR"
    PERSISTENCE_ERROR = "PERSISTENCE_ERROR"
    SECURITY_BLOCK = "SECURITY_BLOCK"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


# Fields that are never allowed in event metadata
SENSITIVE_FIELDS = {
    "api_key",
    "api_key_secret",
    "password",
    "token",
    "private_key",
    "raw_audio",
    "raw_screenshot",
    "clipboard_contents",
}


def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Remove any keys that are considered sensitive and truncate large strings.
    The function is defensive – it never raises.
    """
    sanitized: dict[str, Any] = {}
    for k, v in metadata.items():
        if k.lower() in SENSITIVE_FIELDS:
            continue
        if isinstance(v, str) and len(v) > 256:
            sanitized[k] = v[:256] + "..."
        else:
            sanitized[k] = v
    return sanitized


@dataclass
class Event:
    event_type: EventType
    timestamp: str
    task_id: str | None = None
    execution_id: str | None = None
    component: str | None = None
    state: str | None = None
    duration_ms: int | None = None
    result: dict[str, Any] | None = None
    error_category: ErrorCategory | None = None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["event_type"] = self.event_type.value
        if self.error_category:
            data["error_category"] = self.error_category.value
        return {k: v for k, v in data.items() if v is not None}
