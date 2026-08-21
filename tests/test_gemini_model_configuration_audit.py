# -*- coding: utf-8 -*-
"""Comprehensive audit tests for Gemini model configurations and parameter sanitization.

Verifies:
1. GeminiLLMProvider defaults to 'gemini-1.5-flash-latest'.
2. GenerateContentConfig for 3.7-family models (explicitly configured) omits unsupported parameters.
3. Legacy models (e.g. 'gemini-1.5-pro') retain supported generation parameters.
4. GeminiVisionProvider defaults to 'gemini-1.5-flash-latest' and omits temperature in SDK config.
5. GeminiLiveVoiceSession strictly isolates Live models ('gemini-2.0-flash-exp') and rejects text/vision models.
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


def test_gemini_llm_provider_default_model():
    """Verify GeminiLLMProvider constructor default model is gemini-1.5-flash-latest."""
    provider = GeminiLLMProvider(api_key="TEST_API_KEY")
    assert provider.model == "gemini-1.5-flash-latest"
    assert is_gemini_37_model(provider.model) is False

    settings = get_settings()
    assert settings.llm_model == "gemini-1.5-flash-latest"


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
    """Verify GeminiVisionProvider defaults to gemini-1.5-flash-latest and omits temperature for 3.7."""
    vision = GeminiVisionProvider(api_key="TEST_API_KEY")
    assert vision.model == "gemini-1.5-flash-latest"

    # For 3.7-family models temperature must be omitted from GenerateContentConfig
    mock_client = mock.MagicMock()
    vision37 = GeminiVisionProvider(api_key="TEST_API_KEY", model="gemini-3.7-flash")
    with mock.patch.object(vision37, "_get_client", return_value=mock_client):
        # Valid PNG header + synthetic bytes
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        vision37.analyze_image(image_data=fake_png, mime_type="image/png", temperature=0.5)

        assert mock_client.models.generate_content.called
        call_kwargs = mock_client.models.generate_content.call_args[1]
        passed_config = call_kwargs.get("config")
        assert passed_config is not None
        assert passed_config.temperature is None


def test_gemini_live_voice_session_model_isolation():
    """Verify Live voice session defaults to gemini-2.0-flash-exp and refuses text/vision models."""
    # 1. Default model
    session = GeminiLiveVoiceSession(api_key="TEST_API_KEY")
    assert session.model == "gemini-2.0-flash-exp"

    # 2. Rejection / Fallback when text/vision model is passed
    session_bad = GeminiLiveVoiceSession(api_key="TEST_API_KEY", model="gemini-1.5-flash-latest")
    assert session_bad.model == "gemini-2.0-flash-exp"
    assert session_bad.model != "gemini-1.5-flash-latest"


def test_gemini_embedding_provider_model_and_dimension():
    """Verify GeminiEmbeddingProvider defaults to gemini-embedding-2 with 768 dimensions."""
    embedder = GeminiEmbeddingProvider(api_key="TEST_API_KEY")
    assert embedder.model == "gemini-embedding-2"
    assert embedder.dimension == 768

    settings = get_settings()
    assert settings.embedding_model == "gemini-embedding-2"
    assert settings.embedding_dimension == 768


def test_gemini_37_build_gemini_payload_omits_unsupported_parameters():
    """Verify _build_gemini_payload compatibility method omits temperature for Gemini 3.7 models."""
    for model_name in ["gemini-3.7-flash", "gemini-3.7-pro", "models/gemini-3.7-flash"]:
        provider = GeminiLLMProvider(api_key="TEST_API_KEY", model=model_name, temperature=0.85)
        messages = [
            Message(role=Role.SYSTEM, content="System prompt"),
            Message(role=Role.USER, content="Hello"),
        ]
        payload = provider._build_gemini_payload(messages=messages)

        gen_config = payload.get("generationConfig", {})
        assert "temperature" not in gen_config, f"temperature found in generationConfig for {model_name}"
        assert "top_p" not in gen_config, f"top_p found in generationConfig for {model_name}"
        assert "top_k" not in gen_config, f"top_k found in generationConfig for {model_name}"
        assert "thinking_config" in gen_config
        assert gen_config["thinking_config"]["thinking_level"] == "MEDIUM"


def test_legacy_build_gemini_payload_retains_temperature():
    """Verify _build_gemini_payload compatibility method retains temperature for legacy non-3.7 models."""
    provider = GeminiLLMProvider(api_key="TEST_API_KEY", model="gemini-2.5-flash", temperature=0.65)
    messages = [Message(role=Role.USER, content="Hello legacy")]
    payload = provider._build_gemini_payload(messages=messages)

    gen_config = payload.get("generationConfig", {})
    assert gen_config.get("temperature") == 0.65
    assert "thinking_config" not in gen_config

