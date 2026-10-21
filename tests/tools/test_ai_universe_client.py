"""Unit tests for AI Universe Client (AI Universe Integration) with httpx mocking."""

import asyncio
from unittest import mock

import httpx
import pytest

from friday.core.verification import evaluate_ai_universe_response
from friday.memory.in_memory import InMemoryConversationMemory
from friday.tools.ai_universe_client import (
    AIUniverseClient,
    AIUniverseResponse,
    AIUniverseTool,
    GetAIUniverseStatusTool,
)


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


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method_name, endpoint",
    [
        ("ask", "/v1/friday/ask"),
        ("debate", "/v1/friday/debate"),
    ],
)
async def test_ai_universe_client_rejects_non_object_ask_and_debate_json(method_name, endpoint):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == endpoint
        return httpx.Response(200, json=["unexpected", "array"])

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AIUniverseClient(base_url="http://inference.test")
    with mock.patch("httpx.AsyncClient", return_value=http_client):
        try:
            with pytest.raises(
                ValueError,
                match=(
                    rf"AI Universe {endpoint} response must be a JSON object, "
                    r"got list"
                ),
            ):
                await getattr(client, method_name)("question")
        finally:
            await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "method_name, endpoint",
    [
        ("ask", "/v1/friday/ask"),
        ("debate", "/v1/friday/debate"),
    ],
)
async def test_ai_universe_client_raises_http_error_before_parsing_error_body(
    method_name, endpoint
):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == endpoint
        return httpx.Response(422, json=["validation", "failed"])

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AIUniverseClient(base_url="http://inference.test")
    with mock.patch("httpx.AsyncClient", return_value=http_client):
        try:
            with pytest.raises(httpx.HTTPStatusError) as exc_info:
                await getattr(client, method_name)("question")

            assert exc_info.value.response.status_code == 422
            assert exc_info.value.response.json() == ["validation", "failed"]
        finally:
            await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("method_name", ["ask", "debate"])
async def test_ai_universe_client_propagates_cancellation(method_name):
    cancellation = asyncio.CancelledError("request cancelled")

    class CancellingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise cancellation

    http_client = httpx.AsyncClient(transport=CancellingTransport())
    client = AIUniverseClient(base_url="http://inference.test")
    with mock.patch("httpx.AsyncClient", return_value=http_client):
        try:
            with pytest.raises(asyncio.CancelledError) as exc_info:
                await getattr(client, method_name)("question")

            assert exc_info.value is cancellation
        finally:
            await client.aclose()

    assert http_client.is_closed


@pytest.mark.anyio
async def test_ai_universe_client_rejects_non_object_status_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"status": "healthy"}])

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AIUniverseClient(base_url="http://inference.test")
    with mock.patch("httpx.AsyncClient", return_value=http_client):
        try:
            with pytest.raises(
                ValueError,
                match="AI Universe status response must be a JSON object, got list",
            ):
                await client.get_status()
        finally:
            await client.aclose()


@pytest.mark.anyio
async def test_ai_universe_client_rejects_non_list_agents_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"agents": []})

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AIUniverseClient(base_url="http://inference.test")
    with mock.patch("httpx.AsyncClient", return_value=http_client):
        try:
            with pytest.raises(
                ValueError,
                match="AI Universe agents response must be a JSON array, got dict",
            ):
                await client.get_agents()
        finally:
            await client.aclose()


@pytest.mark.anyio
async def test_ai_universe_client_rejects_non_object_agent_with_index():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": "agent-1"}, "invalid agent"])

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AIUniverseClient(base_url="http://inference.test")
    with mock.patch("httpx.AsyncClient", return_value=http_client):
        try:
            with pytest.raises(
                ValueError,
                match=(
                    "AI Universe agents response item at index 1 must be a JSON object, "
                    "got str"
                ),
            ):
                await client.get_agents()
        finally:
            await client.aclose()


@pytest.mark.anyio
async def test_ai_universe_client_includes_index_in_invalid_agent_field_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[{"id": "agent-1"}, {"id": "agent-2", "strengths": "not-a-list"}],
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AIUniverseClient(base_url="http://inference.test")
    with mock.patch("httpx.AsyncClient", return_value=http_client):
        try:
            with pytest.raises(ValueError) as exc_info:
                await client.get_agents()
        finally:
            await client.aclose()

    error = str(exc_info.value)
    assert "AI Universe agents response item at index 1 failed validation" in error
    assert "strengths" in error
    assert "Input should be a valid list" in error


@pytest.mark.anyio
async def test_ai_universe_client_accepts_empty_agents_array():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AIUniverseClient(base_url="http://inference.test")
    with mock.patch("httpx.AsyncClient", return_value=http_client):
        try:
            assert await client.get_agents() == []
        finally:
            await client.aclose()


def test_ai_universe_tool_reports_malformed_agents_response_as_error():
    clients: list[httpx.AsyncClient] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/friday/agents"
        return httpx.Response(200, json={"agents": []})

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = AIUniverseTool(client=AIUniverseClient(base_url="http://inference.test"))

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        result = tool.execute(mode="agents")

    assert result.is_error
    assert "AI Universe agents response must be a JSON array, got dict" in result.content
    assert len(clients) == 1
    assert clients[0].is_closed


def test_ai_universe_tool_reports_non_object_agent_with_index_as_error():
    clients: list[httpx.AsyncClient] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/friday/agents"
        return httpx.Response(200, json=[{"id": "agent-1"}, "invalid agent"])

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = AIUniverseTool(client=AIUniverseClient(base_url="http://inference.test"))

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        result = tool.execute(mode="agents")

    assert result.is_error
    assert (
        "AI Universe agents response item at index 1 must be a JSON object, got str"
        in result.content
    )
    assert len(clients) == 1
    assert clients[0].is_closed


def test_ai_universe_tool_reports_invalid_agent_field_with_index_as_error():
    clients: list[httpx.AsyncClient] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/friday/agents"
        return httpx.Response(
            200,
            json=[{"id": "agent-1"}, {"id": "agent-2", "strengths": "not-a-list"}],
        )

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = AIUniverseTool(client=AIUniverseClient(base_url="http://inference.test"))

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        result = tool.execute(mode="agents")

    assert result.is_error
    assert "AI Universe agents response item at index 1 failed validation" in result.content
    assert "strengths" in result.content
    assert "Input should be a valid list" in result.content
    assert len(clients) == 1
    assert clients[0].is_closed


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


@pytest.mark.parametrize("mode", ["ask", "debate", "agents", "info"])
def test_ai_universe_tool_runs_inside_active_event_loop(mode):
    """Synchronous tool calls bridge to a worker loop instead of nesting loops."""
    client = mock.MagicMock(spec=AIUniverseClient)
    client.ask = mock.AsyncMock(return_value=AIUniverseResponse(answer="A valid answer", confidence=0.95))
    client.debate = mock.AsyncMock(return_value=AIUniverseResponse(answer="A valid answer", confidence=0.95))
    client.get_agents = mock.AsyncMock(return_value=[])
    client.get_info = mock.AsyncMock(return_value={"version": "1"})
    tool = AIUniverseTool(client=client)

    async def invoke():
        return tool.execute(question="A question", mode=mode)

    result = asyncio.run(invoke())
    assert not result.is_error
    {
        "ask": client.ask,
        "debate": client.debate,
        "agents": client.get_agents,
        "info": client.get_info,
    }[mode].assert_awaited_once()


def test_status_tool_runs_inside_active_event_loop():
    client = mock.MagicMock(spec=AIUniverseClient)
    client.get_status = mock.AsyncMock(return_value={"status": "healthy"})
    tool = GetAIUniverseStatusTool(client=client)

    async def invoke():
        return tool.execute()

    result = asyncio.run(invoke())
    assert not result.is_error
    assert result.metadata == {"status": "healthy"}
    client.get_status.assert_awaited_once()


def test_ai_universe_tool_preserves_error_result_inside_active_event_loop():
    client = mock.MagicMock(spec=AIUniverseClient)
    client.base_url = "http://inference.test"
    client.ask = mock.AsyncMock(side_effect=RuntimeError("provider unavailable"))
    tool = AIUniverseTool(client=client)

    async def invoke():
        return tool.execute(question="A question", mode="ask")

    result = asyncio.run(invoke())
    assert result.is_error
    assert "provider unavailable" in result.content


@pytest.mark.parametrize("mode, path", [("ask", "/v1/friday/ask"), ("debate", "/v1/friday/debate")])
@pytest.mark.parametrize("status_code", [422, 503])
@pytest.mark.parametrize("inside_active_loop", [False, True])
def test_ai_universe_tool_reports_http_errors_and_closes_client(
    mode, path, status_code, inside_active_loop
):
    clients: list[httpx.AsyncClient] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path
        return httpx.Response(status_code, json={"detail": "request failed"})

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = AIUniverseTool(client=AIUniverseClient(base_url="http://inference.test"))

    def invoke():
        return tool.execute(question="A question", mode=mode)

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        if inside_active_loop:
            async def invoke_inside_loop():
                return invoke()

            result = asyncio.run(invoke_inside_loop())
        else:
            result = invoke()

    assert result.is_error
    assert str(status_code) in result.content
    assert len(clients) == 1
    assert clients[0].is_closed


@pytest.mark.parametrize("mode, path", [("ask", "/v1/friday/ask"), ("debate", "/v1/friday/debate")])
@pytest.mark.parametrize("inside_active_loop", [False, True])
def test_ai_universe_tool_reports_malformed_json_and_closes_client(
    mode, path, inside_active_loop
):
    clients: list[httpx.AsyncClient] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path
        return httpx.Response(200, content=b"not-json")

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = AIUniverseTool(client=AIUniverseClient(base_url="http://inference.test"))

    def invoke():
        return tool.execute(question="A question", mode=mode)

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        if inside_active_loop:
            async def invoke_inside_loop():
                return invoke()

            result = asyncio.run(invoke_inside_loop())
        else:
            result = invoke()

    assert result.is_error
    assert "Expecting value" in result.content
    assert len(clients) == 1
    assert clients[0].is_closed


@pytest.mark.parametrize("mode, path", [("ask", "/v1/friday/ask"), ("debate", "/v1/friday/debate")])
def test_ai_universe_tool_propagates_cancellation_inside_active_event_loop(mode, path):
    cancellation = asyncio.CancelledError("request cancelled")
    clients: list[httpx.AsyncClient] = []

    class CancellingTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            assert request.url.path == path
            raise cancellation

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=CancellingTransport(), **kwargs)
        clients.append(client)
        return client

    tool = AIUniverseTool(client=AIUniverseClient(base_url="http://inference.test"))

    async def invoke():
        return tool.execute(question="A question", mode=mode)

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        with pytest.raises(asyncio.CancelledError) as exc_info:
            asyncio.run(invoke())

    assert exc_info.value is cancellation
    assert len(clients) == 1
    assert clients[0].is_closed


def test_status_tool_preserves_error_result_inside_active_event_loop():
    client = mock.MagicMock(spec=AIUniverseClient)
    client.base_url = "http://inference.test"
    client.get_status = mock.AsyncMock(side_effect=RuntimeError("status unavailable"))
    client.get_agents = mock.AsyncMock(return_value=[])
    tool = GetAIUniverseStatusTool(client=client)

    async def invoke():
        return tool.execute()

    result = asyncio.run(invoke())
    assert result.is_error
    assert "status unavailable" in result.content


def test_status_tool_reports_status_and_agent_fallback_errors():
    client = mock.MagicMock(spec=AIUniverseClient)
    client.base_url = "http://inference.test"
    client.get_status = mock.AsyncMock(side_effect=RuntimeError("status unavailable"))
    client.get_agents = mock.AsyncMock(side_effect=RuntimeError("agent discovery unavailable"))
    tool = GetAIUniverseStatusTool(client=client)

    result = tool.execute()

    assert result.is_error
    assert "status unavailable" in result.content
    assert "agent discovery unavailable" in result.content


@pytest.mark.parametrize("mode, path", [("ask", "/v1/friday/ask"), ("debate", "/v1/friday/debate")])
def test_ai_universe_tool_recreates_closed_http_client_inside_active_event_loop(mode, path):
    clients: list[httpx.AsyncClient] = []
    requests: list[str] = []
    response = {
        "answer": "A valid answer",
        "confidence": 0.95,
        "unresolved_disagreements": [],
        "key_evidence": ["Mocked evidence"],
        "run_id": "run_repeated_tool_call",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json=response)

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = AIUniverseTool(client=AIUniverseClient(base_url="http://inference.test"))

    async def invoke_twice():
        results = [
            tool.execute(question="A question", mode=mode),
            tool.execute(question="A question", mode=mode),
        ]
        return results

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        results = asyncio.run(invoke_twice())

    assert all(not result.is_error for result in results)
    assert requests == [path, path]
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)


def test_status_tool_recreates_closed_http_client_inside_active_event_loop():
    clients: list[httpx.AsyncClient] = []
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(200, json={"status": "healthy"})

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = GetAIUniverseStatusTool(client=AIUniverseClient(base_url="http://inference.test"))

    async def invoke_twice():
        return [tool.execute(), tool.execute()]

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        results = asyncio.run(invoke_twice())

    assert all(not result.is_error for result in results)
    assert requests == ["/v1/friday/status", "/v1/friday/status"]
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)


def test_status_tool_falls_back_to_agent_roster_inside_active_event_loop():
    clients: list[httpx.AsyncClient] = []
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/friday/status":
            return httpx.Response(503, json={"detail": "status unavailable"})
        assert request.url.path == "/v1/friday/agents"
        return httpx.Response(
            200,
            json=[{"id": "analyst", "name": "Analyst", "role": "Research"}],
        )

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = GetAIUniverseStatusTool(client=AIUniverseClient(base_url="http://inference.test"))

    async def invoke():
        return tool.execute()

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        result = asyncio.run(invoke())

    assert not result.is_error
    assert "Analyst" in result.content
    assert result.metadata["agents"][0]["id"] == "analyst"
    assert requests == ["/v1/friday/status", "/v1/friday/agents"]
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)


def test_status_tool_falls_back_when_status_response_has_malformed_json_inside_active_event_loop():
    clients: list[httpx.AsyncClient] = []
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/friday/status":
            return httpx.Response(200, content=b"{")
        assert request.url.path == "/v1/friday/agents"
        return httpx.Response(
            200,
            json=[{"id": "analyst", "name": "Analyst", "role": "Research"}],
        )

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = GetAIUniverseStatusTool(client=AIUniverseClient(base_url="http://inference.test"))

    async def invoke():
        return tool.execute()

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        result = asyncio.run(invoke())

    assert not result.is_error
    assert "Analyst" in result.content
    assert result.metadata["agents"][0]["id"] == "analyst"
    assert requests == ["/v1/friday/status", "/v1/friday/agents"]
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)


def test_status_tool_reports_failed_agent_fallback_inside_active_event_loop():
    clients: list[httpx.AsyncClient] = []
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/friday/status":
            return httpx.Response(503, json={"detail": "status unavailable"})
        assert request.url.path == "/v1/friday/agents"
        return httpx.Response(502, json={"detail": "agent discovery unavailable"})

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = GetAIUniverseStatusTool(client=AIUniverseClient(base_url="http://inference.test"))

    async def invoke():
        return tool.execute()

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        result = asyncio.run(invoke())

    assert result.is_error
    assert "503 Service Unavailable" in result.content
    assert "502 Bad Gateway" in result.content
    assert requests == ["/v1/friday/status", "/v1/friday/agents"]
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)


def test_status_tool_reports_transport_errors_from_status_and_agent_fallback():
    clients: list[httpx.AsyncClient] = []
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/friday/status":
            raise httpx.ConnectError("status connection failed", request=request)
        assert request.url.path == "/v1/friday/agents"
        raise httpx.ConnectError("agent discovery connection failed", request=request)

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = GetAIUniverseStatusTool(client=AIUniverseClient(base_url="http://inference.test"))

    async def invoke():
        return tool.execute()

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        result = asyncio.run(invoke())

    assert result.is_error
    assert "status connection failed" in result.content
    assert "agent discovery connection failed" in result.content
    assert requests == ["/v1/friday/status", "/v1/friday/agents"]
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)


def test_status_tool_reports_read_timeout_inside_active_event_loop():
    clients: list[httpx.AsyncClient] = []
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/friday/status":
            raise httpx.ReadTimeout("status read timed out", request=request)
        assert request.url.path == "/v1/friday/agents"
        raise httpx.ConnectError("agent discovery unavailable", request=request)

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = GetAIUniverseStatusTool(client=AIUniverseClient(base_url="http://inference.test"))

    async def invoke():
        return tool.execute()

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        result = asyncio.run(invoke())

    assert result.is_error
    assert "status read timed out" in result.content
    assert "agent discovery unavailable" in result.content
    assert requests == ["/v1/friday/status", "/v1/friday/agents"]
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)


def test_status_tool_recovers_from_read_timeout_with_agent_roster_inside_active_event_loop():
    clients: list[httpx.AsyncClient] = []
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/friday/status":
            raise httpx.ReadTimeout("status read timed out", request=request)
        assert request.url.path == "/v1/friday/agents"
        return httpx.Response(
            200,
            json=[{"id": "analyst", "name": "Analyst", "role": "Research"}],
        )

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = GetAIUniverseStatusTool(client=AIUniverseClient(base_url="http://inference.test"))

    async def invoke():
        return tool.execute()

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        result = asyncio.run(invoke())

    assert not result.is_error
    assert "Analyst" in result.content
    assert result.metadata["agents"][0]["id"] == "analyst"
    assert requests == ["/v1/friday/status", "/v1/friday/agents"]
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)


def test_status_tool_recovers_from_non_object_status_json_inside_active_event_loop():
    clients: list[httpx.AsyncClient] = []
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path == "/v1/friday/status":
            return httpx.Response(200, json=[{"status": "healthy"}])
        assert request.url.path == "/v1/friday/agents"
        return httpx.Response(
            200,
            json=[{"id": "analyst", "name": "Analyst", "role": "Research"}],
        )

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = GetAIUniverseStatusTool(client=AIUniverseClient(base_url="http://inference.test"))

    async def invoke():
        return tool.execute()

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        result = asyncio.run(invoke())

    assert not result.is_error
    assert "Analyst" in result.content
    assert result.metadata["agents"][0]["id"] == "analyst"
    assert requests == ["/v1/friday/status", "/v1/friday/agents"]
    assert len(clients) == 2
    assert all(client.is_closed for client in clients)



@pytest.mark.parametrize("mode, path", [("ask", "/v1/friday/ask"), ("debate", "/v1/friday/debate")])
@pytest.mark.parametrize("inside_active_loop", [False, True])
def test_ai_universe_tool_reports_schema_invalid_json_and_closes_client(
    mode, path, inside_active_loop
):
    """A JSON object with invalid field types is a tool error, not a successful answer."""
    clients: list[httpx.AsyncClient] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path
        # Confidence is a string, while the response contract requires a number.
        return httpx.Response(
            200,
            json={
                "answer": "This payload violates the response schema.",
                "confidence": "not-a-number",
                "unresolved_disagreements": [],
                "key_evidence": [],
                "run_id": "run_invalid_schema",
            },
        )

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = AIUniverseTool(client=AIUniverseClient(base_url="http://inference.test"))

    def invoke():
        return tool.execute(question="A question", mode=mode)

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        if inside_active_loop:
            async def invoke_inside_loop():
                return invoke()

            result = asyncio.run(invoke_inside_loop())
        else:
            result = invoke()

    assert result.is_error
    assert "confidence" in result.content
    assert len(clients) == 1
    assert clients[0].is_closed



@pytest.mark.parametrize("mode, path", [("ask", "/v1/friday/ask"), ("debate", "/v1/friday/debate")])
@pytest.mark.parametrize("inside_active_loop", [False, True])
def test_ai_universe_tool_reports_schema_invalid_list_field_and_closes_client(
    mode, path, inside_active_loop
):
    """A schema-invalid list field cannot be returned as a successful response."""
    clients: list[httpx.AsyncClient] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == path
        return httpx.Response(
            200,
            json={
                "answer": "This payload violates the response schema.",
                "confidence": 0.91,
                "unresolved_disagreements": [],
                "key_evidence": "must-be-an-array",
                "run_id": "run_invalid_evidence",
            },
        )

    async_client_type = httpx.AsyncClient

    def create_client(*args, **kwargs) -> httpx.AsyncClient:
        client = async_client_type(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    tool = AIUniverseTool(client=AIUniverseClient(base_url="http://inference.test"))

    def invoke():
        return tool.execute(question="A question", mode=mode)

    with mock.patch("httpx.AsyncClient", side_effect=create_client):
        if inside_active_loop:
            async def invoke_inside_loop():
                return invoke()

            result = asyncio.run(invoke_inside_loop())
        else:
            result = invoke()

    assert result.is_error
    assert "key_evidence" in result.content
    assert len(clients) == 1
    assert clients[0].is_closed
