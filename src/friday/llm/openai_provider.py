"""OpenAI-compatible LLM Provider using HTTPX."""

import json
import time
from typing import Any

import httpx

from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.core.types import Message, Role, ToolCall
from friday.llm.base import BaseLLMProvider

logger = get_logger("llm.openai")


class OpenAILLMProvider(BaseLLMProvider):
    """LLM Provider for OpenAI and any OpenAI-compatible endpoint (Groq, Ollama, OpenRouter)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float = 60.0,
    ):
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    @property
    def provider_name(self) -> str:
        return "openai"

    def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
    ) -> Message:
        """Call the chat completions endpoint."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_provider_dict() for m in messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        max_retries = 3
        backoff_factor = 2.0
        initial_delay = 1.0
        data = None

        for attempt in range(max_retries + 1):
            try:
                logger.debug(
                    f"Calling OpenAI provider endpoint {url} with model {self.model} "
                    f"(Attempt {attempt + 1}/{max_retries + 1})"
                )
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(url, headers=headers, json=payload)

                if response.status_code == 200:
                    data = response.json()
                    break

                try:
                    err_json = response.json()
                    error_detail = err_json.get("error", {}).get("message") or response.text
                except Exception:
                    error_detail = response.text

                # Truncate long error output
                if isinstance(error_detail, str) and len(error_detail) > 300:
                    error_detail = error_detail[:300] + "... [TRUNCATED]"

                # Proactively mask API key
                if self.api_key and isinstance(error_detail, str) and self.api_key in error_detail:
                    error_detail = error_detail.replace(self.api_key, "***")

                # Candidate status codes for retry: 429 (Rate Limit) and 5xx (Server Errors)
                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < max_retries:
                        wait_time = initial_delay * (backoff_factor ** attempt)
                        retry_after = response.headers.get("Retry-After")
                        if retry_after and isinstance(retry_after, (str, int, float)):
                            try:
                                wait_time = float(retry_after)
                            except (ValueError, TypeError):
                                pass
                        logger.warning(
                            f"LLM API request failed with status {response.status_code}. "
                            f"Retrying in {wait_time:.2f} seconds..."
                        )
                        time.sleep(wait_time)
                        continue

                logger.error(f"LLM API request failed [{response.status_code}]: {error_detail}")
                raise LLMProviderError(f"LLM Provider API returned status {response.status_code}: {error_detail}")

            except httpx.RequestError as e:
                err_msg = str(e)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "***")

                # RequestError is transient (timeout, connect error) -> retry
                if attempt < max_retries:
                    wait_time = initial_delay * (backoff_factor ** attempt)
                    logger.warning(
                        f"Network error communicating with LLM Provider: {err_msg}. "
                        f"Retrying in {wait_time:.2f} seconds..."
                    )
                    time.sleep(wait_time)
                    continue

                logger.error(f"Network error communicating with LLM Provider after retries: {err_msg}")
                raise LLMProviderError(f"Network error during LLM request: {err_msg}") from e
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse LLM response JSON: {e}")
                raise LLMProviderError("Received invalid JSON payload from LLM API") from e

        if data is None:
            raise LLMProviderError("Failed to obtain response from LLM Provider after retries")

        choices = data.get("choices", [])
        if not choices:
            raise LLMProviderError("No choices returned from LLM provider")

        choice_msg = choices[0].get("message", {})
        content = choice_msg.get("content") or ""

        # Parse tool calls if any
        tool_calls_raw = choice_msg.get("tool_calls")
        tool_calls: list[ToolCall] | None = None

        if tool_calls_raw:
            tool_calls = []
            for tc in tool_calls_raw:
                tc_id = tc.get("id", "")
                func = tc.get("function", {})
                tc_name = func.get("name", "")
                args_raw = func.get("arguments", "{}")
                if isinstance(args_raw, str):
                    try:
                        args_dict = json.loads(args_raw)
                    except json.JSONDecodeError:
                        args_dict = {"raw_arguments": args_raw}
                else:
                    args_dict = args_raw or {}

                tool_calls.append(ToolCall(id=tc_id, name=tc_name, arguments=args_dict))

        return Message(
            role=Role.ASSISTANT,
            content=content,
            tool_calls=tool_calls,
        )
