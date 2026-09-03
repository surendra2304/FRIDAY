"""Safe built-in tool for capturing a desktop screen snapshot without OS actions or raw image logging."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from friday.core.config import get_settings
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

if TYPE_CHECKING:
    from friday.vision.screen_base import BaseScreenCaptureProvider, ScreenSnapshot


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
            },
            "query": {
                "type": "string",
                "description": "Optional question or visual analysis query (e.g. 'What is on my screen?', 'What error is visible?')",
            },
            "save_path": {
                "type": "string",
                "description": "Optional file path where the screenshot image should be saved to disk (e.g. 'screenshot.png').",
            },
        },
        "required": [],
    }

    def __init__(
        self,
        capture_provider: BaseScreenCaptureProvider | None = None,
        vision_provider: Any | None = None,
        provider: BaseScreenCaptureProvider | None = None,
    ) -> None:
        super().__init__()
        self._capture_provider = capture_provider or provider
        self._vision_provider = vision_provider
        self.last_snapshot: ScreenSnapshot | None = None
        self.last_context: Any | None = None

    def execute(self, display: str = "primary", query: str | None = None, **kwargs: Any) -> ToolResult:
        """Execute screen capture and optional multimodal vision analysis."""
        try:
            # 1. If query is provided or vision_provider is explicitly injected, perform multimodal analysis
            if query or self._vision_provider is not None:
                from friday.vision.screen_analyzer import ScreenAnalyzer

                analyzer = ScreenAnalyzer(
                    capture_provider=self._capture_provider,
                    vision_provider=self._vision_provider,
                )

                context = analyzer.analyze_current_screen(display=display, user_query=query, **kwargs)
                self.last_context = context

                if context.is_error:
                    return ToolResult(
                        name=self.name,
                        content=f"Screen observation failed: {context.error_message}",
                        is_error=True,
                        safety_level=self.safety_level,
                    )

                output = (
                    f"Screen Snapshot ({context.width}x{context.height}, Display: {context.display_id}):\n"
                    f"{context.summary}"
                )
                return ToolResult(
                    name=self.name,
                    content=output,
                    is_error=False,
                    safety_level=self.safety_level,
                )

            # 2. Otherwise perform fast safe capture and return metadata summary
            from friday.vision.mock_screen import MockScreenCaptureProvider
            from friday.vision.windows_screen import WindowsScreenCaptureProvider

            provider = self._capture_provider
            if provider is None:
                settings = get_settings()
                prov_type = getattr(settings, "screen_capture_provider", "windows").lower()
                provider = MockScreenCaptureProvider() if prov_type == "mock" else WindowsScreenCaptureProvider()

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

            # Optional save to disk
            target_path = kwargs.get("save_path")
            if target_path and hasattr(snapshot, "data_bytes") and snapshot.data_bytes:
                from pathlib import Path
                sp = Path(target_path).resolve()
                sp.parent.mkdir(parents=True, exist_ok=True)
                with open(sp, "wb") as f:
                    f.write(snapshot.data_bytes)
                summary += f"\nSaved to: {sp}"

            return ToolResult(
                name=self.name,
                content=summary,
                is_error=False,
                safety_level=self.safety_level,
            )

        except Exception as e:
            return ToolResult(
                name=self.name,
                content=f"Screen snapshot encountered an unexpected error: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )
