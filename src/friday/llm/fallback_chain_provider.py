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
from friday.core.types import Message, Role
from friday.llm.base import BaseLLMProvider

logger = get_logger("llm.chain")

# Neutral placeholder substituted for tool output blocked by the injection guard
_BLOCKED_TOOL_OUTPUT = "[TOOL OUTPUT REMOVED BY PROMPT-INJECTION GUARD]"


def sanitize_messages_for_providers(messages: List[Message]) -> List[Message]:
    """Defense-in-depth: sanitize untrusted TOOL-role content before any LLM call.

    Tool outputs (screen OCR, web fetches, external commands) are the primary
    prompt-injection vector. Blocked content is replaced with a neutral
    placeholder; risky-but-not-blocked content is stripped of instruction
    markers. Trusted roles (SYSTEM/USER/ASSISTANT) pass through untouched, and
    guard failures never break the request path.
    """
    sanitized: List[Message] = []
    for m in messages:
        if m.role != Role.TOOL or not m.content:
            sanitized.append(m)
            continue
        try:
            from friday.security.prompt_injection import InjectionRisk, SourceType, guard_content

            result = guard_content(SourceType.TOOL_OUTPUT, m.content)
            if result.risk == InjectionRisk.BLOCKED:
                logger.warning(
                    f"Prompt-injection guard BLOCKED tool output (hash={result.content_hash}); "
                    "replacing with neutral placeholder before LLM dispatch."
                )
                sanitized.append(m.model_copy(update={"content": _BLOCKED_TOOL_OUTPUT}))
            elif result.sanitized != m.content:
                sanitized.append(m.model_copy(update={"content": result.sanitized}))
            else:
                sanitized.append(m)
        except Exception as e:  # guard must never crash the cognitive loop
            logger.warning(f"Prompt-injection guard unavailable for tool message: {e}")
            sanitized.append(m)
    return sanitized


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
        messages = sanitize_messages_for_providers(messages)
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
