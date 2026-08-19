"""LLM Provider Factory."""

from friday.core.config import Settings
from friday.core.exceptions import ConfigError
from friday.core.logging import get_logger
from friday.llm.base import BaseLLMProvider
from friday.llm.gemini_provider import GeminiLLMProvider
from friday.auth.credential_pool import credential_pool
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

    if provider_type == "gemini":
        model_name = settings.gemini_model or settings.llm_model
        temperature = settings.gemini_temperature if settings.gemini_temperature is not None else settings.llm_temperature
        max_tokens = settings.gemini_max_tokens if settings.gemini_max_tokens is not None else settings.llm_max_tokens
        logger.info(f"Initializing Google Gemini Provider (model: {model_name}, cost_mode: {settings.cost_mode})")
        return GeminiLLMProvider(
            api_key=None,
            credential_pool=credential_pool,
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=settings.gemini_timeout,
            max_retries=settings.gemini_max_retries,
            backoff_factor=settings.gemini_backoff_factor,
            cost_mode=settings.cost_mode,
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

    raise ConfigError(f"Unsupported LLM provider: '{settings.llm_provider}'. Supported: 'mock', 'openai', 'gemini'")
