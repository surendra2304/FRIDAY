"""Mock implementations of voice input and output for testing.

The ``MockVoiceProvider`` allows the test suite to simulate a full voice
conversation without requiring any audio hardware or external API calls.
It returns a predefined list of transcript strings and produces a silent
MP3 placeholder for synthesized speech.
"""

from collections.abc import Iterator

from .base import VoiceInput, VoiceOutput, VoiceProvider


class MockVoiceInput(VoiceInput):
    def __init__(self, transcripts: list[str]):
        self._iter: Iterator[str] = iter(transcripts)
        self.active = False

    def start(self) -> None:
        self.active = True

    def stop(self) -> None:
        self.active = False

    def read_chunk(self) -> str:
        if not self.active:
            raise RuntimeError("MockVoiceInput not started")
        try:
            return next(self._iter)
        except StopIteration:
            raise StopIteration("No more mock transcripts")


class MockVoiceOutput(VoiceOutput):
    def synthesize(self, text: str) -> bytes:
        # Return a silent MP3 payload (minimal valid MP3 header)
        return b"ID3\x03\x00\x00\x00\x00\x00\x00"

    def play(self, audio: bytes) -> None:
        # No‑op for mock; in real implementation a sound library would be used
        pass


class MockVoiceProvider(VoiceProvider):
    def __init__(self, transcripts: list[str]):
        super().__init__(MockVoiceInput(transcripts), MockVoiceOutput())

    def run_session(self, agent) -> None:
        self.input.start()
        try:
            while True:
                try:
                    user_text = self.input.read_chunk()
                except StopIteration:
                    break
                response = agent.process_message(user_text)
                audio = self.output.synthesize(response.content)
                self.output.play(audio)
        finally:
            self.input.stop()
