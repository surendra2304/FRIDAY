# -*- coding: utf-8 -*-
"""Safe built-in tool for capturing a desktop screen snapshot without OS actions or raw image logging."""

from typing import Any, Optional
from friday.core.config import get_settings
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool
from friday.vision.screen_base import BaseScreenCaptureProvider, ScreenSnapshot
from friday.vision.windows_screen import WindowsScreenCaptureProvider
from friday.vision.mock_screen import MockScreenCaptureProvider


class ScreenSnapshotTool(BaseTool):
    """SAFE Tool to capture a desktop screenshot snapshot and return dimensions and metadata."""

    name = "get_screen_snapshot"
    description = "Capture a desktop screenshot and return screen dimensions, display ID, and timestamp safely."
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "display": {
                "type": "string",
                "description": "Target display: 'primary', 'virtual', or numeric display index",
            }
        },
        "required": [],
    }

    def __init__(
        self,
        provider: Optional[BaseScreenCaptureProvider] = None,
    ) -> None:
        super().__init__()
        self._provider = provider
        self.last_snapshot: Optional[ScreenSnapshot] = None

    def _get_provider(self) -> BaseScreenCaptureProvider:
        """Resolve active screen capture provider based on settings or injection."""
        if self._provider is not None:
            return self._provider

        settings = get_settings()
        prov_type = getattr(settings, "screen_capture_provider", "windows").lower()
        if prov_type == "mock":
            return MockScreenCaptureProvider()
        return WindowsScreenCaptureProvider()

    def execute(self, display: str = "primary", **kwargs: Any) -> ToolResult:
        """Execute screen capture and return safe summary without exposing raw image data in output."""
        try:
            provider = self._get_provider()
            snapshot = provider.capture_screen(display=display)
            self.last_snapshot = snapshot

            if snapshot.is_error:
                return ToolResult(
                    name=self.name,
                    content=f"Screen capture failed: {snapshot.error_message}",
                    is_error=True,
                    safety_level=self.safety_level,
                )

            meta = snapshot.to_dict()
            summary = (
                f"Screen snapshot captured successfully.\n"
                f"Display: {meta['display_id']}\n"
                f"Resolution: {meta['width']}x{meta['height']}\n"
                f"Format: {meta['mime_type']}\n"
                f"Payload size: {meta['size_bytes']} bytes\n"
                f"Timestamp: {meta['captured_at']}"
            )
            return ToolResult(
                name=self.name,
                content=summary,
                is_error=False,
                safety_level=self.safety_level,
            )

        except Exception as e:
            return ToolResult(
                name=self.name,
                content=f"Screen capture encountered an unexpected error: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )
