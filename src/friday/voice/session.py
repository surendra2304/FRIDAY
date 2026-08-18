"""Voice session manager that ties a VoiceProvider to the FridayAgent.

The session is responsible for the high‑level start/stop lifecycle and
for handling user‑initiated interruptions. It simply forwards the agent
instance to the provider's ``run_session`` method.
"""

from typing import Optional

from .base import VoiceProvider
from ..agent.agent import FridayAgent


class VoiceSession:
    def __init__(self, provider: VoiceProvider, agent: FridayAgent):
        self.provider = provider
        self.agent = agent
        self._running = False

    def start(self) -> None:
        """Begin the voice interaction loop.

        This call blocks until the provider signals the end of the session
        (e.g., user says "stop" or the mock input is exhausted).
        """
        self._running = True
        self.provider.run_session(self.agent)
        self._running = False

    def stop(self) -> None:
        """Request termination of the current session.

        The concrete provider should respect this call; for the mock provider
        it simply stops the input stream.
        """
        # Providers are expected to expose a ``stop`` method on the input
        # device. We delegate if available.
        try:
            self.provider.input.stop()
        except Exception:
            pass
        self._running = False

    @property
    def running(self) -> bool:
        return self._running
