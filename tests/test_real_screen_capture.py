# -*- coding: utf-8 -*-
"""Real hardware manual verification test for Phase 6.2 Windows Screen Capture.

Tests actual Windows GDI desktop capture and validates PNG encoding and metadata.

Run manually:
    python tests/test_real_screen_capture.py
"""

import sys
import pytest

# Mark as manual hardware/live test
pytestmark = pytest.mark.hardware

from friday.vision.windows_screen import WindowsScreenCaptureProvider
from friday.tools.builtin.screen_snapshot import ScreenSnapshotTool


def test_real_windows_screen_capture():
    """Verify live Windows desktop capture on physical machine."""
    print("\n==================================================")
    print("REAL WINDOWS SCREEN CAPTURE MANUAL TEST (PHASE 6.2)")
    print("==================================================")

    provider = WindowsScreenCaptureProvider()

    # 1. Enumerate displays
    displays = provider.list_displays()
    print(f"Detected {len(displays)} display configuration(s):")
    for d in displays:
        print(f"  - [{d['id']}] {d['width']}x{d['height']} (primary: {d['is_primary']})")

    assert len(displays) >= 1, "At least one display must be detected"

    # 2. Capture primary display
    print("\nCapturing primary display screenshot...")
    snapshot = provider.capture_screen(display="primary")

    print(f"Capture Status: {'ERROR' if snapshot.is_error else 'SUCCESS'}")
    print(f"Display       : {snapshot.display_id}")
    print(f"Dimensions    : {snapshot.width}x{snapshot.height}")
    print(f"MIME Type     : {snapshot.mime_type}")
    print(f"Payload Size  : {len(snapshot.image_data)} bytes")
    print(f"Captured At   : {snapshot.captured_at.isoformat()}")

    assert snapshot.is_error is False, f"Screen capture failed: {snapshot.error_message}"
    assert snapshot.width > 0 and snapshot.height > 0, "Dimensions must be positive"
    assert snapshot.image_data.startswith(b"\x89PNG"), "Image data must be valid PNG"
    assert len(snapshot.image_data) > 1000, "PNG payload must contain real image content"

    # 3. Test via SAFE Tool
    print("\nTesting get_screen_snapshot Tool...")
    tool = ScreenSnapshotTool(provider=provider)
    res = tool.execute(display="primary")

    print(f"Tool is_error: {res.is_error}")
    print(f"Tool content:\n{res.content}")
    assert res.is_error is False
    assert "Screen snapshot captured successfully" in res.content

    print("\n[PASS] Real Windows Screen Capture verified successfully.")


if __name__ == "__main__":
    test_real_windows_screen_capture()
