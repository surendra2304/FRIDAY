"""Voice abstraction base classes for FRIDAY.

These classes define the contract for voice input, output, and provider
implementations. They are deliberately lightweight and synchronous to keep
the implementation simple for the initial cloud‑first approach.
"""

from abc import ABC, abstractmethod
from typing import List


class VoiceInput(ABC):
    """Interface for capturing audio / transcribed text.

    The concrete implementation may stream raw audio bytes to a remote
    service or, for testing, return pre‑defined transcript strings.
    """

    @abstractmethod
    def start(self) -> None:
        """Prepare the input source (e.g., open microphone)."""

    @abstractmethod
    def stop(self) -> None:
        """Terminate the input source and release resources."""

    @abstractmethod
    def read_chunk(self) -> str:
        """Return the next chunk of transcribed text.

        For a streaming implementation this would block until a phrase is
        recognized. For the mock provider it returns the next predefined
        transcript or raises ``StopIteration`` when exhausted.
        """


class VoiceOutput(ABC):
    """Interface for converting text to audio and playing it back."""

    @abstractmethod
    def synthesize(self, text: str) -> bytes:
        """Return audio bytes for the given text.

        The concrete implementation should call the Gemini TTS endpoint or
        return a silent placeholder for mocks.
        """

    @abstractmethod
    def play(self, audio: bytes) -> None:
        """Play the supplied audio bytes on the local speaker.

        Implementations may use a library like ``sounddevice`` or ``pyaudio``.
        In the mock version this is a no‑op.
        """


class VoiceProvider(ABC):
    """High‑level orchestrator that ties ``VoiceInput`` and ``VoiceOutput``.

    ``run_session`` should block until the session ends (e.g., user issues a
    stop command or the input source is exhausted). It receives a ``FridayAgent``
    instance to delegate all reasoning, tool calls and memory handling.
    """

    def __init__(self, input_device: VoiceInput, output_device: VoiceOutput):
        self.input = input_device
        self.output = output_device

    @abstractmethod
    def run_session(self, agent) -> None:
        """Start the voice interaction loop.

        Steps performed for each user utterance:
        1. ``self.input.read_chunk`` → transcribed string.
        2. ``agent.process_message`` with that string.
        3. ``self.output.synthesize`` the response text.
        4. ``self.output.play`` the resulting audio.
        """
