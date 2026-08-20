"""Tests for test suite integrity, environment isolation, and quota protection."""

import os
from pathlib import Path
from unittest import mock
import pytest

from friday.core.config import Settings, get_settings
from friday.memory.embeddings.gemini import GeminiEmbeddingProvider
from friday.core.exceptions import LLMProviderError


@pytest.mark.security
def test_default_pytest_environment_has_synthetic_keys():
    """Verify that automated tests never use real API keys or production embedding providers."""
    # Embedding provider must be disabled by default during normal pytest runs
    assert os.environ.get("FRIDAY_EMBEDDING_PROVIDER") == "none"
    
    # API keys must be synthetic placeholders
    gemini_key = os.environ.get("FRIDAY_GEMINI_API_KEY", "")
    assert "FAKE" in gemini_key or "TEST" in gemini_key or "MOCK" in gemini_key

    llm_key = os.environ.get("FRIDAY_LLM_API_KEY", "")
    assert "fake" in llm_key or "TEST" in llm_key or "MOCK" in llm_key


@pytest.mark.security
def test_settings_resolve_env_file_bypassed_in_tests():
    """Verify that Settings instantiation during tests does not read user's local .env file."""
    settings = Settings()
    # Ensure active keys are synthetic
    assert settings.embedding_provider == "none"
    if settings.gemini_api_key:
        assert "FAKE" in settings.gemini_api_key or "TEST" in settings.gemini_api_key


@pytest.mark.unit
def test_embedding_circuit_breaker_fails_fast_on_quota():
    """Verify that when 429 quota is hit, the circuit breaker opens and immediately rejects subsequent requests."""
    import time
    provider = GeminiEmbeddingProvider(api_key="TEST_KEY")
    
    # Simulate an open circuit breaker
    GeminiEmbeddingProvider._circuit_breaker_cooldown_until = time.time() + 60.0
    try:
        with pytest.raises(LLMProviderError) as exc_info:
            provider.embed_text("Test sentence to embed")
        assert "circuit breaker is open" in str(exc_info.value)
    finally:
        # Reset circuit breaker
        GeminiEmbeddingProvider._circuit_breaker_cooldown_until = 0.0


@pytest.mark.unit
def test_hardware_test_marker_isolation():
    """Verify that hardware tests are decorated with the 'hardware' marker so they are excluded by default."""
    import tests.test_real_live_hardware as hw_module
    marker = getattr(hw_module, "pytestmark", None)
    assert marker is not None
    assert getattr(marker, "name", "") == "hardware" or "hardware" in str(marker)
