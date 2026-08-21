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

    # Patch _get_client to always return mock_client regardless of which API key is active.
    # Without this patch, _get_client() detects the key change when rotating to FALLBACK_1
    # and instantiates a real genai.Client, overwriting the mock and causing real API calls
    # and unexpected backoff sleep() calls.
    with mock.patch.object(provider, "_get_client", return_value=mock_client), \
         mock.patch("friday.llm.gemini_provider.time.sleep") as mock_sleep:
        resp = provider.generate([Message(role=Role.USER, content="Hello")])

    assert resp.content == "Response from Fallback 1"
    # Primary attempted EXACTLY ONCE (zero retries on primary)
    assert key_attempts["KEY_PRIMARY"] == 1
    # Fallback 1 attempted EXACTLY ONCE and succeeded
    assert key_attempts["KEY_FALLBACK_1"] == 1
    assert key_attempts["KEY_FALLBACK_2"] == 0
    # No backoff sleep called for quota exhaustion (immediate failover path)
    mock_sleep.assert_not_called()
    # Primary must be in cooldown
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


def test_interactive_friday_agent_path_failover(tmp_path):
    """Verify that FridayAgent -> create_llm_provider -> GeminiLLMProvider -> GeminiCredentialPool

    fails over immediately when Primary returns 429 RESOURCE_EXHAUSTED.
    """
    from friday.agent.agent import FridayAgent
    from friday.core.config import Settings
    from friday.llm.factory import create_llm_provider

    state_file = tmp_path / "pool_state.json"
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1", "KEY_FALLBACK_2"]
    pool = GeminiCredentialPool(keys=keys, cooldown_seconds=3600, state_file=state_file)
    pool.load_keys(keys)
    pool.reset_all()

    settings = Settings(
        llm_provider="gemini",
        llm_model="gemini-3.6-flash",
        gemini_api_key=None,
        llm_api_key=None,
    )

    # Patch global credential_pool in factory/llm
    with mock.patch("friday.llm.factory.credential_pool", pool), \
         mock.patch("friday.auth.credential_pool.credential_pool", pool):
        provider = create_llm_provider(settings)
        # Verify provider received the credential pool and has no static api_key lock
        assert provider.credential_pool is pool
        assert provider._explicit_api_key is None

        key_calls = {}

        def mock_generate(model, contents, config):
            curr_key = provider._current_key
            key_calls[curr_key] = key_calls.get(curr_key, 0) + 1
            if curr_key == "KEY_PRIMARY":
                raise Exception("429 RESOURCE_EXHAUSTED: generate_content_free_tier_requests limit: 20 model: gemini-3.6-flash")
            return make_mock_response("Interactive agent response from Fallback 1")

        mock_client = mock.MagicMock()
        mock_client._is_mock = True
        mock_client.models.generate_content.side_effect = mock_generate
        provider._client = mock_client

        agent = FridayAgent(settings=settings, llm_provider=provider)
        response = agent.process_message("Hello FRIDAY")

        assert "Interactive agent response from Fallback 1" in response.content
        assert key_calls["KEY_PRIMARY"] == 1
        assert key_calls["KEY_FALLBACK_1"] == 1
        assert pool.credentials[0].is_healthy(1) is False
        assert pool.get_active_label() == "FALLBACK 1"


def test_cooldown_expiry_restores_primary(tmp_path):
    """Verify that when a cooldown expires, Primary becomes eligible again."""
    state_file = tmp_path / "pool_state.json"
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1"]
    pool = GeminiCredentialPool(keys=keys, cooldown_seconds=60, state_file=state_file)
    pool.load_keys(keys)
    pool.reset_all()

    # Fail primary
    pool.report_failure("KEY_PRIMARY", Exception("429 Quota Exceeded"))
    assert pool.get_active_label() == "FALLBACK 1"
    assert pool.credentials[0].is_healthy(1) is False

    # Simulate cooldown expiry
    pool.credentials[0].cooldown_until = datetime.utcnow() - timedelta(seconds=5)
    pool.credentials[0].failure_count = 0

    assert pool.credentials[0].is_healthy(1) is True
    assert pool.get_active_label() == "PRIMARY"

