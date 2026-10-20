"""Unit tests for Audio I/O PortAudio callback deadlock prevention and async lifecycle."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from friday.voice.audio_io import (
    MicrophoneStream,
    MockMicrophoneStream,
    MockSpeakerStream,
    SpeakerStream,
    _close_stream_safely,
)
from friday.voice.gemini_provider import GeminiVoiceInput, GeminiVoiceOutput


@pytest.mark.asyncio
async def test_microphone_stream_stop_unblocks_waiting_reader():
    """Verify that stopping MicrophoneStream unblocks read_chunk immediately with b''."""
    fake_sounddevice = SimpleNamespace(RawInputStream=MagicMock())
    with patch("friday.voice.audio_io.sd", fake_sounddevice):
        mock_inst = MagicMock()
        fake_sounddevice.RawInputStream.return_value = mock_inst

        mic = MicrophoneStream()
        loop = asyncio.get_running_loop()
        mic.start(loop=loop)

        # Launch read_chunk in background task (queue is initially empty)
        read_task = asyncio.create_task(mic.read_chunk())
        await asyncio.sleep(0.02)
        assert not read_task.done()

        # Call stop_async - must unblock read_task immediately
        await mic.stop_async()
        result = await asyncio.wait_for(read_task, timeout=1.0)
        assert result == b""
        assert not mic.is_active


@pytest.mark.asyncio
async def test_microphone_stream_stop_sync_off_loop_safety():
    """Verify synchronous stop() invokes teardown safely without blocking event loop."""
    mic = MicrophoneStream()
    mock_raw_stream = MagicMock()
    mic._stream = mock_raw_stream
    mic._active = True
    mic._queue = asyncio.Queue()

    mic.stop()
    assert not mic.is_active
    assert mic._stream is None


@pytest.mark.asyncio
async def test_speaker_stream_drain_async():
    """Verify SpeakerStream.drain_async() waits non-blockingly."""
    spk = SpeakerStream(sample_rate=24000, prebuffer_ms=0)
    start_time = time.monotonic()
    await spk.drain_async(timeout_seconds=0.1)
    assert time.monotonic() - start_time < 0.3


@pytest.mark.asyncio
async def test_speaker_stream_close_async():
    """Verify SpeakerStream.close_async() terminates off-loop."""
    spk = SpeakerStream()
    mock_raw_stream = MagicMock()
    spk._stream = mock_raw_stream
    spk._active = True

    await spk.close_async()
    assert not spk.is_active
    assert spk._stream is None


def test_close_stream_safely_handles_exceptions_and_none():
    """Verify _close_stream_safely handles None and faulty streams without crashing."""
    _close_stream_safely(None)

    faulty_stream = MagicMock()
    faulty_stream.stop.side_effect = RuntimeError("PortAudio error")
    faulty_stream.close.side_effect = RuntimeError("PortAudio close error")
    _close_stream_safely(faulty_stream, timeout_seconds=0.5)


@pytest.mark.asyncio
async def test_gemini_voice_adapters_async_lifecycle():
    """Verify GeminiVoiceInput and GeminiVoiceOutput async methods."""
    fake_sounddevice = SimpleNamespace(
        RawInputStream=MagicMock(),
        RawOutputStream=MagicMock(),
    )
    with patch("friday.voice.audio_io.sd", fake_sounddevice):
        v_in = GeminiVoiceInput(sample_rate=16000)
        loop = asyncio.get_running_loop()
        v_in.start(loop=loop)
        assert v_in.stream._loop is loop

        await v_in.stop_async()
        assert not v_in.stream.is_active

        v_out = GeminiVoiceOutput(sample_rate=24000)
        v_out.play(b"\x00" * 100)
        await v_out.drain_async(timeout_seconds=0.1)
        await v_out.stop_async()
        assert not v_out.stream.is_active


@pytest.mark.asyncio
async def test_mock_microphone_and_speaker_streams_async_parity():
    """Verify mock audio streams have full async method parity."""
    mock_mic = MockMicrophoneStream(chunks=[b"chunk1", b"chunk2"])
    mock_mic.start()
    chunk1 = await mock_mic.read_chunk()
    assert chunk1 == b"chunk1"
    await mock_mic.stop_async()
    chunk_after_stop = await mock_mic.read_chunk()
    assert chunk_after_stop == b""

    mock_spk = MockSpeakerStream()
    mock_spk.start()
    mock_spk.play_chunk(b"audio")
    await mock_spk.drain_async()
    await mock_spk.close_async()
    assert not mock_spk.is_active
