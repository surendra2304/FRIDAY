"""Unit and integration tests for FRIDAY Phase 5.6: Futuristic Voice Persona."""

import asyncio
from unittest import mock
import pytest

from friday.agent.agent import FridayAgent
from friday.core.auth import AutoApproveAuthorizer
from friday.core.config import Settings
from friday.core.types import Message, Role, SafetyLevel, ToolResult
from friday.memory.sqlite import SQLiteConversationMemory
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry
from friday.voice.audio_io import MockSpeakerStream
from friday.voice.gemini_live_session import GeminiLiveVoiceSession


class MockGenAIServerMessage:
    def __init__(self, server_content=None, tool_call=None):
        self.server_content = server_content
        self.tool_call = tool_call
        self.tool_call_cancellation = None


class MockAsyncSession:
    def __init__(self, receive_messages=None):
        self._receive_messages = receive_messages or []
        self.sent_tool_responses = []

    async def receive(self):
        for msg in self._receive_messages:
            yield msg

    async def send_tool_response(self, function_responses=None):
        if function_responses:
            self.sent_tool_responses.extend(function_responses)


class FastTimeTool(BaseTool):
    name = "get_time"
    description = "Get current time"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return ToolResult(name=self.name, content="11:15 AM", is_error=False)


class FailingTool(BaseTool):
    name = "broken_service"
    description = "Simulates an external API error"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return ToolResult(name=self.name, content="Remote service unavailable (503)", is_error=True)


@pytest.fixture
def memory_db(tmp_path):
    db_file = tmp_path / "test_persona.db"
    return SQLiteConversationMemory(db_path=str(db_file), embedding_provider=None)


def test_voice_persona_system_prompt_guidelines(memory_db):
    """Verify system prompt contains the calm, concise, futuristic voice persona rules."""
    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="none", user_name="Surendra"),
        memory=memory_db,
    )
    session = GeminiLiveVoiceSession(
        api_key="AIzaTestKey",
        agent=agent,
        voice_name="Aoede",
    )
    sys_inst = session._build_system_instruction()
    assert sys_inst is not None
    prompt_text = sys_inst.parts[0].text

    # Core personality checks
    assert "Calm, intelligent, concise, confident, natural, professional" in prompt_text
    assert "Do NOT repeat the user's name (Surendra) on every turn" in prompt_text
    assert "Do NOT use repetitive acknowledgements" in prompt_text
    assert "Do NOT use excessive 'Boss'" in prompt_text
    assert "INTERRUPTION ADAPTATION" in prompt_text
    assert "Done." in prompt_text


def test_voice_name_configurability():
    """Verify voice_name is configurable via Settings or constructor."""
    settings = Settings(env="testing", voice_name="Charon")
    session = GeminiLiveVoiceSession(
        api_key="AIzaTestKey",
        voice_name=None,
    )
    # Falls back to configured voice name
    assert session.voice_name in ("Charon", "Aoede", "Puck")

    # Explicit constructor override
    custom_session = GeminiLiveVoiceSession(
        api_key="AIzaTestKey",
        voice_name="Fenrir",
    )
    assert custom_session.voice_name == "Fenrir"


@pytest.mark.anyio
async def test_short_question_spoken_response(memory_db):
    """Verify short question responses are recorded and dispatched cleanly."""
    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="none"),
        memory=memory_db,
    )
    session = GeminiLiveVoiceSession(api_key="AIzaTestKey", agent=agent)
    session._active = True

    # User: "What time is it?" -> Assistant: "It is 11:15 AM."
    server_turn = mock.MagicMock(
        turn_complete=True,
        interrupted=False,
        input_transcription=mock.MagicMock(text="What time is it?"),
        output_transcription=mock.MagicMock(text="It is 11:15 AM."),
        model_turn=None,
    )
    msg = MockGenAIServerMessage(server_content=server_turn)
    mock_ws = MockAsyncSession([msg])
    spk = MockSpeakerStream()

    await session._audio_receiver_loop(mock_ws, spk, None, asyncio.Event())

    history = agent.memory.get_messages(agent.conversation_id)
    assert len(history) == 2
    assert history[0].content == "What time is it?"
    assert history[1].content == "It is 11:15 AM."


@pytest.mark.anyio
async def test_tool_request_concise_status_and_execution(memory_db):
    """Verify tool requests execute cleanly and return concise outputs."""
    registry = ToolRegistry()
    registry.register(FastTimeTool())

    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="none"),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer(),
        memory=memory_db,
    )
    session = GeminiLiveVoiceSession(api_key="AIzaTestKey", agent=agent)
    session._active = True

    fc = mock.MagicMock(name="get_time", id="call_time_001", args={})
    fc.name = "get_time"
    tool_msg = MockGenAIServerMessage(tool_call=mock.MagicMock(function_calls=[fc]))

    mock_ws = MockAsyncSession([tool_msg])
    spk = MockSpeakerStream()

    await session._audio_receiver_loop(mock_ws, spk, None, asyncio.Event())

    assert len(mock_ws.sent_tool_responses) == 1
    resp = mock_ws.sent_tool_responses[0]
    assert resp.name == "get_time"
    assert resp.response == {"output": "11:15 AM"}


@pytest.mark.anyio
async def test_tool_error_graceful_handling(memory_db):
    """Verify tool errors are captured cleanly without crashing the session."""
    registry = ToolRegistry()
    registry.register(FailingTool())

    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="none"),
        tool_registry=registry,
        authorizer=AutoApproveAuthorizer(),
        memory=memory_db,
    )
    session = GeminiLiveVoiceSession(api_key="AIzaTestKey", agent=agent)
    session._active = True

    fc = mock.MagicMock(name="broken_service", id="call_err_002", args={})
    fc.name = "broken_service"
    tool_msg = MockGenAIServerMessage(tool_call=mock.MagicMock(function_calls=[fc]))

    mock_ws = MockAsyncSession([tool_msg])
    spk = MockSpeakerStream()

    await session._audio_receiver_loop(mock_ws, spk, None, asyncio.Event())

    assert len(mock_ws.sent_tool_responses) == 1
    resp = mock_ws.sent_tool_responses[0]
    assert resp.name == "broken_service"
    assert "Error: Remote service unavailable (503)" in resp.response["output"]


@pytest.mark.anyio
async def test_interruption_and_followup_dialogue(memory_db):
    """Verify seamless conversational follow-up after an interrupted turn."""
    agent = FridayAgent(
        settings=Settings(env="testing", embedding_provider="none"),
        memory=memory_db,
    )
    session = GeminiLiveVoiceSession(api_key="AIzaTestKey", agent=agent)
    session._active = True

    # 1. Turn 1 interrupted
    turn1_interrupted = mock.MagicMock(
        interrupted=True,
        turn_complete=False,
        model_turn=None,
        input_transcription=None,
        output_transcription=None,
    )
    turn1_complete = mock.MagicMock(
        interrupted=False,
        turn_complete=True,
        input_transcription=mock.MagicMock(text="Tell me a long story about quantum"),
        output_transcription=mock.MagicMock(text="Quantum mechanics is a fundamental"),
        model_turn=None,
    )

    # 2. Turn 2 immediate follow-up
    turn2_complete = mock.MagicMock(
        interrupted=False,
        turn_complete=True,
        input_transcription=mock.MagicMock(text="Never mind, what is 2 plus 2?"),
        output_transcription=mock.MagicMock(text="4."),
        model_turn=None,
    )

    messages = [
        MockGenAIServerMessage(server_content=turn1_interrupted),
        MockGenAIServerMessage(server_content=turn1_complete),
        MockGenAIServerMessage(server_content=turn2_complete),
    ]

    mock_ws = MockAsyncSession(messages)
    spk = MockSpeakerStream()

    await session._audio_receiver_loop(mock_ws, spk, None, asyncio.Event())

    history = agent.memory.get_messages(agent.conversation_id)
    assert len(history) == 4
    # Check turn 1 got tagged with interrupted
    assert "[interrupted]" in history[1].content
    # Check turn 2 is clean
    assert history[2].content == "Never mind, what is 2 plus 2?"
    assert history[3].content == "4."
