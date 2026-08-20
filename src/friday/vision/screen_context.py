# -*- coding: utf-8 -*-
"""Data structures and container models for FRIDAY Screen Understanding context."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ScreenContext:
    """Normalized structured representation of analyzed screen visual context."""

    summary: str
    active_application: Optional[str] = None
    window_title: Optional[str] = None
    visible_text: Optional[str] = None
    ui_elements: List[Dict[str, Any]] = field(default_factory=list)
    buttons: List[str] = field(default_factory=list)
    dialogs: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    charts: List[str] = field(default_factory=list)
    width: int = 0
    height: int = 0
    display_id: str = "primary"
    captured_at: datetime = field(default_factory=datetime.utcnow)
    is_error: bool = False
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert screen context into safe dictionary representation."""
        return {
            "summary": self.summary,
            "active_application": self.active_application,
            "window_title": self.window_title,
            "visible_text": self.visible_text,
            "ui_elements": self.ui_elements,
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
        }

    def format_for_prompt(self) -> str:
        """Format screen context as UNTRUSTED visual data block for LLM reasoning."""
        lines = [
            "=== VISUAL SCREEN OBSERVATION (UNTRUSTED DATA) ===",
            f"Display: {self.display_id} ({self.width}x{self.height}) at {self.captured_at.isoformat()}",
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
        if self.visible_text:
            # Truncate visible text to safe length
            safe_text = self.visible_text[:1500].replace("\n", " ")
            lines.append(f"Visible Text Excerpt: {safe_text}")
        lines.append("=== END VISUAL OBSERVATION ===")
        return "\n".join(lines)
