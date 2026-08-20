# -*- coding: utf-8 -*-
"""Real manual verification script for Phase 6.1 Vision Foundation.

This test requires a valid Gemini API key and sends real image bytes (synthetically generated
PNG with geometric shapes/text) to the official Google Gemini multimodal API using GeminiVisionProvider.

Run manually:
    python tests/test_real_vision.py
"""

import sys
import os
import pytest
from pathlib import Path

# Mark as manual hardware/live test
pytestmark = pytest.mark.hardware

from friday.core.config import get_settings
from friday.core.logging import setup_logging, get_logger
from friday.vision.gemini_vision import GeminiVisionProvider
from friday.auth.credential_pool import credential_pool

logger = get_logger("test.real_vision")


def _create_synthetic_test_png() -> bytes:
    """Generate a valid, compact PNG in-memory without external heavy dependencies."""
    import struct
    import zlib

    width, height = 64, 64
    # Create raw RGBA image data: red square with white border
    raw_rows = []
    for y in range(height):
        row = bytearray([0])  # filter type 0 (None)
        for x in range(width):
            if x < 4 or x >= 60 or y < 4 or y >= 60:
                row.extend([255, 255, 255, 255])  # White border
            elif 20 <= x <= 44 and 20 <= y <= 44:
                row.extend([0, 180, 255, 255])    # Cyan square in center
            else:
                row.extend([30, 30, 30, 255])     # Dark background
        raw_rows.append(bytes(row))

    raw_data = b"".join(raw_rows)
    compressed = zlib.compress(raw_data)

    png = bytearray(b"\x89PNG\r\n\x1a\n")
    # IHDR
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    png.extend(struct.pack(">I", len(ihdr_data)))
    png.extend(b"IHDR")
    png.extend(ihdr_data)
    png.extend(struct.pack(">I", zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF))

    # IDAT
    png.extend(struct.pack(">I", len(compressed)))
    png.extend(b"IDAT")
    png.extend(compressed)
    png.extend(struct.pack(">I", zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF))

    # IEND
    png.extend(struct.pack(">I", 0))
    png.extend(b"IEND")
    png.extend(struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF))

    return bytes(png)


def test_real_gemini_vision_analysis():
    """Manual real test executing live Gemini multimodal visual analysis."""
    setup_logging(level="DEBUG")
    settings = get_settings()

    api_key = credential_pool.get_active_key() or settings.gemini_api_key or settings.llm_api_key
    if not api_key:
        print("\n[SKIP] No real Gemini API key configured in environment or .env. Skipping live vision test.")
        return

    print("==================================================")
    print("REAL GEMINI VISION FOUNDATION TEST (PHASE 6.1)")
    print("==================================================")
    print(f"Active Model: {settings.vision_model}")
    print(f"Active Project: {credential_pool.get_active_label()}")

    provider = GeminiVisionProvider(credential_pool=credential_pool, model=settings.vision_model)

    image_bytes = _create_synthetic_test_png()
    print(f"Generated synthetic test image ({len(image_bytes)} bytes, PNG).")

    prompt = "Describe the colors and geometric shapes visible in this image concisely."
    print(f"\nSending vision request to Gemini: '{prompt}'...")

    result = provider.analyze_image(image_bytes, mime_type="image/png", prompt=prompt)

    print("\n--- Live Gemini Vision Result ---")
    print(f"Is Error   : {result.is_error}")
    print(f"Model      : {result.model}")
    print(f"Response   :\n{result.text}")
    print("---------------------------------\n")

    assert result.is_error is False, f"Vision request failed: {result.error_message}"
    assert len(result.text) > 0, "Vision response text should not be empty"
    print("[PASS] Real Gemini Vision Foundation test succeeded.")


if __name__ == "__main__":
    test_real_gemini_vision_analysis()
