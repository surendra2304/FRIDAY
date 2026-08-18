"""Gemini voice provider implementation (simplified placeholder).

This provider demonstrates the expected structure for a cloud‑first voice
integration using Google Gemini's audio capabilities. The full streaming
implementation is left for future work; for now ``read_chunk`` raises
``NotImplementedError`` so that the module can be imported without side
effects when voice support is disabled.
"""

from typing import Optional

import google.generativeai as genai

from .base import VoiceInput, VoiceOutput, VoiceProvider
from ..core.config import get_settings


class GeminiVoiceInput(VoiceInput):
    def __init__(self, api_key: str, sample_rate: int = 16000):
        self.api_key = api_key
        self.sample_rate = sample_rate
        self.active = False
        # In a full implementation, we would open the microphone here.

    def start(self) -> None:
        self.active = True
        # Placeholder: real microphone capture would be initialized.

    def stop(self) -> None:
        self.active = False
        # Placeholder: close microphone resources.

    def read_chunk(self) -> str:
        if not self.active:
            raise RuntimeError("GeminiVoiceInput not started")
        # Real implementation would stream audio to Gemini Live API and return
        # the transcribed text. For now we raise to indicate unimplemented.
        raise NotImplementedError(
            "GeminiVoiceInput.read_chunk is not implemented. "
            "Use MockVoiceProvider for testing or implement streaming logic."
        )


class GeminiVoiceOutput(VoiceOutput):
    def __init__(self, api_key: str, output_format: str = "mp3"):
        self.api_key = api_key
        self.output_format = output_format

    def synthesize(self, text: str) -> bytes:
        genai.configure(api_key=self.api_key)
        # Use Gemini's text‑to‑speech endpoint. The actual API may differ;
        # this placeholder demonstrates the intent.
        # The "generate_content" call with "audio" mode is not publicly
        # documented at the time of writing, so we return a silent placeholder.
        # In production replace with:
        #   response = genai.generate_audio(text, format=self.output_format)
        #   return response.audio_content
        return b"ID3\x03\x00\x00\x00\x00\x00\x00"  # silent MP3

    def play(self, audio: bytes) -> None:
        # In a full implementation we would send ``audio`` to a playback
        # library such as ``sounddevice.play``. For the placeholder we simply
        # ignore the payload.
        pass


class GeminiVoiceProvider(VoiceProvider):
    def __init__(self):
        settings = get_settings()
        api_key = settings.gemini_api_key
        if not api_key:
            raise ValueError("Gemini API key not configured (FRIDAY_GEMINI_API_KEY)")
        input_dev = GeminiVoiceInput(api_key=api_key, sample_rate=settings.voice_input_sample_rate)
        output_dev = GeminiVoiceOutput(api_key=api_key, output_format=settings.voice_output_format)
        super().__init__(input_dev, output_dev)

    def run_session(self, agent) -> None:
        self.input.start()
        try:
            while True:
                try:
                    user_text = self.input.read_chunk()
                except NotImplementedError:
                    # Streaming not implemented; exit the loop.
                    break
                response = agent.process_message(user_text)
                audio = self.output.synthesize(response.content)
                self.output.play(audio)
        finally:
            self.input.stop()
