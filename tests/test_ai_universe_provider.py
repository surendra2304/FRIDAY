# -*- coding: utf-8 -*-
"""Unit tests for AI Universe LLM Provider and Fallback Chain Integration."""

from unittest import mock
import pytest
import httpx

from friday.core.config import Settings
from friday.core.exceptions import LLMProviderError
from friday.core.types import Message, Role
from friday.llm.ai_universe_provider import AIUniverseLLMProvider
from friday.llm.factory import create_llm_provider
from friday.llm.fallback_chain_provider import FallbackChainLLMProvider
from friday.tools.ai_universe_client import AIUniverseResponse


def test_ai_universe_provider_generate_success():
    """AIUniverseLLMProvider queries /v1/friday/ask and returns standard Message."""
    mock_client = mock.MagicMock()
    valid_resp = AIUniverseResponse(
        answer="The optimal solution is to use asynchronous message queues with backpressure.",
        confidence=0.89,
        unresolved_disagreements=[],
        key_evidence=["Throughput benchmarks"],
        run_id="run_llm_01",
    )

    async def mock_ask(query: str, mode: str = "auto"):
        assert "distributed systems" in query
        return valid_resp

    mock_client.ask = mock_ask
    mock_client.base_url = "http://localhost:8000"

    provider = AIUniverseLLMProvider(base_url="http://localhost:8000", api_key="secret-key")
    provider.client = mock_client

    messages = [
        Message(role=Role.USER, content="Design a reliable architecture for distributed systems"),
    ]

    result = provider.generate(messages=messages)
    assert result.role == Role.ASSISTANT
    assert "asynchronous message queues" in result.content
    assert result.metadata["run_id"] == "run_llm_01"
    assert result.metadata["confidence"] == 0.89


def test_ai_universe_provider_low_confidence_raises_error():
    """AIUniverseLLMProvider raises LLMProviderError when response confidence is low."""
    mock_client = mock.MagicMock()
    low_conf_resp = AIUniverseResponse(
        answer="Maybe try approach X.",
        confidence=0.55,
        unresolved_disagreements=["Conflicting benchmarks"],
        key_evidence=[],
        run_id="run_low_02",
    )

    async def mock_ask(query: str, mode: str = "auto"):
        return low_conf_resp

    mock_client.ask = mock_ask
    mock_client.base_url = "http://localhost:8000"

    provider = AIUniverseLLMProvider(base_url="http://localhost:8000", min_confidence=0.70)
    provider.client = mock_client

    messages = [Message(role=Role.USER, content="Uncertain query")]

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate(messages=messages)

    assert "below verification threshold" in str(exc_info.value)


def test_fallback_chain_includes_ai_universe_provider_as_last_resort():
    """Factory constructs fallback chain: Groq -> Cerebras -> Mistral -> OpenRouter -> AIUniverse."""
    settings = Settings(
        env="testing",
        llm_provider="chain",
        groq_api_key="gsk-test",
        cerebras_api_key="csk-test",
        mistral_api_key="msk-test",
        openrouter_api_key="sk-or-test",
        universe_api_url="http://localhost:8000",
        api_key="friday-universe-key",
    )

    provider = create_llm_provider(settings)
    assert isinstance(provider, FallbackChainLLMProvider)
    provider_names = [p.provider_name for p in provider.providers]
    assert provider_names == ["groq", "cerebras", "mistral", "openrouter", "ai_universe"]
