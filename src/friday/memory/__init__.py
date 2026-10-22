"""Memory module for FRIDAY."""

from friday.memory.base import BaseMemory
from friday.memory.compactor import MemoryCompactor
from friday.memory.embeddings.base import BaseEmbeddingProvider
from friday.memory.embeddings.factory import create_embedding_provider
from friday.memory.embeddings.gemini import GeminiEmbeddingProvider
from friday.memory.embeddings.mock import MockEmbeddingProvider
from friday.memory.factory import create_memory
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.sqlite import SQLiteConversationMemory
from friday.memory.task_context import ActiveTaskContext, TaskObservation

__all__ = [
    "ActiveTaskContext",
    "BaseEmbeddingProvider",
    "BaseMemory",
    "GeminiEmbeddingProvider",
    "InMemoryConversationMemory",
    "MemoryCompactor",
    "MockEmbeddingProvider",
    "SQLiteConversationMemory",
    "TaskObservation",
    "create_embedding_provider",
    "create_memory",
]
