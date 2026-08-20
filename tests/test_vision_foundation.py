# -*- coding: utf-8 -*-
"""Deterministic unit tests for Phase 6.1 Vision Foundation."""

from unittest import mock
import pytest

from friday.vision.base import BaseVisionProvider, VisionAnalysisResult
from friday.vision.mock_vision import MockVisionProvider
from friday.vision.gemini_vision import GeminiVisionProvider, validate_image_data, SUPPORTED_MIME_TYPES
from friday.auth.credential_pool import GeminiCredentialPool, FailureCategory


# Sample synthetic image payloads with valid magic byte headers
SAMPLE_PNG_HEADER = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
SAMPLE_JPEG_HEADER = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
SAMPLE_WEBP_HEADER = b"RIFF\x20\x00\x00\x00WEBPVP8 \x14\x00\x00\x00"


def test_vision_analysis_result_dataclass():
    """Verify VisionAnalysisResult serializes to dict safely without exposing secrets."""
    res = VisionAnalysisResult(
        text="A desktop with terminal open.",
        description="A desktop with terminal open.",
        visual_elements=[{"type": "terminal", "bounds": [0, 0, 100, 100]}],
        model="gemini-3.6-flash",
    )
    d = res.to_dict()
    assert d["text"] == "A desktop with terminal open."
    assert d["model"] == "gemini-3.6-flash"
    assert d["is_error"] is False
    assert len(d["visual_elements"]) == 1


def test_mock_vision_provider_deterministic_behavior():
    """Verify MockVisionProvider records calls and honors custom responses."""
    mock_prov = MockVisionProvider(default_response="Default visual description.")
    mock_prov.set_response_for_prompt_substring("error", "Error dialog with status code 404.")

    # Standard query
    res1 = mock_prov.analyze_image(SAMPLE_PNG_HEADER, mime_type="image/png", prompt="What is on screen?")
    assert res1.text == "Default visual description."
    assert len(mock_prov.call_history) == 1

    # Custom prompt query
    res2 = mock_prov.analyze_image(SAMPLE_PNG_HEADER, mime_type="image/png", prompt="What error is visible?")
    assert res2.text == "Error dialog with status code 404."

    # Simulated failure
    mock_prov.should_fail = True
    res3 = mock_prov.analyze_image(SAMPLE_PNG_HEADER, mime_type="image/png")
    assert res3.is_error is True
    assert "Mock vision provider simulated error" in res3.error_message


def test_validate_image_data_boundaries():
    """Verify image payload validation enforces MIME types, magic bytes, and size boundaries."""
    # Empty data
    with pytest.raises(ValueError, match="Image data is empty"):
        validate_image_data(b"", "image/png")

    # Unsupported MIME
    with pytest.raises(ValueError, match="Unsupported image MIME type"):
        validate_image_data(b"some_random_bytes", "image/bmp")

    # Corrupted magic bytes for declared MIME type
    with pytest.raises(ValueError, match="Corrupted or invalid image data"):
        validate_image_data(b"NOT_A_PNG_FILE_HEADER", "image/png")

    # Oversized payload
    with pytest.raises(ValueError, match="exceeds maximum allowed size"):
        validate_image_data(SAMPLE_PNG_HEADER + (b"\x00" * 200), "image/png", max_bytes=50)

    # Valid PNG, JPEG, WEBP headers
    validate_image_data(SAMPLE_PNG_HEADER, "image/png")
    validate_image_data(SAMPLE_JPEG_HEADER, "image/jpeg")
    validate_image_data(SAMPLE_WEBP_HEADER, "image/webp")


def test_gemini_vision_provider_successful_analysis():
    """Verify GeminiVisionProvider builds multimodal prompt and parses response."""
    mock_pool = mock.MagicMock(spec=GeminiCredentialPool)
    mock_pool.get_active_key.return_value = "TEST_GEMINI_KEY"

    provider = GeminiVisionProvider(credential_pool=mock_pool, model="gemini-3.6-flash")

    mock_client = mock.MagicMock()
    mock_response = mock.MagicMock()
    mock_response.text = "Visual summary: VS Code is open on the left, browser on the right."
    mock_client.models.generate_content.return_value = mock_response

    with mock.patch.object(provider, "_get_client", return_value=mock_client):
        result = provider.analyze_image(
            image_data=SAMPLE_PNG_HEADER,
            mime_type="image/png",
            prompt="Analyze open windows",
        )

    assert result.is_error is False
    assert "VS Code is open" in result.text
    assert result.model == "gemini-3.6-flash"
    mock_pool.reset_key.assert_called_once_with("TEST_GEMINI_KEY")


def test_gemini_vision_provider_failover_on_quota_error():
    """Verify GeminiVisionProvider reports failure category to credential pool on API errors."""
    mock_pool = mock.MagicMock(spec=GeminiCredentialPool)
    mock_pool.get_active_key.side_effect = ["KEY_1", "KEY_2"]
    mock_pool.classify_error.return_value = FailureCategory.QUOTA_EXHAUSTED

    provider = GeminiVisionProvider(
        credential_pool=mock_pool,
        model="gemini-3.6-flash",
        max_retries=1,
        backoff_factor=0.01,
    )

    mock_client = mock.MagicMock()
    # First attempt fails with 429 quota, second succeeds
    mock_success_response = mock.MagicMock()
    mock_success_response.text = "Recovered after failover: chart is showing uptrend."
    quota_err = Exception("429 ResourceExhausted: Quota exceeded for project")
    mock_client.models.generate_content.side_effect = [
        quota_err,
        mock_success_response,
    ]

    with mock.patch.object(provider, "_get_client", return_value=mock_client):
        result = provider.analyze_image(
            image_data=SAMPLE_PNG_HEADER,
            mime_type="image/png",
            prompt="Read chart",
        )

    assert result.is_error is False
    assert "Recovered after failover" in result.text
    # Should report quota failure for first key and reset for second
    mock_pool.report_failure.assert_called_with("KEY_1", quota_err)
    mock_pool.reset_key.assert_called_with("KEY_2")
