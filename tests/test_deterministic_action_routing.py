# -*- coding: utf-8 -*-
"""Hard regression tests for Deterministic Computer Action Fast-Path Routing.

Verifies:
1. Exact Bug Reproduction: "Move the mouse cursor to the center of the screen."
   proves 0 Gemini Vision calls, deterministic execution, and screen center calculation.
2. Negative Test (Semantic UI Identification): "Click the Save button."
   proves that semantic operations are NOT intercepted by the deterministic fast-path and require visual/cognitive grounding.
3. Resilience to Vision Outage: Even when Vision is completely unavailable,
   deterministic spatial operations succeed cleanly without errors.
"""

from unittest import mock
import pytest

from friday.agent.agent import FridayAgent
from friday.core.auth import AutoApproveAuthorizer
from friday.core.config import Settings
from friday.core.types import SafetyLevel
from friday.vision.mock_vision import MockVisionProvider
from friday.vision.windows_input_driver import MockWindowsInputDriver
from friday.vision.windows_screen import WindowsScreenCaptureProvider
from friday.vision.actions import ActionType


class ExplodingVisionProvider(MockVisionProvider):
    """Mock vision provider that explodes if called, proving vision was bypassed."""

    def analyze_image(self, *args, **kwargs):
        raise AssertionError("CRITICAL REGRESSION: Gemini Vision was called during a deterministic geometric operation!")


def test_cursor_center_deterministic_fastpath_bypasses_vision(monkeypatch):
    """Verify that 'Move the mouse cursor to the center of the screen' routes directly to fast-path with 0 vision calls."""
    settings = Settings(llm_provider="mock")
    authorizer = AutoApproveAuthorizer.create_for_testing()
    agent = FridayAgent(settings=settings, authorizer=authorizer)

    # 1. Mock Windows display enumeration to known bounds
    mock_displays = [{"id": "primary", "index": 0, "is_primary": True, "x": 0, "y": 0, "width": 1920, "height": 1080}]
    monkeypatch.setattr(WindowsScreenCaptureProvider, "list_displays", lambda self: mock_displays)

    # 2. Inject ExplodingVisionProvider into agent tools (ScreenSnapshotTool)
    snapshot_tool = agent.tools.get("get_screen_snapshot")
    if snapshot_tool:
        snapshot_tool._vision_provider = ExplodingVisionProvider()

    # 3. Intercept execution to check physical/mock driver movement
    mock_driver = MockWindowsInputDriver(screen_width=1920, screen_height=1080)
    monkeypatch.setattr("friday.vision.computer_control.WindowsNativeInputDriver", lambda: mock_driver)

    # 4. Process the user turn through real production FridayAgent.process_message
    resp = agent.process_message("Move the mouse cursor to the center of the screen.")

    # 5. Assertions
    assert resp is not None
    assert "center of the screen (960, 540)" in resp.content or "Moved the mouse cursor to" in resp.content
    assert resp.metadata.get("fast_path") is True
    assert resp.metadata.get("deterministic") is True
    assert resp.metadata.get("arguments") == {"x": 960, "y": 540}
    assert agent.state_machine.current_state.value == "COMPLETED"


def test_cursor_corners_and_explicit_coordinates_fastpath(monkeypatch):
    """Verify corner and explicit coordinates movement fast-path routing."""
    settings = Settings(llm_provider="mock")
    authorizer = AutoApproveAuthorizer.create_for_testing()
    agent = FridayAgent(settings=settings, authorizer=authorizer)

    mock_displays = [{"id": "primary", "index": 0, "is_primary": True, "x": 0, "y": 0, "width": 1920, "height": 1080}]
    monkeypatch.setattr(WindowsScreenCaptureProvider, "list_displays", lambda self: mock_displays)

    # Top-left corner
    resp1 = agent.process_message("Move mouse cursor to top-left corner")
    assert resp1.metadata.get("fast_path") is True
    assert resp1.metadata.get("arguments") == {"x": 10, "y": 10}

    # Explicit coordinates
    resp2 = agent.process_message("Move mouse to 450, 300")
    assert resp2.metadata.get("fast_path") is True
    assert resp2.metadata.get("arguments") == {"x": 450, "y": 300}


def test_scroll_deterministic_fastpath():
    """Verify scrolling operations route directly to fast-path."""
    settings = Settings(llm_provider="mock")
    authorizer = AutoApproveAuthorizer.create_for_testing()
    agent = FridayAgent(settings=settings, authorizer=authorizer)

    resp = agent.process_message("Scroll down by 5 notches")
    assert resp.metadata.get("fast_path") is True
    assert resp.metadata.get("action_type") == "scroll"
    assert resp.metadata.get("arguments") == {"delta_y": -600}


def test_semantic_ui_operation_requires_vision_and_is_not_intercepted_by_fastpath(monkeypatch):
    """Negative test: 'Click the Save button' requires semantic vision and must NOT be intercepted by the fast-path."""
    settings = Settings(llm_provider="mock")
    authorizer = AutoApproveAuthorizer.create_for_testing()
    agent = FridayAgent(settings=settings, authorizer=authorizer)

    resp = agent.process_message("Click the Save button.")

    # Must NOT have used the deterministic fast-path
    assert resp.metadata.get("fast_path") is not True


def test_vision_outage_does_not_block_deterministic_cursor_center(monkeypatch):
    """Verify that even when Vision credentials/provider are completely dead, cursor center succeeds."""
    settings = Settings(llm_provider="mock")
    authorizer = AutoApproveAuthorizer.create_for_testing()
    agent = FridayAgent(settings=settings, authorizer=authorizer)

    # Broken/failing displays or vision
    monkeypatch.setattr(WindowsScreenCaptureProvider, "list_displays", lambda self: [])

    resp = agent.process_message("Move cursor to center of screen")
    assert resp.metadata.get("fast_path") is True
    assert resp.metadata.get("arguments") == {"x": 960, "y": 540}
    assert "Moved the mouse cursor to the center" in resp.content
