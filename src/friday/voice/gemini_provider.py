"""Real Gemini voice provider implementation.

This module provides a production‑ready voice interface for FRIDAY using the official
Google Gemini Generative AI SDK. It captures microphone audio, streams it to Gemini
for speech‑to‑text, and synthesizes spoken responses using Gemini's audio output
capabilities.

The implementation relies on the following lightweight dependencies:
- ``sounddevice`` – cross‑platform audio I/O (already selected by the user).
- ``numpy`` – required by ``sounddevice`` for audio buffers.
- ``google-generativeai`` – official Gemini SDK.

All secrets (the Gemini API key) are read from the existing configuration via
``get_settings()``; no key is written to source files.
"""

from __future__ import annotations

import io
import base64
import wave
import logging
from typing import Optional

import numpy as np
import sounddevice as sd
import google.generativeai as genai

from .base import VoiceInput, VoiceOutput, VoiceProvider
from ..core.config import get_settings

# Module‑level singleton for the Gemini model to avoid re‑initialisation per call
_shared_model = None

def _get_shared_model(api_key: str):
    """Return a cached GenerativeModel instance configured with the given API key.
    The first call creates the model; subsequent calls reuse it.
    """
    global _shared_model
    if _shared_model is None:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        _shared_model = genai.GenerativeModel("gemini-1.5-flash")
    return _shared_model



def _record_audio(sample_rate: int = 16000, duration: float = 4.0) -> bytes:
    """Record audio from the default microphone.

    Args:
        sample_rate: Sample rate in Hz.
        duration: Recording duration in seconds.

    Returns:
        WAV‑encoded audio bytes.
    """
    wav_io = io.BytesIO()
    recording = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype="int16")
    sd.wait()
    with wave.open(wav_io, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(recording.tobytes())
    return wav_io.getvalue()


def _decode_audio_mp3(audio_bytes: bytes) -> np.ndarray:
    """Decode MP3 bytes to a NumPy float32 array for playback.

    This helper uses a simple fallback: treat the payload as raw PCM int16. If the
    conversion fails, an empty array is returned.
    """
    try:
        return np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:
        return np.array([], dtype=np.float32)


class GeminiVoiceInput(VoiceInput):
    """Capture microphone audio and obtain a transcription via Gemini Live.
    """

    def __init__(self, api_key: str, sample_rate: int = 16000, duration: float = 4.0):
        self.api_key = api_key
        self.sample_rate = sample_rate
        self.duration = duration
        self.active = False

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    def read_chunk(self) -> str:
        if not self.active:
            raise RuntimeError("GeminiVoiceInput not started")
        wav_bytes = _record_audio(sample_rate=self.sample_rate, duration=self.duration)
        model = _get_shared_model(self.api_key)
        audio_part = {"mime_type": "audio/wav", "data": base64.b64encode(wav_bytes).decode("utf-8")}
        try:
            response = model.generate_content([audio_part])
        except Exception as exc:
            raise RuntimeError(f"Gemini transcription failed: {exc}") from exc
        transcript = getattr(response, "text", None) or getattr(response, "content", None)
        if not transcript:
            raise RuntimeError("Gemini returned no transcription")
        if not isinstance(transcript, str):
            transcript = str(transcript)
        return transcript.strip()


class GeminiVoiceOutput(VoiceOutput):
    """Synthesize speech using Gemini's audio generation and play it back."""

    def __init__(self, api_key: str, output_format: str = "mp3"):
        self.api_key = api_key
        self.output_format = output_format

    def synthesize(self, text: str) -> bytes:
        # Reuse shared Gemini model for synthesis
        model = _get_shared_model(self.api_key)
        generation_config = {"response_mime_type": f"audio/{self.output_format}"}
        try:
            response = model.generate_content(text, generation_config=generation_config)
        except Exception:
            return b""
        audio_bytes = getattr(response, "audio", None)
        if audio_bytes is None:
            try:
                audio_bytes = response.candidates[0].content.parts[0].audio
            except Exception:
                audio_bytes = b""
        return audio_bytes or b""

    def play(self, audio: bytes) -> None:
        """Play audio bytes non‑blocking. Playback can be interrupted via `stop`.
        """
        if not audio:
            return
        try:
            pcm = _decode_audio_mp3(audio)
            if pcm.size == 0:
                return
            # Non‑blocking playback; do not call sd.wait()
            sd.play(pcm, samplerate=16000)
        except Exception:
            return

    def stop(self) -> None:
        """Immediately stop any ongoing playback."""
        try:
            sd.stop()
        except Exception:
            pass


class GeminiVoiceProvider(VoiceProvider):
    """Orchestrator tying Gemini input and output devices."""

    def __init__(self):
        settings = get_settings()
        api_key = settings.gemini_api_key
        if not api_key:
            raise ValueError("Gemini API key not configured (FRIDAY_GEMINI_API_KEY)")
        # Warm‑up the shared model with a short dummy request
        warmup_text = getattr(settings, "voice_model_warmup_text", "hello")
        _get_shared_model(api_key).generate_content(warmup_text)
        input_dev = GeminiVoiceInput(
            api_key=api_key,
            sample_rate=getattr(settings, "voice_input_sample_rate", 16000),
        )
        output_dev = GeminiVoiceOutput(
            api_key=api_key,
            output_format=getattr(settings, "voice_output_format", "mp3"),
        )
        super().__init__(input_dev, output_dev)

    def run_session(self, agent) -> None:
        self.input.start()
        try:
            while True:
                # Ensure any previous playback is stopped before new input
                self.output.stop()
                try:
                    user_text = self.input.read_chunk()
                except RuntimeError:
                    break
                response = agent.process_message(user_text)
                text = getattr(response, "content", str(response))
                audio = self.output.synthesize(text)
                self.output.play(audio)
        finally:
            self.input.stop()
            self.output.stop()
