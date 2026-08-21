# -*- coding: utf-8 -*-
"""OpenAI-compatible Multimodal Vision Provider using HTTPX.

Implements BaseVisionProvider for OpenAI GPT-4o / GPT-4-turbo or any OpenAI-compatible
multimodal vision endpoint (Groq, Ollama, OpenRouter, vLLM).
"""

import base64
import json
import time
from typing import Any, Dict, List, Optional
import httpx

from friday.core.exceptions import VisionProviderError
from friday.core.logging import get_logger
from friday.security.scrubber import redact_secrets
from friday.vision.base import BaseVisionProvider, VisionAnalysisResult
from friday.vision.screen_analyzer import parse_vision_json_response

logger = get_logger("vision.openai_vision")


class OpenAIVisionProvider(BaseVisionProvider):
    """Multimodal Vision Provider for OpenAI and OpenAI-compatible vision endpoints."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or ""
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout

    @property
    def provider_name(self) -> str:
        return "openai"

    def analyze_image(
        self,
        image_data: bytes,
        mime_type: str = "image/png",
        prompt: str = "Describe what is visible in this image in detail.",
        **kwargs: Any,
    ) -> VisionAnalysisResult:
        """Analyze image bytes with guiding prompt using OpenAI-compatible multimodal endpoint."""
        if not image_data:
            return VisionAnalysisResult(
                text="",
                is_error=True,
                error_message="Image data is empty.",
                model=self.model,
            )

        b64_image = base64.b64encode(image_data).decode("utf-8")
        image_url = f"data:{mime_type};base64,{b64_image}"

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: Dict[str, Any] = {
            "model": kwargs.get("model", self.model),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                }
            ],
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()

            choice = data.get("choices", [{}])[0]
            content = choice.get("message", {}).get("content", "")

            # Attempt structured JSON parsing
            parsed_dict = parse_vision_json_response(content)
            elements = parsed_dict.get("ui_elements", [])

            return VisionAnalysisResult(
                text=content,
                description=parsed_dict.get("summary", content[:200]),
                visual_elements=elements,
                model=self.model,
                is_error=False,
                raw_response=data,
            )
        except Exception as e:
            err_msg = redact_secrets(str(e))
            logger.error(f"OpenAIVisionProvider analysis failed: {err_msg}")
            return VisionAnalysisResult(
                text="",
                is_error=True,
                error_message=f"OpenAI vision call failed: {err_msg}",
                model=self.model,
            )
