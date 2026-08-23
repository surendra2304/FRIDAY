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
from friday.voice.gemini_live_session import GeminiLiveVoiceSession, LiveSessionState


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
async def test_sender_loop_streams_audio_continuously_without_client_barge_in_purge():
    """Verify sender loop streams audio to server without client RMS purging active speaker buffer."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
    )
    session.headphones_mode = True
    session._active = True

    loud_pcm = struct.pack("<800h", *[2000] * 800)
    # Provide 3 chunks
    mic = MockMicrophoneStream(chunks=[loud_pcm, loud_pcm, loud_pcm])
    mic.start()

    spk = SpeakerStream(sample_rate=24000)
    spk._active = True
    spk.play_chunk(b"outgoing_ai_speech" * 50)
    assert spk.is_playing

    mock_ws_session = MockAsyncSession()
    stop_event = asyncio.Event()

    task = asyncio.create_task(session._audio_sender_loop(mock_ws_session, mic, spk, stop_event))
    await asyncio.sleep(0.05)
    stop_event.set()
    await task

    # Speaker stream is NOT interrupted locally; frames are forwarded to server VAD
    assert spk.is_playing
    assert len(mock_ws_session.sent_realtime_chunks) == 3


@pytest.mark.anyio
async def test_false_barge_in_echo_protection_suppresses_speaker_leakage():
    """Verify moderate speaker acoustic echo (e.g. RMS 400 with baseline threshold 300) does not falsely trigger interruption."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        barge_in_rms_threshold=300.0,
    )
    session.barge_in_playback_factor = 2.5  # Effective threshold = 750 while speaker active
    session.headphones_mode = False
    session._active = True

    # Moderate acoustic leakage audio from speakers into mic (RMS ~400)
    echo_pcm = struct.pack("<800h", *[400] * 800)
    mic = MockMicrophoneStream(chunks=[echo_pcm, echo_pcm, echo_pcm, echo_pcm])
    mic.start()

    spk = SpeakerStream(sample_rate=24000)
    spk._active = True
    spk.play_chunk(b"outgoing_ai_speech" * 50)
    assert spk.is_playing

    mock_ws_session = MockAsyncSession()
    stop_event = asyncio.Event()

    task = asyncio.create_task(session._audio_sender_loop(mock_ws_session, mic, spk, stop_event))
    await asyncio.sleep(0.05)
    stop_event.set()
    await task

    # Speaker must remain playing — echo was safely suppressed
    assert spk.is_playing
    assert spk.queue_size > 0


@pytest.mark.anyio
async def test_server_vad_authoritative_interruption():
    """Verify server-side VAD interruption signal is authoritative and immediately purges speaker."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
    )
    session._active = True

    spk = MockSpeakerStream(sample_rate=24000)
    spk.start()
    spk.play_chunk(b"outgoing_speech" * 10)
    assert spk.is_playing

    msg = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            interrupted=True,
            turn_complete=False,
        )
    )

    mock_ws_session = MockAsyncSession(receive_messages=[msg])
    stop_event = asyncio.Event()

    await session._audio_receiver_loop(mock_ws_session, spk, lambda u, a: None, stop_event)

    # Verified: Purged and transitioned to INTERRUPTED state
    assert session.state == LiveSessionState.INTERRUPTED
    assert spk.interrupted_count == 1
    assert not spk.is_playing


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


@pytest.mark.anyio
async def test_speaker_mode_eliminates_self_interruption_even_with_large_echo():
    """Verify speaker mode (default) eliminates self-interruption from speaker echo even with large acoustic RMS spikes (e.g. 7600+)."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        barge_in_rms_threshold=350.0,
    )
    session.local_barge_in_during_playback = False
    session.headphones_mode = False
    session._active = True

    # Real-world observed large acoustic echo spike from laptop speakers (RMS > 7000)
    loud_speaker_echo_pcm = struct.pack("<800h", *[7500] * 800)
    mic = MockMicrophoneStream(chunks=[loud_speaker_echo_pcm] * 10)
    mic.start()

    spk = SpeakerStream(sample_rate=24000)
    spk._active = True
    spk.play_chunk(b"ai_playing_output" * 50)
    assert spk.is_playing

    mock_ws = MockAsyncSession()
    stop_event = asyncio.Event()

    task = asyncio.create_task(session._audio_sender_loop(mock_ws, mic, spk, stop_event))
    await asyncio.sleep(0.08)
    stop_event.set()
    await task

    # Under speaker mode, speaker playback must NOT be interrupted locally by echo spikes
    assert spk.is_playing
    assert session.speaker_playback_interruptions == 0
    # But mic audio is continuously forwarded to Gemini for authoritative server VAD
    assert len(mock_ws.sent_realtime_chunks) == 10


@pytest.mark.anyio
async def test_adaptive_noise_floor_updates_during_silence():
    """Verify ambient noise floor dynamically updates from incoming audio frames when speaker is idle."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        barge_in_rms_threshold=350.0,
    )
    session._ambient_noise_floor = 20.0
    session.adaptive_noise_alpha = 0.2
    session._active = True

    # Moderate background room noise (RMS ~100)
    noise_pcm = struct.pack("<800h", *[100] * 800)
    mic = MockMicrophoneStream(chunks=[noise_pcm, noise_pcm, noise_pcm])
    mic.start()

    spk = SpeakerStream(sample_rate=24000)
    spk._active = False  # Idle speaker

    mock_ws = MockAsyncSession()
    stop_event = asyncio.Event()

    task = asyncio.create_task(session._audio_sender_loop(mock_ws, mic, spk, stop_event))
    await asyncio.sleep(0.05)
    stop_event.set()
    await task

    # Adaptive noise floor must have adjusted upward toward 100
    assert session._ambient_noise_floor > 20.0


@pytest.mark.anyio
def test_server_vad_configuration_tuning():
    """Verify LiveConnectConfig applies tuned VAD parameters for conversational voice."""
    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY",
        vad_start_sensitivity="LOW",
        vad_end_sensitivity="HIGH",
        vad_prefix_padding_ms=300,
        vad_silence_duration_ms=800,
    )
    live_config = session._build_live_config()
    realtime_cfg = live_config.realtime_input_config
    assert realtime_cfg is not None
    auto_vad = realtime_cfg.automatic_activity_detection
    assert auto_vad is not None
    assert auto_vad.prefix_padding_ms == 300
    assert auto_vad.silence_duration_ms == 800


@pytest.mark.anyio
async def test_user_speech_then_silence_completes_full_response():
    """Verify that when user finishes speaking and remains silent, model turn completes fully without interruption."""
    agent_mock = mock.MagicMock()
    agent_mock.memory = mock.MagicMock()

    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY", agent=agent_mock)
    session._active = True

    # Multi-chunk complete model turn
    msg1 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            parts=[MockGenAIPart(data=b"chunk1", text="Good morning. ")],
            turn_complete=False,
            input_tx="Hi FRIDAY",
        )
    )
    msg2 = MockGenAIServerMessage(
        server_content=MockGenAIServerContent(
            parts=[MockGenAIPart(data=b"chunk2", text="How can I help you today?")],
            turn_complete=True,
            output_tx="Good morning. How can I help you today?",
        )
    )

    mock_ws = MockAsyncSession(receive_messages=[msg1, msg2])
    spk = MockSpeakerStream(sample_rate=24000)
    spk.start()
    stop_event = asyncio.Event()

    recorded = []
    await session._audio_receiver_loop(mock_ws, spk, lambda u, a: recorded.append((u, a)), stop_event)

    # Must complete with 0 interruptions and complete text
    assert len(recorded) == 1
    user_tx, agent_tx = recorded[0]
    assert user_tx == "Hi FRIDAY"
    assert agent_tx == "Good morning. How can I help you today?"
    assert "[interrupted]" not in agent_tx
    assert session.server_interruptions == 0
    assert session.user_interruptions == 0


