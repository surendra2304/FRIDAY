"""Comprehensive tests for Gemini Vision Credential Pool Failover architecture.

Validates:
1. Vision 429 detection.
2. Immediate credential failover without retrying exhausted keys.
3. Fallback 1 selection when Primary is in cooldown.
4. Multi-step failover chain (Primary -> FB1 -> FB2 -> FB3 -> FB4).
5. Cooldown expiration recovery.
6. All-credential exhaustion clean error handling without hanging loops.
7. Vision successful response parsing after fallback.
"""

from unittest import mock

from google.genai import errors as genai_errors

from friday.auth.credential_pool import (
    Credential,
    FailureCategory,
    GeminiCredentialPool,
)
from friday.vision.gemini_vision import GeminiVisionProvider

SAMPLE_PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"


def _create_mock_pool(key_count: int = 5) -> GeminiCredentialPool:
    pool = GeminiCredentialPool()
    pool.credentials = [
        Credential(
            api_key=f"TEST_KEY_{i}",
            project_label="PRIMARY" if i == 0 else f"FALLBACK {i}",
            is_primary=(i == 0),
        )
        for i in range(key_count)
    ]
    pool._session_active_key = None
    return pool


def test_vision_immediate_failover_on_429_quota_exhausted():
    """Verify Vision skips exhausted Primary immediately upon 429 and succeeds on Fallback 1."""
    pool = _create_mock_pool(5)
    provider = GeminiVisionProvider(credential_pool=pool, model="gemini-3.6-flash", backoff_factor=1.0)

    # 429 quota error from Google API
    quota_error = genai_errors.APIError(
        429,
        {"error": {"message": "Resource has been exhausted (quota limit reached).", "status": "RESOURCE_EXHAUSTED"}},
    )

    mock_client = mock.MagicMock()
    mock_success_response = mock.MagicMock()
    mock_success_response.text = "Visual observation: Desktop active window is Chrome."

    # First call on Primary fails with 429, second call on Fallback 1 succeeds
    mock_client.models.generate_content.side_effect = [quota_error, mock_success_response]

    with mock.patch.object(provider, "_get_client", return_value=mock_client), \
         mock.patch("time.sleep") as mock_sleep:

        result = provider.analyze_image(
            image_data=SAMPLE_PNG_HEADER,
            mime_type="image/png",
            prompt="What is on screen?",
        )

        assert result.is_error is False
        assert "Desktop active window is Chrome" in result.text
        assert mock_client.models.generate_content.call_count == 2
        # Zero sleep delay on quota exhaustion
        mock_sleep.assert_not_called()

        # Check pool state
        assert pool.credentials[0].is_healthy(1) is False
        assert pool.credentials[0].last_failure_category == FailureCategory.QUOTA_EXHAUSTED
        assert pool.credentials[1].is_healthy(1) is True


def test_vision_primary_skipped_when_already_in_cooldown():
    """Verify that if Primary is already in quota cooldown, Vision starts on Fallback 1."""
    pool = _create_mock_pool(5)
    # Put Primary in cooldown
    pool.report_failure("TEST_KEY_0", Exception("429 RESOURCE_EXHAUSTED quota exceeded"))
    assert pool.get_active_label() == "FALLBACK 1"

    provider = GeminiVisionProvider(credential_pool=pool, model="gemini-3.6-flash")

    mock_client = mock.MagicMock()
    mock_success_response = mock.MagicMock()
    mock_success_response.text = "Visual observation: Code editor open."
    mock_client.models.generate_content.return_value = mock_success_response

    with mock.patch.object(provider, "_get_client", return_value=mock_client):
        result = provider.analyze_image(
            image_data=SAMPLE_PNG_HEADER,
            mime_type="image/png",
            prompt="Analyze desktop",
        )

        assert result.is_error is False
        assert result.text == "Visual observation: Code editor open."
        # Directly attempted and succeeded on Fallback 1
        assert mock_client.models.generate_content.call_count == 1


def test_vision_failover_chain_primary_to_fallback_3():
    """Verify failure cascade: Primary (429) -> FB1 (429) -> FB2 (429) -> FB3 (Success)."""
    pool = _create_mock_pool(5)
    provider = GeminiVisionProvider(credential_pool=pool, model="gemini-3.6-flash")

    quota_err = genai_errors.APIError(
        429,
        {"error": {"message": "Resource has been exhausted (quota limit reached).", "status": "RESOURCE_EXHAUSTED"}},
    )

    mock_client = mock.MagicMock()
    mock_success_response = mock.MagicMock()
    mock_success_response.text = "Chart uptrend detected."

    mock_client.models.generate_content.side_effect = [
        quota_err,
        quota_err,
        quota_err,
        mock_success_response,
    ]

    with mock.patch.object(provider, "_get_client", return_value=mock_client), \
         mock.patch("time.sleep") as mock_sleep:

        result = provider.analyze_image(
            image_data=SAMPLE_PNG_HEADER,
            mime_type="image/png",
            prompt="Analyze chart",
        )

        assert result.is_error is False
        assert result.text == "Chart uptrend detected."
        assert mock_client.models.generate_content.call_count == 4
        mock_sleep.assert_not_called()

        assert pool.credentials[0].is_healthy(1) is False
        assert pool.credentials[1].is_healthy(1) is False
        assert pool.credentials[2].is_healthy(1) is False
        assert pool.credentials[3].is_healthy(1) is True


def test_vision_all_credentials_exhausted_fails_cleanly():
    """Verify that when all 5 credentials in the pool are exhausted, Vision fails gracefully."""
    pool = _create_mock_pool(5)
    provider = GeminiVisionProvider(credential_pool=pool, model="gemini-3.6-flash")

    quota_err = genai_errors.APIError(
        429,
        {"error": {"message": "Resource has been exhausted (quota limit reached).", "status": "RESOURCE_EXHAUSTED"}},
    )

    mock_client = mock.MagicMock()
    # All 5 return quota exhausted
    mock_client.models.generate_content.side_effect = [quota_err] * 5

    with mock.patch.object(provider, "_get_client", return_value=mock_client), \
         mock.patch("time.sleep") as mock_sleep:

        result = provider.analyze_image(
            image_data=SAMPLE_PNG_HEADER,
            mime_type="image/png",
            prompt="Analyze screen",
        )

        assert result.is_error is True
        assert "RESOURCE_EXHAUSTED" in result.error_message or "quota" in result.error_message.lower()
        # Must make at most 5 attempts (1 per pool credential) without infinite loop
        assert mock_client.models.generate_content.call_count == 5
        mock_sleep.assert_not_called()


def test_vision_cooldown_expiration_recovery():
    """Verify that when a credential's cooldown expires, it becomes available again for Vision."""
    from datetime import datetime, timedelta

    pool = _create_mock_pool(2)
    # Put Primary in past cooldown
    primary = pool.credentials[0]
    primary.failure_count = 1
    primary.last_failed_at = datetime.utcnow() - timedelta(seconds=70)
    primary.cooldown_until = datetime.utcnow() - timedelta(seconds=10)

    assert primary.is_healthy(1) is True
    assert pool.get_active_label() == "PRIMARY"

    provider = GeminiVisionProvider(credential_pool=pool, model="gemini-3.6-flash")
    mock_client = mock.MagicMock()
    mock_response = mock.MagicMock()
    mock_response.text = "Recovered on primary."
    mock_client.models.generate_content.return_value = mock_response

    with mock.patch.object(provider, "_get_client", return_value=mock_client):
        result = provider.analyze_image(
            image_data=SAMPLE_PNG_HEADER,
            mime_type="image/png",
            prompt="Check recovery",
        )

        assert result.is_error is False
        assert result.text == "Recovered on primary."
        assert primary.failure_count == 0
        assert primary.is_healthy(1) is True
