"""Unit tests for AI Universe LLM Provider and Fallback Chain Integration."""

import asyncio
from unittest import mock

import httpx
import pytest

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
    mock_client.aclose = mock.AsyncMock()
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


def test_ai_universe_provider_generate_inside_running_event_loop():
    """The synchronous provider remains usable from async orchestration code."""
    mock_client = mock.MagicMock()
    valid_resp = AIUniverseResponse(
        answer="Use bounded asynchronous queues.",
        confidence=0.89,
        unresolved_disagreements=[],
        key_evidence=["Load test results"],
        run_id="run_async_loop_01",
    )

    async def mock_ask(query: str, mode: str = "auto"):
        assert query == "Design a reliable queue"
        assert mode == "auto"
        return valid_resp

    mock_client.ask = mock_ask
    mock_client.aclose = mock.AsyncMock()
    mock_client.base_url = "http://localhost:8000"
    provider = AIUniverseLLMProvider(base_url="http://localhost:8000")
    provider.client = mock_client

    async def call_provider():
        return provider.generate(
            messages=[Message(role=Role.USER, content="Design a reliable queue")]
        )

    result = asyncio.run(call_provider())

    assert result.content == "Use bounded asynchronous queues."
    assert result.metadata["run_id"] == "run_async_loop_01"
    assert mock_client.aclose.await_count == 1


def test_ai_universe_provider_repeated_calls_close_each_client_loop():
    """Each synchronous call releases its loop-bound HTTP client."""
    mock_client = mock.MagicMock()
    response = AIUniverseResponse(
        answer="Use bounded queues.",
        confidence=0.89,
        key_evidence=["Load test results"],
        run_id="run_repeated",
    )
    calls: list[str] = []

    async def mock_ask(query: str, mode: str = "auto"):
        calls.append(query)
        return response

    mock_client.ask = mock_ask
    mock_client.aclose = mock.AsyncMock()
    mock_client.base_url = "http://localhost:8000"
    provider = AIUniverseLLMProvider(base_url="http://localhost:8000")
    provider.client = mock_client
    message = [Message(role=Role.USER, content="Design a queue")]

    assert provider.generate(message).content == "Use bounded queues."
    assert provider.generate(message).content == "Use bounded queues."
    assert calls == ["Design a queue", "Design a queue"]
    assert mock_client.aclose.await_count == 2


def test_ai_universe_provider_repeated_calls_use_fresh_http_clients():
    """Real AsyncClient instances are not reused across asyncio.run loops."""
    response_body = {
        "answer": "Use bounded queues.",
        "confidence": 0.89,
        "key_evidence": ["Load test results"],
        "run_id": "run_http_transport",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/friday/ask"
        return httpx.Response(200, json=response_body)

    async_client_type = httpx.AsyncClient
    created_clients: list[httpx.AsyncClient] = []

    def make_client(**kwargs):
        client = async_client_type(
            transport=httpx.MockTransport(handler), **kwargs
        )
        created_clients.append(client)
        return client

    provider = AIUniverseLLMProvider(base_url="http://localhost:8000")
    message = [Message(role=Role.USER, content="Design a queue")]
    with mock.patch("httpx.AsyncClient", side_effect=make_client):
        assert provider.generate(message).content == "Use bounded queues."
        assert provider.generate(message).content == "Use bounded queues."

    assert len(created_clients) == 2
    assert all(client.is_closed for client in created_clients)


def test_ai_universe_provider_closes_client_when_request_fails():
    """Request errors are still wrapped and cleanup runs on the request loop."""
    mock_client = mock.MagicMock()

    async def failing_ask(query: str, mode: str = "auto"):
        raise OSError("connection reset")

    mock_client.ask = failing_ask
    mock_client.aclose = mock.AsyncMock()
    mock_client.base_url = "http://localhost:8000"
    provider = AIUniverseLLMProvider(base_url="http://localhost:8000")
    provider.client = mock_client

    with pytest.raises(LLMProviderError, match="connection reset"):
        provider.generate([Message(role=Role.USER, content="Retry safely")])
    assert mock_client.aclose.await_count == 1


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
    mock_client.aclose = mock.AsyncMock()
    mock_client.base_url = "http://localhost:8000"

    provider = AIUniverseLLMProvider(base_url="http://localhost:8000", min_confidence=0.70)
    provider.client = mock_client

    messages = [Message(role=Role.USER, content="Uncertain query")]

    with pytest.raises(LLMProviderError) as exc_info:
        provider.generate(messages=messages)

    assert "below verification threshold" in str(exc_info.value)


def test_fallback_chain_includes_ai_universe_provider_as_last_resort():
    """Factory preserves peer fallback order and may prepend configured Gemini."""
    settings = Settings(
        env="testing",
        llm_provider="chain",
        groq_api_key="gsk-test",
        mistral_api_key="msk-test",
        openrouter_api_key="sk-or-test",
        gemini_api_key="",
        llm_api_key="",
        inference_url="http://localhost:8000",
        inference_api_key="friday-universe-key",
    )

    provider = create_llm_provider(settings)
    assert isinstance(provider, FallbackChainLLMProvider)
    provider_names = [p.provider_name for p in provider.providers]
    assert provider_names[-4:] == ["groq", "mistral", "openrouter", "ai_universe"]
    assert provider_names in (
        ["groq", "mistral", "openrouter", "ai_universe"],
        ["gemini", "groq", "mistral", "openrouter", "ai_universe"],
    )
