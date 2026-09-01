"""Base interface for embedding providers."""

from abc import ABC, abstractmethod


class BaseEmbeddingProvider(ABC):
    """Abstract Base Class for generating vector embeddings."""

    def __init__(self, model: str, dimension: int):
        self.model = model
        self.dimension = dimension

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Name of the embedding provider."""

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text input."""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for a batch of text inputs."""
