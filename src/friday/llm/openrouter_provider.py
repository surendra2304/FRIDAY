"""OpenRouter LLM Provider using the OpenAI-compatible SDK.

Uses the `openai` Python package pointed at OpenRouter's OpenAI-compatible
endpoint. OpenRouter itself provides cross-model routing upstream, so this
provider keeps a single configurable model and standard transient retry logic.
"""

import time
from typing import Any

from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.core.types import Message
from friday.llm.base import BaseLLMProvider
from friday.llm.groq_provider import _is_rate_limit

try:  # Soft dependency: SDK only required for live calls, not for import/tests
    import openai as _openai_sdk
except ImportError:  # pragma: no cover - exercised only when SDK absent
    _openai_sdk = None

logger = get_logger("llm.openrouter")

OPENROUTER_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct"


class OpenRouterLLMProvider(BaseLLMProvider):
    """LLM Provider for OpenRouter via the OpenAI SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = OPENROUTER_DEFAULT_BASE_URL,
        model: str = OPENROUTER_DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        credential_pool: Any | None = None,
        referer: str | None = None,
        app_title: str | None = None,
    ):
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        if not api_key and credential_pool is not None:
            try:
                api_key = credential_pool.get_active_key()
            except Exception:
                api_key = None
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self._client: Any | None = None
        self._default_headers: dict[str, str] = {}
        if referer:
            self._default_headers["HTTP-Referer"] = referer
        if app_title:
            self._default_headers["X-Title"] = app_title

    @property
    def provider_name(self) -> str:
        return "openrouter"

    def _get_client(self) -> Any:
        if self._client is None:
            if _openai_sdk is None:
                raise LLMProviderError(
                    "The 'openai' Python package is required for the OpenRouter provider. "
                    "Install it with: pip install openai"
                )
            if not self.api_key:
                raise LLMProviderError("OpenRouter API key is not configured (FRIDAY_OPENROUTER_API_KEY)")
            self._client = _openai_sdk.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                default_headers=self._default_headers or None,
            )
        return self._client

    def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Call OpenRouter chat completions with retry on transient errors."""
        from friday.llm.groq_provider import GroqLLMProvider, compact_messages_and_tools

        client = self._get_client()

        total_est_chars = sum(len(m.content or "") for m in messages)
        should_compact = total_est_chars > 8000

        msg_dicts, active_tools = compact_messages_and_tools(
            messages,
            tools,
            include_tools=True
        ) if should_compact else ([m.to_provider_dict() for m in messages], tools)

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": msg_dicts,
            "temperature": self.temperature,
            "max_tokens": min(self.max_tokens, 1024),
        }
        if active_tools:
            kwargs["tools"] = active_tools
            kwargs["tool_choice"] = "auto"

        initial_delay = 1.0
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = client.chat.completions.create(**kwargs)
                return GroqLLMProvider._parse_response(response)
            except Exception as e:
                err_text = str(e).lower()
                # If credit or context limit is hit, retry once with plain text without tools
                if ("credit" in err_text or "context" in err_text or "limit" in err_text or "token" in err_text or "402" in err_text) and active_tools:
                    logger.warning("OpenRouter context/credit limit reached with tools. Retrying with compact messages and tools stripped...")
                    compact_msg_dicts, _ = compact_messages_and_tools(messages, None, include_tools=False)
                    kwargs["messages"] = compact_msg_dicts
                    kwargs.pop("tools", None)
                    kwargs.pop("tool_choice", None)
                    kwargs["max_tokens"] = min(self.max_tokens, 768)
                    active_tools = None
                    try:
                        response = client.chat.completions.create(**kwargs)
                        return GroqLLMProvider._parse_response(response)
                    except Exception as inner_e:
                        e = inner_e
                transient = _is_rate_limit(e) or "timeout" in str(e).lower() or "connection" in str(e).lower()
                err_msg = str(e)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "***")
                if transient and attempt < self.max_retries:
                    wait_time = initial_delay * (self.backoff_factor ** attempt)
                    logger.warning(
                        f"OpenRouter transient error: {err_msg}. Retrying in {wait_time:.2f}s "
                        f"(attempt {attempt + 1}/{self.max_retries + 1})..."
                    )
                    time.sleep(wait_time)
                    last_error = e
                    continue
                logger.error(f"OpenRouter API request failed: {err_msg}")
                raise LLMProviderError(f"OpenRouter API request failed: {err_msg}") from e

        raise LLMProviderError(
            f"OpenRouter API request failed after retries: {last_error}"
        )
