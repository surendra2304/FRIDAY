"""Controlled background screen awareness controller.

Orchestrates periodic screen captures, enforces throttle windows, filters unchanged screens
with ScreenChangeDetector, and performs request deduplication to avoid redundant Gemini calls.
"""

import time
from datetime import datetime, timezone
from typing import Any

from friday.core.config import get_settings
from friday.core.logging import get_logger
from friday.vision.base import BaseVisionProvider
from friday.vision.change_detector import ScreenChangeDetector
from friday.vision.screen_analyzer import ScreenAnalyzer
from friday.vision.screen_base import BaseScreenCaptureProvider
from friday.vision.screen_context import ScreenContext

logger = get_logger("vision.screen_awareness")


class ScreenAwarenessController:
    """Controller managing controlled screen awareness, rate throttling, and deduplication."""

    def __init__(
        self,
        capture_provider: BaseScreenCaptureProvider | None = None,
        vision_provider: BaseVisionProvider | None = None,
        enabled: bool | None = None,
        interval_seconds: float | None = None,
        change_threshold: float | None = None,
    ) -> None:
        settings = get_settings()
        self.enabled = getattr(settings, "screen_aware", False) if enabled is None else enabled
        self.interval_seconds = getattr(settings, "screen_interval_seconds", 10.0) if interval_seconds is None else interval_seconds
        self.change_threshold = getattr(settings, "screen_change_threshold", 0.05) if change_threshold is None else change_threshold

        self._analyzer = ScreenAnalyzer(
            capture_provider=capture_provider,
            vision_provider=vision_provider,
        )
        self._change_detector = ScreenChangeDetector(change_threshold=self.change_threshold)

        self.last_capture_time: float | None = None
        self.last_analysis_time: float | None = None
        self.last_context: ScreenContext | None = None
        self.total_captures_evaluated: int = 0
        self.total_gemini_calls: int = 0
        self.total_unchanged_suppressed: int = 0

    def get_status(self) -> dict[str, Any]:
        """Return safe screen awareness operational status."""
        return {
            "enabled": self.enabled,
            "interval_seconds": self.interval_seconds,
            "change_threshold": self.change_threshold,
            "last_capture_time": datetime.fromtimestamp(self.last_capture_time, tz=timezone.utc).isoformat() if self.last_capture_time else None,
            "last_analysis_time": datetime.fromtimestamp(self.last_analysis_time, tz=timezone.utc).isoformat() if self.last_analysis_time else None,
            "total_captures": self.total_captures_evaluated,
            "total_gemini_calls": self.total_gemini_calls,
            "total_suppressed": self.total_unchanged_suppressed,
        }

    def process_tick(
        self,
        force: bool = False,
        display: str = "primary",
        user_query: str | None = None,
    ) -> ScreenContext | None:
        """Process an awareness tick.

        Returns:
            ScreenContext if screen changed and analysis was performed.
            None if awareness is OFF, capture is throttled, or screen is unchanged.
        """
        if not self.enabled and not force:
            return None

        now = time.time()

        # 1. Throttling check (unless forced by user)
        if not force and self.last_capture_time is not None:
            elapsed = now - self.last_capture_time
            if elapsed < self.interval_seconds:
                return None

        self.last_capture_time = now
        self.total_captures_evaluated += 1

        # 2. Capture screenshot
        capture_prov = self._analyzer._get_capture_provider()
        snapshot = capture_prov.capture_screen(display=display)
        if snapshot.is_error or not snapshot.image_data:
            logger.warning(f"Screen awareness capture failed: {snapshot.error_message}")
            return None

        # 3. Change detection / deduplication check
        has_changed, diff_ratio = self._change_detector.evaluate_change(snapshot.image_data)

        if not has_changed and not force:
            self.total_unchanged_suppressed += 1
            logger.debug(f"Screen unchanged (diff={diff_ratio:.4f} < {self.change_threshold}); suppressed Gemini call.")
            return None

        # 4. Perform visual analysis via Gemini
        self.last_analysis_time = now
        self.total_gemini_calls += 1

        vision_prov = self._analyzer._get_vision_provider()
        from friday.vision.screen_analyzer import DEFAULT_ANALYSIS_PROMPT
        prompt = DEFAULT_ANALYSIS_PROMPT
        if user_query and user_query.strip():
            prompt = f"{DEFAULT_ANALYSIS_PROMPT}\n\nUser Question: {user_query.strip()}"

        result = vision_prov.analyze_image(
            image_data=snapshot.image_data,
            mime_type=snapshot.mime_type,
            prompt=prompt,
        )

        context = ScreenContext(
            summary=result.text.strip() if result.text else "No content detected.",
            width=snapshot.width,
            height=snapshot.height,
            display_id=display,
            captured_at=snapshot.captured_at,
            is_error=result.is_error,
            error_message=result.error_message,
        )
        self.last_context = context
        return context
