"""Factory for instantiating memory backends based on Settings."""

from typing import Optional
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.memory.base import BaseMemory
from friday.memory.embeddings.factory import create_embedding_provider
from friday.memory.in_memory import InMemoryConversationMemory
from friday.memory.sqlite import SQLiteConversationMemory

logger = get_logger("memory.factory")


def create_memory(
    settings: Settings,
    conversation_id: Optional[str] = None,
) -> BaseMemory:
    """Instantiate and return the configured memory backend with optional embedding provider."""
    embedding_provider = create_embedding_provider(settings)
    backend = settings.memory_backend.lower().strip()
    if backend == "sqlite":
        logger.debug(f"Initializing SQLiteConversationMemory (db: '{settings.memory_db_path}')")
        return SQLiteConversationMemory(
            db_path=settings.memory_db_path,
            conversation_id=conversation_id,
            max_messages=settings.memory_max_messages,
            embedding_provider=embedding_provider,
        )
    elif backend in ("in_memory", "memory", "mock"):
        logger.debug("Initializing InMemoryConversationMemory")
        return InMemoryConversationMemory(
            max_messages=settings.memory_max_messages,
            embedding_provider=embedding_provider,
        )
    else:
        logger.warning(
            f"Unknown memory backend '{backend}'. Falling back to InMemoryConversationMemory."
        )
        return InMemoryConversationMemory(
            max_messages=settings.memory_max_messages,
            embedding_provider=embedding_provider,
        )
