# -*- coding: utf-8 -*-
"""Comprehensive audit tests for Gemini model configurations and parameter sanitization.

Verifies:
1. GeminiLLMProvider defaults to 'gemini-3.7-flash'.
2. GenerateContentConfig for Gemini 3.7 strictly omits unsupported parameters (temperature, top_p, top_k).
3. Legacy models (e.g. 'gemini-1.5-pro') retain supported generation parameters.
4. GeminiVisionProvider defaults to 'gemini-3.7-flash' and omits temperature in SDK config.
5. GeminiLiveVoiceSession strictly isolates Live models ('gemini-3.1-flash-live-preview') and rejects text/vision models.
6. GeminiEmbeddingProvider defaults to 'gemini-embedding-2' with 768 dimensions.
"""

from unittest import mock
import pytest

from friday.core.config import Settings, get_settings
from friday.core.types import Message, Role
from friday.llm.gemini_provider import GeminiLLMProvider, is_gemini_37_model
from friday.memory.embeddings.gemini import GeminiEmbeddingProvider
from friday.vision.gemini_vision import GeminiVisionProvider
from friday.voice.gemini_live_session import GeminiLiveVoiceSession


def test_gemini_llm_provider_default_model_is_37():
    """Verify GeminiLLMProvider constructor default model is gemini-3.7-flash."""
    provider = GeminiLLMProvider(api_key="TEST_API_KEY")
    assert provider.model == "gemini-3.7-flash"
    assert is_gemini_37_model(provider.model) is True

    settings = get_settings()
    assert settings.llm_model == "gemini-3.7-flash"


def test_gemini_37_generate_content_config_omits_unsupported_parameters():
    """Verify GenerateContentConfig for Gemini 3.7 strictly excludes temperature, top_p, and top_k."""
    # Explicitly pass temperature=0.9 to constructor to test omission logic
    provider = GeminiLLMProvider(api_key="TEST_API_KEY", model="gemini-3.7-flash", temperature=0.9)
    assert provider.temperature == 0.9

    messages = [
        Message(role=Role.SYSTEM, content="You are a helpful assistant."),
        Message(role=Role.USER, content="Compute 2+2"),
    ]

    contents, config = provider._build_contents_and_config(messages=messages)

    # Prove temperature is None / unset in SDK config object
    assert config.temperature is None, f"Expected config.temperature to be None for Gemini 3.7, got {config.temperature}"
    assert config.top_p is None, f"Expected config.top_p to be None for Gemini 3.7, got {config.top_p}"
    assert config.top_k is None, f"Expected config.top_k to be None for Gemini 3.7, got {config.top_k}"
    assert config.thinking_config is not None


def test_legacy_model_generate_content_config_preserves_temperature():
    """Verify non-3.7 legacy models preserve temperature parameter in GenerateContentConfig."""
    provider = GeminiLLMProvider(api_key="TEST_API_KEY", model="gemini-1.5-pro", temperature=0.6)
    assert is_gemini_37_model(provider.model) is False

    messages = [Message(role=Role.USER, content="Hello legacy")]
    contents, config = provider._build_contents_and_config(messages=messages)

    assert config.temperature == 0.6


def test_gemini_vision_provider_model_and_parameter_sanitization():
    """Verify GeminiVisionProvider defaults to gemini-3.7-flash and omits temperature for 3.7."""
    vision = GeminiVisionProvider(api_key="TEST_API_KEY")
    assert vision.model == "gemini-3.7-flash"

    # Mock client.models.generate_content to inspect actual config passed to SDK
    mock_client = mock.MagicMock()
    with mock.patch.object(vision, "_get_client", return_value=mock_client):
        # Valid PNG header + synthetic bytes
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        vision.analyze_image(image_data=fake_png, mime_type="image/png", temperature=0.5)

        assert mock_client.models.generate_content.called
        call_kwargs = mock_client.models.generate_content.call_args[1]
        passed_config = call_kwargs.get("config")
        assert passed_config is not None
        # For Gemini 3.7, temperature must be None in GenerateContentConfig
        assert passed_config.temperature is None


def test_gemini_live_voice_session_model_isolation():
    """Verify Live voice session defaults to gemini-3.1-flash-live-preview and refuses text/vision models."""
    # 1. Default model
    session = GeminiLiveVoiceSession(api_key="TEST_API_KEY")
    assert session.model == "gemini-3.1-flash-live-preview"

    # 2. Rejection / Fallback when text/vision model is passed
    session_bad = GeminiLiveVoiceSession(api_key="TEST_API_KEY", model="gemini-3.7-flash")
    assert session_bad.model == "gemini-3.1-flash-live-preview"
    assert session_bad.model != "gemini-3.7-flash"


def test_gemini_embedding_provider_model_and_dimension():
    """Verify GeminiEmbeddingProvider defaults to gemini-embedding-2 with 768 dimensions."""
    embedder = GeminiEmbeddingProvider(api_key="TEST_API_KEY")
    assert embedder.model == "gemini-embedding-2"
    assert embedder.dimension == 768

    settings = get_settings()
    assert settings.embedding_model == "gemini-embedding-2"
    assert settings.embedding_dimension == 768
