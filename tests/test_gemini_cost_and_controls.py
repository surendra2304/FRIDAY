"""Tests for Gemini model controls, cost policies, retries, timeouts, and usage observability."""

from unittest import mock
import httpx
import pytest
from friday.agent.agent import FridayAgent
from friday.core.config import Settings
from friday.core.exceptions import ConfigError, LLMProviderError
from friday.core.types import Message, Role
from friday.llm.factory import create_llm_provider
from friday.llm.gemini_provider import GeminiLLMProvider
from friday.llm.mock_provider import MockLLMProvider
from friday.llm.openai_provider import OpenAILLMProvider
from friday.memory.in_memory import InMemoryConversationMemory


def test_gemini_cost_configuration_defaults():
    """Verify default cost control and provider tuning settings."""
    settings = Settings()
    assert settings.cost_mode == "free_first"
    assert settings.gemini_timeout == 60.0
    assert settings.gemini_max_retries == 3
    assert settings.gemini_backoff_factor == 2.0
    assert settings.gemini_model in (None, "gemini-3.6-flash", "gemini-2.5-flash")
    assert settings.gemini_max_tokens is None
    assert settings.gemini_temperature is None
    assert settings.max_daily_requests is None


def test_gemini_custom_configuration_and_model_override():
    """Verify custom model and cost settings override global defaults."""
    settings = Settings(
        llm_provider="gemini",
        llm_model="default-model",
        gemini_model="gemini-1.5-pro",
        gemini_api_key="TEST_GEMINI_API_KEY",
        gemini_timeout=30.0,
        gemini_max_retries=1,
        gemini_backoff_factor=1.5,
        gemini_max_tokens=4096,
        gemini_temperature=0.2,
        cost_mode="custom",
    )
    provider = create_llm_provider(settings)
    assert isinstance(provider, GeminiLLMProvider)
    assert provider.model == "gemini-1.5-pro"  # Overridden by gemini_model
    assert provider.timeout == 30.0
    assert provider.max_retries == 1
    assert provider.backoff_factor == 1.5
    assert provider.max_tokens == 4096
    assert provider.temperature == 0.2
    assert provider.cost_mode == "custom"


def test_gemini_missing_api_key_fails_cleanly_without_silent_fallback():
    """Verify missing API key raises clear error rather than silently routing data elsewhere."""
    settings = Settings(llm_provider="gemini", gemini_api_key="", llm_api_key="")
    provider = create_llm_provider(settings)

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate([Message(role=Role.USER, content="Test prompt")])

    assert "Gemini API key is required" in str(exc_info.value)


def test_gemini_retry_behavior_bounded_by_max_retries():
    """Verify transient failures retry up to max_retries and fail predictably without endless loops."""
    from google.genai import errors as genai_errors

    provider = GeminiLLMProvider(
        api_key="TEST_GEMINI_API_KEY",
        model="gemini-2.5-flash",
        max_retries=2,
        backoff_factor=1.0,
    )

    api_error = genai_errors.APIError(
        429,
        {"error": {"message": "Resource has been exhausted (quota limit reached).", "status": "RESOURCE_EXHAUSTED"}},
    )

    provider._client = mock.Mock()
    provider._client.models.generate_content.side_effect = api_error

    with mock.patch("time.sleep") as mock_sleep:
        with pytest.raises(LLMProviderError) as exc_info:
            provider.generate([Message(role=Role.USER, content="Hello")])

    # Initial attempt + 2 retries = 3 calls total
    assert provider._client.models.generate_content.call_count == 3
    assert mock_sleep.call_count == 2
    assert "429" in str(exc_info.value)
    assert "Resource has been exhausted" in str(exc_info.value)


def test_gemini_timeout_handling():
    """Verify client timeouts are caught and converted to LLMProviderError without crashing."""
    provider = GeminiLLMProvider(
        api_key="TEST_GEMINI_API_KEY",
        model="gemini-2.5-flash",
        timeout=5.0,
        max_retries=1,
    )

    provider._client = mock.Mock()
    provider._client.models.generate_content.side_effect = Exception("Read timed out.")

    with mock.patch("time.sleep"):
        with pytest.raises(LLMProviderError) as exc_info:
            provider.generate([Message(role=Role.USER, content="Hello")])

    assert "Gemini provider error" in str(exc_info.value)
    assert "Read timed out" in str(exc_info.value)


def test_mock_mode_availability_and_fallback_isolation():
    """Verify mock provider is fully functional and distinct from cloud providers."""
    mock_settings = Settings(llm_provider="mock", llm_model="mock-v1")
    provider = create_llm_provider(mock_settings)
    assert isinstance(provider, MockLLMProvider)
    assert provider.provider_name == "mock"

    resp = provider.generate([Message(role=Role.USER, content="Ping")])
    assert resp.role == Role.ASSISTANT
    assert "Ping" in resp.content


def test_provider_selection_validation():
    """Verify explicit provider selection rejects invalid provider strings cleanly."""
    valid_gemini = Settings(llm_provider="gemini", gemini_api_key="key")
    assert isinstance(create_llm_provider(valid_gemini), GeminiLLMProvider)

    valid_openai = Settings(llm_provider="openai", llm_api_key="TEST_OPENAI_API_KEY")
    assert isinstance(create_llm_provider(valid_openai), OpenAILLMProvider)

    invalid = Settings(llm_provider="unsupported_cloud")
    with pytest.raises(ConfigError) as exc_info:
        create_llm_provider(invalid)
    assert "Unsupported LLM provider" in str(exc_info.value)


def test_usage_observability_metadata_in_agent_response():
    """Verify non-secret metadata (latency, iterations, provider, model, request_count, cost_mode) is exposed."""
    from google.genai import types

    provider = GeminiLLMProvider(api_key="TEST_GEMINI_API_KEY", model="gemini-2.5-flash", cost_mode="free_first")
    settings = Settings(llm_provider="gemini", gemini_api_key="TEST_GEMINI_API_KEY", cost_mode="free_first", embedding_provider="none")
    memory = InMemoryConversationMemory()
    agent = FridayAgent(settings=settings, llm_provider=provider, memory=memory)

    mock_resp = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(
                    parts=[types.Part.from_text(text="All systems nominal, Surendra.")],
                    role="model",
                ),
                finish_reason=types.FinishReason.STOP,
            )
        ]
    )

    provider._client = mock.Mock()
    provider._client.models.generate_content.return_value = mock_resp

    response = agent.process_message("Status report")

    assert response.is_done is True
    assert "All systems nominal" in response.content

    meta = response.metadata
    assert "duration_seconds" in meta
    assert meta["duration_seconds"] > 0
    assert meta["iterations"] == 1
    assert meta["request_count"] == 1
    assert meta["provider"] == "gemini"
    assert meta["model"] == "gemini-2.5-flash"
    assert meta["cost_mode"] == "free_first"
    assert meta["success"] is True
    # Ensure no secrets or API keys are present in metadata
    assert "api_key" not in meta
    assert "TEST_GEMINI_API_KEY" not in str(meta)
