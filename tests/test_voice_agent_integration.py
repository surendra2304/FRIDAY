"""Integration tests for Unified Voice Agent: Tool calling, Authorization, Semantic Memory, and Resilience."""

import asyncio
from unittest import mock
import pytest

from friday.agent.agent import FridayAgent
from friday.core.auth import AutoApproveAuthorizer, BaseAuthorizer
from friday.core.config import Settings
from friday.core.types import (
    AuthorizationDecision,
    AuthorizationRequest,
    AuthorizationResponse,
    Message,
    Role,
    SafetyLevel,
    ToolResult,
)
from friday.memory.embeddings.mock import MockEmbeddingProvider
from friday.memory.sqlite import SQLiteConversationMemory
from friday.tools.base import BaseTool
from friday.tools.builtin.memory_search import MemorySearchTool
from friday.tools.registry import ToolRegistry
from friday.voice.audio_io import MockSpeakerStream
from friday.voice.gemini_live_session import GeminiLiveVoiceSession


class SafeCalcTool(BaseTool):
    name = "calculator"
    description = "Multiply numbers"
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    }

    def execute(self, expression: str = "", **kwargs):
        if expression == "123 * 456":
            return ToolResult(name=self.name, content="56088", is_error=False)
        return ToolResult(name=self.name, content="0", is_error=False)


class FailingTool(BaseTool):
    name = "failing_tool"
    description = "A tool that throws an error"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        raise RuntimeError("Service unavailable: connection timed out")


class DangerousSystemTool(BaseTool):
    name = "delete_file"
    description = "Delete a file"
    safety_level = SafetyLevel.DANGEROUS
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string"}},
        "required": ["path"],
    }

    def execute(self, path: str = "", **kwargs):
        return ToolResult(name=self.name, content=f"Deleted {path}", is_error=False)


class SensitiveActionTool(BaseTool):
    name = "send_email"
    description = "Send an email"
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {"recipient": {"type": "string"}},
        "required": ["recipient"],
    }

    def execute(self, recipient: str = "", **kwargs):
        return ToolResult(name=self.name, content=f"Email sent to {recipient}", is_error=False)


class DenyAllAuthorizer(BaseAuthorizer):
    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        return AuthorizationResponse(
            decision=AuthorizationDecision.DENIED,
            reason="User denied dangerous action via voice authorization",
        )


class MockGenAIServerMessage:
    def __init__(self, server_content=None, tool_call=None, tool_call_cancellation=None):
        self.server_content = server_content
        self.tool_call = tool_call
        self.tool_call_cancellation = tool_call_cancellation


class MockAsyncSession:
    def __init__(self, receive_messages=None):
        self.sent_tool_responses = []
        self._receive_messages = receive_messages or []

    async def send_tool_response(self, function_responses):
        self.sent_tool_responses.extend(function_responses)

    async def receive(self):
        for msg in self._receive_messages:
            yield msg


@pytest.fixture
def memory_db(tmp_path):
    db_file = tmp_path / "test_voice_agent.db"
    mem = SQLiteConversationMemory(
        db_path=str(db_file),
        embedding_provider=MockEmbeddingProvider(dimension=128),
    )
    return mem


@pytest.mark.anyio
async def test_voice_tool_calling_with_unified_registry(memory_db):
    """Verify Gemini Live function calls execute via unified agent ToolRegistry."""
    registry = ToolRegistry()
    registry.register(SafeCalcTool())

    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="mock"),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer(),
        memory=memory_db,
    )

    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        agent=agent,
    )
    session._active = True

    fc_mock = mock.MagicMock()
    fc_mock.name = "calculator"
    fc_mock.id = "call_calc_456"
    fc_mock.args = {"expression": "123 * 456"}

    tool_call_msg = MockGenAIServerMessage(
        tool_call=mock.MagicMock(function_calls=[fc_mock])
    )

    mock_ws = MockAsyncSession(receive_messages=[tool_call_msg])
    spk = MockSpeakerStream()
    stop_event = asyncio.Event()

    await session._audio_receiver_loop(mock_ws, spk, None, stop_event)

    # Verify tool response sent to WebSocket
    assert len(mock_ws.sent_tool_responses) == 1
    resp = mock_ws.sent_tool_responses[0]
    assert resp.name == "calculator"
    assert resp.id == "call_calc_456"
    assert resp.response == {"output": "56088"}

    # Verify tool execution persisted in SQLite memory
    messages = agent.memory.get_messages(agent.conversation_id)
    tool_msgs = [m for m in messages if m.role == Role.TOOL]
    assert len(tool_msgs) == 1
    assert tool_msgs[0].content == "56088"
    assert tool_msgs[0].tool_call_id == "call_calc_456"


@pytest.mark.anyio
async def test_voice_authorization_gating_blocks_dangerous_tools(memory_db):
    """Verify dangerous tools are blocked by authorizer during voice sessions."""
    registry = ToolRegistry()
    registry.register(DangerousSystemTool())

    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="mock"),
        tool_registry=registry,
        authorizer=DenyAllAuthorizer(),
        memory=memory_db,
    )

    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        agent=agent,
    )
    session._active = True

    fc_mock = mock.MagicMock()
    fc_mock.name = "delete_file"
    fc_mock.id = "call_del_999"
    fc_mock.args = {"path": "/etc/hosts"}

    tool_call_msg = MockGenAIServerMessage(
        tool_call=mock.MagicMock(function_calls=[fc_mock])
    )

    mock_ws = MockAsyncSession(receive_messages=[tool_call_msg])
    spk = MockSpeakerStream()
    stop_event = asyncio.Event()

    await session._audio_receiver_loop(mock_ws, spk, None, stop_event)

    # Verify execution was denied
    assert len(mock_ws.sent_tool_responses) == 1
    resp = mock_ws.sent_tool_responses[0]
    assert resp.name == "delete_file"
    assert "error" in resp.response
    assert "rejected" in resp.response["error"].lower()


@pytest.mark.anyio
async def test_voice_multi_step_tool_calls(memory_db):
    """Verify multiple tool calls in a single turn execute and correlate correctly."""
    registry = ToolRegistry()
    registry.register(SafeCalcTool())

    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="mock"),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer(),
        memory=memory_db,
    )

    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY", agent=agent)
    session._active = True

    fc1 = mock.MagicMock(name="calculator", id="call_1", args={"expression": "123 * 456"})
    fc1.name = "calculator"
    fc2 = mock.MagicMock(name="calculator", id="call_2", args={"expression": "0"})
    fc2.name = "calculator"

    tool_call_msg = MockGenAIServerMessage(
        tool_call=mock.MagicMock(function_calls=[fc1, fc2])
    )

    mock_ws = MockAsyncSession(receive_messages=[tool_call_msg])
    spk = MockSpeakerStream()
    stop_event = asyncio.Event()

    await session._audio_receiver_loop(mock_ws, spk, None, stop_event)

    assert len(mock_ws.sent_tool_responses) == 2
    assert mock_ws.sent_tool_responses[0].id == "call_1"
    assert mock_ws.sent_tool_responses[0].response == {"output": "56088"}
    assert mock_ws.sent_tool_responses[1].id == "call_2"
    assert mock_ws.sent_tool_responses[1].response == {"output": "0"}


@pytest.mark.anyio
async def test_voice_tool_failure_resilience(memory_db):
    """Verify tool execution exceptions are safely caught and returned as structured errors to Gemini Live."""
    registry = ToolRegistry()
    registry.register(FailingTool())

    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="mock"),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer(),
        memory=memory_db,
    )

    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY", agent=agent)
    session._active = True

    fc = mock.MagicMock(name="failing_tool", id="call_err_1", args={})
    fc.name = "failing_tool"

    tool_call_msg = MockGenAIServerMessage(
        tool_call=mock.MagicMock(function_calls=[fc])
    )

    mock_ws = MockAsyncSession(receive_messages=[tool_call_msg])
    spk = MockSpeakerStream()
    stop_event = asyncio.Event()

    await session._audio_receiver_loop(mock_ws, spk, None, stop_event)

    assert len(mock_ws.sent_tool_responses) == 1
    resp = mock_ws.sent_tool_responses[0]
    assert resp.name == "failing_tool"
    assert resp.id == "call_err_1"
    assert "output" in resp.response
    assert "Execution error" in resp.response["output"] or "error" in resp.response


@pytest.mark.anyio
async def test_voice_semantic_memory_retrieval(memory_db):
    """Verify voice session can execute memory_search tool and retrieve semantic records."""
    # Pre-populate memory with facts
    conv_id = memory_db.create_conversation(title="Test Conversation")
    memory_db.add_message(Message(role=Role.USER, content="Remember that my favorite IDE is VS Code."), conv_id)
    memory_db.add_message(Message(role=Role.ASSISTANT, content="Understood, VS Code is your favorite."), conv_id)

    registry = ToolRegistry()
    registry.register(MemorySearchTool(memory=memory_db))

    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="mock"),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer(),
        memory=memory_db,
    )
    agent.switch_conversation(conv_id)

    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY", agent=agent)
    session._active = True

    fc = mock.MagicMock(name="search_memory", id="call_mem_search", args={"query": "favorite editor VS Code"})
    fc.name = "search_memory"

    tool_call_msg = MockGenAIServerMessage(
        tool_call=mock.MagicMock(function_calls=[fc])
    )

    mock_ws = MockAsyncSession(receive_messages=[tool_call_msg])
    spk = MockSpeakerStream()
    stop_event = asyncio.Event()

    await session._audio_receiver_loop(mock_ws, spk, None, stop_event)

    assert len(mock_ws.sent_tool_responses) == 1
    resp = mock_ws.sent_tool_responses[0]
    assert resp.name == "search_memory"
    assert "output" in resp.response
    assert "VS Code" in resp.response["output"]


@pytest.mark.anyio
async def test_bidirectional_text_save_voice_retrieve(memory_db):
    """Verify text turns save to memory and are available for voice retrieval."""
    conv_id = memory_db.create_conversation(title="Shared Memory Conv")
    # Save via Text
    memory_db.add_message(Message(role=Role.USER, content="My favorite language is Python."), conv_id)
    memory_db.add_message(Message(role=Role.ASSISTANT, content="Got it, Python is your favorite."), conv_id)

    # Retrieve in Voice session
    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="mock"),
        memory=memory_db,
    )
    agent.switch_conversation(conv_id)

    history = agent.memory.get_messages(conv_id)
    assert len(history) == 2
    assert "Python" in history[0].content


@pytest.mark.anyio
async def test_bidirectional_voice_save_text_retrieve(memory_db):
    """Verify voice turn completion saves to memory and is available for text agent retrieval."""
    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="mock"),
        memory=memory_db,
    )
    conv_id = agent.conversation_id

    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY", agent=agent)
    session._active = True

    # Complete voice turn
    server_content = mock.MagicMock(
        turn_complete=True,
        input_transcription=mock.MagicMock(text="Save project note: deployment is on Friday."),
        output_transcription=mock.MagicMock(text="Saved note about Friday deployment."),
        interrupted=False,
        model_turn=None,
    )
    msg = MockGenAIServerMessage(server_content=server_content)

    mock_ws = MockAsyncSession(receive_messages=[msg])
    spk = MockSpeakerStream()
    stop_event = asyncio.Event()

    await session._audio_receiver_loop(mock_ws, spk, None, stop_event)

    # Text agent queries the same conversation
    history = agent.memory.get_messages(conv_id)
    assert len(history) == 2
    assert "deployment is on Friday" in history[0].content
    assert "Saved note about Friday deployment" in history[1].content
