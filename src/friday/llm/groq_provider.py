"""Groq LLM Provider using the OpenAI-compatible SDK.

Uses the `openai` Python package pointed at Groq's OpenAI-compatible endpoint.
Implements an internal model fallback: on a 429 rate limit with the default
model (`llama-3.3-70b-versatile`), the exact same prompt is retried once with
`llama-3.1-8b-instant`.
"""

import json
from typing import Any

from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.core.types import Message, Role, ToolCall
from friday.llm.base import BaseLLMProvider

try:  # Soft dependency: SDK only required for live calls, not for import/tests
    import openai as _openai_sdk
except ImportError:  # pragma: no cover - exercised only when SDK absent
    _openai_sdk = None

logger = get_logger("llm.groq")

GROQ_DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
GROQ_FALLBACK_MODEL = "openai/gpt-oss-20b"
GROQ_UNIVERSAL_FALLBACK_MODEL = "openai/gpt-oss-120b"


class _RateLimitedError(Exception):
    """Internal signal that the current model hit a 429 and a fallback may help."""


class _ModelNotFoundError(Exception):
    """Internal signal that the current model returned 404 model_not_found."""


def _is_rate_limit(error: Exception) -> bool:
    """Detect a 429 across native SDK exceptions and SDK-less environments."""
    if _openai_sdk is not None and isinstance(error, _openai_sdk.RateLimitError):
        return True
    if getattr(error, "status_code", None) == 429:
        return True
    return "429" in str(error) or "rate limit" in str(error).lower()


def _is_model_not_found(error: Exception) -> bool:
    """Detect a 404 model_not_found (including decommissioned models)."""
    if _openai_sdk is not None and isinstance(error, _openai_sdk.NotFoundError):
        return True
    if getattr(error, "status_code", None) == 404:
        return True
    err = str(error).lower()
    return "404" in err or "model_not_found" in err or "model not found" in err or "decommissioned" in err


class GroqLLMProvider(BaseLLMProvider):
    """LLM Provider for Groq via the OpenAI SDK with automatic model fallback on 429."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = GROQ_DEFAULT_BASE_URL,
        model: str = GROQ_DEFAULT_MODEL,
        fallback_model: str = GROQ_FALLBACK_MODEL,
        universal_fallback_model: str = GROQ_UNIVERSAL_FALLBACK_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float = 60.0,
        credential_pool: Any | None = None,
    ):
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        if not api_key and credential_pool is not None:
            try:
                api_key = credential_pool.get_active_key()
            except Exception:
                api_key = None
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self.fallback_model = fallback_model
        self.universal_fallback_model = universal_fallback_model
        self.timeout = timeout
        self._client: Any | None = None

    @property
    def provider_name(self) -> str:
        return "groq"

    def _get_client(self) -> Any:
        if self._client is None:
            if _openai_sdk is None:
                raise LLMProviderError(
                    "The 'openai' Python package is required for the Groq provider. "
                    "Install it with: pip install openai"
                )
            if not self.api_key:
                raise LLMProviderError("Groq API key is not configured (FRIDAY_GROQ_API_KEY)")
            self._client = _openai_sdk.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Call Groq chat completions with automatic in-provider model fallbacks.

        - 429 rate limit on the primary model -> retry once with `fallback_model`
          (fast fallback), then with `universal_fallback_model` if that model
          is not found.
        - 404 model_not_found on the primary model -> retry directly with the
          universally available `universal_fallback_model` (llama-3.1-8b-instant).
        - A second 429 fails fast (Groq rate limits are organization-wide, so
          further same-org retries waste quota): raise LLMProviderError so the
          fallback chain advances to Mistral/OpenRouter.
        """
        try:
            return self._generate_with_model(self.model, messages, tools)
        except _RateLimitedError as primary_error:
            if self.fallback_model and self.fallback_model != self.model:
                logger.warning(
                    f"Groq rate limit (429) on model '{self.model}'. "
                    f"Retrying same prompt with fallback model '{self.fallback_model}'..."
                )
                try:
                    return self._generate_with_model(self.fallback_model, messages, tools)
                except _ModelNotFoundError:
                    logger.warning(
                        f"Groq fallback model '{self.fallback_model}' not found (404). "
                        f"Retrying with universally available model '{self.universal_fallback_model}'..."
                    )
                    return self._generate_with_model(self.universal_fallback_model, messages, tools)
                except _RateLimitedError as fallback_error:
                    raise LLMProviderError(
                        f"Groq rate limited on both '{self.model}' and '{self.fallback_model}': {fallback_error}"
                    ) from fallback_error
            raise LLMProviderError(f"Groq rate limited on '{self.model}': {primary_error}") from primary_error
        except _ModelNotFoundError:
            logger.warning(
                f"Groq model '{self.model}' not found (404). Retrying same prompt with "
                f"universally available model '{self.universal_fallback_model}'..."
            )
            try:
                return self._generate_with_model(self.universal_fallback_model, messages, tools)
            except (_RateLimitedError, _ModelNotFoundError) as universal_error:
                raise LLMProviderError(
                    f"Groq failed on '{self.model}' (model_not_found) and on "
                    f"'{self.universal_fallback_model}': {universal_error}"
                ) from universal_error

    def _generate_with_model(
        self,
        model: str,
        messages: list[Message],
        tools: list[dict[str, Any]] | None,
    ) -> Message:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": [m.to_provider_dict() for m in messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            response = client.chat.completions.create(**kwargs)
        except Exception as e:
            if _is_rate_limit(e):
                raise _RateLimitedError(str(e)) from e
            if _is_model_not_found(e):
                raise _ModelNotFoundError(str(e)) from e
            err_msg = str(e)
            if self.api_key and self.api_key in err_msg:
                err_msg = err_msg.replace(self.api_key, "***")
            logger.error(f"Groq API request failed: {err_msg}")
            raise LLMProviderError(f"Groq API request failed: {err_msg}") from e

        return self._parse_response(response)

    @staticmethod
    def _parse_response(response: Any) -> Message:
        """Convert an OpenAI-SDK ChatCompletion into a FRIDAY Message."""
        try:
            choice = response.choices[0]
            choice_msg = choice.message
        except (AttributeError, IndexError) as e:
            raise LLMProviderError("Malformed response from Groq API: no choices") from e

        content = getattr(choice_msg, "content", None) or ""
        tool_calls_raw = getattr(choice_msg, "tool_calls", None)
        tool_calls: list[ToolCall] | None = None

        if tool_calls_raw:
            tool_calls = []
            for tc in tool_calls_raw:
                func = getattr(tc, "function", None)
                args_raw = getattr(func, "arguments", "{}") if func else "{}"
                if isinstance(args_raw, str):
                    try:
                        args_dict = json.loads(args_raw)
                    except json.JSONDecodeError:
                        args_dict = {"raw_arguments": args_raw}
                else:
                    args_dict = args_raw or {}
                tool_calls.append(
                    ToolCall(
                        id=getattr(tc, "id", "") or "",
                        name=getattr(func, "name", "") if func else "",
                        arguments=args_dict,
                    )
                )

        return Message(role=Role.ASSISTANT, content=content, tool_calls=tool_calls)
