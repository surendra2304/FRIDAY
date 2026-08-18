"""OpenAI-compatible LLM Provider using HTTPX."""

import json
from typing import Any, Dict, List, Optional
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
        api_key: Optional[str] = None,
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
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Message:
        """Call the chat completions endpoint."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_provider_dict() for m in messages],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        logger.debug(f"Calling OpenAI provider endpoint {url} with model {self.model}")

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                if response.status_code != 200:
                    try:
                        err_json = response.json()
                        error_detail = err_json.get("error", {}).get("message") or response.text
                    except Exception:
                        error_detail = response.text

                    # Truncate long error output to prevent terminal flooding (e.g. raw HTML error pages)
                    if isinstance(error_detail, str) and len(error_detail) > 300:
                        error_detail = error_detail[:300] + "... [TRUNCATED]"

                    # Proactively mask any potential API key in the error string to prevent leaks
                    if self.api_key and isinstance(error_detail, str) and self.api_key in error_detail:
                        error_detail = error_detail.replace(self.api_key, "***")

                    logger.error(f"LLM API request failed [{response.status_code}]: {error_detail}")
                    raise LLMProviderError(f"LLM Provider API returned status {response.status_code}: {error_detail}")

                data = response.json()
        except httpx.RequestError as e:
            err_msg = str(e)
            if self.api_key and self.api_key in err_msg:
                err_msg = err_msg.replace(self.api_key, "***")
            logger.error(f"Network error communicating with LLM Provider: {err_msg}")
            raise LLMProviderError(f"Network error during LLM request: {err_msg}") from e
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response JSON: {e}")
            raise LLMProviderError("Received invalid JSON payload from LLM API") from e

        choices = data.get("choices", [])
        if not choices:
            raise LLMProviderError("No choices returned from LLM provider")

        choice_msg = choices[0].get("message", {})
        content = choice_msg.get("content") or ""

        # Parse tool calls if any
        tool_calls_raw = choice_msg.get("tool_calls")
        tool_calls: Optional[List[ToolCall]] = None

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
