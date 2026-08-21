# -*- coding: utf-8 -*-
"""Vision Provider package for FRIDAY Multimodal Analysis."""

from friday.vision.base import BaseVisionProvider, VisionAnalysisResult
from friday.vision.gemini_vision import GeminiVisionProvider, validate_image_data
from friday.vision.mock_vision import MockVisionProvider
from friday.vision.openai_vision import OpenAIVisionProvider
from friday.vision.screen_base import BaseScreenCaptureProvider, ScreenSnapshot
from friday.vision.windows_screen import WindowsScreenCaptureProvider
from friday.vision.mock_screen import MockScreenCaptureProvider, create_synthetic_png
from friday.vision.screen_context import ScreenContext
from friday.vision.screen_analyzer import ScreenAnalyzer, DEFAULT_ANALYSIS_PROMPT
from friday.vision.change_detector import ScreenChangeDetector, compute_image_difference_ratio
from friday.vision.screen_awareness import ScreenAwarenessController
from friday.vision.vision_memory import VisionMemoryManager, redact_sensitive_visual_text
from friday.vision.actions import ActionType, ComputerActionProposal, ProposalBuilder
from friday.vision.computer_control import (
    ActionExecutionResult,
    ComputerActionExecutor,
    ExecutionStatus,
    HARD_BLOCKED_INTENTS,
    SAFE_HOTKEY_ALLOWLIST,
    SAFE_KEY_ALLOWLIST,
)
from friday.vision.windows_input_driver import (
    BaseWindowsInputDriver,
    MockWindowsInputDriver,
    WindowsNativeInputDriver,
)

from friday.vision.ui_elements import BoundingBox, ElementType, UIElement
from friday.vision.temporal import (
    EnvironmentalChange,
    EnvironmentalChangeType,
    TemporalEnvironmentTracker,
    TemporalObservation,
)
from friday.vision.episodic_memory import (
    EpisodicEnvironmentalFact,
    EpisodicEnvironmentalMemoryManager,
    MemoryImportance,
)
from friday.vision.active_perception import (
    ActivePerceptionEngine,
    ObservationDecision,
    ObservationNecessity,
)
from friday.vision.action_preparer import (
    ActionPreparationResult,
    GroundedElementTarget,
    GroundingStatus,
    PerceptionActionPreparer,
)
from friday.vision.cache_manager import (
    CachedObservation,
    PerceptionCacheManager,
    PerceptionCacheTelemetry,
)

from friday.vision.region_filter import (
    LocalRegionPreFilter,
    ROIAnalysisResult,
    TextDensityLevel,
    VisualDeltaTaskContextFeeder,
    crop_image_region,
    decode_png_to_rgba,
    encode_rgba_to_png,
    estimate_local_text_density,
)
from friday.vision.pipeline import (
    MonitorInfo,
    PerceptionPipeline,
    PerceptionResult,
)
from friday.vision.coordinates import (
    CoordinateTransform,
    DisplayMonitor,
    StaleCoordinateGuard,
)

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
    "ScreenChangeDetector",
    "compute_image_difference_ratio",
    "ScreenAwarenessController",
    "VisionMemoryManager",
    "redact_sensitive_visual_text",
    "ActionType",
    "ComputerActionProposal",
    "ProposalBuilder",
    "ComputerActionExecutor",
    "ActionExecutionResult",
    "ExecutionStatus",
    "HARD_BLOCKED_INTENTS",
    "SAFE_KEY_ALLOWLIST",
    "SAFE_HOTKEY_ALLOWLIST",
    "BaseWindowsInputDriver",
    "WindowsNativeInputDriver",
    "MockWindowsInputDriver",
    "BoundingBox",
    "ElementType",
    "UIElement",
    "EnvironmentalChange",
    "EnvironmentalChangeType",
    "TemporalEnvironmentTracker",
    "TemporalObservation",
    "EpisodicEnvironmentalFact",
    "EpisodicEnvironmentalMemoryManager",
    "MemoryImportance",
    "ActivePerceptionEngine",
    "ObservationDecision",
    "ObservationNecessity",
    "PerceptionActionPreparer",
    "ActionPreparationResult",
    "GroundedElementTarget",
    "GroundingStatus",
    "CachedObservation",
    "PerceptionCacheManager",
    "PerceptionCacheTelemetry",
    "LocalRegionPreFilter",
    "ROIAnalysisResult",
    "TextDensityLevel",
    "VisualDeltaTaskContextFeeder",
    "crop_image_region",
    "decode_png_to_rgba",
    "encode_rgba_to_png",
    "estimate_local_text_density",
    "PerceptionPipeline",
    "PerceptionResult",
    "MonitorInfo",
    "CoordinateTransform",
    "DisplayMonitor",
    "StaleCoordinateGuard",
]
