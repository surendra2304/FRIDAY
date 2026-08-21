# -*- coding: utf-8 -*-
"""Data structures and container models for FRIDAY Screen Understanding context."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Dict, List, Optional

from friday.vision.ui_elements import BoundingBox, ElementType, UIElement


@dataclass
class ScreenContext:
    """Normalized structured representation of analyzed screen visual context."""

    summary: str
    active_application: Optional[str] = None
    window_title: Optional[str] = None
    visible_text: Optional[str] = None
    ui_elements: List[UIElement] = field(default_factory=list)
    buttons: List[str] = field(default_factory=list)
    dialogs: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    charts: List[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    display_id: str = "primary"
    captured_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_error: bool = False
    error_message: Optional[str] = None
    overall_confidence: float = 1.0
    screen_state_id: Optional[str] = None
    provider_model: Optional[str] = None
    source: str = "fresh"
    is_cached: bool = False

    def get_elements_by_type(self, element_type: ElementType) -> List[UIElement]:
        """Filter detected elements by their structural type."""
        return [el for el in self.ui_elements if el.element_type == element_type]

    def find_element_by_label(self, label: str, min_confidence: float = 0.5) -> Optional[UIElement]:
        """Find the best-matching UI element with label matching the query."""
        clean = label.strip().lower()
        candidates = [
            el for el in self.ui_elements
            if el.confidence >= min_confidence and (clean in el.label.lower() or el.label.lower() in clean)
        ]
        if candidates:
            # Return element with highest confidence
            return max(candidates, key=lambda el: el.confidence)
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Convert screen context into safe dictionary representation with provenance."""
        return {
            "summary": self.summary,
            "active_application": self.active_application,
            "window_title": self.window_title,
            "visible_text": self.visible_text,
            "ui_elements": [el.to_dict() for el in self.ui_elements],
            "buttons": self.buttons,
            "dialogs": self.dialogs,
            "errors": self.errors,
            "warnings": self.warnings,
            "charts": self.charts,
            "width": self.width,
            "height": self.height,
            "display_id": self.display_id,
            "captured_at": self.captured_at.isoformat(),
            "is_error": self.is_error,
            "error_message": self.error_message,
            "overall_confidence": self.overall_confidence,
            "screen_state_id": self.screen_state_id,
            "provider_model": self.provider_model,
            "source": self.source,
            "is_cached": self.is_cached,
        }

    def format_for_prompt(self) -> str:
        """Format screen context as UNTRUSTED visual data block for LLM reasoning."""
        provenance_str = f"Source: {self.source} | Model: {self.provider_model or 'unknown'} | State ID: {self.screen_state_id or 'none'} | Cached: {self.is_cached}"
        lines = [
            "=== VISUAL SCREEN OBSERVATION (UNTRUSTED DATA) ===",
            f"Display: {self.display_id} ({self.width}x{self.height}) at {self.captured_at.isoformat()} [{provenance_str}]",
            f"Summary: {self.summary}",
        ]
        if self.active_application:
            lines.append(f"Active Application: {self.active_application}")
        if self.window_title:
            lines.append(f"Window Title: {self.window_title}")
        if self.errors:
            lines.append(f"Detected Errors: {', '.join(self.errors)}")
        if self.warnings:
            lines.append(f"Detected Warnings: {', '.join(self.warnings)}")
        if self.buttons:
            lines.append(f"Interactive Buttons: {', '.join(self.buttons)}")
        if self.dialogs:
            lines.append(f"Open Dialogs: {', '.join(self.dialogs)}")
        if self.charts:
            lines.append(f"Charts / Visuals: {', '.join(self.charts)}")

        if self.ui_elements:
            lines.append(f"Structured UI Elements ({len(self.ui_elements)} detected):")
            for el in self.ui_elements[:15]:  # Bound prompt length
                bbox = el.bounding_box
                lines.append(
                    f"  - [{el.element_type.value}] \"{el.label}\" at [{bbox.ymin},{bbox.xmin},{bbox.ymax},{bbox.xmax}] "
                    f"(conf: {el.confidence:.2f})"
                )

        if self.visible_text:
            # Truncate visible text to safe length
            safe_text = self.visible_text[:1500].replace("\n", " ")
            lines.append(f"Visible Text Excerpt: {safe_text}")
        lines.append("=== END VISUAL OBSERVATION ===")
        return "\n".join(lines)
