# -*- coding: utf-8 -*-
"""Real Physical Audio Hardware Integration & Verification Test.

Test Type: HARDWARE / REAL AUDIO IO
Mark: pytest.mark.hardware

Validates:
1. Physical microphone detection and real 16 kHz 16-bit linear PCM audio chunk capture.
2. Physical speaker detection and live 24 kHz 16-bit PCM playback stream.
3. Verification that missing hardware or permission failures are classified honestly as BLOCKED or FAIL,
   never silently converted into synthetic passes.
"""

import sys
import time
import pytest

pytestmark = [pytest.mark.hardware]

from friday.voice.audio_io import (
    MicrophoneStream,
    SpeakerStream,
    check_device_availability,
    compute_pcm_rms,
    get_audio_diagnostics,
)
from friday.core.exceptions import VoiceError


def test_real_audio_hardware_diagnostics_and_devices():
    """Verify physical audio driver and device availability."""
    diag = get_audio_diagnostics()
    assert isinstance(diag, dict)

    if not diag.get("driver_available"):
        pytest.skip(f"Audio driver unavailable: {diag.get('error')} -> BLOCKED")

    dev_count = diag.get("device_count", 0)
    if dev_count == 0:
        pytest.skip("No physical audio devices detected on this system -> BLOCKED")

    assert dev_count > 0, "No audio devices detected"


def test_real_microphone_capture_stream():
    """Verify continuous 16kHz PCM capture on real physical microphone."""
    has_input, in_err = check_device_availability("input")
    if not has_input:
        pytest.skip(f"Physical microphone input device unavailable: {in_err} -> BLOCKED")

    import asyncio

    async def _capture():
        mic = MicrophoneStream(sample_rate=16000, chunk_duration_ms=40)
        loop = asyncio.get_running_loop()
        mic.start(loop=loop)

        if not mic.is_active or mic.error:
            pytest.fail(f"Physical microphone failed to start: {mic.error}")

        # Capture 5 real chunks (200ms of real audio)
        chunks = []
        for _ in range(5):
            chunk = await mic.read_chunk()
            if chunk:
                chunks.append(chunk)

        mic.stop()
        assert not mic.is_active

        # Verify chunks contain real 16-bit PCM samples (16000 * 0.04 * 2 bytes = 1280 bytes/chunk)
        assert len(chunks) > 0, "No audio chunks captured from physical microphone"
        for c in chunks:
            assert len(c) == 1280, f"Expected 1280 bytes per 40ms 16kHz chunk, got {len(c)}"
            rms = compute_pcm_rms(c)
            assert rms >= 0.0

    asyncio.run(_capture())


def test_real_speaker_playback_stream():
    """Verify live 24kHz PCM output stream on physical speaker."""
    has_output, out_err = check_device_availability("output")
    if not has_output:
        pytest.skip(f"Physical speaker output device unavailable: {out_err} -> BLOCKED")

    import numpy as np

    spk = SpeakerStream(sample_rate=24000)
    spk.start()

    if not spk.is_active or spk.error:
        pytest.fail(f"Physical speaker stream failed to start: {spk.error}")

    # Generate 100ms of 440Hz test sine tone in 16-bit PCM (2400 samples = 4800 bytes)
    sample_rate = 24000
    duration_s = 0.1
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    sine_wave = (np.sin(2 * np.pi * 440 * t) * 5000).astype(np.int16)
    tone_bytes = sine_wave.tobytes()

    spk.play_chunk(tone_bytes)
    time.sleep(0.15)

    # Purge / Stop
    spk.stop()
    spk.close()
    assert not spk.is_active


def test_hardware_failure_raises_voice_error():
    """Verify that an invalid device index raises VoiceError and never produces empty synthetic success."""
    import asyncio

    async def _test_invalid_device():
        from friday.voice.gemini_live_session import GeminiLiveVoiceSession
        session = GeminiLiveVoiceSession(
            api_key="test_key",
            model="gemini-2.0-flash-exp",
        )
        invalid_mic = MicrophoneStream(device=99999)  # Non-existent device index
        invalid_spk = SpeakerStream(device=99999)

        with pytest.raises(VoiceError) as exc_info:
            await session.run_live_loop(input_stream=invalid_mic, output_stream=invalid_spk)

        assert "unavailable" in str(exc_info.value).lower()

    asyncio.run(_test_invalid_device())
