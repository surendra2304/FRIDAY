# -*- coding: utf-8 -*-
"""Mock screen capture provider for deterministic offline testing and fixture isolation."""

import struct
from typing import Any, Dict, List, Optional
import zlib

from friday.vision.screen_base import BaseScreenCaptureProvider, ScreenSnapshot


def create_synthetic_png(width: int = 64, height: int = 64, color: tuple = (0, 150, 255)) -> bytes:
    """Create valid PNG bytes in memory without external dependencies."""
    r, g, b = color
    raw_rows = []
    for _ in range(height):
        row = bytearray([0])
        for _ in range(width):
            row.extend([r, g, b, 255])
        raw_rows.append(bytes(row))

    compressed = zlib.compress(b"".join(raw_rows), level=1)
    png = bytearray(b"\x89PNG\r\n\x1a\n")
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png.extend(struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr + struct.pack(">I", zlib.crc32(b"IHDR" + ihdr) & 0xFFFFFFFF))
    png.extend(struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF))
    png.extend(struct.pack(">I", 0) + b"IEND" + struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF))
    return bytes(png)


class MockScreenCaptureProvider(BaseScreenCaptureProvider):
    """Mock screen capture provider returning synthetic test snapshots."""

    def __init__(
        self,
        width: int = 1920,
        height: int = 1080,
        synthetic_color: tuple = (50, 100, 200),
    ) -> None:
        self.width = width
        self.height = height
        self.synthetic_color = synthetic_color
        self.call_history: List[Dict[str, Any]] = []
        self.should_fail: bool = False
        self.failure_error: str = "Mock screen capture simulated error"

    def list_displays(self) -> List[Dict[str, Any]]:
        """Return synthetic display list."""
        return [
            {"id": "primary", "index": 0, "is_primary": True, "width": self.width, "height": self.height},
            {"id": "secondary", "index": 1, "is_primary": False, "width": 1920, "height": 1080},
        ]

    def capture_screen(
        self,
        display: str = "primary",
        **kwargs: Any,
    ) -> ScreenSnapshot:
        """Return synthetic ScreenSnapshot without OS interaction."""
        self.call_history.append({"display": display, "kwargs": kwargs})

        if self.should_fail:
            return ScreenSnapshot(
                image_data=b"",
                mime_type="image/png",
                display_id=display,
                is_error=True,
                error_message=self.failure_error,
            )

        png_bytes = create_synthetic_png(self.width, self.height, self.synthetic_color)
        return ScreenSnapshot(
            image_data=png_bytes,
            mime_type="image/png",
            width=self.width,
            height=self.height,
            display_id=display,
            is_error=False,
        )
