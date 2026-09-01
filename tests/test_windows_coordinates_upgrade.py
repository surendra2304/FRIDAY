"""Verification tests for FRIDAY's Windows Display & Coordinate Transformation Layer."""

import sys

import pytest

from friday.core.types import SafetyLevel
from friday.vision.coordinates import (
    CoordinateTransform,
    DisplayMonitor,
    StaleCoordinateGuard,
)
from friday.vision.ui_elements import BoundingBox
from friday.vision.windows_input_driver import WindowsNativeInputDriver
from friday.vision.windows_screen import WindowsScreenCaptureProvider

# ============================================================================
# 1. Multi-Monitor & Negative Virtual Coordinates Tests
# ============================================================================

def test_negative_virtual_desktop_coordinates():
    """Verify coordinate transformation for secondary monitor positioned to the left of primary (negative X)."""
    monitors = [
        # Secondary monitor: 1920x1080 positioned at (-1920, 0)
        DisplayMonitor(
            monitor_id="secondary_left",
            index=1,
            x=-1920,
            y=0,
            width=1920,
            height=1080,
            dpi_scale=1.0,
            is_primary=False,
        ),
        # Primary monitor: 1920x1080 positioned at (0, 0)
        DisplayMonitor(
            monitor_id="primary",
            index=0,
            x=0,
            y=0,
            width=1920,
            height=1080,
            dpi_scale=1.0,
            is_primary=True,
        ),
    ]

    transform = CoordinateTransform(monitors=monitors)

    # 1. Primary center (500, 500) -> Virtual (960, 540)
    vx_prim, vy_prim = transform.normalized_to_virtual(500, 500, monitor_id="primary")
    assert vx_prim == 959 or vx_prim == 960
    assert vy_prim == 539 or vy_prim == 540

    # 2. Secondary center (500, 500) -> Virtual (-1920 + 960 = -960, 540)
    vx_sec, vy_sec = transform.normalized_to_virtual(500, 500, monitor_id="secondary_left")
    assert -961 <= vx_sec <= -959
    assert 539 <= vy_sec <= 540

    # 3. Virtual point resolution back to monitor-local
    mon_res, local_x, local_y = transform.virtual_to_monitor_relative(-960, 540)
    assert mon_res is not None
    assert mon_res.monitor_id == "secondary_left"
    assert local_x == 960
    assert local_y == 540

    # 4. Virtual desktop bounds (-1920, 0, 1920, 1080)
    min_x, min_y, max_x, max_y = transform.get_virtual_desktop_bounds()
    assert min_x == -1920
    assert min_y == 0
    assert max_x == 1920
    assert max_y == 1080


# ============================================================================
# 2. Windows DPI Scaling (100%, 125%, 150%, 200%) Tests
# ============================================================================

@pytest.mark.parametrize("dpi_scale,expected_phys_x,expected_phys_y", [
    (1.0, 100, 200),    # 100% scale: 1:1
    (1.25, 125, 250),   # 125% scale: 100 * 1.25 = 125
    (1.5, 150, 300),    # 150% scale: 100 * 1.5 = 150
    (2.0, 200, 400),    # 200% scale: 100 * 2.0 = 200
])
def test_dpi_scaling_transformations(dpi_scale, expected_phys_x, expected_phys_y):
    """Verify bidirectional DPI scaling transformations between logical and physical coordinates."""
    mon = DisplayMonitor(
        monitor_id="dpi_test",
        index=0,
        x=0,
        y=0,
        width=3840,
        height=2160,
        dpi_scale=dpi_scale,
        is_primary=True,
    )
    transform = CoordinateTransform(monitors=[mon])

    # Logical (100, 200) -> Physical
    phys_x, phys_y = transform.logical_to_physical(100, 200, monitor_id="dpi_test")
    assert phys_x == expected_phys_x
    assert phys_y == expected_phys_y

    # Physical back to Logical
    log_x, log_y = transform.physical_to_logical(phys_x, phys_y, monitor_id="dpi_test")
    assert log_x == 100
    assert log_y == 200


# ============================================================================
# 3. Topology Change & Monitor Disconnect Tests
# ============================================================================

def test_detect_topology_change_on_resolution_and_disconnect():
    """Verify topology change detector flags resolution changes and monitor disconnects."""
    mon1 = DisplayMonitor("mon1", 0, 0, 0, 1920, 1080, 1.0, True)
    mon2 = DisplayMonitor("mon2", 1, 1920, 0, 1920, 1080, 1.0, False)
    transform = CoordinateTransform(monitors=[mon1, mon2])

    # 1. Unchanged topology
    current_state = [
        {"id": "mon1", "index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080, "dpi_scale": 1.0},
        {"id": "mon2", "index": 1, "x": 1920, "y": 0, "width": 1920, "height": 1080, "dpi_scale": 1.0},
    ]
    assert transform.detect_topology_change(current_state) is False

    # 2. Resolution changed on mon1 (e.g. 4K switched to 1080p)
    res_changed = [
        {"id": "mon1", "index": 0, "x": 0, "y": 0, "width": 3840, "height": 2160, "dpi_scale": 1.5},
        {"id": "mon2", "index": 1, "x": 3840, "y": 0, "width": 1920, "height": 1080, "dpi_scale": 1.0},
    ]
    assert transform.detect_topology_change(res_changed) is True

    # 3. Monitor 2 disconnected
    disconnected = [
        {"id": "mon1", "index": 0, "x": 0, "y": 0, "width": 1920, "height": 1080, "dpi_scale": 1.0},
    ]
    assert transform.detect_topology_change(disconnected) is True


# ============================================================================
# 4. Stale Coordinate Guard Tests
# ============================================================================

def test_stale_coordinate_guard_blocks_moved_and_stale_elements():
    """Verify StaleCoordinateGuard prevents executing actions on shifted or stale coordinates."""
    guard = StaleCoordinateGuard(max_observation_age_seconds=10.0)

    t0 = 1000.0

    # 1. Fresh observation with no intervening actions -> Valid
    ok, err = guard.validate_action_freshness(observation_time=t0, last_action_time=990.0, current_time=1002.0)
    assert ok is True
    assert err is None

    # 2. Action executed AFTER observation -> Blocked
    ok, err = guard.validate_action_freshness(observation_time=t0, last_action_time=1001.0, current_time=1002.0)
    assert ok is False
    assert "A UI action was executed" in (err or "")

    # 3. Observation too old (>10s) -> Blocked
    ok, err = guard.validate_action_freshness(observation_time=t0, last_action_time=990.0, current_time=1015.0)
    assert ok is False
    assert "Visual context is 15.0s old" in (err or "")

    # 4. Sensitive action requires fresh perception (<5s)
    ok_sens, err_sens = guard.validate_action_freshness(
        observation_time=t0,
        last_action_time=990.0,
        safety_level=SafetyLevel.SENSITIVE,
        current_time=1006.0,  # 6s old -> blocked for sensitive
    )
    assert ok_sens is False
    assert "Sensitive action requires fresh perception" in (err_sens or "")

    # 5. Target element shifted on screen -> Blocked
    box1 = BoundingBox(ymin=100, xmin=100, ymax=140, xmax=200)
    box_moved = BoundingBox(ymin=250, xmin=300, ymax=290, xmax=400)
    ok_move, err_move = guard.validate_element_not_moved(box1, box_moved)
    assert ok_move is False
    assert "moved by" in (err_move or "")


# ============================================================================
# 5. Real Windows Machine Topology Tests
# ============================================================================

def test_real_windows_machine_topology_query():
    """Verify live display query on Windows host system."""
    if sys.platform != "win32":
        pytest.skip("Windows host required for live Win32 API test")

    provider = WindowsScreenCaptureProvider()
    displays = provider.list_displays()

    assert len(displays) >= 1
    primary_disp = displays[0]
    assert primary_disp["width"] > 0
    assert primary_disp["height"] > 0
    assert primary_disp["is_primary"] is True

    # Verify input driver cursor query on Windows
    driver = WindowsNativeInputDriver()
    width, height = driver.get_screen_dimensions()
    assert width > 0
    assert height > 0
    cur_x, cur_y = driver.get_cursor_position()
    assert isinstance(cur_x, int)
    assert isinstance(cur_y, int)
