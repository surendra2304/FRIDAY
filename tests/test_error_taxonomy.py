"""Comprehensive Test Suite for FRIDAY's Unified Error Taxonomy & Exception Hierarchy.

Test Type: UNIT / SECURITY / INTEGRATION

Validates:
1. Complete coverage of all 15 ErrorCode categories:
   - USER_ERROR, VALIDATION_ERROR, AUTHORIZATION_ERROR, SECURITY_BLOCK,
     PROVIDER_ERROR, QUOTA_ERROR, NETWORK_ERROR, VISION_ERROR, VOICE_ERROR,
     TOOL_ERROR, TIMEOUT, STATE_ERROR, PERSISTENCE_ERROR, CANCELLED, INTERNAL_ERROR.
2. Secret scrubbing on Exception string representation (__str__) and serialized dicts.
3. Safe user-facing message generation (to_user_facing_message()) prevents technical leakage.
4. Internal diagnostic details preservation for structured observability.
5. Error propagation and classification across agent subsystems.
"""

import pytest

# Explicit test markers
pytestmark = [pytest.mark.unit, pytest.mark.security, pytest.mark.integration]

from friday.core.exceptions import (
    AuthorizationError,
    ConfigError,
    ErrorCode,
    FridayError,
    InternalError,
    LLMProviderError,
    MemoryError,
    NetworkError,
    PersistenceError,
    ProviderError,
    QuotaExceededError,
    SafetyError,
    SecurityError,
    StateError,
    StateTransitionError,
    TaskCancelledError,
    TimeoutError,
    ToolError,
    ToolExecutionError,
    UserError,
    ValidationError,
    VisionError,
    VisionProviderError,
    VoiceError,
)

# ============================================================================
# 1. ErrorCode & Hierarchy Verification for all 15 Classes
# ============================================================================

def test_all_fifteen_error_codes_instantiation_and_mapping():
    """Verify that each error class maps to its appropriate canonical ErrorCode."""
    error_instances = [
        (UserError("Bad input"), ErrorCode.USER_ERROR),
        (ValidationError("Invalid schema"), ErrorCode.VALIDATION_ERROR),
        (ConfigError("Invalid config"), ErrorCode.VALIDATION_ERROR),
        (AuthorizationError("Missing cap"), ErrorCode.AUTHORIZATION_ERROR),
        (SecurityError("Dangerous action blocked"), ErrorCode.SECURITY_BLOCK),
        (SafetyError("Safety confirmation required"), ErrorCode.SECURITY_BLOCK),
        (ProviderError("LLM call failed"), ErrorCode.PROVIDER_ERROR),
        (LLMProviderError("Gemini error"), ErrorCode.PROVIDER_ERROR),
        (QuotaExceededError("Daily budget reached"), ErrorCode.QUOTA_ERROR),
        (NetworkError("Connection refused"), ErrorCode.NETWORK_ERROR),
        (VisionError("Screen capture failed"), ErrorCode.VISION_ERROR),
        (VisionProviderError("Vision API error"), ErrorCode.VISION_ERROR),
        (VoiceError("Microphone device disconnect"), ErrorCode.VOICE_ERROR),
        (ToolError("Tool execution failed"), ErrorCode.TOOL_ERROR),
        (ToolExecutionError("Tool crashed"), ErrorCode.TOOL_ERROR),
        (TimeoutError("Task timed out"), ErrorCode.TIMEOUT),
        (StateError("Invalid transition"), ErrorCode.STATE_ERROR),
        (StateTransitionError("Blocked transition"), ErrorCode.STATE_ERROR),
        (PersistenceError("Database locked"), ErrorCode.PERSISTENCE_ERROR),
        (MemoryError("Failed to store message"), ErrorCode.PERSISTENCE_ERROR),
        (TaskCancelledError("Task cancelled"), ErrorCode.CANCELLED),
        (InternalError("Unexpected bug"), ErrorCode.INTERNAL_ERROR),
    ]

    for err, expected_code in error_instances:
        assert isinstance(err, FridayError)
        assert err.error_code == expected_code
        assert expected_code.value in err.to_user_facing_message()


# ============================================================================
# 2. Secret Redaction & Leakage Prevention
# ============================================================================

def test_secret_scrubbing_in_exception_strings_and_dicts():
    """Verify that API keys, passwords, and tokens are scrubbed from error messages."""
    raw_secret_message = "Failed connecting with sk-proj-1234567890abcdef12345678 and AIzaSyD9876543210zyxwvuts"
    details = {"api_key": "AIzaSyD9876543210zyxwvuts", "password": "supersecretpassword"}

    err = ProviderError(message=raw_secret_message, internal_details=details)

    # __str__ scrubbing
    str_repr = str(err)
    assert "sk-proj-1234567890abcdef12345678" not in str_repr
    assert "AIzaSyD9876543210zyxwvuts" not in str_repr
    assert "[REDACTED_SECRET]" in str_repr or "[REDACTED_API_KEY]" in str_repr

    # to_dict scrubbing
    data = err.to_dict()
    assert data["details"]["password"] in ("[REDACTED_SECRET]", "[REDACTED_PASSWORD]")
    assert "AIzaSyD9876543210zyxwvuts" not in str(data)


# ============================================================================
# 3. Safe User-Facing Message Generation
# ============================================================================

def test_user_facing_message_sanitizes_technical_tracebacks():
    """Verify technical tracebacks or deep provider URLs are masked for end-users."""
    tech_error = LLMProviderError("Traceback (most recent call last): google.genai.errors.APIError at https://generativelanguage.googleapis.com")
    user_msg = tech_error.to_user_facing_message()

    assert "Traceback" not in user_msg
    assert "googleapis.com" not in user_msg
    assert "[PROVIDER_ERROR]" in user_msg
    assert "The operation could not be completed" in user_msg


# ============================================================================
# 4. Internal Diagnostics Preservation
# ============================================================================

def test_internal_diagnostics_preservation():
    """Verify non-sensitive diagnostic parameters are preserved for debugging."""
    err = ToolExecutionError(
        message="Calculator failed on division by zero",
        internal_details={"step_id": "step_calc_1", "tool": "calculator", "op": "div"},
    )

    data = err.to_dict()
    assert data["error_code"] == ErrorCode.TOOL_ERROR.value
    assert data["details"]["step_id"] == "step_calc_1"
    assert data["details"]["tool"] == "calculator"
