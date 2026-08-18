"""Base Memory interface."""

from abc import ABC, abstractmethod
from typing import List
from friday.core.types import Message


class BaseMemory(ABC):
    """Abstract Base Class for agent memory systems."""

    @abstractmethod
    def add_message(self, message: Message) -> None:
        """Append a single message to memory."""
        pass

    @abstractmethod
    def get_messages(self) -> List[Message]:
        """Retrieve all stored messages in chronological order."""
        pass

    @abstractmethod
    def clear(self) -> None:
        """Clear all messages in memory."""
        pass

    @abstractmethod
    def get_context_window(self, max_messages: int) -> List[Message]:
        """Retrieve the most recent messages constrained by count."""
        pass
