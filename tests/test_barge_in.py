"""Deterministic unit tests for true barge-in, acoustic interruptions, and context preservation."""

import asyncio
import math
import struct
from unittest import mock
import pytest

from friday.core.types import Message, Role
from friday.voice.audio_io import MockMicrophoneStream, MockSpeakerStream, compute_pcm_rms
from friday.voice.gemini_live_session import GeminiLiveVoiceSession


def _generate_pcm_tone(sample_rate=16000, duration_s=0.1, amplitude=0.5, freq=440.0):
    """Helper to generate synthetic PCM audio bytes with deterministic RMS."""
    num_samples = int(sample_rate * duration_s)
    pcm = bytearray()
    for i in range(num_samples):
        sample = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * freq * (i / sample_rate)))
        pcm.extend(struct.pack("<h", sample))
    return bytes(pcm)


def test_compute_pcm_rms():
    """Verify RMS calculation accurately measures signal energy."""
    silence = b"\x00\x00" * 800
    assert compute_pcm_rms(silence) == 0.0

    loud_chunk = _generate_pcm_tone(amplitude=0.8)
    rms = compute_pcm_rms(loud_chunk)
    assert rms > 15000.0


@pytest.mark.anyio
async def test_local_acoustic_barge_in_triggers_speaker_stop():
    """Verify high-energy user speech instantly triggers speaker.stop() when speaker is active."""
    # 1. Setup mock session and devices
    mock_ws = mock.MagicMock()
    mock_ws.send_realtime_input = mock.AsyncMock()

    spk = MockSpeakerStream(sample_rate=24000)
    spk.start()
    spk.play_chunk(b"assistant_speech_playing")
    assert spk.is_playing

    loud_speech_chunk = _generate_pcm_tone(duration_s=0.1, amplitude=0.5)
    mic = MockMicrophoneStream(sample_rate=16000, chunks=[loud_speech_chunk])
    mic.start()

    session = GeminiLiveVoiceSession(
        api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12123",
        barge_in_threshold=500.0,
    )
    session._active = True

    stop_event = asyncio.Event()

    # Run sender loop for one chunk
    send_task = asyncio.create_task(session._audio_sender_loop(mock_ws, mic, spk, stop_event))
    await asyncio.sleep(0.05)
    stop_event.set()
    await send_task

    # Verify speaker stopped immediately
    assert spk.interrupted_count >= 1
    assert len(spk.played_chunks) == 0


@pytest.mark.anyio
async def test_spoken_stop_word_triggers_interruption():
    """Verify spoken command like 'stop' immediately halts active playback."""
    spk = MockSpeakerStream(sample_rate=24000)
    spk.start()
    spk.play_chunk(b"long_audio_chunk")
    assert spk.is_playing

    msg = mock.MagicMock()
    msg.server_content = mock.MagicMock(
        interrupted=False,
        model_turn=None,
        input_transcription=mock.MagicMock(text="Stop right now"),
        output_transcription=None,
        turn_complete=False,
    )
    msg.tool_call = None
    msg.tool_call_cancellation = None

    class MockWS:
        async def receive(self):
            yield msg

    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12123")
    session._active = True
    stop_event = asyncio.Event()

    await session._audio_receiver_loop(MockWS(), spk, None, stop_event)

    # Verify speaker playback was stopped
    assert spk.interrupted_count >= 1
    assert len(spk.played_chunks) == 0


@pytest.mark.anyio
async def test_context_coherence_across_interruption():
    """Verify conversation history correctly records user turns after an interruption."""
    mock_memory = mock.MagicMock()
    mock_agent = mock.MagicMock(memory=mock_memory)

    spk = MockSpeakerStream(sample_rate=24000)
    spk.start()

    # Message 1: Interruption
    msg1 = mock.MagicMock()
    msg1.server_content = mock.MagicMock(
        interrupted=True,
        model_turn=None,
        input_transcription=None,
        output_transcription=None,
        turn_complete=False,
    )
    msg1.tool_call = None
    msg1.tool_call_cancellation = None

    # Message 2: Completed new turn
    msg2 = mock.MagicMock()
    msg2.server_content = mock.MagicMock(
        interrupted=False,
        model_turn=None,
        input_transcription=mock.MagicMock(text="What is the weather?"),
        output_transcription=mock.MagicMock(text="It is 72 degrees and sunny."),
        turn_complete=True,
    )
    msg2.tool_call = None
    msg2.tool_call_cancellation = None

    class MockWS:
        async def receive(self):
            yield msg1
            yield msg2

    session = GeminiLiveVoiceSession(api_key="TEST_GEMINI_API_KEY_PLACEHOLDER_12123", agent=mock_agent)
    session._active = True
    stop_event = asyncio.Event()

    turns_logged = []
    def on_turn(u, a):
        turns_logged.append((u, a))

    await session._audio_receiver_loop(MockWS(), spk, on_turn, stop_event)

    # Verify memory committed the coherent turn
    assert len(turns_logged) == 1
    assert turns_logged[0] == ("What is the weather?", "It is 72 degrees and sunny.")
    assert mock_memory.add_message.call_count == 2
    calls = mock_memory.add_message.call_args_list
    assert calls[0][0][0].role == Role.USER
    assert calls[0][0][0].content == "What is the weather?"
    assert calls[1][0][0].role == Role.ASSISTANT
    assert calls[1][0][0].content == "It is 72 degrees and sunny."
