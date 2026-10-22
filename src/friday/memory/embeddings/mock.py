"""Deterministic Mock Embedding Provider for fast testing and offline verification."""

import hashlib
import math

from friday.memory.embeddings.base import BaseEmbeddingProvider


class MockEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic Mock Embedding Provider producing normalized vectors from hashes."""

    def __init__(self, model: str = "mock-embedding-v1", dimension: int = 768):
        super().__init__(model=model, dimension=dimension)

    @property
    def provider_name(self) -> str:
        return "mock"

    def _compute_vector(self, text: str) -> list[float]:
        """Generate a deterministic normalized unit vector for the given string."""
        if not text:
            return [0.0] * self.dimension

        # Generate a seed from MD5 hash of the text
        seed_bytes = hashlib.md5(text.encode("utf-8")).digest()
        seed_int = int.from_bytes(seed_bytes, "big")

        raw_vec = []
        for i in range(self.dimension):
            # Deterministic pseudo-random generation per dimension
            val = math.sin((seed_int % 100000) + (i + 1) * 0.73)
            raw_vec.append(val)

        # Normalize to unit length (L2 norm)
        norm = math.sqrt(sum(v * v for v in raw_vec)) or 1.0
        return [v / norm for v in raw_vec]

    def embed_text(self, text: str) -> list[float]:
        return self._compute_vector(text)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self._compute_vector(t) for t in texts]
