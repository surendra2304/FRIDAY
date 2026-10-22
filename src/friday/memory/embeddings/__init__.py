"""Semantic embeddings module."""

from friday.memory.embeddings.base import BaseEmbeddingProvider
from friday.memory.embeddings.factory import create_embedding_provider
from friday.memory.embeddings.gemini import GeminiEmbeddingProvider
from friday.memory.embeddings.mock import MockEmbeddingProvider

__all__ = [
    "BaseEmbeddingProvider",
    "GeminiEmbeddingProvider",
    "MockEmbeddingProvider",
    "create_embedding_provider",
]
