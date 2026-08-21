# -*- coding: utf-8 -*-
"""Real hardware manual verification test for Windows Screen Capture.

Test Type: HARDWARE / LIVE

Tests actual Windows GDI desktop capture and validates PNG encoding and metadata.
"""

import sys
import pytest

# Mark as hardware test (opt-in only via pytest -m hardware)
pytestmark = [pytest.mark.hardware, pytest.mark.live]

from friday.vision.windows_screen import WindowsScreenCaptureProvider
from friday.tools.builtin.screen_snapshot import ScreenSnapshotTool


def test_hardware_windows_screen_capture():
    """Verify live Windows desktop capture on physical machine."""
    if sys.platform != "win32":
        pytest.skip("Windows screen capture requires Win32 platform.")

    provider = WindowsScreenCaptureProvider()

    # 1. Enumerate displays
    displays = provider.list_displays()
    if not displays:
        pytest.skip("No physical or virtual displays detected.")

    assert len(displays) >= 1, "At least one display must be detected"

    # 2. Capture primary display
    snapshot = provider.capture_screen(display="primary")
    assert snapshot.is_error is False, f"Screen capture failed: {snapshot.error_message}"
    assert snapshot.width > 0 and snapshot.height > 0, "Dimensions must be positive"
    assert snapshot.image_data.startswith(b"\x89PNG"), "Image data must be valid PNG"
    assert len(snapshot.image_data) > 1000, "PNG payload must contain real image content"

    # 3. Test via SAFE Tool
    tool = ScreenSnapshotTool(capture_provider=provider)
    res = tool.execute(display="primary")
    assert res.is_error is False
    assert "Screen snapshot captured successfully" in res.content
