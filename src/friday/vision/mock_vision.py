# -*- coding: utf-8 -*-
"""Deterministic mock vision provider for offline testing and fixture isolation."""

from typing import Any, Dict, List, Optional
from friday.vision.base import BaseVisionProvider, VisionAnalysisResult


class MockVisionProvider(BaseVisionProvider):
    """Mock implementation of BaseVisionProvider for deterministic test suites."""

    def __init__(
        self,
        default_response: str = "Mock visual analysis: clean desktop interface with code editor visible.",
        model: str = "mock-vision-v1",
    ) -> None:
        self.default_response = default_response
        self.model = model
        self.call_history: List[Dict[str, Any]] = []
        self.custom_responses: Dict[str, str] = {}
        self.should_fail: bool = False
        self.failure_error: str = "Mock vision provider simulated error"

    def set_response_for_prompt_substring(self, substring: str, response: str) -> None:
        """Register custom response triggered when prompt contains substring."""
        self.custom_responses[substring] = response

    def analyze_image(
        self,
        image_data: bytes,
        mime_type: str = "image/png",
        prompt: str = "Describe what is visible in this image in detail.",
        **kwargs: Any,
    ) -> VisionAnalysisResult:
        """Process image mock-analysis."""
        self.call_history.append({
            "image_size": len(image_data) if image_data else 0,
            "mime_type": mime_type,
            "prompt": prompt,
            "kwargs": kwargs,
        })

        if self.should_fail:
            return VisionAnalysisResult(
                text="",
                is_error=True,
                error_message=self.failure_error,
                model=self.model,
            )

        # Check for custom substring matches
        response_text = self.default_response
        for sub, custom_resp in self.custom_responses.items():
            if sub.lower() in prompt.lower():
                response_text = custom_resp
                break

        return VisionAnalysisResult(
            text=response_text,
            description=response_text,
            model=self.model,
            visual_elements=[{"type": "window", "name": "Editor"}],
            is_error=False,
        )

    @property
    def call_count(self) -> int:
        return len(self.call_history)
