"""Base Memory interface."""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional
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

    def create_conversation(self, title: Optional[str] = None, metadata: Optional[dict] = None) -> str:
        """Create a new conversation session and return its ID."""
        return "default"

    def list_conversations(self, limit: int = 50) -> List[dict]:
        """List available conversation sessions."""
        return []

    def get_conversation(self, conversation_id: str) -> Optional[dict]:
        """Retrieve details of a specific conversation session."""
        return None

    def rename_conversation(self, conversation_id: str, new_title: str) -> bool:
        """Rename a conversation session."""
        return False

    def load_conversation(self, conversation_id: str) -> None:
        """Set the active conversation session."""
        pass

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation session and all its messages."""
        return False
