"""Reasoning State Machine and Lifecycle Management for FRIDAY Tasks and Requests.

Defines the explicit task states and validated state transitions:
    NOT_STARTED -> UNDERSTANDING -> PLANNING -> EXECUTING -> VERIFYING -> COMPLETED
    [Any active state] -> FAILED

Completely provider-independent and zero-trust safe.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("agent.state")


class TaskState(str, Enum):
    """Enumeration of explicit task and request reasoning states."""
    NOT_STARTED = "NOT_STARTED"
    UNDERSTANDING = "UNDERSTANDING"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    PAUSED = "PAUSED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


# Valid deterministic transitions from each state
VALID_TRANSITIONS: dict[TaskState, list[TaskState]] = {
    TaskState.NOT_STARTED: [TaskState.UNDERSTANDING, TaskState.PLANNING, TaskState.CANCELLED, TaskState.FAILED],
    TaskState.UNDERSTANDING: [TaskState.PLANNING, TaskState.CANCELLED, TaskState.FAILED],
    TaskState.PLANNING: [TaskState.PLANNING, TaskState.EXECUTING, TaskState.PAUSED, TaskState.VERIFYING, TaskState.CANCELLED, TaskState.FAILED],
    TaskState.EXECUTING: [TaskState.PLANNING, TaskState.EXECUTING, TaskState.PAUSED, TaskState.VERIFYING, TaskState.CANCELLED, TaskState.FAILED],
    TaskState.PAUSED: [TaskState.EXECUTING, TaskState.CANCELLED, TaskState.FAILED],
    TaskState.VERIFYING: [TaskState.COMPLETED, TaskState.PLANNING, TaskState.EXECUTING, TaskState.CANCELLED, TaskState.FAILED],
    TaskState.COMPLETED: [],  # Terminal state
    TaskState.CANCELLED: [],  # Terminal state
    TaskState.FAILED: [],     # Terminal state
}


class InvalidStateTransitionError(ValueError):
    """Raised when an illegal state transition is attempted."""


@dataclass
class StateTransitionRecord:
    """Audit record for a single state transition."""
    from_state: TaskState
    to_state: TaskState
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        from friday.security.scrubber import recursive_sanitize, redact_secrets
        return recursive_sanitize({
            "from_state": self.from_state.value,
            "to_state": self.to_state.value,
            "timestamp": self.timestamp.isoformat(),
            "reason": redact_secrets(self.reason) if self.reason else None,
        })


class ReasoningStateMachine:
    """Manages explicit state progression and audit history for a single task or turn."""

    def __init__(
        self,
        task_id: str | None = None,
        on_transition: Callable[[TaskState, TaskState, str | None], None] | None = None,
        initial_state: TaskState = TaskState.NOT_STARTED,
    ) -> None:
        self.task_id: str = task_id or str(uuid.uuid4())
        self._current_state: TaskState = initial_state
        self._history: list[StateTransitionRecord] = []
        self._on_transition = on_transition
        self._failure_reason: str | None = None
        self._failure_metadata: dict[str, Any] = {}

    @property
    def current_state(self) -> TaskState:
        """Return the current state."""
        return self._current_state

    @property
    def is_terminal(self) -> bool:
        """Return True if the state machine is in a terminal state."""
        return self._current_state in (TaskState.COMPLETED, TaskState.CANCELLED, TaskState.FAILED)

    @property
    def can_execute_tools(self) -> bool:
        """Return True only if the state machine is in EXECUTING state."""
        return self._current_state == TaskState.EXECUTING

    @property
    def history(self) -> list[StateTransitionRecord]:
        """Return the transition audit trail."""
        return list(self._history)

    @property
    def failure_reason(self) -> str | None:
        """Return the safe failure reason if failed."""
        return self._failure_reason

    @property
    def failure_metadata(self) -> dict[str, Any]:
        """Return failure metadata."""
        return dict(self._failure_metadata)

    def transition_to(self, new_state: TaskState, reason: str | None = None) -> TaskState:
        """Validate and execute a state transition."""
        from friday.security.scrubber import redact_secrets

        allowed = VALID_TRANSITIONS.get(self._current_state, [])
        if new_state != self._current_state and new_state not in allowed:
            err_msg = (
                f"Invalid state transition from {self._current_state.value} to {new_state.value}. "
                f"Allowed target states: {[s.value for s in allowed]}"
            )
            logger.error(err_msg)
            raise InvalidStateTransitionError(err_msg)

        old_state = self._current_state
        self._current_state = new_state
        safe_reason = redact_secrets(reason) if reason else None
        record = StateTransitionRecord(from_state=old_state, to_state=new_state, reason=safe_reason)
        self._history.append(record)
        logger.debug(f"Task '{self.task_id}': {old_state.value} -> {new_state.value} (reason: {safe_reason})")

        if self._on_transition:
            try:
                self._on_transition(old_state, new_state, safe_reason)
            except Exception as e:
                logger.warning(f"Error in on_transition callback: {e}")

        return self._current_state

    def pause(self, reason: str = "Task execution paused") -> TaskState:
        """Transition task to PAUSED state."""
        return self.transition_to(TaskState.PAUSED, reason=reason)

    def resume(self, reason: str = "Resuming task execution") -> TaskState:
        """Transition task from PAUSED back to EXECUTING."""
        return self.transition_to(TaskState.EXECUTING, reason=reason)

    def cancel(self, reason: str = "Task execution cancelled by user") -> TaskState:
        """Transition task to CANCELLED state."""
        return self.transition_to(TaskState.CANCELLED, reason=reason)

    def fail(self, reason: str, metadata: dict[str, Any] | None = None) -> TaskState:
        """Transition task directly to FAILED with sanitized error metadata."""
        from friday.security.scrubber import recursive_sanitize, redact_secrets

        safe_reason = redact_secrets(reason) if reason else None
        self._failure_reason = safe_reason
        self._failure_metadata = recursive_sanitize(metadata or {})
        return self.transition_to(TaskState.FAILED, reason=safe_reason)

    def to_dict(self) -> dict[str, Any]:
        """Serialize current state and audit trail to dictionary with recursive sanitization."""
        from friday.security.scrubber import recursive_sanitize

        raw_dict = {
            "task_id": self.task_id,
            "current_state": self._current_state.value,
            "history": [r.to_dict() for r in self._history],
            "failure_reason": self._failure_reason,
            "failure_metadata": self._failure_metadata,
        }
        return recursive_sanitize(raw_dict)
