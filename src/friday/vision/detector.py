# -*- coding: utf-8 -*-
"""Deterministic Computer Action Detector for FRIDAY.

Parses purely geometric, non-semantic computer control operations from natural language
without requiring multimodal Vision or external LLM inference.
"""

from dataclasses import dataclass
import re
from typing import Any, Dict, Optional, Tuple

from friday.core.types import SafetyLevel
from friday.vision.actions import ActionType, ComputerActionProposal
from friday.vision.windows_screen import WindowsScreenCaptureProvider


@dataclass
class DeterministicActionIntent:
    """Structured intent representation for a detected deterministic action."""
    action_type: ActionType
    arguments: Dict[str, Any]
    intent: str
    confidence: float
    risk_level: SafetyLevel
    requires_confirmation: bool = False
    target_display: str = "primary"

    def to_proposal(self) -> ComputerActionProposal:
        """Convert detected intent to an official ComputerActionProposal."""
        return ComputerActionProposal(
            action_type=self.action_type,
            arguments=self.arguments,
            intent=self.intent,
            risk_level=self.risk_level,
            requires_confirmation=self.requires_confirmation,
        )


class DeterministicActionDetector:
    """Detects and parses safe, local deterministic computer control actions."""

    # Regex patterns for deterministic cursor movements
    MOVE_CENTER_PATTERN = re.compile(
        r"^(?:please\s+)?(?:move|set|place|put|point)(?:\s+the)?(?:\s+mouse)?(?:\s+cursor)?(?:\s+to)?(?:\s+the)?\s+(?:center|middle)(?:\s+of)?(?:\s+the)?(?:\s+screen|\s+display)?[\.\!\?]*$",
        re.IGNORECASE,
    )
    MOVE_CORNER_PATTERN = re.compile(
        r"^(?:please\s+)?(?:move|set|place|put|point)(?:\s+the)?(?:\s+mouse)?(?:\s+cursor)?(?:\s+to)?(?:\s+the)?\s+(top[\s\-]left|top[\s\-]right|bottom[\s\-]left|bottom[\s\-]right)(?:\s+corner)?(?:\s+of)?(?:\s+the)?(?:\s+screen|\s+display)?[\.\!\?]*$",
        re.IGNORECASE,
    )
    MOVE_COORDS_PATTERN = re.compile(
        r"^(?:please\s+)?(?:move|set|place|put|point)(?:\s+the)?(?:\s+mouse)?(?:\s+cursor)?(?:\s+to)?\s*(?:x\s*[:=]\s*)?(-?\d+)\s*(?:,|\s+and\s+|\s+)\s*(?:y\s*[:=]\s*)?(-?\d+)[\.\!\?]*$",
        re.IGNORECASE,
    )

    # Regex patterns for deterministic clicks at coordinates
    CLICK_COORDS_PATTERN = re.compile(
        r"^(?:please\s+)?(?:(double|right)\s+)?click(?:\s+at)?\s*(?:x\s*[:=]\s*)?(-?\d+)\s*(?:,|\s+and\s+|\s+)\s*(?:y\s*[:=]\s*)?(-?\d+)[\.\!\?]*$",
        re.IGNORECASE,
    )

    # Regex patterns for scrolling
    SCROLL_PATTERN = re.compile(
        r"^(?:please\s+)?scroll\s+(up|down)(?:\s+by)?(?:\s+(\d+))?(?:\s+(?:notches|clicks|steps|lines|times))?[\.\!\?]*$",
        re.IGNORECASE,
    )

    # Regex patterns for single key / hotkeys
    KEY_PRESS_PATTERN = re.compile(
        r"^(?:please\s+)?press(?:\s+the)?\s+(enter|return|escape|esc|tab|space|backspace|delete|up|down|left|right|f[1-9]|f1[0-2])(?:\s+key)?[\.\!\?]*$",
        re.IGNORECASE,
    )
    HOTKEY_PATTERN = re.compile(
        r"^(?:please\s+)?(?:press|send|hotkey)\s+((?:ctrl|alt|shift|win)\s*[\+\-]\s*(?:[a-z0-9]|f[1-9]|f1[0-2]|tab|space|enter|esc))[\.\!\?]*$",
        re.IGNORECASE,
    )

    @classmethod
    def get_display_metrics(cls, display_id: str = "primary") -> Tuple[int, int, int, int]:
        """Fetch left, top, width, height for the requested display."""
        try:
            displays = WindowsScreenCaptureProvider().list_displays()
            target = next((d for d in displays if d.get("id") == display_id), None)
            if target:
                return (
                    int(target.get("x", 0)),
                    int(target.get("y", 0)),
                    int(target.get("width", 1920)),
                    int(target.get("height", 1080)),
                )
            if displays:
                d = displays[0]
                return (
                    int(d.get("x", 0)),
                    int(d.get("y", 0)),
                    int(d.get("width", 1920)),
                    int(d.get("height", 1080)),
                )
        except Exception:
            pass
        return (0, 0, 1920, 1080)

    @classmethod
    def detect(cls, user_input: str) -> Optional[DeterministicActionIntent]:
        """Classify user input into a deterministic action intent if solvable without vision."""
        text = user_input.strip()
        if not text:
            return None

        # 1. Center of the screen
        m_center = cls.MOVE_CENTER_PATTERN.match(text)
        if m_center:
            left, top, width, height = cls.get_display_metrics("primary")
            center_x = left + (width // 2)
            center_y = top + (height // 2)
            return DeterministicActionIntent(
                action_type=ActionType.MOVE,
                arguments={"x": center_x, "y": center_y},
                intent="Move mouse cursor to center of the screen",
                confidence=1.0,
                risk_level=SafetyLevel.SAFE,
                requires_confirmation=False,
            )

        # 2. Corners of the screen
        m_corner = cls.MOVE_CORNER_PATTERN.match(text)
        if m_corner:
            corner = m_corner.group(1).lower().replace("-", " ")
            left, top, width, height = cls.get_display_metrics("primary")
            if "top left" in corner:
                cx, cy = left + 10, top + 10
            elif "top right" in corner:
                cx, cy = left + width - 10, top + 10
            elif "bottom left" in corner:
                cx, cy = left + 10, top + height - 10
            else:  # bottom right
                cx, cy = left + width - 10, top + height - 10

            return DeterministicActionIntent(
                action_type=ActionType.MOVE,
                arguments={"x": cx, "y": cy},
                intent=f"Move mouse cursor to {corner} corner of the screen",
                confidence=1.0,
                risk_level=SafetyLevel.SAFE,
                requires_confirmation=False,
            )

        # 3. Explicit Coordinates Movement
        m_coords = cls.MOVE_COORDS_PATTERN.match(text)
        if m_coords:
            x_val = int(m_coords.group(1))
            y_val = int(m_coords.group(2))
            return DeterministicActionIntent(
                action_type=ActionType.MOVE,
                arguments={"x": x_val, "y": y_val},
                intent=f"Move mouse cursor to coordinates ({x_val}, {y_val})",
                confidence=1.0,
                risk_level=SafetyLevel.SAFE,
                requires_confirmation=False,
            )

        # 4. Explicit Coordinates Click
        m_click = cls.CLICK_COORDS_PATTERN.match(text)
        if m_click:
            click_type = (m_click.group(1) or "single").lower()
            x_val = int(m_click.group(2))
            y_val = int(m_click.group(3))
            
            act_type = ActionType.CLICK
            if click_type == "double":
                act_type = ActionType.DOUBLE_CLICK
            elif click_type == "right":
                act_type = ActionType.RIGHT_CLICK

            return DeterministicActionIntent(
                action_type=act_type,
                arguments={"x": x_val, "y": y_val},
                intent=f"Perform {click_type} click at coordinates ({x_val}, {y_val})",
                confidence=0.98,
                risk_level=SafetyLevel.SENSITIVE,
                requires_confirmation=True,
            )

        # 5. Scrolling
        m_scroll = cls.SCROLL_PATTERN.match(text)
        if m_scroll:
            direction = m_scroll.group(1).lower()
            count = int(m_scroll.group(2) or 3)
            delta = count * (120 if direction == "up" else -120)
            return DeterministicActionIntent(
                action_type=ActionType.SCROLL,
                arguments={"delta_y": delta},
                intent=f"Scroll {direction} by {count} steps",
                confidence=0.98,
                risk_level=SafetyLevel.SAFE,
                requires_confirmation=False,
            )

        # 6. Single Key Press
        m_key = cls.KEY_PRESS_PATTERN.match(text)
        if m_key:
            key_name = m_key.group(1).lower()
            return DeterministicActionIntent(
                action_type=ActionType.KEY_PRESS,
                arguments={"key": key_name},
                intent=f"Press {key_name} key",
                confidence=0.95,
                risk_level=SafetyLevel.SENSITIVE,
                requires_confirmation=True,
            )

        # 7. Hotkey
        m_hotkey = cls.HOTKEY_PATTERN.match(text)
        if m_hotkey:
            combo_str = m_hotkey.group(1).lower().replace(" ", "")
            keys = re.split(r"[\+\-]", combo_str)
            return DeterministicActionIntent(
                action_type=ActionType.HOTKEY,
                arguments={"keys": keys},
                intent=f"Execute hotkey combination {'+'.join(keys)}",
                confidence=0.95,
                risk_level=SafetyLevel.SENSITIVE,
                requires_confirmation=True,
            )

        return None
