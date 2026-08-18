"""Memory module for FRIDAY."""

from friday.memory.base import BaseMemory
from friday.memory.in_memory import InMemoryConversationMemory

__all__ = [
    "BaseMemory",
    "InMemoryConversationMemory",
]
