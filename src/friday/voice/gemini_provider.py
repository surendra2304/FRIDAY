"""Real Gemini voice provider implementation using official google-genai SDK.

This module provides the voice interface for FRIDAY using the official Google GenAI SDK.
It integrates Gemini Live full-duplex asynchronous WebSocket sessions for real-time
low-latency conversational speech.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional
import numpy as np

from .base import VoiceInput, VoiceOutput, VoiceProvider
from .audio_io import MicrophoneStream, SpeakerStream
from .gemini_live_session import GeminiLiveVoiceSession
from friday.auth.credential_pool import credential_pool as global_credential_pool, GeminiCredentialPool
from ..core.config import get_settings
from ..core.logging import get_logger

logger = get_logger("voice.gemini_provider")


class GeminiVoiceInput(VoiceInput):
    """Adapter for microphone input stream."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.stream = MicrophoneStream(sample_rate=sample_rate)

    def start(self) -> None:
        self.stream.start()

    def stop(self) -> None:
        self.stream.stop()

    def read_chunk(self) -> str:
        """Read audio chunk from stream or return description."""
        return f"[PCM Audio Stream: {self.sample_rate}Hz active={self.stream._active}]"


class GeminiVoiceOutput(VoiceOutput):
    """Adapter for low-latency PCM speaker stream."""

    def __init__(self, sample_rate: int = 24000):
        self.sample_rate = sample_rate
        self.stream = SpeakerStream(sample_rate=sample_rate)

    def synthesize(self, text: str) -> bytes:
        """Synthesize PCM audio bytes for given text."""
        if not text or not text.strip():
            return b""
        duration_s = max(0.05, min(len(text) * 0.03, 3.0))
        samples = int(self.sample_rate * duration_s)
        # Generate 16-bit mono silence/tone array
        pcm_array = np.zeros(samples, dtype=np.int16)
        return pcm_array.tobytes()

    def play(self, audio: bytes) -> None:
        self.stream.play_chunk(audio)

    def stop(self) -> None:
        self.stream.stop()


class GeminiVoiceProvider(VoiceProvider):
    """Orchestrator for Gemini Live full-duplex voice interaction."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        credential_pool: Optional[GeminiCredentialPool] = None,
    ):
        settings = get_settings()
        self.credential_pool = credential_pool or global_credential_pool
        if api_key:
            self.api_key = api_key
        elif self.credential_pool:
            try:
                self.api_key = self.credential_pool.get_active_key()
            except Exception:
                self.api_key = settings.gemini_api_key or settings.llm_api_key
        else:
            self.api_key = settings.gemini_api_key or settings.llm_api_key

        if not self.api_key:
            raise ValueError("Gemini API key not configured (FRIDAY_GEMINI_API_KEY)")
        self.model = model or getattr(settings, "voice_live_model", "gemini-3.1-flash-live-preview")
        
        input_dev = GeminiVoiceInput(sample_rate=getattr(settings, "voice_input_sample_rate", 16000))
        output_dev = GeminiVoiceOutput(sample_rate=getattr(settings, "voice_live_sample_rate", 24000))
        super().__init__(input_dev, output_dev)
        self._live_session: Optional[GeminiLiveVoiceSession] = None

    async def run_live_async(self, agent: Any, stop_event: Optional[asyncio.Event] = None) -> None:
        """Run the full-duplex Gemini Live session asynchronously."""
        self._live_session = GeminiLiveVoiceSession(
            api_key=self.api_key,
            model=self.model,
            agent=agent,
            credential_pool=self.credential_pool,
        )
        await self._live_session.run_live_loop(
            input_stream=self.input.stream,  # type: ignore[attr-defined]
            output_stream=self.output.stream,  # type: ignore[attr-defined]
            stop_event=stop_event,
        )

    def run_session(self, agent: Any) -> None:
        """Synchronous wrapper to run the live session."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.run_live_async(agent))
            else:
                loop.run_until_complete(self.run_live_async(agent))
        except RuntimeError:
            asyncio.run(self.run_live_async(agent))
