# -*- coding: utf-8 -*-
"""Deterministic unit tests for Credential Pool immediate 429 quota exhaustion failover chain and cooldown."""

from datetime import datetime, timedelta
from unittest import mock
import pytest
from google.genai import types

from friday.auth.credential_pool import GeminiCredentialPool, FailureCategory
from friday.core.exceptions import LLMProviderError
from friday.core.types import Message, Role
from friday.llm.gemini_provider import GeminiLLMProvider


def make_mock_response(text: str = "Success"):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    role="model",
                    parts=[types.Part.from_text(text=text)],
                ),
                finish_reason=types.FinishReason.STOP,
            )
        ]
    )


def test_immediate_failover_on_429_quota_exhausted():
    """Verify that a 429 quota exhaustion immediately switches to Fallback 1 with ZERO retry attempts on Primary."""
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1", "KEY_FALLBACK_2", "KEY_FALLBACK_3", "KEY_FALLBACK_4"]
    pool = GeminiCredentialPool(keys=keys, cooldown_seconds=3600)
    pool.load_keys(keys)
    pool.reset_all()

    provider = GeminiLLMProvider(api_key=None, credential_pool=pool, max_retries=3, backoff_factor=1.0)

    # Track requests per API key
    key_attempts = {"KEY_PRIMARY": 0, "KEY_FALLBACK_1": 0, "KEY_FALLBACK_2": 0}

    def fake_generate_content(model, contents, config):
        active_k = provider._current_key
        key_attempts[active_k] = key_attempts.get(active_k, 0) + 1
        if active_k == "KEY_PRIMARY":
            raise Exception("429 RESOURCE_EXHAUSTED: generate_content_free_tier_requests limit: 20 model: gemini-3.6-flash")
        return make_mock_response("Response from Fallback 1")

    mock_client = mock.MagicMock()
    mock_client._is_mock = True
    mock_client.models.generate_content.side_effect = fake_generate_content
    provider._client = mock_client

    with mock.patch("time.sleep") as mock_sleep:
        resp = provider.generate([Message(role=Role.USER, content="Hello")])

    assert resp.content == "Response from Fallback 1"
    # Primary attempted EXACTLY ONCE (zero retries on primary)
    assert key_attempts["KEY_PRIMARY"] == 1
    # Fallback 1 attempted EXACTLY ONCE and succeeded
    assert key_attempts["KEY_FALLBACK_1"] == 1
    assert key_attempts["KEY_FALLBACK_2"] == 0
    # No backoff sleep called for quota exhaustion
    mock_sleep.assert_not_called()
    # Primary in cooldown
    assert pool.credentials[0].last_failure_category == FailureCategory.QUOTA_EXHAUSTED
    assert pool.credentials[0].cooldown_until is not None


def test_failure_chain_primary_to_fb3():
    """Verify that Primary -> FB1 -> FB2 failure chain succeeds on FB3."""
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1", "KEY_FALLBACK_2", "KEY_FALLBACK_3", "KEY_FALLBACK_4"]
    pool = GeminiCredentialPool(keys=keys, cooldown_seconds=3600)
    pool.load_keys(keys)
    pool.reset_all()

    provider = GeminiLLMProvider(api_key=None, credential_pool=pool, max_retries=5, backoff_factor=1.0)

    key_attempts = {}

    def fake_generate_content(model, contents, config):
        active_k = provider._current_key
        key_attempts[active_k] = key_attempts.get(active_k, 0) + 1
        if active_k in ("KEY_PRIMARY", "KEY_FALLBACK_1", "KEY_FALLBACK_2"):
            raise Exception(f"429 Quota Exceeded for {active_k}")
        return make_mock_response("Response from Fallback 3")

    mock_client = mock.MagicMock()
    mock_client._is_mock = True
    mock_client.models.generate_content.side_effect = fake_generate_content
    provider._client = mock_client

    with mock.patch("time.sleep") as mock_sleep:
        resp = provider.generate([Message(role=Role.USER, content="Test")])

    assert resp.content == "Response from Fallback 3"
    assert key_attempts.get("KEY_PRIMARY") == 1
    assert key_attempts.get("KEY_FALLBACK_1") == 1
    assert key_attempts.get("KEY_FALLBACK_2") == 1
    assert key_attempts.get("KEY_FALLBACK_3") == 1
    assert key_attempts.get("KEY_FALLBACK_4", 0) == 0
    mock_sleep.assert_not_called()


def test_all_five_credentials_exhausted_graceful_failure():
    """Verify graceful immediate failure with clear error message when all 5 keys are exhausted."""
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1", "KEY_FALLBACK_2", "KEY_FALLBACK_3", "KEY_FALLBACK_4"]
    pool = GeminiCredentialPool(keys=keys, cooldown_seconds=3600)
    pool.load_keys(keys)
    pool.reset_all()

    provider = GeminiLLMProvider(api_key=None, credential_pool=pool, max_retries=5, backoff_factor=1.0)

    def fake_generate_content(model, contents, config):
        raise Exception("429 RESOURCE_EXHAUSTED Quota Exceeded")

    mock_client = mock.MagicMock()
    mock_client._is_mock = True
    mock_client.models.generate_content.side_effect = fake_generate_content
    provider._client = mock_client

    with mock.patch("time.sleep") as mock_sleep:
        with pytest.raises(LLMProviderError) as exc_info:
            provider.generate([Message(role=Role.USER, content="Test")])

    assert "exhausted" in str(exc_info.value).lower() or "gemini" in str(exc_info.value).lower()
    # No long blocking sleeps
    mock_sleep.assert_not_called()
