"""Canonical Windows Multi-Monitor & DPI-Aware Coordinate Transformation Engine.

Provides:
1. Full Multi-Monitor Support (primary, secondary, negative virtual desktop origins).
2. Windows DPI Scaling conversion (100%, 125%, 150%, 200%, custom).
3. Physical Pixel <-> Logical Coordinate <-> Normalized (0..1000) <-> Virtual Desktop transformations.
4. Display Orientation, Resolution Change & Monitor Disconnect detection.
5. Stale Coordinate Guard: prevents executing actions against moved/stale UI elements.
6. Revalidation & Fresh Perception enforcement for sensitive actions.
"""

import time
from dataclasses import dataclass
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel
from friday.vision.ui_elements import BoundingBox

logger = get_logger("vision.coordinates")


@dataclass
class DisplayMonitor:
    """Represents a display monitor within the Windows virtual desktop topology."""
    monitor_id: str
    index: int
    x: int  # Virtual desktop X origin (can be negative)
    y: int  # Virtual desktop Y origin (can be negative)
    width: int  # Physical pixel width
    height: int  # Physical pixel height
    dpi_scale: float = 1.0  # e.g., 1.0 (100%), 1.25 (125%), 1.5 (150%), 2.0 (200%)
    is_primary: bool = False
    orientation: int = 0  # 0, 90, 180, 270 degrees

    @property
    def logical_width(self) -> int:
        return int(round(self.width / max(0.25, self.dpi_scale)))

    @property
    def logical_height(self) -> int:
        return int(round(self.height / max(0.25, self.dpi_scale)))

    def contains_virtual_point(self, vx: int, vy: int) -> bool:
        """Check if virtual desktop coordinate (vx, vy) lies within this monitor."""
        return (self.x <= vx < self.x + self.width) and (self.y <= vy < self.y + self.height)

    def to_dict(self) -> dict[str, Any]:
        return {
            "monitor_id": self.monitor_id,
            "index": self.index,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "dpi_scale": self.dpi_scale,
            "logical_width": self.logical_width,
            "logical_height": self.logical_height,
            "is_primary": self.is_primary,
            "orientation": self.orientation,
        }


class CoordinateTransform:
    """Canonical transformation layer between Normalized, Physical, Logical, and Virtual coordinates."""

    def __init__(self, monitors: list[DisplayMonitor] | None = None) -> None:
        self.monitors: list[DisplayMonitor] = monitors or [
            DisplayMonitor(
                monitor_id="primary",
                index=0,
                x=0,
                y=0,
                width=1920,
                height=1080,
                dpi_scale=1.0,
                is_primary=True,
            )
        ]

    def get_monitor(self, monitor_id: str | None = None) -> DisplayMonitor:
        """Get specified monitor by ID or index, defaulting to primary monitor."""
        if monitor_id:
            for mon in self.monitors:
                if mon.monitor_id == monitor_id or str(mon.index) == str(monitor_id):
                    return mon
        for mon in self.monitors:
            if mon.is_primary:
                return mon
        return self.monitors[0] if self.monitors else DisplayMonitor("primary", 0, 0, 0, 1920, 1080, 1.0, True)

    def normalized_to_physical(
        self,
        norm_x: float,
        norm_y: float,
        monitor_id: str | None = None,
    ) -> tuple[int, int]:
        """Convert normalized [0..1000] coordinates to monitor-local physical pixels."""
        mon = self.get_monitor(monitor_id)
        clamped_x = max(0.0, min(1000.0, float(norm_x)))
        clamped_y = max(0.0, min(1000.0, float(norm_y)))
        px = int(round((clamped_x / 1000.0) * (mon.width - 1)))
        py = int(round((clamped_y / 1000.0) * (mon.height - 1)))
        return px, py

    def normalized_to_virtual(
        self,
        norm_x: float,
        norm_y: float,
        monitor_id: str | None = None,
    ) -> tuple[int, int]:
        """Convert normalized [0..1000] coordinates to absolute Windows virtual desktop coordinates."""
        mon = self.get_monitor(monitor_id)
        local_px, local_py = self.normalized_to_physical(norm_x, norm_y, monitor_id=mon.monitor_id)
        virt_x = mon.x + local_px
        virt_y = mon.y + local_py
        return virt_x, virt_y

    def physical_to_logical(
        self,
        phys_x: int,
        phys_y: int,
        monitor_id: str | None = None,
    ) -> tuple[int, int]:
        """Convert physical pixels to logical DIPs using monitor's DPI scaling."""
        mon = self.get_monitor(monitor_id)
        scale = max(0.25, mon.dpi_scale)
        log_x = int(round(phys_x / scale))
        log_y = int(round(phys_y / scale))
        return log_x, log_y

    def logical_to_physical(
        self,
        log_x: int,
        log_y: int,
        monitor_id: str | None = None,
    ) -> tuple[int, int]:
        """Convert logical DIPs to physical pixels using monitor's DPI scaling."""
        mon = self.get_monitor(monitor_id)
        scale = max(0.25, mon.dpi_scale)
        phys_x = int(round(log_x * scale))
        phys_y = int(round(log_y * scale))
        return phys_x, phys_y

    def virtual_to_monitor_relative(
        self,
        virt_x: int,
        virt_y: int,
    ) -> tuple[DisplayMonitor | None, int, int]:
        """Find the monitor containing virtual coordinate (virt_x, virt_y) and return monitor-local pixels."""
        for mon in self.monitors:
            if mon.contains_virtual_point(virt_x, virt_y):
                local_x = virt_x - mon.x
                local_y = virt_y - mon.y
                return mon, local_x, local_y
        # Fallback to primary
        prim = self.get_monitor()
        return prim, virt_x - prim.x, virt_y - prim.y

    def monitor_relative_to_virtual(
        self,
        monitor_id: str,
        rel_x: int,
        rel_y: int,
    ) -> tuple[int, int]:
        """Convert monitor-local pixel coordinate to virtual desktop coordinate."""
        mon = self.get_monitor(monitor_id)
        return mon.x + rel_x, mon.y + rel_y

    def is_valid_virtual_coordinate(self, virt_x: int, virt_y: int) -> bool:
        """Check if virtual desktop coordinate is within the bounds of any active monitor."""
        return any(mon.contains_virtual_point(virt_x, virt_y) for mon in self.monitors)

    def get_virtual_desktop_bounds(self) -> tuple[int, int, int, int]:
        """Return bounding box of entire virtual desktop (min_x, min_y, max_x, max_y)."""
        if not self.monitors:
            return 0, 0, 1920, 1080
        min_x = min(mon.x for mon in self.monitors)
        min_y = min(mon.y for mon in self.monitors)
        max_x = max(mon.x + mon.width for mon in self.monitors)
        max_y = max(mon.y + mon.height for mon in self.monitors)
        return min_x, min_y, max_x, max_y

    def detect_topology_change(self, new_displays: list[dict[str, Any]]) -> bool:
        """Check if display count, resolution, DPI, or position changed (e.g. monitor disconnect/plug)."""
        if len(new_displays) != len(self.monitors):
            return True
        for d in new_displays:
            matched = False
            for m in self.monitors:
                if m.monitor_id == d.get("id") or m.index == d.get("index"):
                    if (
                        m.x != d.get("x", 0)
                        or m.y != d.get("y", 0)
                        or m.width != d.get("width", 1920)
                        or m.height != d.get("height", 1080)
                        or m.dpi_scale != d.get("dpi_scale", 1.0)
                    ):
                        return True
                    matched = True
                    break
            if not matched:
                return True
        return False


class StaleCoordinateGuard:
    """Validates that a proposed coordinate or UI element target has not become stale."""

    def __init__(self, max_observation_age_seconds: float = 10.0) -> None:
        self.max_observation_age_seconds = max_observation_age_seconds

    def validate_action_freshness(
        self,
        observation_time: float,
        last_action_time: float,
        safety_level: SafetyLevel = SafetyLevel.SAFE,
        current_time: float | None = None,
    ) -> tuple[bool, str | None]:
        """Verify whether an observation is sufficiently fresh to execute an action."""
        now = current_time or time.time()
        age = now - observation_time

        # 1. Action barrier: Any intervening UI action invalidates prior coordinates
        if last_action_time > observation_time:
            return False, f"Stale coordinate detected: A UI action was executed at t={last_action_time:.2f} after observation t={observation_time:.2f}. Fresh perception required."

        # 2. Strict age limit
        if age > self.max_observation_age_seconds:
            return False, f"Stale observation: Visual context is {age:.1f}s old (max allowed {self.max_observation_age_seconds:.1f}s). Fresh perception required."

        # 3. Sensitive / Dangerous actions require fresh perception (< 5.0s)
        if safety_level in (SafetyLevel.SENSITIVE, SafetyLevel.DANGEROUS) and age > 5.0:
            return False, f"Sensitive action requires fresh perception (<5s). Context is {age:.1f}s old. Revalidation required."

        return True, None

    def validate_element_not_moved(
        self,
        original_box: BoundingBox,
        current_box: BoundingBox | None,
        movement_tolerance_normalized: float = 10.0,
    ) -> tuple[bool, str | None]:
        """Verify that target UI element has not shifted on screen."""
        if current_box is None:
            return False, "Target UI element is no longer visible on screen."

        orig_cx = (original_box.xmin + original_box.xmax) / 2.0
        orig_cy = (original_box.ymin + original_box.ymax) / 2.0
        curr_cx = (current_box.xmin + current_box.xmax) / 2.0
        curr_cy = (current_box.ymin + current_box.ymax) / 2.0

        dist = ((orig_cx - curr_cx) ** 2 + (orig_cy - curr_cy) ** 2) ** 0.5
        if dist > movement_tolerance_normalized:
            return False, f"Target UI element moved by {dist:.1f} units (tolerance {movement_tolerance_normalized:.1f}). Re-grounding required."

        return True, None
