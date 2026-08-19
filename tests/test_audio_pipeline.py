"""Unit tests for real-time audio pipeline, buffers, diagnostics, and barge-in."""

import asyncio
import queue
from unittest import mock
import pytest

from friday.voice.audio_io import (
    MicrophoneStream,
    SpeakerStream,
    MockMicrophoneStream,
    MockSpeakerStream,
    get_audio_diagnostics,
)


def test_audio_diagnostics():
    """Verify audio device diagnostics returns structured hardware information."""
    diag = get_audio_diagnostics()
    assert "driver_available" in diag
    assert isinstance(diag["driver_available"], bool)
    assert "devices" in diag
    assert isinstance(diag["devices"], list)


def test_microphone_stream_chunk_sizing():
    """Verify microphone calculates block size correctly based on duration ms."""
    mic = MicrophoneStream(sample_rate=16000, chunk_duration_ms=100)
    assert mic.sample_rate == 16000
    assert mic.channels == 1
    assert mic.block_size == 1600  # 16000 * 0.1s = 1600 samples


def test_speaker_stream_buffering_and_purge():
    """Verify speaker stream enqueues chunks and purges queue immediately on interruption."""
    spk = SpeakerStream(sample_rate=24000)
    spk._active = True

    chunk_a = b"\x01\x02" * 100
    chunk_b = b"\x03\x04" * 100

    spk.play_chunk(chunk_a)
    spk.play_chunk(chunk_b)
    assert spk.queue_size == 2

    # Barge-in interruption
    spk.stop()
    assert spk.queue_size == 0


@pytest.mark.anyio
async def test_mock_microphone_stream_async_iter():
    """Verify MockMicrophoneStream yields predefined PCM chunks asynchronously."""
    chunks = [b"chunk_1", b"chunk_2", b"chunk_3"]
    mock_mic = MockMicrophoneStream(sample_rate=16000, chunks=chunks)
    mock_mic.start()

    collected = []
    async for c in mock_mic.iter_chunks():
        collected.append(c)

    assert collected == chunks
    mock_mic.stop()
    assert not mock_mic.is_active


def test_mock_speaker_stream_playback_and_interruption():
    """Verify MockSpeakerStream stores chunks and clears on interruption."""
    mock_spk = MockSpeakerStream(sample_rate=24000)
    mock_spk.start()

    mock_spk.play_chunk(b"audio_part_1")
    mock_spk.play_chunk(b"audio_part_2")
    assert len(mock_spk.played_chunks) == 2

    mock_spk.stop()
    assert len(mock_spk.played_chunks) == 0
    assert mock_spk.interrupted_count == 1
    mock_spk.close()
    assert not mock_spk.is_active


def test_microphone_device_failure_handling():
    """Verify MicrophoneStream gracefully records error state on device failure."""
    with mock.patch("sounddevice.RawInputStream", side_effect=RuntimeError("Device Busy")):
        mic = MicrophoneStream(sample_rate=16000)
        mic.start()
        assert not mic.is_active
        assert mic.error is not None
        assert "Device Busy" in mic.error


def test_speaker_device_failure_handling():
    """Verify SpeakerStream gracefully records error state on device failure."""
    with mock.patch("sounddevice.RawOutputStream", side_effect=RuntimeError("Device Disconnected")):
        spk = SpeakerStream(sample_rate=24000)
        spk.start()
        assert not spk.is_active
        assert spk._error is not None
        assert "Device Disconnected" in spk._error


@pytest.mark.anyio
async def test_concurrent_mic_and_speaker_pipeline():
    """Verify simultaneous non-blocking microphone capture and speaker streaming."""
    mic = MockMicrophoneStream(sample_rate=16000, chunks=[b"in_1", b"in_2"])
    spk = MockSpeakerStream(sample_rate=24000)

    mic.start()
    spk.start()

    async def mic_reader():
        chunks = []
        async for c in mic.iter_chunks():
            chunks.append(c)
        return chunks

    async def spk_player():
        for i in range(3):
            spk.play_chunk(f"out_{i}".encode())
            await asyncio.sleep(0.01)

    mic_res, _ = await asyncio.gather(mic_reader(), spk_player())
    assert mic_res == [b"in_1", b"in_2"]
    assert len(spk.played_chunks) == 3
