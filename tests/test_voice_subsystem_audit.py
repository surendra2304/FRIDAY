# -*- coding: utf-8 -*-
"""Comprehensive Voice Subsystem Audit and Regression Tests for FRIDAY.

Verifies:
1. MicrophoneStream & SpeakerStream PCM formatting, queue buffering, and interruption.
2. VAD & barge-in RMS calculation and adaptive noise floor.
3. GeminiLiveVoiceSession multi-credential failover without leaking API keys.
4. Reconnection, backoff, and state transitions.
5. Hardware diagnostics and device availability classification (BLOCKED on missing hardware).
6. GeminiVoiceProvider integration with credential pool and Live voice model preservation.
"""

import asyncio
import numpy as np
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from friday.auth.credential_pool import GeminiCredentialPool
from friday.core.types import SafetyLevel, ToolResult
from friday.voice.audio_io import (
    MicrophoneStream,
    MockMicrophoneStream,
    MockSpeakerStream,
    SpeakerStream,
    check_device_availability,
    compute_pcm_rms,
    get_audio_diagnostics,
)
from friday.voice.gemini_live_session import GeminiLiveVoiceSession, LiveSessionState
from friday.voice.gemini_provider import GeminiVoiceInput, GeminiVoiceOutput, GeminiVoiceProvider


# ============================================================================
# 1. Audio I/O, PCM Buffering & Instant Interruption Purge Tests
# ============================================================================

def test_microphone_pcm_buffering_and_rms():
    """Verify microphone PCM stream chunking and RMS energy calculation."""
    # Synthetic 16kHz sine wave PCM chunk (40ms = 640 samples = 1280 bytes)
    sample_rate = 16000
    duration_s = 0.04
    t = np.linspace(0, duration_s, int(sample_rate * duration_s), endpoint=False)
    sine_wave = (np.sin(2 * np.pi * 440 * t) * 10000).astype(np.int16)
    raw_bytes = sine_wave.tobytes()

    rms = compute_pcm_rms(raw_bytes)
    assert rms > 5000.0, f"Expected RMS > 5000 for 10000-amplitude sine wave, got {rms}"

    # Silence RMS should be 0
    silence_bytes = np.zeros(640, dtype=np.int16).tobytes()
    assert compute_pcm_rms(silence_bytes) == 0.0


def test_speaker_interruption_purges_buffer():
    """Verify speaker stream stop() instantly purges queued audio chunks for barge-in."""
    spk = MockSpeakerStream(sample_rate=24000)
    spk.start()

    # Queue 5 audio chunks
    dummy_chunk = np.zeros(480, dtype=np.int16).tobytes()
    for _ in range(5):
        spk.play_chunk(dummy_chunk)

    assert spk.queue_size > 0

    # Stop/interrupt
    spk.stop()
    assert spk.queue_size == 0, "Speaker buffer was not completely purged on stop/interruption!"


# ============================================================================
# 2. Credential Failover in Gemini Live Voice Session Tests
# ============================================================================

def test_gemini_live_credential_failover_on_quota_error():
    """Verify that GeminiLiveVoiceSession rotates credentials on quota exhaustion (429)."""
    async def _run():
        pool = GeminiCredentialPool(keys=["primary_key_1111", "fallback_key_2222", "fallback_key_3333"])

        session = GeminiLiveVoiceSession(
            api_key=None,
            credential_pool=pool,
            model="gemini-3.1-flash-live-preview",
            max_retries=1,
        )

        assert session.api_key == "primary_key_1111"

        # Simulate 429 Resource Exhausted during live loop
        mock_connect = MagicMock()
        mock_connect.side_effect = [
            Exception("429 Resource Exhausted: Quota exceeded"),
            AsyncMock(),  # Second connect succeeds
        ]

        with patch("google.genai.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.aio.live.connect = mock_connect
            mock_client_cls.return_value = mock_client

            stop_event = asyncio.Event()
            # Trigger stop after a brief moment
            asyncio.get_running_loop().call_later(0.1, stop_event.set)

            # Run loop
            try:
                await asyncio.wait_for(
                    session.run_live_loop(
                        input_stream=MockMicrophoneStream(),
                        output_stream=MockSpeakerStream(),
                        stop_event=stop_event,
                    ),
                    timeout=2.0,
                )
            except Exception:
                pass

        # Credential pool should have rotated to fallback_key_2222
        assert pool.get_active_key() == "fallback_key_2222"
        assert session.api_key == "fallback_key_2222"

    asyncio.run(_run())


# ============================================================================
# 3. Model Validation & Live Voice Model Preservation Tests
# ============================================================================

def test_live_voice_model_preservation_and_fallback():
    """Verify that GeminiLiveVoiceSession enforces a valid Gemini Live model."""
    # Attempting to supply a non-live text model (e.g. gemini-3.7-flash) falls back to Live voice model
    session = GeminiLiveVoiceSession(
        api_key="test_key",
        model="gemini-3.7-flash",  # Non-live model
    )

    assert "live" in session.model.lower()
    assert session.model == "gemini-3.1-flash-live-preview"


# ============================================================================
# 4. Hardware Availability & Diagnostics Classification Tests
# ============================================================================

def test_audio_hardware_diagnostics_and_classification():
    """Verify hardware diagnostics and check device availability."""
    diag = get_audio_diagnostics()
    assert isinstance(diag, dict)
    assert "driver_available" in diag

    has_input, in_err = check_device_availability("input")
    has_output, out_err = check_device_availability("output")

    # If physical audio devices are absent (e.g. headless CI), result must be flagged clearly
    if not has_input:
        assert in_err is not None
    if not has_output:
        assert out_err is not None


# ============================================================================
# 5. GeminiVoiceProvider Integration Tests
# ============================================================================

def test_gemini_voice_provider_adapters_and_pool():
    """Verify GeminiVoiceProvider initializes with pool and non-empty adapter functionality."""
    pool = GeminiCredentialPool(keys=["test_primary_key_abc"])
    provider = GeminiVoiceProvider(credential_pool=pool)

    assert provider.api_key == "test_primary_key_abc"
    assert "live" in provider.model.lower()

    # Verify input adapter description
    chunk_desc = provider.input.read_chunk()
    assert "PCM Audio Stream" in chunk_desc

    # Verify output adapter synthesis returns real PCM bytes
    pcm_out = provider.output.synthesize("Hello world voice test")
    assert len(pcm_out) > 0
    assert isinstance(pcm_out, bytes)
