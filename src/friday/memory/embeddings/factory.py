"""Factory for instantiating embedding providers based on application configuration."""

from typing import Optional
from friday.core.config import Settings
from friday.core.logging import get_logger
from friday.memory.embeddings.base import BaseEmbeddingProvider
from friday.memory.embeddings.gemini import GeminiEmbeddingProvider
from friday.memory.embeddings.mock import MockEmbeddingProvider

logger = get_logger("memory.embeddings.factory")


def create_embedding_provider(settings: Settings) -> Optional[BaseEmbeddingProvider]:
    """Create configured embedding provider instance or None if disabled."""
    provider_type = (settings.embedding_provider or "none").lower().strip()

    if provider_type in ("none", "disabled", "false", ""):
        logger.info("Semantic embeddings are disabled.")
        return None

    if provider_type == "mock":
        logger.info(f"Initializing Mock Embedding Provider (dimension: {settings.embedding_dimension})")
        return MockEmbeddingProvider(
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
        )

    if provider_type == "gemini":
        api_key = settings.gemini_api_key or settings.llm_api_key
        logger.info(
            f"Initializing Google Gemini Cloud Embedding Provider (model: {settings.embedding_model}, "
            f"dimension: {settings.embedding_dimension})"
        )
        return GeminiEmbeddingProvider(
            api_key=api_key,
            model=settings.embedding_model,
            dimension=settings.embedding_dimension,
            timeout=settings.gemini_timeout,
            max_retries=settings.gemini_max_retries,
            backoff_factor=settings.gemini_backoff_factor,
        )

    logger.warning(f"Unsupported embedding provider: '{settings.embedding_provider}'. Semantic search disabled.")
    return None
