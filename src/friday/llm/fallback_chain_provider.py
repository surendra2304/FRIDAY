"""Cross-provider automatic failover chain.

`FallbackChainLLMProvider` holds an ordered list of LLM providers (e.g.
Groq -> Cerebras -> OpenRouter) and forwards each `generate()` call to the
first provider, automatically advancing to the next one whenever a provider
raises `LLMProviderError`. Only `LLMProviderError` triggers failover — any
other exception is a programming bug and propagates immediately.
"""

from typing import Any, Dict, List, Optional

from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.core.types import Message
from friday.llm.base import BaseLLMProvider

logger = get_logger("llm.chain")


class FallbackChainLLMProvider(BaseLLMProvider):
    """Sequential cross-provider failover wrapper over multiple LLM providers."""

    def __init__(self, providers: List[BaseLLMProvider]):
        if not providers:
            raise LLMProviderError("FallbackChainLLMProvider requires at least one provider")
        first = providers[0]
        super().__init__(
            model=first.model,
            temperature=first.temperature,
            max_tokens=first.max_tokens,
        )
        self.providers: List[BaseLLMProvider] = list(providers)

    @property
    def provider_name(self) -> str:
        return "chain(" + " -> ".join(p.provider_name for p in self.providers) + ")"

    def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Message:
        """Try each provider in order; on LLMProviderError, fail over to the next."""
        failures: List[str] = []

        for provider in self.providers:
            try:
                return provider.generate(messages, tools)
            except LLMProviderError as e:
                failures.append(f"{provider.provider_name}: {e}")
                remaining = len(self.providers) - len(failures)
                if remaining:
                    logger.warning(
                        f"Provider '{provider.provider_name}' failed. "
                        f"Failing over to next provider ({remaining} left): {e}"
                    )

        raise LLMProviderError(
            "All providers in fallback chain failed. " + " | ".join(failures)
        )
