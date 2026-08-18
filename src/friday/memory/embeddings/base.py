"""Base interface for embedding providers."""

from abc import ABC, abstractmethod
from typing import List


class BaseEmbeddingProvider(ABC):
    """Abstract Base Class for generating vector embeddings."""

    def __init__(self, model: str, dimension: int):
        self.model = model
        self.dimension = dimension

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the embedding provider."""
        pass

    @abstractmethod
    def embed_text(self, text: str) -> List[float]:
        """Generate an embedding vector for a single text input."""
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embedding vectors for a batch of text inputs."""
        pass
