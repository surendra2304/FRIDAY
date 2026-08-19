"""Mocked asynchronous tests for Gemini Live real-time voice session."""

import asyncio
from unittest import mock
import pytest

from friday.core.config import Settings
from friday.core.exceptions import LLMProviderError
from friday.core.types import Message, Role, ToolResult, SafetyLevel
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry
from friday.voice.audio_io import MicrophoneStream, SpeakerStream
from friday.voice.gemini_live_session import GeminiLiveVoiceSession
from friday.voice.gemini_provider import GeminiVoiceProvider


class DummyTimeTool(BaseTool):
    name = "get_time"
    description = "Get current time"
    safety_level = SafetyLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def execute(self, **kwargs):
        return ToolResult(name=self.name, content="11:30 AM", is_error=False)


class MockGenAIPart:
    def __init__(self, data=None, text=None):
        self.inline_data = mock.MagicMock(data=data) if data else None
        self.text = text


class MockGenAIServerContent:
    def __init__(self, parts=None, interrupted=False, turn_complete=False, input_tx=None, output_tx=None):
        self.model_turn = mock.MagicMock(parts=parts or [])
        self.interrupted = interrupted
        self.turn_complete = turn_complete
        self.input_transcription = mock.MagicMock(text=input_tx) if input_tx else None
        self.output_transcription = mock.MagicMock(text=output_tx) if output_tx else None


class MockGenAIServerMessage:
    def __init__(
        self,
        server_content=None,
        tool_call=None,
        tool_call_cancellation=None,
        session_resumption_update=None,
        go_away=None,
    ):
        self.server_content = server_content
        self.tool_call = tool_call
        self.tool_call_cancellation = tool_call_cancellation
        self.session_resumption_update = session_resumption_update
        self.go_away = go_away


class MockAsyncSession:
    def __init__(self, receive_messages=None):
        self.sent_realtime_chunks = []
        self.sent_tool_responses = []
        self._receive_messages = receive_messages or []
        self.closed = False

    async def send_realtime_input(self, audio=None, media=None, media_chunks=None):
        if audio:
            self.sent_realtime_chunks.append(audio)
        elif media:
            self.sent_realtime_chunks.append(media)
        elif media_chunks:
            self.sent_realtime_chunks.extend(media_chunks)

    async def send_tool_response(self, function_responses):
        self.sent_tool_responses.extend(function_responses)

    async def receive(self):
        for msg in self._receive_messages:
            yield msg

    async def close(self):
        self.closed = True


@pytest.fixture
def mock_agent():
    agent = mock.MagicMock()
    registry = ToolRegistry()
    registry.register(DummyTimeTool())
    agent.tools = registry
    agent.tool_registry = registry
    agent.memory = mock.MagicMock()
    agent.authorizer = mock.MagicMock()
    return agent


@pytest.mark.anyio
async def test_live_session_initialization():
    """Verify GeminiLiveVoiceSession initializes with proper defaults."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        model="gemini-2.5-flash-native-audio-latest",
        voice_name="Puck",
    )
    assert session.model == "gemini-2.5-flash-native-audio-latest"
    assert session.voice_name == "Puck"
    assert session.sample_rate_in == 16000
    assert session.sample_rate_out == 24000
    assert session.is_active is False
    assert session.resumption_handle is None


@pytest.mark.anyio
async def test_live_session_tool_config_building(mock_agent):
    """Verify tool schemas are extracted and converted to GenAI declarations."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        agent=mock_agent,
    )
    tools_cfg = session._build_tools_config()
    assert tools_cfg is not None
    assert len(tools_cfg) == 1
    assert len(tools_cfg[0].function_declarations) == 1
    assert tools_cfg[0].function_declarations[0].name == "get_time"


@pytest.mark.anyio
async def test_audio_sender_and_receiver_loop(mock_agent):
    """Test full-duplex send and receive loops with audio streaming, transcriptions, and barge-in."""
    sample_pcm_24k = b"\x01\x02\x03\x04" * 100
    msg1 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            parts=[MockGenAIPart(data=sample_pcm_24k, text="Hello")],
            turn_complete=False,
        )
    )
    msg2 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            interrupted=True,
            turn_complete=False,
        )
    )
    msg3 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            parts=[MockGenAIPart(text=" world!")],
            turn_complete=True,
            input_tx="Hi Friday",
            output_tx="Hello world!",
        )
    )

    mock_ws_session = MockAsyncSession(receive_messages=[msg1, msg2, msg3])

    live_session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        agent=mock_agent,
    )
    live_session._active = True

    # Setup mock audio devices
    mic = mock.MagicMock(spec=MicrophoneStream)
    mic.read_chunk = mock.AsyncMock(side_effect=[b"pcm_chunk_1", b"pcm_chunk_2", b""])

    spk = mock.MagicMock(spec=SpeakerStream)
    stop_event = asyncio.Event()

    on_turn_called = []
    def turn_callback(u, a):
        on_turn_called.append((u, a))

    await live_session._audio_receiver_loop(mock_ws_session, spk, turn_callback, stop_event)

    # Assertions
    spk.play_chunk.assert_called_with(sample_pcm_24k)
    spk.stop.assert_called()
    assert len(on_turn_called) == 1
    assert on_turn_called[0] == ("Hi Friday", "Hello world! [interrupted]")
    assert mock_agent.memory.add_message.call_count == 2


@pytest.mark.anyio
async def test_live_session_audio_sender_loop():
    """Verify audio sender captures mic chunks and sends realtime blobs."""
    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY")
    session._active = True

    mic = mock.MagicMock(spec=MicrophoneStream)
    mic.read_chunk = mock.AsyncMock(side_effect=[b"chunk_1", b"chunk_2", b""])

    spk = mock.MagicMock(spec=SpeakerStream)
    spk.is_playing = False
    spk.queue_size = 0

    mock_ws = MockAsyncSession()
    stop_event = asyncio.Event()

    # Run sender task briefly
    task = asyncio.create_task(session._audio_sender_loop(mock_ws, mic, spk, stop_event))
    await asyncio.sleep(0.05)
    stop_event.set()
    await task

    assert len(mock_ws.sent_realtime_chunks) >= 2
    assert mock_ws.sent_realtime_chunks[0].data == b"chunk_1"
    assert "audio/pcm;rate=16000" in mock_ws.sent_realtime_chunks[0].mime_type


@pytest.mark.anyio
async def test_live_session_resumption_update():
    """Verify session resumption update messages store the new handle."""
    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY")
    session._active = True

    resumption_msg = MockGenAIServerMessage(
        session_resumption_update=mock.MagicMock(new_handle="handle_xyz_123")
    )
    mock_ws = MockAsyncSession(receive_messages=[resumption_msg])
    spk = mock.MagicMock(spec=SpeakerStream)
    stop_event = asyncio.Event()

    await session._audio_receiver_loop(mock_ws, spk, None, stop_event)

    assert session.resumption_handle == "handle_xyz_123"


@pytest.mark.anyio
async def test_live_session_go_away_handling():
    """Verify GoAway signal triggers clean exit from receive loop for reconnection."""
    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY")
    session._active = True

    go_away_msg = MockGenAIServerMessage(go_away=mock.MagicMock())
    mock_ws = MockAsyncSession(receive_messages=[go_away_msg])
    spk = mock.MagicMock(spec=SpeakerStream)
    stop_event = asyncio.Event()

    # Receiver loop should break cleanly on GoAway
    await session._audio_receiver_loop(mock_ws, spk, None, stop_event)


@pytest.mark.anyio
async def test_live_session_tool_cancellation():
    """Verify tool call cancellation messages are logged and handled without raising."""
    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY")
    session._active = True

    cancel_msg = MockGenAIServerMessage(
        tool_call_cancellation=mock.MagicMock(ids=["call_abc_123"])
    )
    mock_ws = MockAsyncSession(receive_messages=[cancel_msg])
    spk = mock.MagicMock(spec=SpeakerStream)
    stop_event = asyncio.Event()

    await session._audio_receiver_loop(mock_ws, spk, None, stop_event)


@pytest.mark.anyio
async def test_live_session_tool_execution(mock_agent):
    """Test tool execution requested by Gemini Live WebSocket server."""
    fc_mock = mock.MagicMock()
    fc_mock.name = "get_time"
    fc_mock.id = "call_time_123"
    fc_mock.args = {}

    tool_call_msg = MockGenAIServerMessage(
        tool_call=mock.MagicMock(function_calls=[fc_mock])
    )

    mock_ws_session = MockAsyncSession(receive_messages=[tool_call_msg])

    mock_agent._execute_single_tool_call.return_value = mock.MagicMock(
        is_error=False,
        content="11:30 AM"
    )

    live_session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        agent=mock_agent,
    )
    live_session._active = True

    spk = mock.MagicMock(spec=SpeakerStream)
    stop_event = asyncio.Event()

    await live_session._audio_receiver_loop(mock_ws_session, spk, None, stop_event)

    assert len(mock_ws_session.sent_tool_responses) == 1
    response = mock_ws_session.sent_tool_responses[0]
    assert response.name == "get_time"
    assert response.id == "call_time_123"
    assert response.response == {"output": "11:30 AM"}


def test_provider_adapter_instantiation():
    """Verify GeminiVoiceProvider instantiates cleanly without hardware dependencies."""
    provider = GeminiVoiceProvider(api_key="TEST_GEMINI_API_KEY")
    assert provider.model == "gemini-2.5-flash"
    assert provider.api_key == "TEST_GEMINI_API_KEY"
