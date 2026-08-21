"""Cerebras LLM Provider using the OpenAI-compatible SDK.

Uses the `openai` Python package pointed at Cerebras' OpenAI-compatible
endpoint. Cerebras offers extremely low-latency inference; transient errors
are retried with exponential backoff.
"""

import time
from typing import Any, Dict, List, Optional

from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.core.types import Message
from friday.llm.base import BaseLLMProvider
from friday.llm.groq_provider import GroqLLMProvider, _is_rate_limit

try:  # Soft dependency: SDK only required for live calls, not for import/tests
    import openai as _openai_sdk
except ImportError:  # pragma: no cover - exercised only when SDK absent
    _openai_sdk = None

logger = get_logger("llm.cerebras")

CEREBRAS_DEFAULT_BASE_URL = "https://api.cerebras.ai/v1"
CEREBRAS_DEFAULT_MODEL = "llama3.1-70b-4096"


class CerebrasLLMProvider(BaseLLMProvider):
    """LLM Provider for Cerebras via the OpenAI SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = CEREBRAS_DEFAULT_BASE_URL,
        model: str = CEREBRAS_DEFAULT_MODEL,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        credential_pool: Optional[Any] = None,
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
        self._client: Optional[Any] = None

    @property
    def provider_name(self) -> str:
        return "cerebras"

    def _get_client(self) -> Any:
        if self._client is None:
            if _openai_sdk is None:
                raise LLMProviderError(
                    "The 'openai' Python package is required for the Cerebras provider. "
                    "Install it with: pip install openai"
                )
            if not self.api_key:
                raise LLMProviderError("Cerebras API key is not configured (FRIDAY_CEREBRAS_API_KEY)")
            self._client = _openai_sdk.OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Message:
        """Call Cerebras chat completions with retry on transient errors."""
        client = self._get_client()
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_provider_dict() for m in messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        initial_delay = 1.0
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = client.chat.completions.create(**kwargs)
                return GroqLLMProvider._parse_response(response)
            except Exception as e:
                transient = _is_rate_limit(e) or "timeout" in str(e).lower() or "connection" in str(e).lower()
                err_msg = str(e)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "***")
                if transient and attempt < self.max_retries:
                    wait_time = initial_delay * (self.backoff_factor ** attempt)
                    logger.warning(
                        f"Cerebras transient error: {err_msg}. Retrying in {wait_time:.2f}s "
                        f"(attempt {attempt + 1}/{self.max_retries + 1})..."
                    )
                    time.sleep(wait_time)
                    last_error = e
                    continue
                logger.error(f"Cerebras API request failed: {err_msg}")
                raise LLMProviderError(f"Cerebras API request failed: {err_msg}") from e

        raise LLMProviderError(
            f"Cerebras API request failed after retries: {last_error}"
        )
