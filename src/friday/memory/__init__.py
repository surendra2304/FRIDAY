"""Memory module for FRIDAY.

The public surface exposes Oracle-backed conversation memory. The SQLite backend
lives in :mod:`friday.memory.sqlite` for the test suite only and is deliberately
not re-exported here.
"""

from friday.memory.base import BaseMemory
from friday.memory.compactor import MemoryCompactor
from friday.memory.embeddings.base import BaseEmbeddingProvider
from friday.memory.embeddings.factory import create_embedding_provider
from friday.memory.embeddings.gemini import GeminiEmbeddingProvider
from friday.memory.embeddings.mock import MockEmbeddingProvider
from friday.memory.factory import create_memory
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.oracle import OracleConversationMemory
from friday.memory.task_context import ActiveTaskContext, TaskObservation

__all__ = [
    "ActiveTaskContext",
    "BaseEmbeddingProvider",
    "BaseMemory",
    "GeminiEmbeddingProvider",
    "InMemoryConversationMemory",
    "MemoryCompactor",
    "MockEmbeddingProvider",
    "OracleConversationMemory",
    "TaskObservation",
    "create_embedding_provider",
    "create_memory",
]
