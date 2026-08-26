# -*- coding: utf-8 -*-
"""Structured UI element and visual region models for Evidence-Based Verification.2.

Provides normalized bounding boxes, typed UI element categories, confidence scores,
and structured parsing for fine-grained desktop screen understanding.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple


class ElementType(str, Enum):
    """Categorized UI element types on a desktop or application screen."""
    BUTTON = "BUTTON"
    INPUT_FIELD = "INPUT_FIELD"
    TEXT_REGION = "TEXT_REGION"
    WINDOW = "WINDOW"
    APPLICATION_REGION = "APPLICATION_REGION"
    DIALOG = "DIALOG"
    MODAL = "MODAL"
    MENU = "MENU"
    MENU_ITEM = "MENU_ITEM"
    TAB = "TAB"
    TABLE = "TABLE"
    NOTIFICATION = "NOTIFICATION"
    ICON = "ICON"
    CHECKBOX = "CHECKBOX"
    DROPDOWN = "DROPDOWN"
    CODE_EDITOR = "CODE_EDITOR"
    TERMINAL = "TERMINAL"
    CHART = "CHART"
    UNKNOWN = "UNKNOWN"


@dataclass
class BoundingBox:
    """Normalized bounding box coordinates (0 to 1000 scale).

    Coordinates:
        ymin: Top edge (0 - 1000)
        xmin: Left edge (0 - 1000)
        ymax: Bottom edge (0 - 1000)
        xmax: Right edge (0 - 1000)
    """
    ymin: int = 0
    xmin: int = 0
    ymax: int = 1000
    xmax: int = 1000

    def to_dict(self) -> Dict[str, int]:
        return {
            "ymin": self.ymin,
            "xmin": self.xmin,
            "ymax": self.ymax,
            "xmax": self.xmax,
        }

    def to_pixel_coordinates(self, screen_width: int, screen_height: int) -> Tuple[int, int, int, int]:
        """Convert normalized [0, 1000] coordinates to absolute pixel coordinates [x1, y1, x2, y2]."""
        x1 = int((self.xmin / 1000.0) * screen_width)
        y1 = int((self.ymin / 1000.0) * screen_height)
        x2 = int((self.xmax / 1000.0) * screen_width)
        y2 = int((self.ymax / 1000.0) * screen_height)
        return (x1, y1, x2, y2)

    def get_center_pixel(self, screen_width: int, screen_height: int) -> Tuple[int, int]:
        """Compute pixel center (x, y) for clicking or hovering."""
        x1, y1, x2, y2 = self.to_pixel_coordinates(screen_width, screen_height)
        return ((x1 + x2) // 2, (y1 + y2) // 2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BoundingBox":
        if not isinstance(data, dict):
            return cls()
        return cls(
            ymin=int(data.get("ymin", data.get("top", 0))),
            xmin=int(data.get("xmin", data.get("left", 0))),
            ymax=int(data.get("ymax", data.get("bottom", 1000))),
            xmax=int(data.get("xmax", data.get("right", 1000))),
        )


@dataclass
class UIElement:
    """Structured, confidence-aware representation of an identified UI element."""
    element_id: str
    element_type: ElementType
    label: str
    bounding_box: BoundingBox
    confidence: float = 1.0
    is_interactive: bool = True
    attributes: Dict[str, Any] = field(default_factory=dict)
    observed_text: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "element_id": self.element_id,
            "element_type": self.element_type.value,
            "label": self.label,
            "bounding_box": self.bounding_box.to_dict(),
            "confidence": self.confidence,
            "is_interactive": self.is_interactive,
            "attributes": self.attributes,
            "observed_text": self.observed_text,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UIElement":
        etype_str = str(data.get("element_type", "UNKNOWN")).upper()
        try:
            etype = ElementType(etype_str)
        except ValueError:
            etype = ElementType.UNKNOWN

        bbox_data = data.get("bounding_box", {})
        bbox = BoundingBox.from_dict(bbox_data) if isinstance(bbox_data, dict) else BoundingBox()

        return cls(
            element_id=str(data.get("element_id", "elem_0")),
            element_type=etype,
            label=str(data.get("label", "")),
            bounding_box=bbox,
            confidence=float(data.get("confidence", 1.0)),
            is_interactive=bool(data.get("is_interactive", True)),
            attributes=data.get("attributes", {}) if isinstance(data.get("attributes"), dict) else {},
            observed_text=data.get("observed_text"),
        )
