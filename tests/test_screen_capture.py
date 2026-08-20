# -*- coding: utf-8 -*-
"""Deterministic unit tests for Phase 6.2 Windows Screen Capture and ScreenSnapshotTool."""

from unittest import mock
import pytest

from friday.core.types import SafetyLevel
from friday.vision.screen_base import BaseScreenCaptureProvider, ScreenSnapshot
from friday.vision.mock_screen import MockScreenCaptureProvider, create_synthetic_png
from friday.vision.windows_screen import WindowsScreenCaptureProvider
from friday.tools.builtin.screen_snapshot import ScreenSnapshotTool


def test_screen_snapshot_dataclass():
    """Verify ScreenSnapshot serializes to dict safely without exposing raw image bytes."""
    png_data = create_synthetic_png(width=100, height=50)
    snapshot = ScreenSnapshot(
        image_data=png_data,
        mime_type="image/png",
        width=100,
        height=50,
        display_id="primary",
    )

    d = snapshot.to_dict()
    assert d["mime_type"] == "image/png"
    assert d["width"] == 100
    assert d["height"] == 50
    assert d["display_id"] == "primary"
    assert d["size_bytes"] == len(png_data)
    assert d["is_error"] is False
    assert "image_data" not in d  # Crucial: raw bytes not leaked into dict

    repr_str = repr(snapshot)
    assert "100x50" in repr_str
    assert "display='primary'" in repr_str


def test_mock_screen_capture_provider():
    """Verify MockScreenCaptureProvider returns valid PNGs and handles mock errors."""
    mock_prov = MockScreenCaptureProvider(width=800, height=600)

    # 1. Enumerate displays
    displays = mock_prov.list_displays()
    assert len(displays) >= 1
    assert displays[0]["id"] == "primary"
    assert displays[0]["is_primary"] is True

    # 2. Capture primary
    snap = mock_prov.capture_screen("primary")
    assert snap.is_error is False
    assert snap.width == 800
    assert snap.height == 600
    assert snap.image_data.startswith(b"\x89PNG")
    assert len(mock_prov.call_history) == 1

    # 3. Simulate failure
    mock_prov.should_fail = True
    snap_err = mock_prov.capture_screen("primary")
    assert snap_err.is_error is True
    assert "Mock screen capture simulated error" in snap_err.error_message


def test_screen_snapshot_tool_safe_execution():
    """Verify ScreenSnapshotTool is classified as SAFE and executes without raw image output."""
    mock_prov = MockScreenCaptureProvider(width=1280, height=720)
    tool = ScreenSnapshotTool(provider=mock_prov)

    assert tool.name == "get_screen_snapshot"
    assert tool.safety_level == SafetyLevel.SAFE

    # Execute tool
    res = tool.execute(display="primary")
    assert res.is_error is False
    assert "Screen snapshot captured successfully" in res.content
    assert "1280x720" in res.content
    assert tool.last_snapshot is not None
    assert tool.last_snapshot.width == 1280


def test_screen_snapshot_tool_failure_handling():
    """Verify ScreenSnapshotTool returns graceful ToolResult.fail on provider error."""
    mock_prov = MockScreenCaptureProvider()
    mock_prov.should_fail = True
    tool = ScreenSnapshotTool(provider=mock_prov)

    res = tool.execute(display="primary")
    assert res.is_error is True
    assert "Screen capture failed" in res.content


def test_windows_screen_capture_gdi_cleanup_on_error():
    """Verify WindowsScreenCaptureProvider cleans up GDI handles if an exception occurs."""
    prov = WindowsScreenCaptureProvider()

    with mock.patch.object(prov._user32, "GetSystemMetrics", return_value=-1):
        snap = prov.capture_screen("primary")
        assert snap.is_error is True
        assert "Invalid display dimensions detected" in snap.error_message
