"""Windows 11 Native Screen Freshness Detection and UI Automation Grounding.

Provides low-latency perceptual delta calculation and foreground window context
grounding for the desktop companion loop.
"""

from __future__ import annotations

import sys
from typing import Any

from friday.core.logging import get_logger
from friday.vision.active_context import get_active_window_context
from friday.vision.change_detector import ScreenChangeDetector

logger = get_logger("desktop.grounding")


class DesktopScreenGrounding:
    """Manages screen freshness evaluation and foreground UI automation context."""

    def __init__(self, change_threshold: float = 0.05) -> None:
        self.change_threshold = change_threshold
        self.detector = ScreenChangeDetector(change_threshold=self.change_threshold)
        self._capture_provider: Any | None = None
        self._last_context: dict[str, Any] = {}
        self._last_diff_ratio: float = 0.0
        self._last_has_changed: bool = True

    def _get_capture_provider(self) -> Any:
        if self._capture_provider is None:
            if sys.platform == "win32":
                try:
                    from friday.vision.windows_screen import WindowsScreenCaptureProvider
                    self._capture_provider = WindowsScreenCaptureProvider()
                except Exception as exc:
                    logger.debug("Failed to initialize WindowsScreenCaptureProvider: %s", exc)
            if self._capture_provider is None:
                try:
                    from friday.vision.mock_screen import MockScreenCaptureProvider
                    self._capture_provider = MockScreenCaptureProvider()
                except Exception:
                    self._capture_provider = None
        return self._capture_provider

    def check_screen_freshness(self) -> tuple[bool, float, dict[str, Any]]:
        """Evaluate if the desktop screen has changed and capture current window context.

        Returns:
            Tuple of (has_changed: bool, diff_ratio: float, window_context: dict).
        """
        provider = self._get_capture_provider()
        window_ctx = get_active_window_context()
        self._last_context = window_ctx

        if provider is None:
            return False, 0.0, window_ctx

        try:
            snapshot = provider.capture_screen(display="primary")
            if snapshot.is_error or not snapshot.image_data:
                return False, 0.0, window_ctx

            has_changed, diff_ratio = self.detector.evaluate_change(snapshot.image_data)
            self._last_has_changed = has_changed
            self._last_diff_ratio = diff_ratio
            return has_changed, diff_ratio, window_ctx
        except Exception as exc:
            logger.debug("Screen freshness evaluation error: %s", exc)
            return False, 0.0, window_ctx

    def format_grounding_context(self) -> str:
        """Format screen freshness and window context into a concise ambient string."""
        ctx = self._last_context or get_active_window_context()
        title = ctx.get("title", "")
        proc = ctx.get("process_name", "")
        url = ctx.get("url")
        status_parts = []
        if proc:
            status_parts.append(f"app={proc}")
        if title:
            status_parts.append(f"window='{title}'")
        if url:
            status_parts.append(f"url='{url}'")
        if not title and not proc and not url:
            return f"active_screen=idle | delta={self._last_diff_ratio:.2f}"
        status_parts.append(f"delta={self._last_diff_ratio:.2f}")
        return " | ".join(status_parts)
