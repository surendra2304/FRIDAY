"""Real Gemini voice provider implementation using official google-genai SDK.

This module provides a voice interface for FRIDAY using the official Google GenAI SDK.
It captures microphone audio, sends it to Gemini for transcription, and synthesizes
responses using Gemini audio capabilities.
"""

from __future__ import annotations

import base64
import io
import wave
from typing import Optional

import numpy as np
import sounddevice as sd
from google import genai
from google.genai import types as genai_types

from .base import VoiceInput, VoiceOutput, VoiceProvider
from ..core.config import get_settings

_shared_client: Optional[genai.Client] = None


def _get_shared_client(api_key: str) -> genai.Client:
    """Return a cached GenAI Client configured with the given API key."""
    global _shared_client
    if _shared_client is None:
        _shared_client = genai.Client(api_key=api_key)
    return _shared_client


def _record_audio(sample_rate: int = 16000, duration: float = 4.0) -> bytes:
    """Record audio from the default microphone."""
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
    """Decode audio bytes to a NumPy float32 array for playback."""
    try:
        return np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    except Exception:
        return np.array([], dtype=np.float32)


class GeminiVoiceInput(VoiceInput):
    """Capture microphone audio and obtain a transcription via Gemini."""

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
        client = _get_shared_client(self.api_key)
        audio_part = genai_types.Part.from_bytes(data=wav_bytes, mime_type="audio/wav")
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[audio_part, "Transcribe the spoken audio verbatim. Return only the transcript text."],
            )
        except Exception as exc:
            raise RuntimeError(f"Gemini transcription failed: {exc}") from exc
        transcript = getattr(response, "text", None) or ""
        if not transcript:
            raise RuntimeError("Gemini returned no transcription")
        return transcript.strip()


class GeminiVoiceOutput(VoiceOutput):
    """Synthesize speech using Gemini's audio generation and play it back."""

    def __init__(self, api_key: str, output_format: str = "mp3"):
        self.api_key = api_key
        self.output_format = output_format

    def synthesize(self, text: str) -> bytes:
        client = _get_shared_client(self.api_key)
        config = genai_types.GenerateContentConfig(
            response_mime_type=f"audio/{self.output_format}",
        )
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=text,
                config=config,
            )
        except Exception:
            return b""
        audio_bytes = getattr(response, "audio", None)
        if audio_bytes is None:
            try:
                candidate = response.candidates[0]
                for part in candidate.content.parts:
                    if getattr(part, "inline_data", None):
                        audio_bytes = part.inline_data.data
                        break
            except Exception:
                audio_bytes = b""
        return audio_bytes or b""

    def play(self, audio: bytes) -> None:
        """Play audio bytes non-blocking."""
        if not audio:
            return
        try:
            pcm = _decode_audio_mp3(audio)
            if pcm.size == 0:
                return
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
        api_key = settings.gemini_api_key or settings.llm_api_key
        if not api_key:
            raise ValueError("Gemini API key not configured (FRIDAY_GEMINI_API_KEY)")
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
