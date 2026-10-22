"""Base LLM Provider interface."""

from abc import ABC, abstractmethod
from typing import Any

from friday.core.types import Message


class BaseLLMProvider(ABC):
    """Abstract Base Class for LLM inference providers."""

    def __init__(self, model: str, temperature: float = 0.7, max_tokens: int = 2048):
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abstractmethod
    def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Synchronously send messages and return the assistant response message.

        Args:
            messages: Formatted conversation history.
            tools: Optional list of tool JSON schemas in OpenAI function calling format.

        Returns:
            Assistant Message instance containing content and/or tool_calls.
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the provider (e.g. 'mock', 'openai', 'ollama')."""
