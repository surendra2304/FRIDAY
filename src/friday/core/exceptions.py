"""Unified Error Taxonomy and Exception Hierarchy for FRIDAY.

Provides structured domain exceptions across all subsystems:
- USER_ERROR: Bad user input, missing arguments, or invalid commands.
- VALIDATION_ERROR: Schema validation failures, malformed parameters, DAG cycle errors.
- AUTHORIZATION_ERROR: Denied or missing tool/capability authorizations.
- SECURITY_BLOCK: Safety gate violations, prohibited actions, prompt injections.
- PROVIDER_ERROR: LLM/AI model request failures or unparseable provider outputs.
- QUOTA_ERROR: Provider rate limits, token exhaustion, or cost budget depletion.
- NETWORK_ERROR: HTTP/WebSocket connection timeouts, DNS failures, transport drops.
- VISION_ERROR: Screen capture failures, invalid image bytes, OCR parsing issues.
- VOICE_ERROR: Microphone/speaker failure, VAD error, audio packet corruption.
- TOOL_ERROR: Tool execution exceptions, invalid tool names, or internal tool crashes.
- TIMEOUT: Step execution, plan duration, or background deadline expirations.
- STATE_ERROR: Invalid state machine transitions or corrupted task states.
- PERSISTENCE_ERROR: SQLite database errors, checkpoint save/load corruption, disk full.
- CANCELLED: Explicit task cancellation via user, timeout, or parent task.
- INTERNAL_ERROR: Unhandled system bugs, unexpected invariants, or system faults.

Invariants:
- Never exposes raw provider exception traces or sensitive secrets to the user.
- Preserves structured diagnostic data internally for forensic telemetry and debugging.
- Sanitizes all log strings and dictionary representations.
"""

from enum import Enum
from typing import Any

from friday.security.scrubber import recursive_sanitize, redact_secrets


class ErrorCode(str, Enum):
    """Canonical error categories across all FRIDAY subsystems."""
    USER_ERROR = "USER_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    AUTHORIZATION_ERROR = "AUTHORIZATION_ERROR"
    SECURITY_BLOCK = "SECURITY_BLOCK"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    QUOTA_ERROR = "QUOTA_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    VISION_ERROR = "VISION_ERROR"
    VOICE_ERROR = "VOICE_ERROR"
    TOOL_ERROR = "TOOL_ERROR"
    TIMEOUT = "TIMEOUT"
    STATE_ERROR = "STATE_ERROR"
    PERSISTENCE_ERROR = "PERSISTENCE_ERROR"
    CANCELLED = "CANCELLED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class FridayError(Exception):
    """Base exception for all domain errors within FRIDAY."""

    default_code: ErrorCode = ErrorCode.INTERNAL_ERROR
    default_user_message: str = "An unexpected internal error occurred."

    def __init__(
        self,
        message: str = "",
        error_code: ErrorCode | None = None,
        internal_details: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        self.raw_message = message or self.default_user_message
        self.error_code = error_code or self.default_code
        self.internal_details = internal_details or {}
        self.cause = cause
        sanitized_msg = redact_secrets(self.raw_message)
        super().__init__(sanitized_msg)

    def to_user_facing_message(self) -> str:
        """Return a safe, user-friendly description without leaking stack traces or keys."""
        safe_msg = redact_secrets(self.raw_message)
        # Avoid exposing raw technical stack messages
        if "traceback" in safe_msg.lower() or "google.genai" in safe_msg or "http" in safe_msg:
            return f"[{self.error_code.value}] The operation could not be completed. Please check task parameters."
        return f"[{self.error_code.value}] {safe_msg}"

    def to_dict(self) -> dict[str, Any]:
        """Convert to sanitized diagnostic dictionary."""
        return {
            "error_code": self.error_code.value,
            "message": redact_secrets(self.raw_message),
            "details": recursive_sanitize(self.internal_details),
            "has_cause": self.cause is not None,
        }

    def __str__(self) -> str:
        return redact_secrets(super().__str__())


# ============================================================================
# Specialized Subsystem Exceptions
# ============================================================================

class UserError(FridayError):
    """Raised when user input is invalid, ambiguous, or lacks required information."""
    default_code = ErrorCode.USER_ERROR
    default_user_message = "Invalid or incomplete user input."


class ValidationError(FridayError):
    """Raised when parameters, schemas, or dependency DAGs fail validation."""
    default_code = ErrorCode.VALIDATION_ERROR
    default_user_message = "Parameter or plan validation failed."


class ConfigError(ValidationError):
    """Raised when configuration validation or loading fails."""


class AuthorizationError(FridayError):
    """Raised when authorization is denied, missing, or capability has expired."""
    default_code = ErrorCode.AUTHORIZATION_ERROR
    default_user_message = "Authorization denied or required capability missing."


class SecurityError(FridayError):
    """Raised when security boundaries or dangerous operations are violated."""
    default_code = ErrorCode.SECURITY_BLOCK
    default_user_message = "Operation blocked by security policy."


class SafetyError(SecurityError):
    """Raised when safety constraints or confirmation requirements are rejected."""


class ProviderError(FridayError):
    """Raised when an external LLM or AI provider call fails."""
    default_code = ErrorCode.PROVIDER_ERROR
    default_user_message = "AI service provider encountered an error."


class LLMProviderError(ProviderError):
    """Raised when an LLM provider request fails or returns an invalid payload."""


class QuotaExceededError(FridayError):
    """Raised when rate limits, token quotas, or daily budgets are exhausted."""
    default_code = ErrorCode.QUOTA_ERROR
    default_user_message = "Service quota or budget limit exceeded."


class NetworkError(FridayError):
    """Raised when network transport, HTTP connection, or socket drops."""
    default_code = ErrorCode.NETWORK_ERROR
    default_user_message = "Network connection failed."


class VisionError(FridayError):
    """Raised when screen capture or multimodal vision processing fails."""
    default_code = ErrorCode.VISION_ERROR
    default_user_message = "Visual screen perception failed."


class VisionProviderError(VisionError):
    """Raised when a multimodal vision provider request fails."""


class VoiceError(FridayError):
    """Raised when microphone, speaker, VAD, or voice streaming fails."""
    default_code = ErrorCode.VOICE_ERROR
    default_user_message = "Voice audio processing failed."


class ToolError(FridayError):
    """Raised when a tool fails to register, validate, or execute."""
    default_code = ErrorCode.TOOL_ERROR
    default_user_message = "Tool execution failed."


class ToolExecutionError(ToolError):
    """Raised when tool execution crashes or returns unexpected error."""


class TimeoutError(FridayError):
    """Raised when step, task, or background execution exceeds allotted time limit."""
    default_code = ErrorCode.TIMEOUT
    default_user_message = "Execution timed out."


class StateError(FridayError):
    """Raised when an invalid state transition or state corruption occurs."""
    default_code = ErrorCode.STATE_ERROR
    default_user_message = "Invalid state transition."


class StateTransitionError(StateError):
    """Raised when a state machine transition is rejected."""


class PersistenceError(FridayError):
    """Raised when SQLite, checkpoint store, or file memory operations fail."""
    default_code = ErrorCode.PERSISTENCE_ERROR
    default_user_message = "Data persistence or checkpointing failed."


class MemoryError(PersistenceError):
    """Raised when memory operations fail."""


class TaskCancelledError(FridayError):
    """Raised when an operation or task is halted due to cancellation."""
    default_code = ErrorCode.CANCELLED
    default_user_message = "Task execution was cancelled."


class InternalError(FridayError):
    """Raised when an unexpected internal system fault occurs."""
    default_code = ErrorCode.INTERNAL_ERROR
    default_user_message = "An internal system error occurred."
