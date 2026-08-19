"""Real Gemini voice provider implementation using official google-genai SDK.

This module provides the voice interface for FRIDAY using the official Google GenAI SDK.
It integrates Gemini Live full-duplex asynchronous WebSocket sessions for real-time
low-latency conversational speech.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from .base import VoiceInput, VoiceOutput, VoiceProvider
from .audio_io import MicrophoneStream, SpeakerStream
from .gemini_live_session import GeminiLiveVoiceSession
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
        # Compatibility stub
        return ""


class GeminiVoiceOutput(VoiceOutput):
    """Adapter for low-latency PCM speaker stream."""

    def __init__(self, sample_rate: int = 24000):
        self.sample_rate = sample_rate
        self.stream = SpeakerStream(sample_rate=sample_rate)

    def synthesize(self, text: str) -> bytes:
        return b""

    def play(self, audio: bytes) -> None:
        self.stream.play_chunk(audio)

    def stop(self) -> None:
        self.stream.stop()


class GeminiVoiceProvider(VoiceProvider):
    """Orchestrator for Gemini Live full-duplex voice interaction."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        settings = get_settings()
        self.api_key = api_key or settings.gemini_api_key or settings.llm_api_key
        if not self.api_key:
            raise ValueError("Gemini API key not configured (FRIDAY_GEMINI_API_KEY)")
        self.model = model or getattr(settings, "voice_live_model", "gemini-2.0-flash")
        
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
