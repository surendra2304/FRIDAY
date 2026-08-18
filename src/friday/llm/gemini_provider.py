"""Google Gemini LLM Provider using HTTPX."""

import json
import time
from typing import Any, Dict, List, Optional
import httpx
from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.core.types import Message, Role, ToolCall
from friday.llm.base import BaseLLMProvider

logger = get_logger("llm.gemini")


class GeminiLLMProvider(BaseLLMProvider):
    """LLM Provider for Google Gemini REST API (v1beta / models)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        model: str = "gemini-2.5-flash",
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
        return "gemini"

    def _convert_schema_to_gemini(self, tool_def: Dict[str, Any]) -> Dict[str, Any]:
        """Convert standard OpenAI-compatible tool JSON schema to Gemini function declaration."""
        if tool_def.get("type") == "function" and "function" in tool_def:
            func = tool_def["function"]
            return {
                "name": func.get("name", ""),
                "description": func.get("description", ""),
                "parameters": func.get("parameters", {}),
            }
        return {
            "name": tool_def.get("name", ""),
            "description": tool_def.get("description", ""),
            "parameters": tool_def.get("parameters", {}),
        }

    def _build_gemini_payload(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Translate FRIDAY Messages and Tool definitions into a Gemini API payload."""
        system_instruction_parts = []
        contents = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                if msg.content:
                    system_instruction_parts.append({"text": msg.content})
            elif msg.role == Role.USER:
                contents.append({
                    "role": "user",
                    "parts": [{"text": msg.content}],
                })
            elif msg.role == Role.ASSISTANT:
                parts: List[Dict[str, Any]] = []
                if msg.content:
                    parts.append({"text": msg.content})
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        args = tc.arguments if isinstance(tc.arguments, dict) else {}
                        parts.append({
                            "functionCall": {
                                "name": tc.name,
                                "args": args,
                            }
                        })
                if not parts:
                    parts.append({"text": ""})
                contents.append({
                    "role": "model",
                    "parts": parts,
                })
            elif msg.role == Role.TOOL:
                # In Gemini, function responses are provided with role 'function' or 'user' containing functionResponse
                tool_name = msg.name or "tool"
                # If content is JSON parseable, wrap it as dictionary in response; otherwise wrap as string
                try:
                    parsed_response = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                    if not isinstance(parsed_response, dict):
                        parsed_response = {"output": parsed_response}
                except Exception:
                    parsed_response = {"output": msg.content}

                contents.append({
                    "role": "function",
                    "parts": [{
                        "functionResponse": {
                            "name": tool_name,
                            "response": parsed_response,
                        }
                    }],
                })

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
            },
        }

        if system_instruction_parts:
            payload["systemInstruction"] = {
                "parts": system_instruction_parts,
            }

        if tools:
            func_decls = [self._convert_schema_to_gemini(t) for t in tools]
            payload["tools"] = [{"functionDeclarations": func_decls}]

        return payload

    def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Message:
        """Call the Gemini generateContent endpoint."""
        if not self.api_key:
            raise LLMProviderError(
                "Gemini API key is required. Set FRIDAY_GEMINI_API_KEY or FRIDAY_LLM_API_KEY."
            )

        model_name = self.model
        if not model_name.startswith("models/"):
            model_path = f"models/{model_name}"
        else:
            model_path = model_name

        url = f"{self.base_url}/{model_path}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.api_key,
        }

        payload = self._build_gemini_payload(messages, tools)

        max_retries = 3
        backoff_factor = 2.0
        initial_delay = 1.0
        data = None

        for attempt in range(max_retries + 1):
            try:
                logger.debug(
                    f"Calling Gemini provider endpoint {url} with model {self.model} "
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

                # Status codes eligible for retry: 429 (Rate Limit / Quota) and 5xx (Server Errors)
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
                            f"Gemini API request failed with status {response.status_code}. "
                            f"Retrying in {wait_time:.2f} seconds..."
                        )
                        time.sleep(wait_time)
                        continue

                logger.error(f"Gemini API request failed [{response.status_code}]: {error_detail}")
                raise LLMProviderError(f"Gemini API returned status {response.status_code}: {error_detail}")

            except httpx.RequestError as e:
                err_msg = str(e)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "***")

                # RequestError is transient (timeout, connect error) -> retry
                if attempt < max_retries:
                    wait_time = initial_delay * (backoff_factor ** attempt)
                    logger.warning(
                        f"Network error communicating with Gemini Provider: {err_msg}. "
                        f"Retrying in {wait_time:.2f} seconds..."
                    )
                    time.sleep(wait_time)
                    continue

                logger.error(f"Network error communicating with Gemini Provider after retries: {err_msg}")
                raise LLMProviderError(f"Network error during Gemini request: {err_msg}") from e
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse Gemini response JSON: {e}")
                raise LLMProviderError("Received invalid JSON payload from Gemini API") from e

        if data is None:
            raise LLMProviderError("Failed to obtain response from Gemini Provider after retries")

        # Parse Gemini response candidates
        candidates = data.get("candidates", [])
        if not candidates:
            # Check for prompt feedback block
            feedback = data.get("promptFeedback", {})
            block_reason = feedback.get("blockReason")
            if block_reason:
                raise LLMProviderError(f"Gemini request was blocked by safety filters: {block_reason}")
            raise LLMProviderError("No candidates returned from Gemini provider")

        first_candidate = candidates[0]
        content_obj = first_candidate.get("content", {})
        parts = content_obj.get("parts", [])

        text_content_pieces = []
        tool_calls: Optional[List[ToolCall]] = None

        for part in parts:
            if "text" in part and part["text"]:
                text_content_pieces.append(part["text"])
            elif "functionCall" in part:
                if tool_calls is None:
                    tool_calls = []
                fc = part["functionCall"]
                fc_name = fc.get("name", "")
                fc_args = fc.get("args", {})
                if isinstance(fc_args, str):
                    try:
                        fc_args = json.loads(fc_args)
                    except json.JSONDecodeError:
                        fc_args = {"raw_arguments": fc_args}
                # Generate unique call id
                call_id = f"call_{fc_name}_{int(time.time() * 1000)}"
                tool_calls.append(ToolCall(id=call_id, name=fc_name, arguments=fc_args or {}))

        final_text = "".join(text_content_pieces).strip()

        return Message(
            role=Role.ASSISTANT,
            content=final_text,
            tool_calls=tool_calls,
        )
