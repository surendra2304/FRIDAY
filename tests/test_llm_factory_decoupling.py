# -*- coding: utf-8 -*-
"""Unit tests for LLM provider factory model decoupling."""

from unittest.mock import patch
import pytest

from friday.core.config import Settings
from friday.llm.factory import create_llm_provider
from friday.llm.groq_provider import GROQ_DEFAULT_MODEL, GroqLLMProvider
from friday.llm.mistral_provider import MISTRAL_DEFAULT_MODEL, MistralLLMProvider
from friday.llm.openrouter_provider import OPENROUTER_DEFAULT_MODEL, OpenRouterLLMProvider
from friday.llm.gemini_provider import GeminiLLMProvider
from friday.llm.fallback_chain_provider import FallbackChainLLMProvider


def test_chain_mode_decouples_gemini_from_other_providers():
    """Verify chain mode does not pass Gemini model names to Groq, Mistral, or OpenRouter."""
    settings = Settings(
        llm_provider="chain",
        llm_model="gemini-2.5-flash",
        gemini_api_key="mock_key",
        groq_api_key="mock_key",
        mistral_api_key="mock_key",
        openrouter_api_key="mock_key",
    )

    provider = create_llm_provider(settings)
    assert isinstance(provider, FallbackChainLLMProvider)

    # Check child providers
    for p in provider.providers:
        if isinstance(p, GroqLLMProvider):
            assert p.model == GROQ_DEFAULT_MODEL
            assert "gemini" not in p.model.lower()
        elif isinstance(p, MistralLLMProvider):
            assert p.model == MISTRAL_DEFAULT_MODEL
            assert "gemini" not in p.model.lower()
        elif isinstance(p, OpenRouterLLMProvider):
            assert p.model == OPENROUTER_DEFAULT_MODEL
            assert "gemini" not in p.model.lower()
        elif isinstance(p, GeminiLLMProvider):
            assert p.model == "gemini-2.5-flash"


def test_groq_standalone_rejects_gemini_model_name():
    """Verify standalone Groq provider falls back to GROQ_DEFAULT_MODEL if Gemini model specified."""
    settings = Settings(
        llm_provider="groq",
        llm_model="gemini-3.6-flash",
        groq_api_key="mock_key",
    )

    provider = create_llm_provider(settings)
    assert isinstance(provider, GroqLLMProvider)
    assert provider.model == GROQ_DEFAULT_MODEL


def test_mistral_standalone_rejects_gemini_model_name():
    """Verify standalone Mistral provider falls back to MISTRAL_DEFAULT_MODEL if Gemini model specified."""
    settings = Settings(
        llm_provider="mistral",
        llm_model="gemini-3.6-flash",
        mistral_api_key="mock_key",
    )

    provider = create_llm_provider(settings)
    assert isinstance(provider, MistralLLMProvider)
    assert provider.model == MISTRAL_DEFAULT_MODEL
