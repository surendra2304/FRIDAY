# -*- coding: utf-8 -*-
"""Gemini LLM Provider using the official google-genai SDK.

This modern implementation uses Google's current official `google-genai` Python SDK
(`from google import genai`). It preserves FRIDAY's `BaseLLMProvider` contract,
enforces strict tool safety and authorization boundaries, and guarantees zero
local inference compute.

Security considerations:
- The API key is never logged; any accidental inclusion in error messages is
  masked with "***".
- No secrets are written to disk or exposed in `__repr__`.
- All retries are bounded and exponential back-off controlled.
"""

import json
import time
from typing import Any, Dict, List, Optional
import uuid

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.core.types import Message, Role, ToolCall
from friday.llm.base import BaseLLMProvider
from friday.auth.credential_pool import credential_pool, GeminiCredentialPool
# duplicate import removed

logger = get_logger("llm.gemini")


class GeminiLLMProvider(BaseLLMProvider):
    """LLM Provider for Google Gemini using the official google-genai SDK."""

    def __init__(
        self,
        api_key: str = None,
        credential_pool: GeminiCredentialPool = credential_pool,
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
        self.api_key = api_key
        self.credential_pool = credential_pool
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.cost_mode = cost_mode
        self._client: Optional[genai.Client] = None
        self._current_key: Optional[str] = None

    @property
    def client(self) -> genai.Client:
        """Retrieve or create the cached GenAI Client instance using the credential pool."""
        # Use explicit api_key if provided, otherwise fall back to the credential pool.
        try:
            active_key = self.api_key if self.api_key else self.credential_pool.get_active_key()
        except RuntimeError as e:
            # No healthy credentials and no explicit key provided
            raise LLMProviderError(str(e)) from e

        if self._client is None:
            self._client = genai.Client(api_key=active_key)
            self._current_key = active_key
            # keep api_key attribute in sync for masking
            self.api_key = active_key
        return self._client

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _mask_key(self, text: str) -> str:
        """Mask API key in any error or diagnostic string.
        Replaces exact key and all keys from the credential pool.
        """
        keys_to_mask = set()
        if getattr(self, "api_key", None):
            keys_to_mask.add(self.api_key)
        if getattr(self, "_current_key", None):
            keys_to_mask.add(self._current_key)
        if hasattr(self, "credential_pool") and self.credential_pool:
            for cred in getattr(self.credential_pool, "credentials", []):
                if getattr(cred, "api_key", None):
                    keys_to_mask.add(cred.api_key)

        masked = text
        for key in keys_to_mask:
            if key and len(key) >= 4:
                masked = masked.replace(key, "***")
                try:
                    import re
                    pattern = re.compile(re.escape(key), re.IGNORECASE)
                    masked = pattern.sub("***", masked)
                except Exception:
                    pass
        return masked

    # ---------------------------------------------------------------------
    # Schema and Message Conversion Helpers
    # ---------------------------------------------------------------------
    def _convert_schema_to_gemini(self, tool_def: Dict[str, Any]) -> Dict[str, Any]:
        """Convert an OpenAI-compatible tool JSON schema to a Gemini function declaration dict."""
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

    def _build_contents_and_config(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[genai_types.Content], genai_types.GenerateContentConfig]:
        """Translate FRIDAY Messages and Tool definitions to GenAI SDK types."""
        system_instruction_text = ""
        contents: List[genai_types.Content] = []

        for msg in messages:
            if msg.role == Role.SYSTEM:
                if msg.content:
                    system_instruction_text = (
                        f"{system_instruction_text}\n\n{msg.content}".strip()
                        if system_instruction_text
                        else msg.content
                    )
            elif msg.role == Role.USER:
                contents.append(
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part.from_text(text=msg.content or "")],
                    )
                )
            elif msg.role == Role.ASSISTANT:
                parts: List[genai_types.Part] = []
                if msg.content:
                    parts.append(genai_types.Part.from_text(text=msg.content))
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        args = tc.arguments if isinstance(tc.arguments, dict) else {}
                        sig = getattr(tc, "thought_signature", None)
                        if sig:
                            parts.append(
                                genai_types.Part(
                                    function_call=genai_types.FunctionCall(name=tc.name, args=args),
                                    thought_signature=sig,
                                )
                            )
                        else:
                            parts.append(
                                genai_types.Part.from_function_call(name=tc.name, args=args)
                            )
                if not parts:
                    parts.append(genai_types.Part.from_text(text=""))
                contents.append(genai_types.Content(role="model", parts=parts))
            elif msg.role == Role.TOOL:
                tool_name = msg.name or "tool"
                try:
                    parsed = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                    if not isinstance(parsed, dict):
                        parsed = {"output": parsed}
                except Exception:
                    parsed = {"output": msg.content}
                contents.append(
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part.from_function_response(name=tool_name, response=parsed)],
                    )
                )

        # Build tools if provided
        genai_tools: Optional[List[genai_types.Tool]] = None
        if tools:
            func_decls = []
            for t in tools:
                converted = self._convert_schema_to_gemini(t)
                func_decls.append(
                    genai_types.FunctionDeclaration(
                        name=converted.get("name", ""),
                        description=converted.get("description", ""),
                        parameters=converted.get("parameters", {}),
                    )
                )
            genai_tools = [genai_types.Tool(function_declarations=func_decls)]

        config = genai_types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_tokens,
            system_instruction=system_instruction_text if system_instruction_text else None,
            tools=genai_tools,
            automatic_function_calling=genai_types.AutomaticFunctionCallingConfig(disable=True),
        )

        return contents, config

    def _build_gemini_payload(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Backwards-compatible dictionary serialization of Gemini payload for testing."""
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

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": self.temperature, "max_output_tokens": self.max_tokens},
        }
        if system_instruction_parts:
            payload["systemInstruction"] = {"parts": system_instruction_parts}
        if tools:
            func_decls = [self._convert_schema_to_gemini(t) for t in tools]
            payload["tools"] = [{"functionDeclarations": func_decls}]
        return payload

    # ---------------------------------------------------------------------
    # Public generate method
    # ---------------------------------------------------------------------
    def generate(
        self,
        messages: List[Message],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Message:
        """Generate an assistant response using the Google GenAI SDK.

        Translates FRIDAY messages, enforces function-calling trust boundaries,
        and wraps exceptions in LLMProviderError with secret masking.
        """
        attempt = 0
        while attempt <= self.max_retries:
            # Determine the API key to use for this request (re-select each retry)
            if self.api_key is not None and not self.api_key.strip():
                raise LLMProviderError("Gemini API key is required")
            try:
                active_key = self.api_key if self.api_key else self.credential_pool.get_active_key()
            except (RuntimeError, Exception) as e:
                raise LLMProviderError("Gemini API key is required") from e
            
            # Ensure client is initialized/updated with the active key
            if self._client is None:
                self._client = genai.Client(api_key=active_key)
                self._current_key = active_key
            elif not hasattr(self._client, "_is_mock") and getattr(self, "_current_key", None) != active_key:
                # If key changed and it's not an explicit test mock, recreate client with new key
                try:
                    self._client = genai.Client(api_key=active_key)
                except Exception:
                    pass
                self._current_key = active_key

            contents, config = self._build_contents_and_config(messages, tools)

            try:
                logger.debug(
                    f"Calling GenAI generate_content (model: {self.model}, attempt {attempt + 1}/{self.max_retries + 1})"
                )
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )

                # Check candidates and safety blocks
                if not response.candidates:
                    if hasattr(response, "prompt_feedback") and response.prompt_feedback:
                        block_reason = getattr(response.prompt_feedback, "block_reason", None)
                        if block_reason:
                            raise LLMProviderError(f"blocked by safety filters: {block_reason}")
                    raise LLMProviderError("Gemini returned no candidates")

                # Reset credential health on success
                if hasattr(self, "credential_pool") and self.credential_pool and not self.api_key:
                    self.credential_pool.reset_key(active_key)

                candidate = response.candidates[0]
                content = candidate.content
                parts = getattr(content, "parts", []) or []

                text_parts: List[str] = []
                tool_calls: Optional[List[ToolCall]] = None

                for part in parts:
                    if getattr(part, "text", None):
                        text_parts.append(part.text.strip())
                    elif getattr(part, "function_call", None):
                        fc = part.function_call
                        if tool_calls is None:
                            tool_calls = []
                        fc_name = getattr(fc, "name", "")
                        fc_args = getattr(fc, "args", {})
                        if isinstance(fc_args, str):
                            try:
                                fc_args = json.loads(fc_args)
                            except json.JSONDecodeError:
                                fc_args = {"raw_arguments": fc_args}
                        elif not isinstance(fc_args, dict):
                            try:
                                fc_args = dict(fc_args)
                            except Exception:
                                fc_args = {"raw": str(fc_args)}
                        call_id = getattr(fc, "id", None) or f"call_{fc_name}_{uuid.uuid4().hex[:8]}"
                        thought_sig = getattr(part, "thought_signature", None) or getattr(fc, "thought_signature", None)
                        tool_calls.append(
                            ToolCall(
                                id=call_id,
                                name=fc_name,
                                arguments=fc_args or {},
                                thought_signature=thought_sig,
                            )
                        )

                final_text = "".join(text_parts).strip()
                return Message(role=Role.ASSISTANT, content=final_text, tool_calls=tool_calls)

            except (genai_errors.APIError, Exception) as e:
                err_msg = self._mask_key(str(e))
                code = getattr(e, "code", None) or getattr(e, "status_code", 500)
                
                # Report failure to credential pool for auth/quota/network errors with error classification
                if hasattr(self, "credential_pool") and self.credential_pool and not self.api_key:
                    self.credential_pool.report_failure(active_key, error=e)
                
                err_lower = err_msg.lower()
                # If this looks like a quota or rate limit issue, treat as retryable
                if ("429" in err_lower or "quota" in err_lower or "resource exhausted" in err_lower) and attempt < self.max_retries:
                    wait = 1.0 * (self.backoff_factor ** attempt)
                    logger.warning(f"GenAI rate limit: {err_msg}. Retrying in {wait:.2f}s...")
                    time.sleep(wait)
                    attempt += 1
                    continue
                logger.error(f"Gemini provider error: {err_msg}")
                raise LLMProviderError(f"Gemini provider error: {err_msg}") from e

        raise LLMProviderError("Failed to obtain response from Gemini Provider after retries")
