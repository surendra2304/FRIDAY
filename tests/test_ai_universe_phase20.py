# -*- coding: utf-8 -*-
"""Unit tests for Phase 20: AI Universe Integration & Verification Logic."""

from unittest import mock
import pytest
import httpx

from friday.core.config import Settings
from friday.core.types import SafetyLevel
from friday.core.verification import evaluate_ai_universe_response
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.ai_universe_client import AIUniverseClient, AIUniverseResponse, AIUniverseTool


def test_ai_universe_verification_confidence_gating():
    """Rule 1: If confidence < 0.70, reject and return Needs Human Review."""
    low_conf_payload = {
        "answer": "Option B is slightly better.",
        "confidence": 0.65,
        "unresolved_disagreements": [],
        "key_evidence": ["benchmark A"],
        "run_id": "run_low_01",
    }
    is_valid, reason, extracted = evaluate_ai_universe_response(low_conf_payload)
    assert not is_valid
    assert reason == "Needs Human Review"
    assert extracted["run_id"] == "run_low_01"


def test_ai_universe_verification_security_flagging():
    """Rule 2: If unresolved disagreements contain security keywords, flag for user authorization."""
    security_payload = {
        "answer": "Deploy microservice with root container privileges.",
        "confidence": 0.88,
        "unresolved_disagreements": ["High critical vulnerability in privilege escalation"],
        "key_evidence": ["Docker documentation"],
        "run_id": "run_sec_02",
    }
    is_valid, reason, extracted = evaluate_ai_universe_response(security_payload)
    assert not is_valid
    assert "Flagged for User Authorization" in reason
    assert extracted.get("requires_user_authorization") is True
    assert "critical" in extracted.get("security_flags", [])
    assert "vulnerability" in extracted.get("security_flags", [])


def test_ai_universe_verification_high_confidence_success():
    """Rule 3: High confidence (>= 0.70) without security issues is verified."""
    valid_payload = {
        "answer": "Event-driven CQRS architecture is optimal for this throughput.",
        "confidence": 0.94,
        "unresolved_disagreements": [],
        "key_evidence": ["Latency tests", "Throughput metrics"],
        "run_id": "run_valid_03",
    }
    is_valid, reason, extracted = evaluate_ai_universe_response(valid_payload)
    assert is_valid
    assert reason == "Verified"
    assert extracted["answer"].startswith("Event-driven")
    assert len(extracted["key_evidence"]) == 2


@pytest.mark.anyio
async def test_ai_universe_client_header_injection_and_ask():
    """AIUniverseClient injects X-FRIDAY-API-Key and parses ask responses."""
    client = AIUniverseClient(
        base_url="http://localhost:8000",
        api_key="friday-secret-key-123",
    )

    mock_resp_data = {
        "answer": "Consensus reached on PostgreSQL.",
        "confidence": 0.92,
        "unresolved_disagreements": [],
        "key_evidence": ["ACID compliance"],
        "run_id": "run_ask_01",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://localhost:8000/v1/friday/ask"
        assert request.headers.get("X-FRIDAY-API-Key") == "friday-secret-key-123"
        return httpx.Response(200, json=mock_resp_data)

    transport = httpx.MockTransport(handler)
    with mock.patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        res = await client.ask("Which database should we choose?")
        assert res.answer == "Consensus reached on PostgreSQL."
        assert res.confidence == 0.92
        assert res.run_id == "run_ask_01"


@pytest.mark.anyio
async def test_ai_universe_client_debate_endpoint():
    """AIUniverseClient calls /v1/friday/debate with max_agents payload."""
    client = AIUniverseClient(
        base_url="http://localhost:8000",
        api_key="friday-test-key",
    )

    mock_resp_data = {
        "answer": "Hybrid search beats pure vector search for keyword queries.",
        "confidence": 0.85,
        "unresolved_disagreements": ["Latency overhead under peak spike"],
        "key_evidence": ["Recall comparison benchmark"],
        "run_id": "run_debate_01",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://localhost:8000/v1/friday/debate"
        assert request.headers.get("X-FRIDAY-API-Key") == "friday-test-key"
        return httpx.Response(200, json=mock_resp_data)

    transport = httpx.MockTransport(handler)
    with mock.patch("httpx.AsyncClient", return_value=httpx.AsyncClient(transport=transport)):
        res = await client.debate("Vector vs Hybrid memory search?", max_agents=4)
        assert res.confidence == 0.85
        assert res.run_id == "run_debate_01"


def test_ai_universe_tool_execution_with_memory_integration():
    """Tool executes, verifies response, and stores validated fact in memory."""
    memory = InMemoryConversationMemory(max_messages=10)
    mock_client = mock.MagicMock(spec=AIUniverseClient)

    valid_response = AIUniverseResponse(
        answer="Microservices with gRPC provide the lowest inter-service latency.",
        confidence=0.91,
        unresolved_disagreements=[],
        key_evidence=["gRPC protobuf serialization benchmarks"],
        run_id="run_tool_01",
    )

    async def mock_debate(*args, **kwargs):
        return valid_response

    mock_client.debate = mock_debate
    tool = AIUniverseTool(client=mock_client, memory=memory)

    result = tool.execute(question="Debate REST vs gRPC for internal services", mode="debate")
    assert not result.is_error
    assert "AI Universe Consensus" in result.content
    assert "91.0%" in result.content

    # Check memory persistence
    messages = memory.get_messages()
    assert len(messages) == 1
    assert "AI Universe Validated Fact" in messages[0].content
    assert messages[0].metadata.get("run_id") == "run_tool_01"
    assert messages[0].metadata.get("type") == "validated_fact"
