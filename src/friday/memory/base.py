"""Base Memory interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from friday.core.types import (
    EmbeddingRecord,
    MemorySearchResult,
    Message,
    SemanticSearchResult,
)


class BaseMemory(ABC):
    """Abstract Base Class for agent memory systems."""

    @abstractmethod
    def add_message(self, message: Message) -> None:
        """Append a single message to memory."""

    @abstractmethod
    def get_messages(self) -> list[Message]:
        """Retrieve all stored messages in chronological order."""

    @abstractmethod
    def clear(self) -> None:
        """Clear all messages in memory."""

    @abstractmethod
    def get_context_window(self, max_messages: int) -> list[Message]:
        """Retrieve the most recent messages constrained by count."""

    def create_conversation(self, title: str | None = None, metadata: dict | None = None) -> str:
        """Create a new conversation session and return its ID."""
        return "default"

    def list_conversations(self, limit: int = 50) -> list[dict]:
        """List available conversation sessions."""
        return []

    def get_conversation(self, conversation_id: str) -> dict | None:
        """Retrieve details of a specific conversation session."""
        return None

    def rename_conversation(self, conversation_id: str, new_title: str) -> bool:
        """Rename a conversation session."""
        return False

    def load_conversation(self, conversation_id: str) -> None:
        """Set the active conversation session."""

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation session and all its messages."""
        return False

    def search(
        self,
        query: str,
        conversation_id: str | None = None,
        limit: int = 10,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[MemorySearchResult]:
        """Search stored messages across conversations or within a specific conversation."""
        return []

    def add_embedding(self, record: "EmbeddingRecord") -> None:
        """Store an embedding record."""

    def search_semantic(
        self,
        query: str,
        conversation_id: str | None = None,
        limit: int = 10,
        threshold: float = 0.0,
    ) -> list["SemanticSearchResult"]:
        """Search stored embedding vectors using cosine similarity."""
        return []

    def search_hybrid(
        self,
        query: str,
        conversation_id: str | None = None,
        limit: int = 10,
    ) -> list[MemorySearchResult]:
        """Search memory with semantic similarity if available, degrading gracefully to keyword search."""
        return self.search(query=query, conversation_id=conversation_id, limit=limit)

    def purge_all(self) -> int:
        """Permanently delete all stored conversations and messages. Returns number of purged conversations."""
        return 0

    def prune_expired_messages(self, retention_days: int) -> int:
        """Prune messages older than the specified retention period. Returns number of pruned messages."""
        return 0

    def backup(self, backup_path: str) -> str:
        """Create a local backup of the persistent database. Returns path to backup."""
        return backup_path

    def export_conversation_to_dict(self, conversation_id: str) -> dict[str, Any]:
        """Export a full conversation record including metadata and messages to a dictionary."""
        return {"conversation": {"id": conversation_id}, "messages": []}
