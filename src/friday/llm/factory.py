"""LLM Provider Factory."""

from friday.core.config import Settings
from friday.core.exceptions import ConfigError
from friday.core.logging import get_logger
from friday.llm.base import BaseLLMProvider
from friday.llm.mock_provider import MockLLMProvider
from friday.llm.openai_provider import OpenAILLMProvider

logger = get_logger("llm.factory")


def create_llm_provider(settings: Settings) -> BaseLLMProvider:
    """Create and configure the appropriate LLM provider instance from settings."""
    provider_type = settings.llm_provider.lower().strip()

    if provider_type == "mock":
        logger.info(f"Initializing Mock LLM Provider (model: {settings.llm_model})")
        return MockLLMProvider(
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

    if provider_type in ("openai", "groq", "ollama", "openrouter"):
        logger.info(f"Initializing OpenAI-compatible Provider (provider: {provider_type}, model: {settings.llm_model})")
        return OpenAILLMProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

    raise ConfigError(f"Unsupported LLM provider: '{settings.llm_provider}'. Supported: 'mock', 'openai'")
