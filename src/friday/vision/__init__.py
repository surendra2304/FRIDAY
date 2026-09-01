"""Vision Provider package for FRIDAY Multimodal Analysis."""

from friday.vision.action_preparer import (
    ActionPreparationResult,
    GroundedElementTarget,
    GroundingStatus,
    PerceptionActionPreparer,
)
from friday.vision.actions import ActionType, ComputerActionProposal, ProposalBuilder
from friday.vision.active_perception import (
    ActivePerceptionEngine,
    ObservationDecision,
    ObservationNecessity,
)
from friday.vision.base import BaseVisionProvider, VisionAnalysisResult
from friday.vision.cache_manager import (
    CachedObservation,
    PerceptionCacheManager,
    PerceptionCacheTelemetry,
)
from friday.vision.change_detector import (
    ScreenChangeDetector,
    compute_image_difference_ratio,
)
from friday.vision.computer_control import (
    HARD_BLOCKED_INTENTS,
    SAFE_HOTKEY_ALLOWLIST,
    SAFE_KEY_ALLOWLIST,
    ActionExecutionResult,
    ComputerActionExecutor,
    ExecutionStatus,
)
from friday.vision.coordinates import (
    CoordinateTransform,
    DisplayMonitor,
    StaleCoordinateGuard,
)
from friday.vision.detector import (
    DeterministicActionDetector,
    DeterministicActionIntent,
)
from friday.vision.episodic_memory import (
    EpisodicEnvironmentalFact,
    EpisodicEnvironmentalMemoryManager,
    MemoryImportance,
)
from friday.vision.gemini_vision import GeminiVisionProvider, validate_image_data
from friday.vision.mock_screen import MockScreenCaptureProvider, create_synthetic_png
from friday.vision.mock_vision import MockVisionProvider
from friday.vision.openai_vision import OpenAIVisionProvider
from friday.vision.pipeline import (
    MonitorInfo,
    PerceptionPipeline,
    PerceptionResult,
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
from friday.vision.screen_analyzer import DEFAULT_ANALYSIS_PROMPT, ScreenAnalyzer
from friday.vision.screen_awareness import ScreenAwarenessController
from friday.vision.screen_base import BaseScreenCaptureProvider, ScreenSnapshot
from friday.vision.screen_context import ScreenContext
from friday.vision.screen_watcher import ScreenWatcherService
from friday.vision.temporal import (
    EnvironmentalChange,
    EnvironmentalChangeType,
    TemporalEnvironmentTracker,
    TemporalObservation,
)
from friday.vision.ui_elements import BoundingBox, ElementType, UIElement
from friday.vision.vision_memory import (
    VisionMemoryManager,
    redact_sensitive_visual_text,
)
from friday.vision.windows_input_driver import (
    BaseWindowsInputDriver,
    MockWindowsInputDriver,
    WindowsNativeInputDriver,
)
from friday.vision.windows_screen import WindowsScreenCaptureProvider

__all__ = [
    "DEFAULT_ANALYSIS_PROMPT",
    "HARD_BLOCKED_INTENTS",
    "SAFE_HOTKEY_ALLOWLIST",
    "SAFE_KEY_ALLOWLIST",
    "ActionExecutionResult",
    "ActionPreparationResult",
    "ActionType",
    "ActivePerceptionEngine",
    "BaseScreenCaptureProvider",
    "BaseVisionProvider",
    "BaseWindowsInputDriver",
    "BoundingBox",
    "CachedObservation",
    "ComputerActionExecutor",
    "ComputerActionProposal",
    "CoordinateTransform",
    "DeterministicActionDetector",
    "DeterministicActionIntent",
    "DisplayMonitor",
    "ElementType",
    "EnvironmentalChange",
    "EnvironmentalChangeType",
    "EpisodicEnvironmentalFact",
    "EpisodicEnvironmentalMemoryManager",
    "ExecutionStatus",
    "GeminiVisionProvider",
    "GroundedElementTarget",
    "GroundingStatus",
    "LocalRegionPreFilter",
    "MemoryImportance",
    "MockScreenCaptureProvider",
    "MockVisionProvider",
    "MockWindowsInputDriver",
    "MonitorInfo",
    "ObservationDecision",
    "ObservationNecessity",
    "PerceptionActionPreparer",
    "PerceptionCacheManager",
    "PerceptionCacheTelemetry",
    "PerceptionPipeline",
    "PerceptionResult",
    "ProposalBuilder",
    "ROIAnalysisResult",
    "ScreenAnalyzer",
    "ScreenAwarenessController",
    "ScreenChangeDetector",
    "ScreenContext",
    "ScreenSnapshot",
    "StaleCoordinateGuard",
    "TemporalEnvironmentTracker",
    "TemporalObservation",
    "TextDensityLevel",
    "UIElement",
    "VisionAnalysisResult",
    "VisionMemoryManager",
    "VisualDeltaTaskContextFeeder",
    "WindowsNativeInputDriver",
    "WindowsScreenCaptureProvider",
    "compute_image_difference_ratio",
    "create_synthetic_png",
    "crop_image_region",
    "decode_png_to_rgba",
    "encode_rgba_to_png",
    "estimate_local_text_density",
    "redact_sensitive_visual_text",
    "validate_image_data",
]
