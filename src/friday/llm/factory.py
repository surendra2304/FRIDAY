"""LLM Provider Factory."""

import os
from typing import Any, List, Optional

from friday.auth.credential_pool import (
    credential_pool,
    groq_credential_pool,
    mistral_credential_pool,
    openrouter_credential_pool,
)
from friday.core.config import Settings
from friday.core.exceptions import ConfigError
from friday.core.logging import get_logger
from friday.llm.ai_universe_provider import AIUniverseLLMProvider
from friday.llm.base import BaseLLMProvider
from friday.llm.fallback_chain_provider import FallbackChainLLMProvider
from friday.llm.gemini_provider import GeminiLLMProvider
from friday.llm.groq_provider import GROQ_DEFAULT_MODEL, GroqLLMProvider
from friday.llm.mistral_provider import MISTRAL_DEFAULT_MODEL, MistralLLMProvider
from friday.llm.mock_provider import MockLLMProvider
from friday.llm.openai_provider import OpenAILLMProvider
from friday.llm.openrouter_provider import (
    OPENROUTER_DEFAULT_MODEL,
    OpenRouterLLMProvider,
)

logger = get_logger("llm.factory")

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

    if provider_type in ("ai_universe", "inference"):
        url = (
            getattr(settings, "inference_url", None)
            or os.getenv("FRIDAY_INFERENCE_URL")
            or getattr(settings, "universe_api_url", None)
            or "http://localhost:8001"
        )
        key = (
            getattr(settings, "inference_api_key", None)
            or os.getenv("FRIDAY_INFERENCE_API_KEY")
            or ""
        )
        logger.info(f"Initializing Inference Gateway LLM Provider (URL: {url})")
        return AIUniverseLLMProvider(base_url=url, api_key=key)

    if provider_type == "gemini":
        has_explicit = (settings.gemini_api_key is not None) or (settings.llm_api_key is not None)
        has_keys = (
            bool(settings.gemini_api_key)
            or bool(settings.llm_api_key)
            or bool(os.getenv("FRIDAY_GEMINI_API_KEY"))
            or (credential_pool and len(getattr(credential_pool, "credentials", [])) > 0)
        )
        if not has_keys and not has_explicit:
            logger.info("Direct Gemini API key not configured; using live Inference Cloud Gateway (25 Keys).")
            url = getattr(settings, "inference_url", None) or os.getenv("FRIDAY_INFERENCE_URL") or "http://localhost:8001"
            key = getattr(settings, "inference_api_key", None) or os.getenv("FRIDAY_INFERENCE_API_KEY") or ""
            return AIUniverseLLMProvider(base_url=url, api_key=key)

        api_key = settings.gemini_api_key if settings.gemini_api_key is not None else settings.llm_api_key
        if api_key is None:
            api_key = os.getenv("FRIDAY_GEMINI_API_KEY")

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
        logger.info(f"Initializing Groq Provider (model: {model_name})")
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

    if provider_type == "chain":
        groq_model = settings.groq_model or (
            settings.llm_model if settings.llm_model != _DEFAULT_LLM_MODEL else GROQ_DEFAULT_MODEL
        )
        openrouter_model = settings.openrouter_model or (
            settings.llm_model if settings.llm_model != _DEFAULT_LLM_MODEL else OPENROUTER_DEFAULT_MODEL
        )
        mistral_model = settings.mistral_model or (
            settings.llm_model if settings.llm_model != _DEFAULT_LLM_MODEL else MISTRAL_DEFAULT_MODEL
        )
        gemini_model = settings.gemini_model or settings.llm_model
        chain_providers: List[BaseLLMProvider] = [
            GroqLLMProvider(
                api_key=settings.groq_api_key or settings.llm_api_key,
                credential_pool=groq_credential_pool,
                model=groq_model,
                fallback_model=settings.groq_fallback_model,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
            ),
            MistralLLMProvider(
                api_key=settings.mistral_api_key or settings.llm_api_key,
                credential_pool=mistral_credential_pool,
                model=mistral_model,
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
            AIUniverseLLMProvider(
                base_url=getattr(settings, "universe_api_url", None) or getattr(settings, "ai_universe_api_url", None) or getattr(settings, "inference_url", None) or "http://localhost:8001",
                api_key=getattr(settings, "api_key", None) or getattr(settings, "friday_api_key", None) or getattr(settings, "inference_api_key", None) or "",
            ),
        ]
        logger.info(
            "Initializing Fallback Chain Provider: "
            + " -> ".join(p.provider_name for p in chain_providers)
        )
        return FallbackChainLLMProvider(providers=chain_providers)

    if provider_type == "mistral":
        model_name = settings.mistral_model or (
            settings.llm_model if settings.llm_model != _DEFAULT_LLM_MODEL else MISTRAL_DEFAULT_MODEL
        )
        logger.info(f"Initializing Mistral Provider (model: {model_name})")
        return MistralLLMProvider(
            api_key=settings.mistral_api_key or settings.llm_api_key,
            credential_pool=mistral_credential_pool,
            model=model_name,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

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
        "Supported: 'mock', 'openai', 'gemini', 'groq', 'openrouter', 'mistral', 'chain', 'ai_universe', 'inference', 'ollama'"
    )
