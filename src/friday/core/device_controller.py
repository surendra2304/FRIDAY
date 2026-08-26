# -*- coding: utf-8 -*-
"""Base Device Controller Abstraction for FRIDAY (Inspired by OpenJarvis).

Defines an operating system and hardware-agnostic interface for controlling devices
(Windows desktop, Android mobile, remote browser/sandbox, or headless mock).
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class BaseDeviceController(ABC):
    """Abstract Base Class for multi-platform device controllers."""

    device_type: str = "base"

    @abstractmethod
    def open_app(self, name: str) -> bool:
        """Launch or switch to an application by common name or identifier."""
        pass

    @abstractmethod
    def click(self, x: int, y: int) -> bool:
        """Synthesize a cursor or touch tap at coordinate (x, y)."""
        pass

    @abstractmethod
    def type_text(self, text: str) -> bool:
        """Type literal text into the active input focus."""
        pass

    @abstractmethod
    def screenshot(self) -> Optional[Any]:
        """Capture the current display as an image buffer or PIL Image."""
        pass

    @abstractmethod
    def read_screen_text(self) -> str:
        """Extract visible text from the current screen (OCR or accessibility tree)."""
        pass

    def close_app(self, name: str) -> bool:
        """Close an application by name (optional best-effort implementation)."""
        return False

    def press_key(self, key: str) -> bool:
        """Press a keyboard or hardware navigation key."""
        return False
