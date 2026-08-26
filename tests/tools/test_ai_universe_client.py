# -*- coding: utf-8 -*-
"""Unit tests for AI Universe Client (Phase 20) with httpx mocking."""

import os
from unittest import mock
import pytest
import httpx

from friday.core.verification import evaluate_ai_universe_response
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.ai_universe_client import AIUniverseClient, AIUniverseResponse, AIUniverseTool


@pytest.mark.anyio
async def test_ai_universe_client_ask():
    """Test AIUniverseClient ask() method with mocked httpx response."""
    client = AIUniverseClient(
        base_url="http://localhost:8000",
        api_key="test-api-key-universe",
    )

    mock_resp = {
        "answer": "FastAPI with async handlers is recommended.",
        "confidence": 0.95,
        "unresolved_disagreements": [],
        "key_evidence": ["High benchmark QPS", "Native async support"],
        "run_id": "run_ask_101",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://localhost:8000/v1/friday/ask"
        assert request.headers.get("X-FRIDAY-API-Key") == "test-api-key-universe"
        assert b"Which framework?" in request.content
        return httpx.Response(200, json=mock_resp)

    transport = httpx.MockTransport(handler)
    with mock.patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        res = await client.ask("Which framework?", mode="auto")
        assert res.answer == "FastAPI with async handlers is recommended."
        assert res.confidence == 0.95
        assert res.run_id == "run_ask_101"
        assert len(res.key_evidence) == 2


@pytest.mark.anyio
async def test_ai_universe_client_debate():
    """Test AIUniverseClient debate() method with mocked httpx response."""
    client = AIUniverseClient(
        base_url="http://localhost:8000",
        api_key="test-api-key-universe",
    )

    mock_resp = {
        "answer": "Microservices vs Monolith consensus: Start with modular monolith.",
        "confidence": 0.88,
        "unresolved_disagreements": ["Team scaling threshold"],
        "key_evidence": ["Reduced operational complexity"],
        "run_id": "run_deb_202",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://localhost:8000/v1/friday/debate"
        assert request.headers.get("X-FRIDAY-API-Key") == "test-api-key-universe"
        assert b"Microservices vs Monolith" in request.content
        return httpx.Response(200, json=mock_resp)

    transport = httpx.MockTransport(handler)
    with mock.patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        res = await client.debate("Microservices vs Monolith", max_agents=5)
        assert res.answer.startswith("Microservices vs Monolith")
        assert res.confidence == 0.88
        assert res.run_id == "run_deb_202"
        assert res.unresolved_disagreements == ["Team scaling threshold"]


def test_ai_universe_verification_rules():
    """Verify confidence gating (< 0.70) and security keyword checks."""
    # Low confidence
    is_valid, reason, ext = evaluate_ai_universe_response({
        "answer": "Maybe approach X",
        "confidence": 0.60,
        "unresolved_disagreements": [],
        "key_evidence": [],
        "run_id": "r_low",
    })
    assert not is_valid
    assert reason == "Needs Human Review"

    # Security keywords
    is_valid, reason, ext = evaluate_ai_universe_response({
        "answer": "Execute command with sudo",
        "confidence": 0.90,
        "unresolved_disagreements": ["Potential vulnerability with privilege escalation"],
        "key_evidence": [],
        "run_id": "r_sec",
    })
    assert not is_valid
    assert "Flagged for User Authorization" in reason
    assert ext.get("requires_user_authorization") is True

    # High confidence & valid
    is_valid, reason, ext = evaluate_ai_universe_response({
        "answer": "Use Redis for rate limiting",
        "confidence": 0.92,
        "unresolved_disagreements": [],
        "key_evidence": ["Sub-millisecond latency"],
        "run_id": "r_high",
    })
    assert is_valid
    assert reason == "Verified"
    assert ext["answer"] == "Use Redis for rate limiting"


def test_ai_universe_tool_memory_persistence():
    """Tool integrates with memory to persist structured semantic records and run_id."""
    memory = InMemoryConversationMemory()
    mock_client = mock.MagicMock(spec=AIUniverseClient)

    valid_response = AIUniverseResponse(
        answer="PostgreSQL with pgvector outperforms dedicated vector stores for hybrid workloads.",
        confidence=0.94,
        unresolved_disagreements=[],
        key_evidence=["pgvector indexing benchmarks"],
        run_id="run_mem_303",
    )

    async def mock_ask(*args, **kwargs):
        return valid_response

    mock_client.ask = mock_ask
    tool = AIUniverseTool(client=mock_client, memory=memory)

    result = tool.execute(question="PostgreSQL vs Pinecone for hybrid search", mode="ask")
    assert not result.is_error
    assert "PostgreSQL with pgvector" in result.content

    messages = memory.get_messages()
    assert len(messages) == 1
    assert "AI Universe Validated Fact" in messages[0].content
    assert messages[0].metadata.get("run_id") == "run_mem_303"
