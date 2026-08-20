# -*- coding: utf-8 -*-
"""Base interfaces and data structures for FRIDAY Vision Provider subsystem."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class VisionAnalysisResult:
    """Structured response container for visual image/screen analysis."""

    text: str
    description: Optional[str] = None
    visual_elements: List[Dict[str, Any]] = field(default_factory=list)
    model: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    is_error: bool = False
    error_message: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert analysis result to safe dictionary."""
        return {
            "text": self.text,
            "description": self.description,
            "visual_elements": self.visual_elements,
            "model": self.model,
            "created_at": self.created_at.isoformat(),
            "is_error": self.is_error,
            "error_message": self.error_message,
        }


class BaseVisionProvider(ABC):
    """Abstract interface for multimodal image analysis providers."""

    @abstractmethod
    def analyze_image(
        self,
        image_data: bytes,
        mime_type: str = "image/png",
        prompt: str = "Describe what is visible in this image in detail.",
        **kwargs: Any,
    ) -> VisionAnalysisResult:
        """Analyze raw image bytes with a guiding prompt.

        Args:
            image_data: Raw image bytes (PNG, JPEG, WEBP).
            mime_type: MIME type of the image.
            prompt: Question or guiding prompt for analysis.
            **kwargs: Provider-specific overrides (temperature, max_tokens, etc.).

        Returns:
            VisionAnalysisResult containing structured visual observations.
        """
        pass
