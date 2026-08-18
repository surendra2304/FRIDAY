"""In-memory sliding window conversation buffer memory."""

from typing import List
from friday.core.logging import get_logger
from friday.core.types import Message
from friday.memory.base import BaseMemory

logger = get_logger("memory.in_memory")


class InMemoryConversationMemory(BaseMemory):
    """Simple, fast in-memory conversation memory with sliding window eviction."""

    def __init__(self, max_messages: int = 50) -> None:
        self.max_messages = max(2, max_messages)
        self._messages: List[Message] = []

    def add_message(self, message: Message) -> None:
        """Store a message and apply sliding window trimming if capacity is exceeded."""
        self._messages.append(message)
        if len(self._messages) > self.max_messages:
            excess = len(self._messages) - self.max_messages
            self._messages = self._messages[excess:]
            logger.debug(f"Trimmed {excess} oldest message(s) from memory buffer.")

    def get_messages(self) -> List[Message]:
        """Return a copy of all current messages in buffer."""
        return list(self._messages)

    def clear(self) -> None:
        """Clear all messages from buffer."""
        self._messages.clear()
        logger.debug("Cleared memory buffer.")

    def get_context_window(self, max_messages: int) -> List[Message]:
        """Retrieve recent slice of messages up to max_messages."""
        if max_messages <= 0:
            return []
        return list(self._messages[-max_messages:])

    def __len__(self) -> int:
        return len(self._messages)
