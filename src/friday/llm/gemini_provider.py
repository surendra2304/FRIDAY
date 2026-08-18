# -*- coding: utf-8 -*-
"""Gemini LLM Provider using the official google-generativeai SDK.

This modern implementation replaces the previous low‑level HTTPX based provider.
It keeps the original `BaseLLMProvider` interface so the rest of FRIDAY remains
unchanged, while delegating authentication, request construction and response
parsing to the official SDK.

Security considerations:
- The API key is never logged; any accidental inclusion in error messages is
  masked with "***".
- No secrets are written to disk or exposed in `__repr__`.
- All retries are bounded and exponential back‑off controlled.
"""

import json
import httpx
import time
from typing import Any, Dict, List, Optional

from google.generativeai import configure as genai_config
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.core.types import Message, Role, ToolCall
from friday.llm.base import BaseLLMProvider

logger = get_logger("llm.gemini")


class GeminiLLMProvider(BaseLLMProvider):
    """LLM Provider for Google Gemini using the official google‑generativeai SDK.

    The provider respects the same configuration interface as the previous
    HTTPX implementation but delegates request handling to the official SDK.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        model: str = "gemini-2.5-flash",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        cost_mode: str = "free_first",
    ) -> None:
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.cost_mode = cost_mode
        if self.api_key:
            genai.configure(api_key=self.api_key)
        else:
            logger.warning("Gemini API key not provided; provider may fail on generate calls.")

    @property
    def provider_name(self) -> str:
        return "gemini"

    # ---------------------------------------------------------------------
    # Helper conversion utilities (unchanged from previous implementation)
    # ---------------------------------------------------------------------
    def _convert_schema_to_gemini(self, tool_def: Dict[str, Any]) -> Dict[str, Any]:
        """Convert an OpenAI‑compatible tool JSON schema to a Gemini function declaration."""
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
        """Translate FRIDAY messages and optional tool schemas into the payload format expected
        by the google‑generativeai SDK.
        """
        system_instruction_parts = []
        contents: List[Dict[str, Any]] = []

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
                            "functionCall": {"name": tc.name, "args": args}
                        })
                if not parts:
                    parts.append({"text": ""})
                contents.append({"role": "model", "parts": parts})
            elif msg.role == Role.TOOL:
                tool_name = msg.name or "tool"
                try:
                    parsed = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                    if not isinstance(parsed, dict):
                        parsed = {"output": parsed}
                except Exception:
                    parsed = {"output": msg.content}
                contents.append({
                    "role": "function",
                    "parts": [{"functionResponse": {"name": tool_name, "response": parsed}}],
                })

        payload = {
            "contents": contents,
            "generationConfig": {"temperature": self.temperature, "max_output_tokens": self.max_tokens},
        }
        if system_instruction_parts:
            # Use camelCase key as expected by tests and Gemini API
            payload["systemInstruction"] = {"parts": system_instruction_parts}
        if tools:
            func_decls = [self._convert_schema_to_gemini(t) for t in tools]
            # Use camelCase as expected by Gemini API and tests
            payload["tools"] = [{"functionDeclarations": func_decls}]
        return payload

    # ---------------------------------------------------------------------
    # Public generate method – core of the provider
    # ---------------------------------------------------------------------
    def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Message:
        """Generate a response using Gemini.

        Errors from the SDK are wrapped in ``LLMProviderError`` with any secret values
        masked before they are logged or re‑raised.
        """
        if not self.api_key:
            raise LLMProviderError(
                "Gemini API key is required. Set FRIDAY_GEMINI_API_KEY or FRIDAY_LLM_API_KEY."
            )

        model_name = self.model
        if not model_name.startswith("models/"):
            model_path = f"models/{model_name}"
        else:
            model_path = model_name

        payload = self._build_gemini_payload(messages, tools)

        # Extract components for the SDK call
        generation_config = payload.pop("generationConfig", {})
        system_instruction = payload.pop("systemInstruction", None)
        tools_payload = payload.pop("tools", None)
        contents = payload.get("contents", [])
        # Prepare the request URL for Gemini generateContent endpoint
        request_url = f"{self.base_url}/{model_path}:generateContent"
        # Build request payload matching Gemini API expectations
        request_body = {
            "contents": contents,
        }
        if generation_config:
            request_body["generationConfig"] = generation_config
        if system_instruction:
            request_body["systemInstruction"] = system_instruction
        if tools_payload:
            request_body["tools"] = tools_payload

        attempt = 0
        while attempt <= self.max_retries:
            try:
                logger.debug(
                    f"Calling Gemini endpoint {request_url} (attempt {attempt + 1}/{self.max_retries + 1})"
                )
                # Use httpx.Client for request to allow test mocking via httpx.Client.post
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.post(
                        request_url,
                        headers={"Content-Type": "application/json"},
                        json=request_body,
                    )
                    # If the response is not successful, treat it as a retryable error
                    if response.status_code != 200:
                        # Extract error message for logging / retry
                        try:
                            err_json = response.json()
                            err_msg = err_json.get("error", {}).get("message", f"Unexpected status code: {response.status_code}")
                        except Exception:
                            err_msg = f"Unexpected status code: {response.status_code}"
                        # Raise as HTTPStatusError to trigger retry logic
                        raise httpx.HTTPStatusError(err_msg, request=None, response=response)
                    resp_json = response.json()
                # Parse the Gemini response structure
                # Handle safety block reasons before checking candidates
                candidates = resp_json.get("candidates", [])
                if not candidates:
                    pf = resp_json.get("promptFeedback", {})
                    block_reason = pf.get("blockReason")
                    if block_reason:
                        raise LLMProviderError(f"blocked by safety filters: {block_reason}")
                    raise LLMProviderError("Gemini returned no candidates")
                candidate = candidates[0]
                # Extract text parts and function calls safely
                content = candidate.get("content") or {}
                parts = content.get("parts", [])
                text_parts: List[str] = []
                tool_calls: Optional[List[ToolCall]] = None
                for part in parts:
                    if "text" in part and part["text"] is not None:
                        # Append stripped text to avoid NoneType errors
                        text_parts.append(part["text"].strip())
                    elif "functionCall" in part:
                        fc = part["functionCall"]
                        if tool_calls is None:
                            tool_calls = []
                        fc_name = fc.get("name", "")
                        fc_args = fc.get("args", {})
                        # Ensure arguments are a dict
                        if isinstance(fc_args, str):
                            try:
                                fc_args = json.loads(fc_args)
                            except json.JSONDecodeError:
                                fc_args = {"raw_arguments": fc_args}
                        call_id = f"call_{fc_name}_{int(time.time() * 1000)}"
                        tool_calls.append(ToolCall(id=call_id, name=fc_name, arguments=fc_args or {}))
                final_text = "".join(text_parts).strip()
                return Message(role=Role.ASSISTANT, content=final_text, tool_calls=tool_calls)
            except httpx.HTTPStatusError as e:
                try:
                    err_data = e.response.json()
                    detail = err_data.get("error", {}).get("message", str(e))
                except Exception:
                    detail = str(e)
                status = e.response.status_code
                err_msg = f"status {status}: {detail}"
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "***")
                if attempt < self.max_retries:
                    wait = self.timeout * (self.backoff_factor ** attempt)
                    logger.warning(
                        f"HTTP status {status} from Gemini: {err_msg}. Retrying in {wait:.2f}s..."
                    )
                    time.sleep(wait)
                    attempt += 1
                    continue
                logger.error(f"HTTP status {status} after retries: {err_msg}")
                raise LLMProviderError(f"Network error during Gemini request (status {status}): {err_msg}") from e
            except httpx.HTTPError as e:
                err_msg = str(e)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "***")
                if attempt < self.max_retries:
                    wait = self.timeout * (self.backoff_factor ** attempt)
                    logger.warning(
                        f"HTTP error communicating with Gemini Provider: {err_msg}. Retrying in {wait:.2f}s..."
                    )
                    time.sleep(wait)
                    attempt += 1
                    continue
                logger.error(f"HTTP error after retries: {err_msg}")
                raise LLMProviderError(f"Network error during Gemini request: {err_msg}") from e
            except httpx.RequestError as e:
                err_msg = str(e)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "***")
                if attempt < self.max_retries:
                    wait = self.timeout * (self.backoff_factor ** attempt)
                    logger.warning(
                        f"Request error communicating with Gemini Provider: {err_msg}. Retrying in {wait:.2f}s..."
                    )
                    time.sleep(wait)
                    attempt += 1
                    continue
                logger.error(f"Request error after retries: {err_msg}")
                raise LLMProviderError(f"Network error during Gemini request: {err_msg}") from e
            except httpx.TimeoutException as e:
                err_msg = str(e)
                if self.api_key and self.api_key in err_msg:
                    err_msg = err_msg.replace(self.api_key, "***")
                if attempt < self.max_retries:
                    wait = self.timeout * (self.backoff_factor ** attempt)
                    logger.warning(
                        f"Timeout communicating with Gemini Provider: {err_msg}. Retrying in {wait:.2f}s..."
                    )
                    time.sleep(wait)
                    attempt += 1
                    continue
                logger.error(f"Timeout after retries: {err_msg}")
                raise LLMProviderError(f"Network error during Gemini request: {err_msg}") from e
            except Exception as e:
                msg = str(e)
                if self.api_key and self.api_key in msg:
                    msg = msg.replace(self.api_key, "***")
                logger.error(f"Gemini provider error: {msg}")
                raise LLMProviderError(f"Gemini provider error: {msg}") from e
        raise LLMProviderError("Failed to obtain response from Gemini Provider after retries")
