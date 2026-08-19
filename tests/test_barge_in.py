"""Deterministic tests for true barge-in, natural interruption, VAD signals, and context coherence."""

import asyncio
import struct
from unittest import mock
import pytest

from friday.core.types import Message, Role
from friday.voice.audio_io import (
    MockMicrophoneStream,
    MockSpeakerStream,
    SpeakerStream,
    compute_pcm_rms,
)
from friday.voice.gemini_live_session import GeminiLiveVoiceSession


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
        self._receive_messages = receive_messages or []

    async def send_realtime_input(self, audio=None, media=None, media_chunks=None):
        if audio:
            self.sent_realtime_chunks.append(audio)
        elif media:
            self.sent_realtime_chunks.append(media)
        elif media_chunks:
            self.sent_realtime_chunks.extend(media_chunks)

    async def receive(self):
        for msg in self._receive_messages:
            yield msg


def test_pcm_rms_calculation():
    """Verify compute_pcm_rms correctly measures silence vs loud audio."""
    # 1. Complete silence
    silence = b"\x00\x00" * 800
    assert compute_pcm_rms(silence) == 0.0

    # 2. Audible speech level PCM (amplitude ~1000)
    speech = struct.pack("<800h", *[1000] * 800)
    rms = compute_pcm_rms(speech)
    assert 990.0 < rms < 1010.0


@pytest.mark.anyio
async def test_local_zero_latency_barge_in():
    """Verify local high-energy speech immediately purges active speaker buffer."""
    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY", barge_in_rms_threshold=300.0)
    session._active = True

    loud_pcm = struct.pack("<800h", *[2000] * 800)
    mic = MockMicrophoneStream(chunks=[loud_pcm])
    mic.start()

    spk = SpeakerStream(sample_rate=24000)
    spk._active = True
    spk.play_chunk(b"outgoing_ai_speech" * 50)
    assert spk.is_playing

    mock_ws_session = MockAsyncSession()
    stop_event = asyncio.Event()

    # Run one step of sender loop
    task = asyncio.create_task(session._audio_sender_loop(mock_ws_session, mic, spk, stop_event))
    await asyncio.sleep(0.05)
    stop_event.set()
    await task

    # Speaker stream must be purged immediately by local barge-in detection
    assert not spk.is_playing
    assert spk.queue_size == 0


@pytest.mark.anyio
async def test_server_side_interruption_and_memory_coherence():
    """Verify server interruption signal marks assistant turn as interrupted without corrupting memory."""
    agent_mock = mock.MagicMock()
    agent_mock.memory = mock.MagicMock()

    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY", agent=agent_mock)
    session._active = True

    spk = MockSpeakerStream(sample_rate=24000)
    spk.start()

    # Step 1: Model starts talking
    msg1 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            parts=[MockGenAIPart(data=b"chunk1", text="The answer to your question is")],
            turn_complete=False,
        )
    )
    # Step 2: User interrupts, server sends interrupted=True
    msg2 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            interrupted=True,
            turn_complete=False,
        )
    )
    # Step 3: Turn completes
    msg3 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            parts=[MockGenAIPart(text="...")],
            turn_complete=True,
            input_tx="Wait, what about London?",
            output_tx="The answer to your question is",
        )
    )

    mock_ws_session = MockAsyncSession(receive_messages=[msg1, msg2, msg3])
    stop_event = asyncio.Event()

    recorded_turns = []
    def on_turn(u, a):
        recorded_turns.append((u, a))

    await session._audio_receiver_loop(mock_ws_session, spk, on_turn, stop_event)

    # Interruption triggered speaker stop
    assert spk.interrupted_count == 1

    # Recorded assistant message contains [interrupted] tag
    assert len(recorded_turns) == 1
    user_txt, agent_txt = recorded_turns[0]
    assert user_txt == "Wait, what about London?"
    assert "[interrupted]" in agent_txt


@pytest.mark.anyio
async def test_spoken_stop_backup_command():
    """Verify spoken backup stop command immediately stops playback."""
    agent_mock = mock.MagicMock()
    agent_mock.memory = mock.MagicMock()

    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY", agent=agent_mock)
    session._active = True

    spk = MockSpeakerStream(sample_rate=24000)
    spk.start()

    msg = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            turn_complete=True,
            input_tx="stop",
            output_tx="Stopping now",
        )
    )

    mock_ws_session = MockAsyncSession(receive_messages=[msg])
    stop_event = asyncio.Event()

    recorded_turns = []
    await session._audio_receiver_loop(mock_ws_session, spk, lambda u, a: recorded_turns.append((u, a)), stop_event)

    assert spk.interrupted_count == 1
    assert recorded_turns[0] == ("stop", "[Stopped by user]")


@pytest.mark.anyio
async def test_rapid_followup_dialogue():
    """Verify rapid consecutive conversational turns execute seamlessly without state leakage."""
    agent_mock = mock.MagicMock()
    agent_mock.memory = mock.MagicMock()

    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY", agent=agent_mock)
    session._active = True

    # Turn 1
    turn1 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            turn_complete=True,
            input_tx="Hello FRIDAY",
            output_tx="Hello!",
        )
    )
    # Turn 2 (Rapid follow-up)
    turn2 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            turn_complete=True,
            input_tx="What is 1 + 1?",
            output_tx="2.",
        )
    )

    mock_ws = MockAsyncSession(receive_messages=[turn1, turn2])
    spk = MockSpeakerStream()
    stop_event = asyncio.Event()

    recorded = []
    await session._audio_receiver_loop(mock_ws, spk, lambda u, a: recorded.append((u, a)), stop_event)

    assert len(recorded) == 2
    assert recorded[0] == ("Hello FRIDAY", "Hello!")
    assert recorded[1] == ("What is 1 + 1?", "2.")
    assert agent_mock.memory.add_message.call_count == 4


@pytest.mark.anyio
async def test_silence_input_no_spurious_playback():
    """Verify that silent microphone frames do not trigger local barge-in false positives."""
    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY", barge_in_rms_threshold=350.0)
    session._active = True

    silence = b"\x00\x00" * 800
    mic = MockMicrophoneStream(chunks=[silence, silence])
    mic.start()

    spk = SpeakerStream(sample_rate=24000)
    spk._active = True
    spk.play_chunk(b"active_speech" * 20)
    assert spk.is_playing

    mock_ws = MockAsyncSession()
    stop_event = asyncio.Event()

    task = asyncio.create_task(session._audio_sender_loop(mock_ws, mic, spk, stop_event))
    await asyncio.sleep(0.05)
    stop_event.set()
    await task

    # Silence must NOT purge speaker stream
    assert spk.is_playing
    assert spk.queue_size == 1


@pytest.mark.anyio
async def test_short_utterance_quick_response():
    """Verify short single-word utterances produce clean turn completion."""
    agent_mock = mock.MagicMock()
    agent_mock.memory = mock.MagicMock()

    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY", agent=agent_mock)
    session._active = True

    msg = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            turn_complete=True,
            input_tx="Time?",
            output_tx="11:15 AM.",
        )
    )

    mock_ws = MockAsyncSession(receive_messages=[msg])
    spk = MockSpeakerStream()
    stop_event = asyncio.Event()

    recorded = []
    await session._audio_receiver_loop(mock_ws, spk, lambda u, a: recorded.append((u, a)), stop_event)

    assert len(recorded) == 1
    assert recorded[0] == ("Time?", "11:15 AM.")


@pytest.mark.anyio
async def test_programmatic_cancellation():
    """Verify stop_event immediately halts audio loops cleanly."""
    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY")
    session._active = True

    stop_event = asyncio.Event()
    stop_event.set()  # Immediately cancelled

    mic = MockMicrophoneStream(chunks=[b"chunk_1"])
    spk = MockSpeakerStream()
    mock_ws = MockAsyncSession()

    # Loops should return immediately without processing
    await session._audio_sender_loop(mock_ws, mic, spk, stop_event)
    assert len(mock_ws.sent_realtime_chunks) == 0
