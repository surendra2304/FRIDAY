# -*- coding: utf-8 -*-
"""Base interfaces and data structures for FRIDAY Screen Capture subsystem."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ScreenSnapshot:
    """Container holding captured desktop screen snapshot metadata and raw image bytes."""

    image_data: bytes
    mime_type: str = "image/png"
    width: int = 0
    height: int = 0
    display_id: str = "primary"
    captured_at: datetime = field(default_factory=datetime.utcnow)
    is_error: bool = False
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return safe non-image dictionary metadata (zero raw image data exposed)."""
        return {
            "mime_type": self.mime_type,
            "width": self.width,
            "height": self.height,
            "display_id": self.display_id,
            "size_bytes": len(self.image_data) if self.image_data else 0,
            "captured_at": self.captured_at.isoformat(),
            "is_error": self.is_error,
            "error_message": self.error_message,
        }

    def __repr__(self) -> str:
        """Safe representation without dumping raw image bytes."""
        return (
            f"ScreenSnapshot(display={self.display_id!r}, "
            f"dim={self.width}x{self.height}, "
            f"size={len(self.image_data) if self.image_data else 0}B, "
            f"error={self.is_error})"
        )


class BaseScreenCaptureProvider(ABC):
    """Abstract interface for OS screen capture providers."""

    @abstractmethod
    def capture_screen(
        self,
        display: str = "primary",
        **kwargs: Any,
    ) -> ScreenSnapshot:
        """Capture screenshot from the specified display.

        Args:
            display: 'primary' or display index / identifier.
            **kwargs: Provider-specific options.

        Returns:
            ScreenSnapshot object with raw image bytes and dimensions.
        """
        pass

    @abstractmethod
    def list_displays(self) -> List[Dict[str, Any]]:
        """Return metadata for all available system displays."""
        pass
