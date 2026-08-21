"""LLM Provider Factory."""

from friday.core.config import Settings
from friday.core.exceptions import ConfigError
from friday.core.logging import get_logger
from friday.auth.credential_pool import (
    cerebras_credential_pool,
    credential_pool,
    groq_credential_pool,
    openrouter_credential_pool,
)
from friday.llm.base import BaseLLMProvider
from friday.llm.cerebras_provider import CEREBRAS_DEFAULT_MODEL, CerebrasLLMProvider
from friday.llm.fallback_chain_provider import FallbackChainLLMProvider
from friday.llm.gemini_provider import GeminiLLMProvider
from friday.llm.groq_provider import GROQ_DEFAULT_MODEL, GroqLLMProvider
from friday.llm.mock_provider import MockLLMProvider
from friday.llm.openai_provider import OpenAILLMProvider
from friday.llm.openrouter_provider import OPENROUTER_DEFAULT_MODEL, OpenRouterLLMProvider

logger = get_logger("llm.factory")

# Sentinel: the configured default llm_model means "not user-overridden" — chain
# providers then use their own per-provider default models.
_DEFAULT_LLM_MODEL = Settings.model_fields["llm_model"].default


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
        api_key = settings.gemini_api_key or settings.llm_api_key
        model_name = settings.gemini_model or settings.llm_model
        temperature = settings.gemini_temperature if settings.gemini_temperature is not None else settings.llm_temperature
        max_tokens = settings.gemini_max_tokens if settings.gemini_max_tokens is not None else settings.llm_max_tokens
        logger.info(f"Initializing Google Gemini Provider (model: {model_name}, cost_mode: {settings.cost_mode})")
        return GeminiLLMProvider(
            api_key=api_key,
            credential_pool=credential_pool,
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=settings.gemini_timeout,
            max_retries=settings.gemini_max_retries,
            backoff_factor=settings.gemini_backoff_factor,
            cost_mode=settings.cost_mode,
            thinking_level=getattr(settings, "llm_thinking_level", "medium"),
        )

    if provider_type == "groq":
        model_name = settings.groq_model or (
            settings.llm_model if settings.llm_model != _DEFAULT_LLM_MODEL else GROQ_DEFAULT_MODEL
        )
        logger.info(f"Initializing Groq Provider (model: {model_name}, fallback: {settings.groq_fallback_model})")
        return GroqLLMProvider(
            api_key=settings.groq_api_key or settings.llm_api_key,
            credential_pool=groq_credential_pool,
            model=model_name,
            fallback_model=settings.groq_fallback_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

    if provider_type == "openrouter":
        model_name = settings.openrouter_model or (
            settings.llm_model if settings.llm_model != _DEFAULT_LLM_MODEL else OPENROUTER_DEFAULT_MODEL
        )
        logger.info(f"Initializing OpenRouter Provider (model: {model_name})")
        return OpenRouterLLMProvider(
            api_key=settings.openrouter_api_key or settings.llm_api_key,
            credential_pool=openrouter_credential_pool,
            model=model_name,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

    if provider_type == "cerebras":
        model_name = settings.cerebras_model or (
            settings.llm_model if settings.llm_model != _DEFAULT_LLM_MODEL else CEREBRAS_DEFAULT_MODEL
        )
        logger.info(f"Initializing Cerebras Provider (model: {model_name})")
        return CerebrasLLMProvider(
            api_key=settings.cerebras_api_key or settings.llm_api_key,
            credential_pool=cerebras_credential_pool,
            model=model_name,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

    if provider_type == "chain":
        # Cross-provider automatic failover: Groq -> Cerebras -> OpenRouter.
        groq_model = settings.groq_model or (
            settings.llm_model if settings.llm_model != _DEFAULT_LLM_MODEL else GROQ_DEFAULT_MODEL
        )
        cerebras_model = settings.cerebras_model or (
            settings.llm_model if settings.llm_model != _DEFAULT_LLM_MODEL else CEREBRAS_DEFAULT_MODEL
        )
        openrouter_model = settings.openrouter_model or (
            settings.llm_model if settings.llm_model != _DEFAULT_LLM_MODEL else OPENROUTER_DEFAULT_MODEL
        )
        chain_providers = [
            GroqLLMProvider(
                api_key=settings.groq_api_key or settings.llm_api_key,
                credential_pool=groq_credential_pool,
                model=groq_model,
                fallback_model=settings.groq_fallback_model,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
            ),
            CerebrasLLMProvider(
                api_key=settings.cerebras_api_key or settings.llm_api_key,
                credential_pool=cerebras_credential_pool,
                model=cerebras_model,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
            ),
            OpenRouterLLMProvider(
                api_key=settings.openrouter_api_key or settings.llm_api_key,
                credential_pool=openrouter_credential_pool,
                model=openrouter_model,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
            ),
        ]
        logger.info(
            "Initializing Fallback Chain Provider: "
            + " -> ".join(p.provider_name for p in chain_providers)
        )
        return FallbackChainLLMProvider(providers=chain_providers)

    if provider_type in ("openai", "ollama"):
        logger.info(f"Initializing OpenAI-compatible Provider (provider: {provider_type}, model: {settings.llm_model})")
        return OpenAILLMProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

    raise ConfigError(
        f"Unsupported LLM provider: '{settings.llm_provider}'. "
        "Supported: 'mock', 'openai', 'gemini', 'groq', 'openrouter', 'cerebras', 'chain', 'ollama'"
    )
