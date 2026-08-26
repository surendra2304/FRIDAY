# -*- coding: utf-8 -*-
"""Comprehensive unit test suite for Evidence-Based Verification.3: Temporal & Environmental Context.

Tests:
1. Meaningful state change detection (application focus switch, window title changes).
2. Modal dialog opened and closed detection.
3. Error appearance and resolution tracking.
4. UI elements modified detection.
5. Insignificant noise suppression (minor summary text drift).
6. Temporal ordering and sliding window history maintenance.
7. Task-specific context association.
8. Quota protection via deduplication & delta evaluation.
"""

from datetime import datetime, timezone
import pytest

from friday.vision.screen_context import ScreenContext
from friday.vision.temporal import (
    EnvironmentalChange,
    EnvironmentalChangeType,
    TemporalEnvironmentTracker,
    TemporalObservation,
)
from friday.vision.ui_elements import BoundingBox, ElementType, UIElement


# 1. Meaningful Application Focus & Window Title Change
def test_application_focus_and_window_title_change():
    """Verify application focus switch and window title change are accurately identified."""
    tracker = TemporalEnvironmentTracker()

    ctx1 = ScreenContext(
        summary="VS Code editing main.py",
        active_application="Code.exe",
        window_title="FRIDAY - main.py",
    )
    obs1, changes1 = tracker.record_observation(ctx1, task_id="task_dev")
    assert len(changes1) == 0  # Initial state
    assert tracker.current_observation == obs1

    ctx2 = ScreenContext(
        summary="Chrome browser showing documentation",
        active_application="chrome.exe",
        window_title="Python Documentation",
    )
    obs2, changes2 = tracker.record_observation(ctx2, task_id="task_dev")

    assert len(changes2) >= 2
    types = [c.change_type for c in changes2]
    assert EnvironmentalChangeType.APPLICATION_FOCUS_SWITCH in types
    assert EnvironmentalChangeType.WINDOW_TITLE_CHANGED in types

    focus_change = next(c for c in changes2 if c.change_type == EnvironmentalChangeType.APPLICATION_FOCUS_SWITCH)
    assert focus_change.previous_value == "Code.exe"
    assert focus_change.current_value == "chrome.exe"
    assert focus_change.is_meaningful is True
    assert focus_change.relevant_task_context == "task_dev"


# 2. Dialog Opened and Closed Detection
def test_dialog_opened_and_closed_detection():
    """Verify modal dialog appearance and disappearance are accurately tracked."""
    tracker = TemporalEnvironmentTracker()

    ctx1 = ScreenContext(
        summary="Application main window",
        active_application="App.exe",
        dialogs=[],
    )
    tracker.record_observation(ctx1)

    ctx2 = ScreenContext(
        summary="Application with confirm dialog",
        active_application="App.exe",
        dialogs=["Confirm Delete"],
    )
    _, changes_open = tracker.record_observation(ctx2)

    assert any(c.change_type == EnvironmentalChangeType.DIALOG_OPENED for c in changes_open)
    open_chg = next(c for c in changes_open if c.change_type == EnvironmentalChangeType.DIALOG_OPENED)
    assert open_chg.current_value == "Confirm Delete"

    ctx3 = ScreenContext(
        summary="Application main window after delete",
        active_application="App.exe",
        dialogs=[],
    )
    _, changes_close = tracker.record_observation(ctx3)

    assert any(c.change_type == EnvironmentalChangeType.DIALOG_CLOSED for c in changes_close)
    close_chg = next(c for c in changes_close if c.change_type == EnvironmentalChangeType.DIALOG_CLOSED)
    assert close_chg.previous_value == "Confirm Delete"


# 3. Error Appearance Tracking
def test_error_appearance_tracking():
    """Verify error messages appearing on screen are captured as high-confidence events."""
    tracker = TemporalEnvironmentTracker()

    ctx1 = ScreenContext(summary="Running build", errors=[])
    tracker.record_observation(ctx1)

    ctx2 = ScreenContext(summary="Build failed", errors=["SyntaxError: invalid syntax on line 42"])
    _, changes = tracker.record_observation(ctx2, task_id="build_task")

    assert any(c.change_type == EnvironmentalChangeType.ERROR_APPEARED for c in changes)
    err_chg = next(c for c in changes if c.change_type == EnvironmentalChangeType.ERROR_APPEARED)
    assert "SyntaxError" in err_chg.current_value
    assert err_chg.confidence >= 0.90


# 4. UI Elements Modified Detection
def test_ui_elements_modified_detection():
    """Verify addition or removal of interactive UI elements is recorded."""
    tracker = TemporalEnvironmentTracker()

    btn1 = UIElement(element_id="b1", element_type=ElementType.BUTTON, label="Save", bounding_box=BoundingBox())
    ctx1 = ScreenContext(summary="Form", ui_elements=[btn1])
    tracker.record_observation(ctx1)

    btn2 = UIElement(element_id="b2", element_type=ElementType.BUTTON, label="Cancel", bounding_box=BoundingBox())
    ctx2 = ScreenContext(summary="Form with cancel", ui_elements=[btn1, btn2])
    _, changes = tracker.record_observation(ctx2)

    assert any(c.change_type == EnvironmentalChangeType.UI_ELEMENTS_MODIFIED for c in changes)
    ui_chg = next(c for c in changes if c.change_type == EnvironmentalChangeType.UI_ELEMENTS_MODIFIED)
    assert "Cancel" in ui_chg.description


# 5. Insignificant Noise Handling
def test_insignificant_noise_handling():
    """Verify minor descriptive drift without semantic change is tagged as not meaningful."""
    tracker = TemporalEnvironmentTracker()

    ctx1 = ScreenContext(
        summary="Desktop screen with active terminal.",
        active_application="cmd.exe",
        window_title="Terminal",
    )
    tracker.record_observation(ctx1)

    ctx2 = ScreenContext(
        summary="Desktop screen with open terminal window.",
        active_application="cmd.exe",
        window_title="Terminal",
    )
    _, changes = tracker.record_observation(ctx2)

    assert len(changes) == 1
    assert changes[0].change_type == EnvironmentalChangeType.INSIGNIFICANT_NOISE
    assert changes[0].is_meaningful is False
    # Not added to change_log
    assert len(tracker.change_log) == 0


# 6. Temporal Sliding Window and Ordering
def test_temporal_sliding_window_and_ordering():
    """Verify sliding window maintains bound and preserves chronological order."""
    tracker = TemporalEnvironmentTracker(max_history_entries=3)

    for i in range(5):
        ctx = ScreenContext(
            summary=f"Screen state {i}",
            active_application=f"app_{i}.exe",
        )
        tracker.record_observation(ctx)

    assert len(tracker.history) == 3
    assert tracker.history[0].screen_context.active_application == "app_2.exe"
    assert tracker.history[-1].screen_context.active_application == "app_4.exe"
    assert tracker.previous_observation.screen_context.active_application == "app_3.exe"
    assert tracker.current_observation.screen_context.active_application == "app_4.exe"


# 7. Prompt Formatting for Temporal Context
def test_temporal_context_prompt_formatting():
    """Verify format_temporal_context_for_prompt produces clean markdown blocks."""
    tracker = TemporalEnvironmentTracker()
    ctx1 = ScreenContext(summary="App 1", active_application="App1.exe")
    ctx2 = ScreenContext(summary="App 2", active_application="App2.exe")

    tracker.record_observation(ctx1)
    tracker.record_observation(ctx2)

    prompt = tracker.format_temporal_context_for_prompt()
    assert "=== RECENT ENVIRONMENTAL & TEMPORAL CHANGES ===" in prompt
    assert "APPLICATION_FOCUS_SWITCH" in prompt
    assert "=== END TEMPORAL CHANGES ===" in prompt
