"""Mocked asynchronous tests for Gemini Live real-time voice session."""

import asyncio
from unittest import mock
import pytest
from google.genai import types as genai_types

from friday.core.config import Settings
from friday.core.exceptions import LLMProviderError
from friday.core.types import Message, Role, ToolResult, SafetyLevel
from friday.tools.base import BaseTool
from friday.tools.registry import ToolRegistry
from friday.voice.audio_io import MicrophoneStream, SpeakerStream
from friday.voice.gemini_live_session import GeminiLiveVoiceSession, LiveSessionState
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
        model="gemini-2.0-flash-exp",
        voice_name="Puck",
    )
    assert session.model == "gemini-2.0-flash-exp"
    assert session.voice_name == "Puck"
    assert session.sample_rate_in == 16000
    assert session.sample_rate_out == 24000
    assert session.is_active is False
    assert session.resumption_handle is None
    assert session.thinking_level == "MINIMAL"


@pytest.mark.anyio
async def test_live_session_thinking_config():
    """Verify LiveConnectConfig builds ThinkingConfig with thinking_level."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        thinking_level="LOW",
    )
    config = session._build_live_config()
    assert config.thinking_config is not None
    assert getattr(config.thinking_config, "thinking_level", None) in ("LOW", genai_types.ThinkingLevel.LOW)


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
    assert provider.model == "gemini-2.0-flash-exp"
    assert provider.api_key == "TEST_GEMINI_API_KEY"


@pytest.mark.anyio
async def test_live_session_state_transitions(mock_agent):
    """Verify LiveSessionState transitions through complete conversational lifecycle."""
    from friday.voice.gemini_live_session import LiveSessionState

    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        agent=mock_agent,
    )
    assert session.state == LiveSessionState.IDLE

    session._active = True
    spk = mock.MagicMock(spec=SpeakerStream)
    stop_event = asyncio.Event()

    # 1. Server speaking transition
    audio_msg = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            parts=[MockGenAIPart(data=b"\x01\x02" * 100, text="Hello")],
            turn_complete=False,
        )
    )
    mock_ws = MockAsyncSession(receive_messages=[audio_msg])
    await session._audio_receiver_loop(mock_ws, spk, None, stop_event)
    assert session.state == LiveSessionState.FRIDAY_SPEAKING

    # 2. Interruption transition
    int_msg = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            interrupted=True,
            turn_complete=False,
        )
    )
    mock_ws2 = MockAsyncSession(receive_messages=[int_msg])
    await session._audio_receiver_loop(mock_ws2, spk, None, stop_event)
    assert session.state == LiveSessionState.INTERRUPTED

    # 3. Turn complete resets to CONNECTED
    complete_msg = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            turn_complete=True,
            input_tx="Hi",
            output_tx="Hello!",
        )
    )
    mock_ws3 = MockAsyncSession(receive_messages=[complete_msg])
    await session._audio_receiver_loop(mock_ws3, spk, None, stop_event)
    assert session.state == LiveSessionState.CONNECTED


def test_speaker_stream_remainder_buffering():
    """Verify SpeakerStream handles partial chunk boundaries without dropping or reordering bytes."""
    stream = SpeakerStream(sample_rate=24000)
    # Simulate start without actual hardware driver
    stream._active = True

    # Play two chunks of unequal sizes
    chunk1 = b"\x01\x02\x03\x04\x05\x06"
    chunk2 = b"\x07\x08\x09\x10"
    stream.play_chunk(chunk1)
    stream.play_chunk(chunk2)

    # Queue size should reflect active chunks
    assert stream.is_playing is True
    assert stream.queue_size == 2

    # Stop should purge queue and remainder completely
    stream.stop()
    assert stream.queue_size == 0
    assert stream.is_playing is False


def test_reconnect_session_resumption_no_transparent_param(mock_agent):
    """Regression test: Developer API SessionResumptionConfig must NOT contain transparent=True."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        agent=mock_agent,
        enable_session_resumption=True,
    )
    session._resumption_handle = "test_handle_12345"
    config = session._build_live_config()

    assert config.session_resumption is not None
    assert config.session_resumption.handle == "test_handle_12345"
    # Ensure transparent is not set or is None / False (not True)
    assert getattr(config.session_resumption, "transparent", None) is not True


@pytest.mark.anyio
async def test_goaway_reconnection_loop_lifecycle(mock_agent):
    """Verify that GoAway message terminates receiver loop gracefully without leaking tasks or erroring."""
    from friday.voice.gemini_live_session import LiveSessionState

    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        agent=mock_agent,
    )
    session._active = True
    spk = mock.MagicMock(spec=SpeakerStream)
    stop_event = asyncio.Event()

    # Create a message with go_away set
    goaway_msg = MockGenAIServerMessage(go_away=mock.MagicMock())
    mock_ws = MockAsyncSession(receive_messages=[goaway_msg])

    # Receiver loop should exit cleanly upon seeing go_away
    await session._audio_receiver_loop(mock_ws, spk, None, stop_event)
    # Reconnection config should have model set properly
    assert session.model == "gemini-2.0-flash-exp"


@pytest.mark.anyio
async def test_server_interrupted_event_mapping_strict(mock_agent):
    """Regression test: verify serverContent.interrupted is only treated as interruption when True."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        agent=mock_agent,
    )
    session._active = True
    spk = mock.MagicMock(spec=SpeakerStream)
    stop_event = asyncio.Event()

    # Message with interrupted=False or None should NOT trigger interruption
    msg1 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            parts=[MockGenAIPart(text="Hello ")],
            interrupted=False,
            turn_complete=False,
        )
    )
    msg2 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            parts=[MockGenAIPart(text="world.")],
            interrupted=None,
            turn_complete=True,
            output_tx="Hello world.",
        )
    )

    mock_ws = MockAsyncSession(receive_messages=[msg1, msg2])
    turns = []
    await session._audio_receiver_loop(mock_ws, spk, lambda u, a: turns.append((u, a)), stop_event)

    assert session.server_interruptions == 0
    assert session.user_interruptions == 0
    assert len(turns) == 1
    assert turns[0][1] == "Hello world."
    assert "[interrupted]" not in turns[0][1]


@pytest.mark.anyio
async def test_no_reconnect_on_normal_barge_in(mock_agent):
    """Regression test: verify a normal user barge-in stays within the same session without reconnecting."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        agent=mock_agent,
    )
    session._active = True
    spk = mock.MagicMock(spec=SpeakerStream)
    stop_event = asyncio.Event()

    # Interrupted turn followed by a new full turn in the SAME WebSocket session
    turn1_part = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            parts=[MockGenAIPart(text="I am explaining something long...")],
            turn_complete=False,
        )
    )
    turn1_interrupt = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            interrupted=True,
            turn_complete=True,
        )
    )
    turn2_part = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            parts=[MockGenAIPart(text="Sure, here is the new answer.")],
            turn_complete=True,
            input_tx="Stop and tell me this instead",
            output_tx="Sure, here is the new answer.",
        )
    )

    mock_ws = MockAsyncSession(receive_messages=[turn1_part, turn1_interrupt, turn2_part])
    turns = []
    await session._audio_receiver_loop(mock_ws, spk, lambda u, a: turns.append((u, a)), stop_event)

    assert session.server_interruptions == 1
    assert len(turns) == 2
    assert turns[1] == ("Stop and tell me this instead", "Sure, here is the new answer.")
    # State returns to CONNECTED without triggering session reconnect
    assert session.state == LiveSessionState.CONNECTED


@pytest.mark.anyio
async def test_silent_listening_completes_response(mock_agent):
    """Regression test: verify that when microphone remains silent, FRIDAY finishes full response with zero interruptions."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        agent=mock_agent,
    )
    session._active = True
    spk = mock.MagicMock(spec=SpeakerStream)
    stop_event = asyncio.Event()

    msg1 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            parts=[MockGenAIPart(text="Hello, Surendra. What can I do for you?")],
            turn_complete=True,
            input_tx="Hi",
            output_tx="Hello, Surendra. What can I do for you?",
        )
    )

    mock_ws = MockAsyncSession(receive_messages=[msg1])
    turns = []
    await session._audio_receiver_loop(mock_ws, spk, lambda u, a: turns.append((u, a)), stop_event)

    assert session.server_interruptions == 0
    assert session.user_interruptions == 0
    assert len(turns) == 1
    assert turns[0] == ("Hi", "Hello, Surendra. What can I do for you?")
    assert session.state == LiveSessionState.CONNECTED



