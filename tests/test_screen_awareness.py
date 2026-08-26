# -*- coding: utf-8 -*-
"""Deterministic unit tests for Multimodal Screen Perception.4 Controlled Screen Awareness & Deduplication."""

import time
from unittest import mock
import pytest

from friday.vision.change_detector import ScreenChangeDetector, compute_image_difference_ratio
from friday.vision.mock_screen import MockScreenCaptureProvider, create_synthetic_png
from friday.vision.mock_vision import MockVisionProvider
from friday.vision.screen_awareness import ScreenAwarenessController


def test_change_detector_exact_and_modified_images():
    """Verify ScreenChangeDetector detects byte changes and filters identical images."""
    detector = ScreenChangeDetector(change_threshold=0.05)

    img_blue = create_synthetic_png(width=64, height=64, color=(0, 0, 255))
    img_red = create_synthetic_png(width=64, height=64, color=(255, 0, 0))

    # 1. First observation is always declared changed
    changed, diff = detector.evaluate_change(img_blue)
    assert changed is True
    assert diff == 1.0

    # 2. Repeated exact image is declared unchanged (0.0 diff, 0 API calls)
    changed, diff = detector.evaluate_change(img_blue)
    assert changed is False
    assert diff == 0.0

    # 3. New drastically different image triggers change
    changed, diff = detector.evaluate_change(img_red)
    assert changed is True
    assert diff > 0.05


def test_screen_awareness_off_by_default():
    """Verify ScreenAwarenessController does zero captures and zero Gemini calls when disabled."""
    mock_cap = MockScreenCaptureProvider()
    mock_vis = MockVisionProvider()

    controller = ScreenAwarenessController(
        capture_provider=mock_cap,
        vision_provider=mock_vis,
        enabled=False,  # Explicitly default OFF
    )

    ctx = controller.process_tick()
    assert ctx is None
    assert len(mock_cap.call_history) == 0
    assert len(mock_vis.call_history) == 0
    assert controller.total_gemini_calls == 0


def test_screen_awareness_throttling_and_unchanged_suppression():
    """Verify periodic awareness throttles interval and suppresses unchanged screens."""
    mock_cap = MockScreenCaptureProvider()
    mock_vis = MockVisionProvider(default_response="Observation: IDE active.")

    controller = ScreenAwarenessController(
        capture_provider=mock_cap,
        vision_provider=mock_vis,
        enabled=True,
        interval_seconds=10.0,
        change_threshold=0.05,
    )

    # Tick 1: First capture -> Screen changed -> 1 Gemini call
    ctx1 = controller.process_tick()
    assert ctx1 is not None
    assert controller.total_captures_evaluated == 1
    assert controller.total_gemini_calls == 1

    # Tick 2: Immediate next tick (< 10s) -> Throttled -> 0 captures, 0 Gemini calls
    ctx2 = controller.process_tick()
    assert ctx2 is None
    assert controller.total_captures_evaluated == 1
    assert controller.total_gemini_calls == 1

    # Tick 3: Advance time beyond 10s -> Capture executed, but screen unchanged -> Suppressed Gemini call
    controller.last_capture_time = time.time() - 15.0  # Simulate 15s passed
    ctx3 = controller.process_tick()
    assert ctx3 is None  # Suppressed because synthetic image from mock_cap didn't change
    assert controller.total_captures_evaluated == 2
    assert controller.total_gemini_calls == 1
    assert controller.total_unchanged_suppressed == 1

    # Tick 4: Change mock screen color -> Advance time -> Triggers new Gemini call
    mock_cap.synthetic_color = (255, 200, 50)
    controller.last_capture_time = time.time() - 15.0
    ctx4 = controller.process_tick()
    assert ctx4 is not None
    assert controller.total_captures_evaluated == 3
    assert controller.total_gemini_calls == 2


def test_screen_awareness_forced_override():
    """Verify force=True bypasses throttling and change suppression."""
    mock_cap = MockScreenCaptureProvider()
    mock_vis = MockVisionProvider(default_response="Forced check observation.")

    controller = ScreenAwarenessController(
        capture_provider=mock_cap,
        vision_provider=mock_vis,
        enabled=False,  # Disabled in background
    )

    # Force tick bypasses enabled=False
    ctx = controller.process_tick(force=True, user_query="Check screen now")
    assert ctx is not None
    assert controller.total_gemini_calls == 1
    assert "User Question: Check screen now" in mock_vis.call_history[0]["prompt"]


def test_screen_awareness_status_reporting():
    """Verify get_status returns safe telemetry without raw images."""
    controller = ScreenAwarenessController(enabled=False, interval_seconds=15.0)
    status = controller.get_status()

    assert status["enabled"] is False
    assert status["interval_seconds"] == 15.0
    assert status["total_gemini_calls"] == 0
    assert "last_capture_time" in status
    assert "image_data" not in status
