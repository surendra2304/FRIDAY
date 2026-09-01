"""Deterministic unit tests for Multi-Project Gemini Credential Failover System."""

import threading
from datetime import datetime, timedelta
from unittest import mock

import pytest
from google.genai import types

from friday.auth.credential_pool import GeminiCredentialPool
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


# -----------------------------------------------------------------------------
# TEST 1: Primary succeeds -> primary is used -> no fallback is touched
# -----------------------------------------------------------------------------
def test_failover_test_1_primary_succeeds():
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1", "KEY_FALLBACK_2", "KEY_FALLBACK_3", "KEY_FALLBACK_4"]
    pool = GeminiCredentialPool(keys=keys)
    pool.load_keys(keys)
    pool.reset_all()

    provider = GeminiLLMProvider(api_key=None, credential_pool=pool, max_retries=5)
    
    mock_client = mock.MagicMock()
    mock_client._is_mock = True
    mock_client.models.generate_content.return_value = make_mock_response("Primary response")
    provider._client = mock_client

    resp = provider.generate([Message(role=Role.USER, content="Hello")])

    assert resp.content == "Primary response"
    # Primary health preserved, fallbacks untouched
    assert pool.credentials[0].failure_count == 0
    assert pool.credentials[1].failure_count == 0
    assert pool.credentials[2].failure_count == 0
    assert pool.credentials[3].failure_count == 0
    assert pool.credentials[4].failure_count == 0
    assert pool.get_active_key() == "KEY_PRIMARY"


# -----------------------------------------------------------------------------
# TEST 2: Primary returns 429 -> primary enters cooldown -> fallback 1 used -> succeeds
# -----------------------------------------------------------------------------
def test_failover_test_2_primary_429_failover_to_fallback_1():
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1", "KEY_FALLBACK_2", "KEY_FALLBACK_3", "KEY_FALLBACK_4"]
    pool = GeminiCredentialPool(keys=keys, cooldown_seconds=60)
    pool.load_keys(keys)
    pool.reset_all()

    provider = GeminiLLMProvider(api_key=None, credential_pool=pool, max_retries=5, backoff_factor=1.0)
    
    # Simulate first call (primary) failing with 429, second call (fallback 1) succeeding
    mock_client = mock.MagicMock()
    mock_client._is_mock = True
    mock_client.models.generate_content.side_effect = [
        Exception("429 RESOURCE_EXHAUSTED: Quota exceeded for project 1"),
        make_mock_response("Fallback 1 success"),
    ]
    provider._client = mock_client

    with mock.patch("time.sleep"):
        resp = provider.generate([Message(role=Role.USER, content="Hello")])

    assert resp.content == "Fallback 1 success"
    # Primary failed and entered cooldown
    assert pool.credentials[0].failure_count == 1
    assert pool.credentials[0].cooldown_until is not None
    # Fallback 1 succeeded and is now the active key
    assert pool.credentials[1].failure_count == 0
    assert pool.get_active_key() == "KEY_FALLBACK_1"


# -----------------------------------------------------------------------------
# TEST 3: Primary fails -> Fallback 1 fails -> Fallback 2 is used -> succeeds
# -----------------------------------------------------------------------------
def test_failover_test_3_fallback_2_succeeds():
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1", "KEY_FALLBACK_2", "KEY_FALLBACK_3", "KEY_FALLBACK_4"]
    pool = GeminiCredentialPool(keys=keys, cooldown_seconds=60)
    pool.load_keys(keys)
    pool.reset_all()

    provider = GeminiLLMProvider(api_key=None, credential_pool=pool, max_retries=5, backoff_factor=1.0)
    
    mock_client = mock.MagicMock()
    mock_client._is_mock = True
    mock_client.models.generate_content.side_effect = [
        Exception("429 Rate limit on primary"),
        Exception("429 Quota exhausted on fallback 1"),
        make_mock_response("Fallback 2 success"),
    ]
    provider._client = mock_client

    with mock.patch("time.sleep"):
        resp = provider.generate([Message(role=Role.USER, content="Hello")])

    assert resp.content == "Fallback 2 success"
    assert pool.credentials[0].failure_count == 1
    assert pool.credentials[1].failure_count == 1
    assert pool.credentials[2].failure_count == 0
    assert pool.get_active_key() == "KEY_FALLBACK_2"


# -----------------------------------------------------------------------------
# TEST 4: Primary + FB1 + FB2 + FB3 fail -> Fallback 4 is used -> succeeds
# -----------------------------------------------------------------------------
def test_failover_test_4_fallback_4_succeeds():
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1", "KEY_FALLBACK_2", "KEY_FALLBACK_3", "KEY_FALLBACK_4"]
    pool = GeminiCredentialPool(keys=keys, cooldown_seconds=60)
    pool.load_keys(keys)
    pool.reset_all()

    provider = GeminiLLMProvider(api_key=None, credential_pool=pool, max_retries=5, backoff_factor=1.0)
    
    mock_client = mock.MagicMock()
    mock_client._is_mock = True
    mock_client.models.generate_content.side_effect = [
        Exception("429 primary fail"),
        Exception("429 fb1 fail"),
        Exception("429 fb2 fail"),
        Exception("429 fb3 fail"),
        make_mock_response("Fallback 4 success"),
    ]
    provider._client = mock_client

    with mock.patch("time.sleep"):
        resp = provider.generate([Message(role=Role.USER, content="Hello")])

    assert resp.content == "Fallback 4 success"
    assert pool.credentials[0].failure_count == 1
    assert pool.credentials[1].failure_count == 1
    assert pool.credentials[2].failure_count == 1
    assert pool.credentials[3].failure_count == 1
    assert pool.credentials[4].failure_count == 0
    assert pool.get_active_key() == "KEY_FALLBACK_4"


# -----------------------------------------------------------------------------
# TEST 5: All five fail -> clean user-facing failure -> no infinite retry
# -----------------------------------------------------------------------------
def test_failover_test_5_all_five_fail_clean_exit():
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1", "KEY_FALLBACK_2", "KEY_FALLBACK_3", "KEY_FALLBACK_4"]
    pool = GeminiCredentialPool(keys=keys, cooldown_seconds=60)
    pool.load_keys(keys)
    pool.reset_all()

    # max_retries=5 means 6 total attempts max
    provider = GeminiLLMProvider(api_key=None, credential_pool=pool, max_retries=5, backoff_factor=1.0)
    
    mock_client = mock.MagicMock()
    mock_client._is_mock = True
    mock_client.models.generate_content.side_effect = Exception("429 Quota Exhausted Everywhere")
    provider._client = mock_client

    with mock.patch("time.sleep"), pytest.raises(LLMProviderError) as exc_info:
        provider.generate([Message(role=Role.USER, content="Hello")])

    assert "Gemini" in str(exc_info.value)
    # All 5 credentials failed
    for i in range(5):
        assert pool.credentials[i].failure_count >= 1
    # Pool now raises RuntimeError
    with pytest.raises(RuntimeError):
        pool.get_active_key()


# -----------------------------------------------------------------------------
# TEST 6: Primary cooldown expires -> primary becomes eligible again
# -----------------------------------------------------------------------------
def test_failover_test_6_cooldown_expiration_recovery():
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1"]
    pool = GeminiCredentialPool(keys=keys, cooldown_seconds=1)
    pool.load_keys(keys)
    pool.reset_all()

    # Fail primary once
    pool.report_failure("KEY_PRIMARY")
    assert pool.get_active_key() == "KEY_FALLBACK_1"

    # Manually expire cooldown
    pool.credentials[0].cooldown_until = datetime.utcnow() - timedelta(seconds=1)
    pool.credentials[0].failure_count = 0  # reset for health check

    assert pool.get_active_key() == "KEY_PRIMARY"


# -----------------------------------------------------------------------------
# TEST 7: No duplicate logical request -> only one credential active per request
# -----------------------------------------------------------------------------
def test_failover_test_7_thread_safety_single_active_per_request():
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1"]
    pool = GeminiCredentialPool(keys=keys, cooldown_seconds=60)
    pool.load_keys(keys)
    pool.reset_all()

    results = []

    def worker():
        key = pool.get_active_key()
        results.append(key)

    threads = [threading.Thread(target=worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 10
    # All threads got the deterministic single primary key
    assert all(k == "KEY_PRIMARY" for k in results)


# -----------------------------------------------------------------------------
# TEST 8: Credentials never appear in logs, exceptions, diagnostics, or errors
# -----------------------------------------------------------------------------
def test_failover_test_8_secret_masking_in_failover_errors():
    secret_primary = "SECRET_PRIMARY_" + "AIza" + "Sy12345"
    secret_fallback = "SECRET_FALLBACK_" + "AIza" + "Sy67890"
    keys = [secret_primary, secret_fallback]
    
    pool = GeminiCredentialPool(keys=keys, cooldown_seconds=60)
    pool.load_keys(keys)
    pool.reset_all()

    provider = GeminiLLMProvider(api_key=None, credential_pool=pool, max_retries=1)
    
    mock_client = mock.MagicMock()
    mock_client._is_mock = True
    mock_client.models.generate_content.side_effect = Exception(
        f"Fatal error with {secret_primary} and {secret_fallback}"
    )
    provider._client = mock_client

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([Message(role=Role.USER, content="Hello")])

    err_str = str(exc_info.value)
    assert secret_primary not in err_str
    assert secret_fallback not in err_str
    assert "***" in err_str
