"""Real Gemini voice provider using the official google-genai SDK.

Provides full-duplex Gemini Live streaming and separate one-shot speech synthesis.
"""
from __future__ import annotations

import asyncio
import io
import wave
from typing import Any

from google import genai
from google.genai import types as genai_types

from friday.auth.credential_pool import GeminiCredentialPool
from friday.auth.credential_pool import credential_pool as global_credential_pool
from ..core.config import get_settings
from ..core.exceptions import VoiceError
from ..core.logging import get_logger
from .audio_io import MicrophoneStream, SpeakerStream
from .base import VoiceInput, VoiceOutput, VoiceProvider
from .gemini_live_session import GeminiLiveVoiceSession

logger = get_logger("voice.gemini_provider")


class GeminiVoiceInput(VoiceInput):
    """Adapter for microphone input stream."""

    def __init__(self, sample_rate: int = 16000):
        self.sample_rate = sample_rate
        self.stream = MicrophoneStream(sample_rate=sample_rate)

    def start(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        self.stream.start(loop=loop)

    def stop(self) -> None:
        self.stream.stop()

    async def stop_async(self) -> None:
        if hasattr(self.stream, "stop_async"):
            await self.stream.stop_async()
        else:
            self.stream.stop()

    def read_chunk(self) -> str:
        """Read audio chunk from stream or return description."""
        return f"[PCM Audio Stream: {self.sample_rate}Hz active={self.stream._active}]"


class GeminiVoiceOutput(VoiceOutput):
    """One-shot Gemini TTS adapter; no network request occurs until synthesize()."""

    def __init__(
        self,
        sample_rate: int = 24000,
        api_key: str | None = None,
        model: str | None = None,
        voice_name: str | None = None,
        client: Any | None = None,
    ):
        settings = get_settings()
        self.sample_rate = sample_rate
        self.api_key = api_key or settings.gemini_api_key or settings.llm_api_key
        self.model = model or getattr(settings, "voice_tts_model", "gemini-3.8-flash-tts")
        self.voice_name = voice_name or getattr(settings, "voice_name", "Kore")
        self._client = client
        self.stream = SpeakerStream(sample_rate=sample_rate)

    def _get_client(self) -> Any:
        """Create and cache the SDK client lazily."""
        if self._client is None:
            if not self.api_key:
                raise VoiceError("Gemini API key is required for speech synthesis.")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    @staticmethod
    def _extract_audio(response: Any) -> tuple[bytes, str]:
        """Return the first audio inline payload and its MIME type."""
        for candidate in (getattr(response, "candidates", None) or []):
            content = getattr(candidate, "content", None)
            for part in (getattr(content, "parts", None) or []):
                inline_data = getattr(part, "inline_data", None)
                if inline_data is None:
                    continue
                mime_type = getattr(inline_data, "mime_type", "") or ""
                data = getattr(inline_data, "data", None)
                if not data or (mime_type and not mime_type.lower().startswith("audio/")):
                    continue
                if isinstance(data, bytes):
                    return data, mime_type.lower()
                if isinstance(data, bytearray):
                    return bytes(data), mime_type.lower()
        return b"", ""

    def synthesize(self, text: str) -> bytes:
        """Synthesize speech; empty input is a no-op and provider failures are explicit."""
        if not text or not text.strip():
            return b""

        config = genai_types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=genai_types.SpeechConfig(
                voice_config=genai_types.VoiceConfig(
                    prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                        voice_name=self.voice_name,
                    )
                )
            ),
        )
        try:
            response = self._get_client().models.generate_content(
                model=self.model,
                contents=text.strip(),
                config=config,
            )
            audio, mime_type = self._extract_audio(response)
            if not audio:
                raise VoiceError("Gemini returned no audio payload for speech synthesis.")
            # One-shot Generate Content TTS responses default to a WAV container.
            # SpeakerStream consumes headerless PCM, so validate and unwrap WAV data.
            if mime_type in {"audio/wav", "audio/x-wav"} or audio.startswith(b"RIFF"):
                try:
                    with wave.open(io.BytesIO(audio), "rb") as wav_file:
                        if wav_file.getnchannels() != 1 or wav_file.getsampwidth() != 2:
                            raise VoiceError("Gemini TTS audio must be mono 16-bit PCM.")
                        if wav_file.getframerate() != self.sample_rate:
                            raise VoiceError(
                                f"Gemini TTS sample rate {wav_file.getframerate()}Hz does not match "
                                f"speaker rate {self.sample_rate}Hz."
                            )
                        audio = wav_file.readframes(wav_file.getnframes())
                except (wave.Error, EOFError) as exc:
                    raise VoiceError("Gemini returned an invalid WAV audio payload.") from exc
            return audio
        except VoiceError:
            raise
        except Exception as exc:
            logger.warning("Gemini speech synthesis failed; provider details omitted.")
            raise VoiceError("Gemini speech synthesis failed. Check provider configuration and retry.") from exc

    def play(self, audio: bytes) -> None:
        """Queue non-empty audio for playback."""
        if audio:
            self.stream.play_chunk(audio)

    def stop(self) -> None:
        self.stream.stop()

    async def stop_async(self) -> None:
        if hasattr(self.stream, "close_async"):
            await self.stream.close_async()
        elif hasattr(self.stream, "close"):
            self.stream.close()
        else:
            self.stream.stop()

    def drain(self, timeout_seconds: float = 0.5) -> None:
        self.stream.drain(timeout_seconds=timeout_seconds)

    async def drain_async(self, timeout_seconds: float = 0.5) -> None:
        if hasattr(self.stream, "drain_async"):
            await self.stream.drain_async(timeout_seconds=timeout_seconds)
        else:
            self.stream.drain(timeout_seconds=timeout_seconds)


class GeminiVoiceProvider(VoiceProvider):
    """Orchestrator for Gemini Live full-duplex voice interaction."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        credential_pool: GeminiCredentialPool | None = None,
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
        output_dev = GeminiVoiceOutput(
            sample_rate=getattr(settings, "voice_live_sample_rate", 24000),
            api_key=self.api_key,
            model=getattr(settings, "voice_tts_model", "gemini-2.5-flash-preview-tts"),
            voice_name=getattr(settings, "voice_name", "Kore"),
        )
        super().__init__(input_dev, output_dev)
        self._live_session: GeminiLiveVoiceSession | None = None

    async def run_live_async(self, agent: Any, stop_event: asyncio.Event | None = None) -> None:
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
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None and loop.is_running():
            raise RuntimeError("Use run_live_async() inside an active event loop")
        asyncio.run(self.run_live_async(agent))
