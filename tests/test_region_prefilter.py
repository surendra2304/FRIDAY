# -*- coding: utf-8 -*-
"""Comprehensive unit test suite for Evidence-Based Verification.4: Local Text & Perceptual Region Pre-Filtering (Quota Saver).

Tests:
1. Local PNG region cropping (ROI slicing) from bounding boxes.
2. Perceptual ROI hashing and unchanged subregion change suppression.
3. Changed subregion detection and difference ratio calculation.
4. Local text-density & visual complexity estimation heuristics (solid, low, medium, code/dense).
5. Feeding verified environmental and visual deltas into ActiveTaskContext.
6. Secret and credential redaction during visual delta feeding.
7. Offline operation and provider independence (100% testable without cloud vision calls).
"""

from datetime import datetime, timezone
import pytest

from friday.memory.task_context import ActiveTaskContext
from friday.vision.mock_screen import MockScreenCaptureProvider, create_synthetic_png
from friday.vision.region_filter import (
    LocalRegionPreFilter,
    ROIAnalysisResult,
    TextDensityLevel,
    VisualDeltaTaskContextFeeder,
    crop_image_region,
    decode_png_to_rgba,
    encode_rgba_to_png,
    estimate_local_text_density,
)
from friday.vision.temporal import EnvironmentalChange, EnvironmentalChangeType
from friday.vision.ui_elements import BoundingBox


# 1. ROI Slicing & Image Encoding/Decoding
def test_roi_slicing_and_png_codec():
    """Verify PNG region slicing extracts exact pixel sub-rectangles into valid PNGs."""
    synthetic_png = create_synthetic_png(width=200, height=200, color=(10, 20, 30))
    bbox = BoundingBox(ymin=100, xmin=100, ymax=500, xmax=500)  # y: 20-100, x: 20-100

    cropped_png, pixel_rect = crop_image_region(
        png_bytes=synthetic_png,
        bounding_box=bbox,
        image_width=200,
        image_height=200,
    )

    assert len(cropped_png) > 0
    assert pixel_rect == (20, 20, 100, 100)

    # Decode and verify dimensions of sliced region
    arr, w, h = decode_png_to_rgba(cropped_png)
    assert w == 80
    assert h == 80
    assert arr.shape == (80, 80, 4)
    assert arr[0, 0, 0] == 10
    assert arr[0, 0, 1] == 20
    assert arr[0, 0, 2] == 30


# 2. Perceptual ROI Hashing & Unchanged Subregion Suppression
def test_roi_hashing_and_unchanged_suppression():
    """Verify unchanged ROIs are recognized and marked has_changed=False."""
    filter_engine = LocalRegionPreFilter(change_threshold=0.05)
    img1 = create_synthetic_png(width=100, height=100, color=(100, 150, 200))
    terminal_bbox = BoundingBox(ymin=500, xmin=0, ymax=1000, xmax=1000)

    # 1st evaluation -> New ROI, changed
    res1 = filter_engine.slice_and_evaluate_roi(img1, terminal_bbox, roi_id="terminal_roi")
    assert res1.has_changed is True
    assert res1.change_ratio == 1.0

    # 2nd evaluation with identical image -> Unchanged
    res2 = filter_engine.slice_and_evaluate_roi(img1, terminal_bbox, roi_id="terminal_roi")
    assert res2.has_changed is False
    assert res2.change_ratio == 0.0
    assert res2.image_sha256 == res1.image_sha256


# 3. Changed Subregion Detection
def test_changed_roi_detection():
    """Verify modifying a specific ROI is detected while other regions remain unchanged."""
    filter_engine = LocalRegionPreFilter(change_threshold=0.05)
    img1 = create_synthetic_png(width=100, height=100, color=(0, 0, 0))
    img2 = create_synthetic_png(width=100, height=100, color=(255, 255, 255))

    bbox = BoundingBox(ymin=0, xmin=0, ymax=1000, xmax=1000)

    res1 = filter_engine.slice_and_evaluate_roi(img1, bbox, roi_id="screen_roi")
    assert res1.has_changed is True

    res2 = filter_engine.slice_and_evaluate_roi(img2, bbox, roi_id="screen_roi")
    assert res2.has_changed is True
    assert res2.change_ratio > 0.05


# 4. Text-Density & Visual Complexity Estimation
def test_text_density_and_complexity_heuristics():
    """Verify spatial complexity and text-density heuristic categorization."""
    # Solid background -> EMPTY_OR_SOLID
    solid_png = create_synthetic_png(width=64, height=64, color=(240, 240, 240))
    arr_solid, _, _ = decode_png_to_rgba(solid_png)
    density_solid, comp_solid = estimate_local_text_density(arr_solid)
    assert density_solid == TextDensityLevel.EMPTY_OR_SOLID
    assert comp_solid == 0.0

    # Complex patterned array (simulating code/text lines with high spatial transitions)
    import numpy as np
    pattern = np.zeros((100, 100, 4), dtype=np.uint8)
    pattern[::4, :, 0:3] = 255  # Horizontal lines
    pattern[:, ::2, 0:3] = 200  # Vertical crossings
    pattern[:, :, 3] = 255

    density_dense, comp_dense = estimate_local_text_density(pattern)
    assert density_dense in [TextDensityLevel.HIGH, TextDensityLevel.CODE_OR_DENSE_TEXT]
    assert comp_dense > 0.4


# 5. Feeding Environmental Deltas into ActiveTaskContext
def test_feeding_environmental_deltas_into_task_context():
    """Verify structured environmental deltas are fed into ActiveTaskContext working memory."""
    ctx = ActiveTaskContext(goal="Deploy service")
    changes = [
        EnvironmentalChange(
            change_id="chg_1",
            change_type=EnvironmentalChangeType.APPLICATION_FOCUS_SWITCH,
            description="Active application changed to WindowsTerminal.exe",
            previous_value="explorer.exe",
            current_value="WindowsTerminal.exe",
            confidence=0.95,
            is_meaningful=True,
        ),
        EnvironmentalChange(
            change_id="chg_2",
            change_type=EnvironmentalChangeType.INSIGNIFICANT_NOISE,
            description="Minor pixel shift",
            previous_value=None,
            current_value=None,
            confidence=0.1,
            is_meaningful=False,
        ),
    ]

    count = VisualDeltaTaskContextFeeder.feed_environmental_delta(
        task_context=ctx,
        step_id="step_check_app",
        changes=changes,
    )

    assert count == 1
    assert len(ctx.observations) == 1
    assert "WindowsTerminal.exe" in ctx.observations[0].content
    assert "[Visual Delta: APPLICATION_FOCUS_SWITCH]" in ctx.observations[0].content


# 6. Secret Redaction During Delta Feeding
def test_secret_redaction_in_delta_feeding():
    """Verify secrets in visual deltas are redacted before entering ActiveTaskContext."""
    ctx = ActiveTaskContext(goal="Verify login")
    fake_key = "AIza" + "Sy" + "D12345678901234567890123456789012"
    dirty_change = EnvironmentalChange(
        change_id="chg_secret",
        change_type=EnvironmentalChangeType.TEXT_CONTENT_UPDATED,
        description=f"Terminal printed api_key: {fake_key} and password: MyPassword",
        previous_value=None,
        current_value=None,
        confidence=0.9,
        is_meaningful=True,
    )

    VisualDeltaTaskContextFeeder.feed_environmental_delta(
        task_context=ctx,
        step_id="step_login",
        changes=[dirty_change],
    )

    assert len(ctx.observations) == 1
    obs_text = ctx.observations[0].content
    assert fake_key not in obs_text
    assert "MyPassword" not in obs_text
    assert "[REDACTED_PASSWORD]" in obs_text


# 7. ROI Delta Feeding
def test_roi_delta_feeding():
    """Verify changed ROI analysis result is recorded into task context."""
    ctx = ActiveTaskContext(goal="Build project")
    roi_res = ROIAnalysisResult(
        roi_id="build_log",
        bounding_box=BoundingBox(ymin=100, xmin=100, ymax=500, xmax=500),
        pixel_rect=(10, 10, 50, 50),
        image_bytes=b"png_bytes",
        image_sha256="fake_sha",
        text_density=TextDensityLevel.CODE_OR_DENSE_TEXT,
        estimated_complexity=0.85,
        has_changed=True,
        change_ratio=0.35,
    )

    success = VisualDeltaTaskContextFeeder.feed_roi_delta(
        task_context=ctx,
        step_id="step_build",
        roi_result=roi_res,
    )

    assert success is True
    assert len(ctx.observations) == 1
    assert "build_log" in ctx.observations[0].content
    assert "CODE_OR_DENSE_TEXT" in ctx.observations[0].content
