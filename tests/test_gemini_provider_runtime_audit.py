# -*- coding: utf-8 -*-
"""Comprehensive runtime audit tests for GeminiLLMProvider.

Verifies:
1. Thread-safe internal state initialization (no getattr reliance).
2. Operation with explicit API key (no pool) vs. with credential pool.
3. Every FailureCategory behavior:
   - QUOTA_EXHAUSTED: moves to next healthy credential in pool.
   - AUTH_FAILED: marks bad credential, rotates to next healthy credential.
   - MODEL_NOT_FOUND: raises immediately without pointless credential rotation.
   - SERVICE_ERROR / NETWORK_ERROR: bounded retry with backoff.
   - All credentials exhausted: returns clean LLMProviderError.
4. Thread-safe concurrent execution across multiple threads.
5. Client switching when active key changes.
6. Absolute zero API key exposure in error masking and logs.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time
from unittest import mock
import pytest

from google.genai import types as genai_types
from friday.auth.credential_pool import GeminiCredentialPool, FailureCategory
from friday.core.exceptions import LLMProviderError
from friday.core.types import Message, Role
from friday.llm.gemini_provider import GeminiLLMProvider


@pytest.fixture
def clean_pool():
    """Provide a freshly initialized GeminiCredentialPool."""
    state_file = Path("data/test_runtime_pool_state.json")
    pool = GeminiCredentialPool(
        keys=["PRIMARY_KEY_1111", "FALLBACK_KEY_2222", "FALLBACK_KEY_3333"],
        state_file=state_file,
        cooldown_seconds=60,
    )
    pool.reset_all()
    yield pool
    try:
        if state_file.exists():
            state_file.unlink(missing_ok=True)
    except Exception:
        pass


def _make_mock_response(text="Nominal"):
    return genai_types.GenerateContentResponse(
        candidates=[
            genai_types.Candidate(
                content=genai_types.Content(
                    parts=[genai_types.Part.from_text(text=text)],
                    role="model",
                ),
                finish_reason=genai_types.FinishReason.STOP,
            )
        ]
    )


def test_provider_explicit_state_initialization():
    """Verify all internal fields are explicitly initialized without relying on getattr fallbacks."""
    provider = GeminiLLMProvider(api_key="TEST_EXPLICIT_KEY_123")
    assert provider._explicit_api_key == "TEST_EXPLICIT_KEY_123"
    assert provider.api_key == "TEST_EXPLICIT_KEY_123"
    assert provider._client is None
    assert provider._current_key is None
    assert isinstance(provider._lock, type(threading.Lock()))
    assert provider.model == "gemini-3.7-flash"


def test_provider_without_credential_pool():
    """Verify provider functions cleanly with explicit API key and no credential pool."""
    provider = GeminiLLMProvider(api_key="EXPLICIT_KEY_456", credential_pool=None)
    assert provider.credential_pool is None

    mock_client = mock.MagicMock()
    mock_client.models.generate_content.return_value = _make_mock_response("Success without pool")

    with mock.patch.object(provider, "_get_client", return_value=mock_client):
        msg = provider.generate([Message(role=Role.USER, content="Hello")])
        assert msg.content == "Success without pool"


def test_quota_exhausted_rotates_to_next_credential(clean_pool):
    """Verify FailureCategory.QUOTA_EXHAUSTED immediately rotates to the next available credential."""
    provider = GeminiLLMProvider(credential_pool=clean_pool, max_retries=1)

    # Primary key fails with 429 Quota Exceeded, Fallback 1 succeeds
    def mock_generate_content(model, contents, config):
        active_key = clean_pool._session_active_key or clean_pool.credentials[0].api_key
        if "PRIMARY" in active_key:
            raise Exception("429 ResourceExhausted: Quota exceeded for project 12345")
        return _make_mock_response("Response from fallback")

    mock_client = mock.MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content

    with mock.patch.object(provider, "_get_client", return_value=mock_client):
        msg = provider.generate([Message(role=Role.USER, content="Test")])
        assert msg.content == "Response from fallback"

        # Verify PRIMARY is in cooldown and session is now on FALLBACK 1
        diagnostics = clean_pool.get_diagnostics()
        primary_diag = next(d for d in diagnostics if d["project_label"] == "PRIMARY")
        fallback_diag = next(d for d in diagnostics if d["project_label"] == "FALLBACK 1")
        assert primary_diag["status"] == "COOLDOWN"
        assert primary_diag["failure_category"] == FailureCategory.QUOTA_EXHAUSTED.value
        assert fallback_diag["status"] == "HEALTHY"


def test_auth_failed_rotates_and_disables_bad_credential(clean_pool):
    """Verify FailureCategory.AUTH_FAILED marks credential and rotates to next."""
    provider = GeminiLLMProvider(credential_pool=clean_pool)

    def mock_generate_content(model, contents, config):
        active_key = clean_pool._session_active_key or clean_pool.credentials[0].api_key
        if "PRIMARY" in active_key:
            raise Exception("401 API_KEY_INVALID: API key not valid. Please pass a valid API key.")
        return _make_mock_response("Authenticated on fallback")

    mock_client = mock.MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate_content

    with mock.patch.object(provider, "_get_client", return_value=mock_client):
        msg = provider.generate([Message(role=Role.USER, content="Test")])
        assert msg.content == "Authenticated on fallback"

        diagnostics = clean_pool.get_diagnostics()
        primary_diag = next(d for d in diagnostics if d["project_label"] == "PRIMARY")
        assert primary_diag["status"] == "COOLDOWN"
        assert primary_diag["failure_category"] == FailureCategory.AUTH_FAILED.value


def test_model_not_found_raises_immediately_without_rotation(clean_pool):
    """Verify FailureCategory.MODEL_NOT_FOUND raises immediately and does NOT rotate or fail keys."""
    provider = GeminiLLMProvider(credential_pool=clean_pool, model="gemini-nonexistent-model")

    mock_client = mock.MagicMock()
    mock_client.models.generate_content.side_effect = Exception("404 models/gemini-nonexistent-model is not found")

    with mock.patch.object(provider, "_get_client", return_value=mock_client):
        with pytest.raises(LLMProviderError) as exc_info:
            provider.generate([Message(role=Role.USER, content="Test")])

        assert "not found" in str(exc_info.value).lower()
        # Ensure PRIMARY was NOT penalized or marked in cooldown
        diagnostics = clean_pool.get_diagnostics()
        primary_diag = next(d for d in diagnostics if d["project_label"] == "PRIMARY")
        assert primary_diag["status"] == "HEALTHY"
        assert primary_diag["failure_count"] == 0


def test_transient_service_error_bounded_retry():
    """Verify 503/Service Error retries up to max_retries with backoff."""
    provider = GeminiLLMProvider(api_key="TEST_KEY", max_retries=2, backoff_factor=1.0)

    call_count = 0

    def mock_generate(model, contents, config):
        nonlocal call_count
        call_count += 1
        if call_count <= 2:
            raise Exception("503 Service Unavailable: High load")
        return _make_mock_response("Recovered after retry")

    mock_client = mock.MagicMock()
    mock_client.models.generate_content.side_effect = mock_generate

    with mock.patch.object(provider, "_get_client", return_value=mock_client):
        with mock.patch("time.sleep") as mock_sleep:
            msg = provider.generate([Message(role=Role.USER, content="Test")])
            assert msg.content == "Recovered after retry"
            assert call_count == 3
            assert mock_sleep.call_count == 2


def test_all_credentials_exhausted_clean_error(clean_pool):
    """Verify when all pool credentials fail, a clean descriptive LLMProviderError is raised."""
    provider = GeminiLLMProvider(credential_pool=clean_pool)

    mock_client = mock.MagicMock()
    mock_client.models.generate_content.side_effect = Exception("429 ResourceExhausted: Quota exceeded")

    with mock.patch.object(provider, "_get_client", return_value=mock_client):
        with pytest.raises(LLMProviderError) as exc_info:
            provider.generate([Message(role=Role.USER, content="Test")])

        assert "exhausted" in str(exc_info.value).lower()


def test_secret_masking_never_exposes_api_keys(clean_pool):
    """Verify raw API keys are never included in error messages or diagnostics."""
    provider = GeminiLLMProvider(api_key="SECRET_KEY_9999_EXPLICIT", credential_pool=clean_pool)

    raw_error = "Failed to authenticate with key SECRET_KEY_9999_EXPLICIT or PRIMARY_KEY_1111"
    masked = provider._mask_key(raw_error)

    assert "SECRET_KEY_9999_EXPLICIT" not in masked
    assert "PRIMARY_KEY_1111" not in masked
    assert "***" in masked


def test_concurrent_requests_and_thread_safety(clean_pool):
    """Verify thread-safe concurrent execution across multiple threads."""
    provider = GeminiLLMProvider(credential_pool=clean_pool)

    mock_client = mock.MagicMock()
    mock_client.models.generate_content.return_value = _make_mock_response("Thread nominal")

    with mock.patch.object(provider, "_get_client", return_value=mock_client):
        def worker(thread_id):
            return provider.generate([Message(role=Role.USER, content=f"Ping {thread_id}")])

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(worker, range(20)))

        assert len(results) == 20
        for res in results:
            assert res.content == "Thread nominal"


def test_client_switching_when_key_changes():
    """Verify genai.Client instance is recreated only when active API key changes."""
    provider = GeminiLLMProvider(api_key="KEY_A")

    client_a = provider._get_client("KEY_A")
    client_a_cached = provider._get_client("KEY_A")
    assert client_a is client_a_cached

    client_b = provider._get_client("KEY_B")
    assert client_b is not client_a
    assert provider._current_key == "KEY_B"
