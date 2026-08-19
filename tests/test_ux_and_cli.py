"""Deterministic tests for CLI UX, Provider Preflight, and Quota-Aware Runtime."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock
import pytest

from friday.auth.credential_pool import GeminiCredentialPool, FailureCategory, COOLDOWN_DURATIONS
from friday.cli.main import BANNER, print_status, render_friday_banner, FRIDAY_LOGO_LINES
from friday.core.config import Settings
from friday.core.logging import setup_logging
from friday.core.types import Message, Role
from friday.memory.embeddings.gemini import GeminiEmbeddingProvider
from friday.memory.policies import should_retrieve_memory, should_embed_message


# -----------------------------------------------------------------------------
# TEST 1 & 2: Banner Rendering & PowerShell Safety
# -----------------------------------------------------------------------------
def test_banner_ascii_rendering():
    """Verify banner contains assistant tagline, version, and valid characters without Unicode errors."""
    banner_text = render_friday_banner("0.4.6")
    assert "Fully Responsive Intelligent Digital Assistant for You" in banner_text
    assert "Version 0.4.6" in banner_text
    assert "><" not in banner_text  # Verify no malformed Y geometry
    # Verify all logo lines are present and ASCII-safe
    for l in FRIDAY_LOGO_LINES:
        assert l.strip() in [line.strip() for line in banner_text.splitlines() if line.strip()]
    encoded = banner_text.encode("ascii")
    assert len(encoded) > 50


# -----------------------------------------------------------------------------
# TEST 3: Clean Terminal Logging Default vs Debug Mode
# -----------------------------------------------------------------------------
def test_setup_logging_console_quiet_mode(tmp_path):
    """Verify that default setup_logging console level can be set to WARNING for clean output."""
    log_file = tmp_path / "test.log"
    logger = setup_logging(level="DEBUG", log_file=str(log_file), console_level=logging.WARNING)

    # Console handler should be at WARNING, file handler at DEBUG
    handlers = logger.handlers
    console = [h for h in handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)][0]
    file_h = [h for h in handlers if isinstance(h, logging.FileHandler)][0]

    assert console.level == logging.WARNING
    assert file_h.level == logging.DEBUG


# -----------------------------------------------------------------------------
# TEST 4 & 5: Embedding Circuit Breaker Zero Network Calls & No Repeated Warnings
# -----------------------------------------------------------------------------
def test_embedding_circuit_breaker_zero_network_when_open():
    """Verify that when circuit breaker cooldown is active, embed_text raises immediately without network call."""
    import time
    provider = GeminiEmbeddingProvider(api_key="TEST_FAKE_KEY")
    mock_client = mock.MagicMock()
    provider._client = mock_client

    # Open circuit breaker
    GeminiEmbeddingProvider._circuit_breaker_cooldown_until = time.time() + 3600

    try:
        with pytest.raises(Exception) as exc_info:
            provider.embed_text("Test query text")

        assert "circuit breaker is open" in str(exc_info.value)
        # Ensure zero network calls were attempted
        assert mock_client.models.embed_content.call_count == 0
    finally:
        # Reset circuit breaker
        GeminiEmbeddingProvider._circuit_breaker_cooldown_until = 0.0


# -----------------------------------------------------------------------------
# TEST 6 & 7: Startup Preflight Check
# -----------------------------------------------------------------------------
def test_startup_preflight_primary_healthy():
    """Verify preflight selects primary when it is healthy."""
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1"]
    pool = GeminiCredentialPool(keys=keys)
    pool.load_keys(keys)
    pool.reset_all()

    result = pool.preflight_check(force_probe=True)
    assert result["status"] == "ready"
    assert result["active_project"] == "PRIMARY"
    assert pool.get_active_label() == "PRIMARY"


def test_startup_preflight_skips_known_cooldown_primary():
    """Verify preflight immediately selects healthy fallback when primary is in cooldown."""
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1", "KEY_FALLBACK_2"]
    pool = GeminiCredentialPool(keys=keys)
    pool.load_keys(keys)
    pool.reset_all()

    # Primary in cooldown
    pool.report_failure("KEY_PRIMARY")

    result = pool.preflight_check(force_probe=True)
    assert result["status"] == "fallback_selected"
    assert result["active_project"] == "FALLBACK 1"
    assert pool.get_active_label() == "FALLBACK 1"


# -----------------------------------------------------------------------------
# TEST 8, 9, 10: Session-Level Provider Stickiness (No bouncing)
# -----------------------------------------------------------------------------
def test_session_level_provider_stickiness():
    """Verify that once a fallback is selected, subsequent get_active_key calls stay on that fallback."""
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1", "KEY_FALLBACK_2"]
    pool = GeminiCredentialPool(keys=keys)
    pool.load_keys(keys)
    pool.reset_all()

    pool.report_failure("KEY_PRIMARY")
    assert pool.get_active_label() == "FALLBACK 1"

    # Next call returns Fallback 1 again (sticky session)
    assert pool.get_active_key() == "KEY_FALLBACK_1"
    assert pool.get_active_label() == "FALLBACK 1"


# -----------------------------------------------------------------------------
# TEST 11: Persistent Provider Health State
# -----------------------------------------------------------------------------
def test_persistent_provider_health_state(tmp_path):
    """Verify provider health state is saved to disk and restored across restarts."""
    state_file = tmp_path / "pool_state.json"
    keys = ["KEY_PRIMARY", "KEY_FALLBACK_1"]

    pool1 = GeminiCredentialPool(keys=keys, state_file=state_file)
    pool1.load_keys(keys)
    pool1.reset_all()

    # Report failure on primary
    pool1.report_failure("KEY_PRIMARY", error=Exception("429 Quota Exceeded"))
    assert pool1.credentials[0].last_failure_category == FailureCategory.QUOTA_EXHAUSTED
    assert state_file.exists()

    # Create new pool instance loading from the same state file
    pool2 = GeminiCredentialPool(keys=keys, state_file=state_file)
    pool2.load_keys(keys)
    pool2._load_persisted_state()

    # Primary should still be in cooldown in the restored instance
    assert not pool2.credentials[0].is_healthy(max_failures=1)
    assert pool2.get_active_label() == "FALLBACK 1"


# -----------------------------------------------------------------------------
# TEST 12: Failure Category Classification
# -----------------------------------------------------------------------------
def test_failure_classification_categories():
    """Verify failure classification accurately maps error strings to categories."""
    assert GeminiCredentialPool.classify_error(Exception("401 Unauthorized")) == FailureCategory.AUTH_FAILED
    assert GeminiCredentialPool.classify_error(Exception("404 models/gemini-2.5-flash is no longer available")) == FailureCategory.MODEL_NOT_FOUND
    assert GeminiCredentialPool.classify_error(Exception("429 RESOURCE_EXHAUSTED: daily quota exceeded")) == FailureCategory.QUOTA_EXHAUSTED
    assert GeminiCredentialPool.classify_error(Exception("503 Service Unavailable")) == FailureCategory.SERVICE_ERROR
    assert GeminiCredentialPool.classify_error(Exception("Connection reset by peer")) == FailureCategory.NETWORK_ERROR


# -----------------------------------------------------------------------------
# TEST 13 & 14: Memory Policy Zero-Latency on Trivial Turns
# -----------------------------------------------------------------------------
def test_trivial_turns_skip_memory_retrieval_and_embedding():
    """Verify that greetings, simple math, and clock queries skip embedding and recall."""
    assert not should_retrieve_memory("Hello FRIDAY")
    assert not should_retrieve_memory("What time is it?")
    assert not should_retrieve_memory("Calculate 12345 * 6789")

    assert not should_embed_message(Message(role=Role.USER, content="Hello"))
    assert not should_embed_message(Message(role=Role.USER, content="What time is it?"))
    assert not should_embed_message(Message(role=Role.USER, content="2+2"))

    # Complex memory query should trigger recall
    assert should_retrieve_memory("What was my favorite editor?")
