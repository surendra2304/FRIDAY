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
import threading
import time
from typing import Any, Dict, List, Optional
import uuid

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from friday.core.config import get_settings
from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.core.types import Message, Role, ToolCall
from friday.llm.base import BaseLLMProvider
from friday.auth.credential_pool import credential_pool, GeminiCredentialPool, FailureCategory
from friday.auth.request_accounting import request_accountant

logger = get_logger("llm.gemini")


def is_gemini_37_model(model_name: str) -> bool:
    """Determine whether the specified model is a Gemini 3.7 series model."""
    m = (model_name or "").lower().strip()
    return "3.7" in m or "gemini-3-7" in m


class GeminiLLMProvider(BaseLLMProvider):
    """LLM Provider for Google Gemini using the official google-genai SDK."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        credential_pool: Optional[GeminiCredentialPool] = credential_pool,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        model: str = "gemini-3.7-flash",
        temperature: float = 0.7,
        max_tokens: int = 2048,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        cost_mode: str = "free_first",
        thinking_level: Optional[str] = None,
    ) -> None:
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        self._explicit_api_key: Optional[str] = api_key
        self.api_key: Optional[str] = api_key
        self.credential_pool: Optional[GeminiCredentialPool] = credential_pool
        self.base_url: str = base_url.rstrip("/")
        self.timeout: float = timeout
        self.max_retries: int = max_retries
        self.backoff_factor: float = backoff_factor
        self.cost_mode: str = cost_mode
        self.thinking_level: str = thinking_level or "medium"
        
        # Explicit thread-safe client cache
        self._client: Optional[genai.Client] = None
        self._current_key: Optional[str] = None
        self._lock: threading.Lock = threading.Lock()

        # Validate thinking level
        if self.thinking_level not in ("low", "medium", "high"):
            logger.warning(f"Invalid thinking level '{self.thinking_level}' provided; defaulting to 'medium'.")
            self.thinking_level = "medium"

    @property
    def client(self) -> genai.Client:
        """Retrieve or create the cached GenAI Client instance using the credential pool."""
        active_key = self._get_active_api_key()
        return self._get_client(active_key)

    @property
    def provider_name(self) -> str:
        return "gemini"

    def _get_active_api_key(self) -> str:
        """Retrieve the currently active API key from the explicit setting or pool."""
        if self._explicit_api_key is not None:
            if not self._explicit_api_key.strip():
                raise LLMProviderError("Gemini API key is required")
            return self._explicit_api_key

        if self.credential_pool:
            try:
                key = self.credential_pool.get_active_key()
                if key and key.strip():
                    return key
            except RuntimeError as e:
                raise LLMProviderError(f"Gemini API key is required: {e}") from e

        settings = get_settings()
        key = settings.gemini_api_key or settings.llm_api_key
        if key and key.strip():
            return key

        raise LLMProviderError("Gemini API key is required")

    def _get_client(self, api_key: str) -> genai.Client:
        """Instantiate or reuse genai.Client for the given API key in a thread-safe manner."""
        with self._lock:
            if self._client is None or self._current_key != api_key:
                self._client = genai.Client(api_key=api_key)
                self._current_key = api_key
            return self._client

    def _classify_error(self, error: Exception) -> FailureCategory:
        """Classify exceptions into failure categories for pool cooldown tracking."""
        if self.credential_pool:
            return self.credential_pool.classify_error(error)
        msg = str(error).lower()
        if "429" in msg or "resource_exhausted" in msg or "quota" in msg:
            return FailureCategory.QUOTA_EXHAUSTED
        if "401" in msg or "403" in msg or "invalid_argument" in msg or "api_key" in msg:
            return FailureCategory.AUTH_FAILED
        if "404" in msg or "not_found" in msg or ("model" in msg and "no longer available" in msg):
            return FailureCategory.MODEL_NOT_FOUND
        if "500" in msg or "503" in msg or "internal" in msg or "unavailable" in msg:
            return FailureCategory.SERVICE_ERROR
        if "connect" in msg or "timeout" in msg or "network" in msg:
            return FailureCategory.NETWORK_ERROR
        if "400" in msg or "invalid_argument" in msg:
            return FailureCategory.INVALID_REQUEST
        if "sdk" in msg or "clienterror" in msg:
            return FailureCategory.SDK_ERROR
        if "budget exceeded" in msg or "circuit breaker active" in msg:
            return FailureCategory.CIRCUIT_BLOCK
        return FailureCategory.UNKNOWN

    def _mask_key(self, text: str) -> str:
        """Mask API keys in any error or diagnostic string."""
        keys_to_mask = set()
        if self.api_key:
            keys_to_mask.add(self.api_key)
        if self._explicit_api_key:
            keys_to_mask.add(self._explicit_api_key)
        if self._current_key:
            keys_to_mask.add(self._current_key)
        if self.credential_pool:
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

        # Build config: For Gemini 3.7 models, temperature, top_p, and top_k are unsupported / deprecated.
        # Ensure they cannot accidentally reach the SDK.
        config_kwargs: Dict[str, Any] = {
            "max_output_tokens": self.max_tokens,
            "system_instruction": system_instruction_text if system_instruction_text else None,
            "tools": genai_tools,
            "automatic_function_calling": genai_types.AutomaticFunctionCallingConfig(disable=True),
        }

        if not is_gemini_37_model(self.model):
            # Only include temperature for legacy non-3.7 models
            config_kwargs["temperature"] = self.temperature
        else:
            if getattr(self, "temperature", None) is not None and self.temperature != 0.7:
                logger.info(
                    f"Temperature parameter ({self.temperature}) is unsupported for {self.model} "
                    "and has been omitted from SDK GenerateContentConfig."
                )

        # Add thinking_config if supported
        if hasattr(genai_types, "ThinkingConfig") and hasattr(genai_types, "ThinkingLevel"):
            try:
                level_enum = getattr(genai_types, "ThinkingLevel")
                # Map string to enum (case-insensitive)
                level_val = getattr(level_enum, self.thinking_level.upper())
            except Exception:
                # Fallback to MEDIUM if mapping fails
                level_val = getattr(genai_types, "ThinkingLevel").MEDIUM
            config_kwargs["thinking_config"] = genai_types.ThinkingConfig(thinking_level=level_val)

        config = genai_types.GenerateContentConfig(**config_kwargs)

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

        generation_config: Dict[str, Any] = {
            "max_output_tokens": self.max_tokens,
        }
        if not is_gemini_37_model(self.model):
            generation_config["temperature"] = self.temperature
        else:
            generation_config["thinking_config"] = {"thinking_level": self.thinking_level.upper()}

        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
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
        # 0. Check Request Accounting and Budget Enforcement
        allowed, budget_reason = request_accountant.can_make_request(purpose="reasoning")
        if not allowed:
            logger.warning(f"GeminiLLMProvider: Request blocked by budget limits: {budget_reason}")
            raise LLMProviderError(f"Budget exceeded: {budget_reason}")

        attempt = 0
        pool_creds = getattr(self.credential_pool, "credentials", None) if self.credential_pool else None
        pool_size = len(pool_creds) if (pool_creds is not None and len(pool_creds) > 0) else None
        max_attempts = pool_size if (pool_size is not None and not self._explicit_api_key) else (self.max_retries + 1)

        last_error = None
        call_start = time.perf_counter()

        while attempt < max_attempts:
            active_key = None
            try:
                active_key = self._get_active_api_key()
            except (LLMProviderError, RuntimeError, Exception) as e:
                last_error = e
                break

            label = "PRIMARY"
            if self.credential_pool:
                try:
                    c = self.credential_pool._find_by_key(active_key)
                    if c:
                        label = c.project_label
                except Exception:
                    pass

            try:
                self._current_key = active_key
                client = self._get_client(active_key)

                contents, config = self._build_contents_and_config(messages, tools)

                logger.debug(
                    f"Calling GenAI generate_content (model: {self.model}, attempt {attempt + 1}/{max_attempts})"
                )
                response = client.models.generate_content(
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
                if self.credential_pool and not self._explicit_api_key:
                    self.credential_pool.reset_key(active_key)

                # Extract token metrics if available
                usage = getattr(response, "usage_metadata", None)
                in_tokens = getattr(usage, "prompt_token_count", 0) or 0
                out_tokens = getattr(usage, "candidates_token_count", 0) or 0
                elapsed_ms = (time.perf_counter() - call_start) * 1000.0

                request_accountant.record_request(
                    credential_label=label,
                    model=self.model,
                    purpose="reasoning",
                    retries_count=attempt,
                    fallbacks_count=attempt if label != "PRIMARY" else 0,
                    estimated_input_tokens=in_tokens,
                    estimated_output_tokens=out_tokens,
                    latency_ms=elapsed_ms,
                )

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
                last_error = e
                attempt += 1
                err_msg = self._mask_key(str(e))
                
                # Classify error
                category = self._classify_error(e)

                request_accountant.record_request(
                    credential_label=label,
                    model=self.model,
                    purpose="reasoning",
                    retries_count=attempt,
                    failure_category=category.value,
                    latency_ms=(time.perf_counter() - call_start) * 1000.0,
                )

                # 1. Model Not Found: Rotating credentials or retrying is useless; raise immediately
                if category == FailureCategory.MODEL_NOT_FOUND:
                    logger.error(f"Gemini model not found ({self.model}): {err_msg}")
                    raise LLMProviderError(f"Gemini model not found ({self.model}): {err_msg}") from e

                # 2. Report failure to credential pool if using pool
                failed_key = active_key or self._current_key
                if self.credential_pool and not self._explicit_api_key and failed_key:
                    self.credential_pool.report_failure(failed_key, error=e)

                # 3. Authentication failure handling
                if category == FailureCategory.AUTH_FAILED:
                    if self.credential_pool and not self._explicit_api_key:
                        try:
                            self.credential_pool.get_active_key()
                            logger.warning(
                                f"Gemini credential authentication failed ({self._mask_key(failed_key)}); "
                                "switching to next healthy credential."
                            )
                            continue
                        except (RuntimeError, Exception):
                            logger.error("All Gemini credentials in pool are exhausted or authentication failed.")
                            raise LLMProviderError("CREDENTIAL_EXHAUSTED: All Gemini credentials in pool are exhausted or in cooldown.") from e
                    else:
                        logger.error(f"Gemini authentication failed for explicit key: {err_msg}")
                        raise LLMProviderError(f"Gemini authentication failed: {err_msg}") from e

                # 4. Quota Exhaustion / Rate limit handling
                if category in (FailureCategory.QUOTA_EXHAUSTED, FailureCategory.RATE_LIMIT):
                    if self.credential_pool and not self._explicit_api_key:
                        try:
                            self.credential_pool.get_active_key()
                            logger.warning(
                                f"Gemini quota exhausted for credential ({self._mask_key(failed_key)}); "
                                "switching to next available credential."
                            )
                            continue
                        except (RuntimeError, Exception):
                            logger.error("All Gemini credentials in pool are exhausted or in cooldown.")
                            raise LLMProviderError("CREDENTIAL_EXHAUSTED: All Gemini credentials in pool are exhausted or in cooldown.") from e
                    else:
                        if attempt < max_attempts:
                            wait = 1.0 * (self.backoff_factor ** (attempt - 1))
                            logger.warning(f"Gemini transient rate limit ({category.value}): {err_msg}. Retrying in {wait:.2f}s...")
                            time.sleep(wait)
                            continue
                        logger.error(f"Gemini quota/rate limit exhausted for explicit key: {err_msg}")
                        raise LLMProviderError(f"Gemini quota exhausted: {err_msg}") from e

                # 5. Transient errors (RATE_LIMIT, SERVICE_ERROR, NETWORK_ERROR, UNKNOWN): bounded backoff retry
                if attempt < max_attempts:
                    wait = 1.0 * (self.backoff_factor ** (attempt - 1))
                    logger.warning(f"GenAI transient error ({category.value}): {err_msg}. Retrying in {wait:.2f}s...")
                    time.sleep(wait)
                    continue

                logger.error(f"Gemini provider error ({category.value}): {err_msg}")
                raise LLMProviderError(f"Gemini provider error: {err_msg}") from e

        raise LLMProviderError(f"Failed to obtain response from Gemini Provider: {last_error}")
