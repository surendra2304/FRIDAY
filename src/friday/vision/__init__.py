# -*- coding: utf-8 -*-
"""Vision Provider package for FRIDAY Multimodal Analysis."""

from friday.vision.base import BaseVisionProvider, VisionAnalysisResult
from friday.vision.gemini_vision import GeminiVisionProvider, validate_image_data
from friday.vision.mock_vision import MockVisionProvider
from friday.vision.screen_base import BaseScreenCaptureProvider, ScreenSnapshot
from friday.vision.windows_screen import WindowsScreenCaptureProvider
from friday.vision.mock_screen import MockScreenCaptureProvider, create_synthetic_png
from friday.vision.screen_context import ScreenContext
from friday.vision.screen_analyzer import ScreenAnalyzer, DEFAULT_ANALYSIS_PROMPT

__all__ = [
    "BaseVisionProvider",
    "VisionAnalysisResult",
    "GeminiVisionProvider",
    "MockVisionProvider",
    "validate_image_data",
    "BaseScreenCaptureProvider",
    "ScreenSnapshot",
    "WindowsScreenCaptureProvider",
    "MockScreenCaptureProvider",
    "create_synthetic_png",
    "ScreenContext",
    "ScreenAnalyzer",
    "DEFAULT_ANALYSIS_PROMPT",
]
