"""Unit tests for real-time audio pipeline, buffers, diagnostics, queues, and device error recovery."""

import asyncio
import queue
import struct
from unittest import mock
import pytest

from friday.voice.audio_io import (
    MicrophoneStream,
    SpeakerStream,
    MockMicrophoneStream,
    MockSpeakerStream,
    check_device_availability,
    compute_pcm_rms,
    get_audio_diagnostics,
)


def test_audio_diagnostics_structure():
    """Verify audio device diagnostics returns structured hardware information."""
    diag = get_audio_diagnostics()
    assert "driver_available" in diag
    assert isinstance(diag["driver_available"], bool)
    assert "devices" in diag
    assert isinstance(diag["devices"], list)


def test_check_device_availability():
    """Verify check_device_availability handles input and output queries cleanly."""
    in_ok, in_err = check_device_availability("input")
    out_ok, out_err = check_device_availability("output")
    assert isinstance(in_ok, bool)
    assert isinstance(out_ok, bool)

    # Invalid query
    inv_ok, inv_err = check_device_availability("invalid_type")
    assert inv_ok is False
    assert "Unknown device type" in inv_err


def test_microphone_stream_chunk_sizing():
    """Verify microphone calculates block size correctly based on duration ms."""
    mic = MicrophoneStream(sample_rate=16000, chunk_duration_ms=100)
    assert mic.sample_rate == 16000
    assert mic.channels == 1
    assert mic.block_size == 1600  # 16000 * 0.1s = 1600 samples

    mic2 = MicrophoneStream(sample_rate=16000, chunk_duration_ms=25)
    assert mic2.block_size == 400  # 16000 * 0.025s = 400 samples


def test_speaker_stream_buffering_and_purge():
    """Verify speaker stream enqueues chunks and purges queue immediately on interruption."""
    spk = SpeakerStream(sample_rate=24000, prebuffer_ms=0)
    spk._active = True

    chunk_a = b"\x01\x02" * 100
    chunk_b = b"\x03\x04" * 100

    spk.play_chunk(chunk_a)
    spk.play_chunk(chunk_b)
    assert spk.queue_size == 2
    assert spk.played_chunks == 2

    # Barge-in interruption
    spk.stop()
    assert spk.queue_size == 0


def test_speaker_stream_overflow_protection():
    """Verify speaker stream drops oldest chunk when max queue size is exceeded."""
    spk = SpeakerStream(sample_rate=24000, max_buffer_chunks=2, prebuffer_ms=0)
    spk._active = True

    spk.play_chunk(b"chunk_1")
    spk.play_chunk(b"chunk_2")
    assert spk.queue_size == 2

    # Push 3rd chunk, should trigger overflow protection
    spk.play_chunk(b"chunk_3")
    assert spk.queue_size == 2
    assert spk.overflow_count == 1


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
    assert mock_spk.queue_size == 2

    mock_spk.stop()
    assert len(mock_spk.played_chunks) == 0
    assert mock_spk.interrupted_count == 1
    mock_spk.close()
    assert not mock_spk.is_active


def test_mock_stream_simulated_errors():
    """Verify mock audio streams properly simulate initialization and device errors."""
    mock_mic = MockMicrophoneStream(simulate_error="Permission Denied: Microphone Access")
    mock_mic.start()
    assert not mock_mic.is_active
    assert mock_mic.error == "Permission Denied: Microphone Access"

    mock_spk = MockSpeakerStream(simulate_error="Audio device busy (exclusive mode)")
    mock_spk.start()
    assert not mock_spk.is_active
    assert mock_spk.error == "Audio device busy (exclusive mode)"


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
        spk = SpeakerStream(sample_rate=24000, prebuffer_ms=0)
        spk.start()
        assert not spk.is_active
        assert spk.error is not None
        assert "Device Disconnected" in spk.error


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


def test_compute_pcm_rms_accuracy():
    """Verify RMS energy calculation handles silence, noise, and clipping."""
    assert compute_pcm_rms(b"") == 0.0
    silence = b"\x00\x00" * 400
    assert compute_pcm_rms(silence) == 0.0

    loud = struct.pack("<400h", *[5000] * 400)
    assert 4990 < compute_pcm_rms(loud) < 5010
