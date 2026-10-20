"""Unit tests for Windows 11 Desktop Screen Freshness Detection and UI Automation Grounding."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from friday.desktop.grounding import DesktopScreenGrounding
from friday.vision.screen_base import ScreenSnapshot


def test_desktop_screen_grounding_initial_and_subsequent_eval():
    """Verify DesktopScreenGrounding detects image change and evaluates difference ratio."""
    grounding = DesktopScreenGrounding(change_threshold=0.05)

    mock_provider = MagicMock()
    grounding._capture_provider = mock_provider

    # 1. First observation (must declare has_changed=True)
    img1 = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
    mock_provider.capture_screen.return_value = ScreenSnapshot(
        image_data=img1,
        width=1920,
        height=1080,
    )

    with patch("friday.desktop.grounding.get_active_window_context") as mock_win_ctx:
        mock_win_ctx.return_value = {
            "title": "Visual Studio Code - FRIDAY",
            "process_name": "Code.exe",
            "url": "https://github.com",
            "is_active": True,
        }

        has_changed, diff_ratio, win_ctx = grounding.check_screen_freshness()
        assert has_changed is True
        assert win_ctx["process_name"] == "Code.exe"
        prompt = grounding.format_grounding_context()
        assert "app=Code.exe" in prompt
        assert "Visual Studio Code" in prompt
        assert "url='https://github.com'" in prompt

        # 2. Second observation with identical bytes (must declare has_changed=False)
        has_changed2, diff_ratio2, _ = grounding.check_screen_freshness()
        assert has_changed2 is False
        assert diff_ratio2 == 0.0

        # 3. Third observation with substantially different bytes
        img2 = b"\x89PNG\r\n\x1a\n" + b"\xff" * 200
        mock_provider.capture_screen.return_value = ScreenSnapshot(
            image_data=img2,
            width=1920,
            height=1080,
        )
        has_changed3, diff_ratio3, _ = grounding.check_screen_freshness()
        assert has_changed3 is True
        assert diff_ratio3 > 0.05


def test_desktop_screen_grounding_handles_error_snapshots():
    """Verify grounding handles snapshot failures gracefully without raising."""
    grounding = DesktopScreenGrounding()
    mock_provider = MagicMock()
    mock_provider.capture_screen.return_value = ScreenSnapshot(
        image_data=b"",
        is_error=True,
        error_message="Capture failed",
    )
    grounding._capture_provider = mock_provider

    has_changed, diff_ratio, win_ctx = grounding.check_screen_freshness()
    assert has_changed is False
    assert diff_ratio == 0.0


def test_desktop_screen_grounding_provider_init_and_fallbacks():
    """Verify capture provider initialization on win32 and mock fallback."""
    grounding = DesktopScreenGrounding()
    prov = grounding._get_capture_provider()
    assert prov is not None


def test_format_grounding_context_idle():
    """Verify format_grounding_context formats idle state when context is empty."""
    grounding = DesktopScreenGrounding()
    grounding._last_context = {}
    with patch("friday.desktop.grounding.get_active_window_context", return_value={}):
        assert grounding.format_grounding_context() == "active_screen=idle | delta=0.00"
