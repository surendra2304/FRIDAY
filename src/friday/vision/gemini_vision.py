# -*- coding: utf-8 -*-
"""Gemini Multimodal Vision Provider using official google-genai SDK.

Integrates with FRIDAY's GeminiCredentialPool for primary and fallback API key failover,
performs safe image format validation, and enforces zero secret exposure.
"""

import time
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from friday.auth.credential_pool import credential_pool, GeminiCredentialPool, FailureCategory
from friday.core.config import get_settings
from friday.core.exceptions import LLMProviderError
from friday.core.logging import get_logger
from friday.vision.base import BaseVisionProvider, VisionAnalysisResult

logger = get_logger("vision.gemini")

SUPPORTED_MIME_TYPES = {
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/jpeg": b"\xff\xd8\xff",
    "image/webp": b"RIFF",
}


def validate_image_data(image_data: bytes, mime_type: str, max_bytes: int = 20971520) -> None:
    """Validate image payload format, magic bytes, and size boundaries."""
    if not image_data or len(image_data) == 0:
        raise ValueError("Image data is empty")

    if len(image_data) > max_bytes:
        raise ValueError(
            f"Image payload exceeds maximum allowed size ({len(image_data)} bytes > {max_bytes} bytes)"
        )

    norm_mime = mime_type.lower().strip()
    if norm_mime not in SUPPORTED_MIME_TYPES:
        raise ValueError(
            f"Unsupported image MIME type '{mime_type}'. Supported: {list(SUPPORTED_MIME_TYPES.keys())}"
        )

    # Magic byte header validation
    expected_magic = SUPPORTED_MIME_TYPES[norm_mime]
    if not image_data.startswith(expected_magic):
        raise ValueError(f"Corrupted or invalid image data for declared MIME type '{mime_type}'")


class GeminiVisionProvider(BaseVisionProvider):
    """Google Gemini multimodal vision provider with credential pool failover."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        credential_pool: Optional[GeminiCredentialPool] = credential_pool,
        timeout: float = 60.0,
        max_retries: int = 3,
        backoff_factor: float = 2.0,
        max_image_bytes: Optional[int] = None,
    ) -> None:
        settings = get_settings()
        self.credential_pool = credential_pool
        self._explicit_api_key = api_key
        self.model = model or getattr(settings, "vision_model", "gemini-3.6-flash")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.max_image_bytes = max_image_bytes or getattr(settings, "vision_max_image_bytes", 20971520)
        self._client: Optional[genai.Client] = None
        self._current_key: Optional[str] = None

    def _get_active_api_key(self) -> str:
        """Resolve active API key respecting credential pool state."""
        if self._explicit_api_key:
            return self._explicit_api_key

        if self.credential_pool:
            try:
                key = self.credential_pool.get_active_key()
                if key:
                    return key
            except RuntimeError as e:
                raise LLMProviderError(str(e)) from e

        settings = get_settings()
        key = settings.gemini_api_key or settings.llm_api_key
        if key:
            return key

        raise LLMProviderError("No healthy Gemini API key available in credential pool for vision")

    def _get_client(self, api_key: str) -> genai.Client:
        """Instantiate or reuse genai.Client for the given API key."""
        if self._client is None or getattr(self, "_current_key", None) != api_key:
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
        if "404" in msg or "not_found" in msg:
            return FailureCategory.MODEL_NOT_FOUND
        if "500" in msg or "503" in msg or "internal" in msg:
            return FailureCategory.SERVICE_ERROR
        if "timeout" in msg or "connection" in msg:
            return FailureCategory.NETWORK_ERROR
        return FailureCategory.UNKNOWN

    def analyze_image(
        self,
        image_data: bytes,
        mime_type: str = "image/png",
        prompt: str = "Describe what is visible in this image in detail.",
        **kwargs: Any,
    ) -> VisionAnalysisResult:
        """Analyze image bytes with Google Gemini multimodal API and credential failover."""
        # 1. Validate payload boundaries and magic bytes
        validate_image_data(image_data, mime_type=mime_type, max_bytes=self.max_image_bytes)

        # 2. Build multimodal contents part
        image_part = genai_types.Part.from_bytes(data=image_data, mime_type=mime_type)
        contents = [image_part, prompt]

        # 3. Configure generation options
        temp = kwargs.get("temperature", 0.4)
        max_output_tokens = kwargs.get("max_tokens", 2048)
        gen_config = genai_types.GenerateContentConfig(
            temperature=temp,
            max_output_tokens=max_output_tokens,
        )

        last_error = None
        attempt = 0

        pool_creds = getattr(self.credential_pool, "credentials", None) if self.credential_pool else None
        pool_size = len(pool_creds) if (pool_creds is not None and isinstance(pool_creds, list) and len(pool_creds) > 0) else None
        max_attempts = pool_size if (pool_size is not None and not self._explicit_api_key) else (self.max_retries + 1)

        while attempt < max_attempts:
            active_key = None
            try:
                active_key = self._get_active_api_key()
            except (LLMProviderError, RuntimeError, Exception) as e:
                last_error = e
                break

            try:
                self._current_key = active_key
                client = self._get_client(active_key)

                response = client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=gen_config,
                )

                if self.credential_pool and not self._explicit_api_key:
                    self.credential_pool.reset_key(active_key)

                response_text = getattr(response, "text", "") or ""
                return VisionAnalysisResult(
                    text=response_text,
                    description=response_text,
                    model=self.model,
                    is_error=False,
                )

            except Exception as e:
                last_error = e
                attempt += 1

                cat = self._classify_error(e)
                if self.credential_pool and not self._explicit_api_key and (active_key or self._current_key):
                    failed_key = active_key or self._current_key
                    self.credential_pool.report_failure(failed_key, e)

                logger.warning(
                    f"Gemini Vision call failed (attempt {attempt}/{max_attempts}): {type(e).__name__} ({cat.value})"
                )

                # If quota exhausted or auth failed and pool is active, immediately fail over to next credential with 0 delay
                if self.credential_pool and not self._explicit_api_key and cat in (
                    FailureCategory.QUOTA_EXHAUSTED,
                    FailureCategory.AUTH_FAILED,
                ):
                    old_label = "key"
                    try:
                        c = self.credential_pool._find_by_key(active_key or self._current_key) if callable(getattr(self.credential_pool, "_find_by_key", None)) else None
                        if c and hasattr(c, "project_label") and isinstance(c.project_label, str):
                            old_label = c.project_label
                    except Exception:
                        pass

                    next_label = "next available credential"
                    try:
                        next_c = self.credential_pool._find_by_key(active_key or self._current_key) if callable(getattr(self.credential_pool, "_find_by_key", None)) else None
                    except Exception:
                        pass

                    logger.warning(
                        f"Gemini credential {old_label} quota exhausted; switching to next available credential."
                    )
                    continue

                if attempt < max_attempts:
                    delay = self.backoff_factor ** (attempt - 1)
                    time.sleep(delay)

        error_msg = f"Gemini Vision analysis failed after {attempt} attempts: {last_error}"
        logger.error(error_msg)
        return VisionAnalysisResult(
            text="",
            is_error=True,
            error_message=str(last_error),
            model=self.model,
        )
