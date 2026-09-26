"""Media Control Tool for system audio playback and media app control."""

from __future__ import annotations

import sys
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.media_control")

# Windows Virtual Key Codes for Media
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
KEYEVENTF_KEYUP = 0x0002


def _send_windows_media_key(vk_code: int) -> bool:
    """Simulate a Windows media key press using user32.dll."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        user32 = ctypes.windll.user32
        user32.keybd_event(vk_code, 0, 0, 0)
        user32.keybd_event(vk_code, 0, KEYEVENTF_KEYUP, 0)
        return True
    except Exception as e:
        logger.warning(f"Failed to send Windows media key {vk_code}: {e}")
        return False


class MediaControlTool(BaseTool):
    """Send system-wide media keys and adjust system volume on Windows."""

    name = "media_control"
    description = (
        "Send system-wide Windows media-key actions: 'play_pause', 'next', 'previous', "
        "'volume_up', 'volume_down', or 'mute'. Media keys act on whichever media session Windows "
        "routes them to; they do not select a track, target Spotify specifically, or prove playback started. "
        "Use a service-specific integration for track search or playback."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["play_pause", "next", "previous", "volume_up", "volume_down", "mute"],
                "description": "Media operation to perform.",
            },
        },
        "required": ["action"],
    }

    def execute(self, action: str, **kwargs: Any) -> ToolResult:
        act = (action or "play_pause").lower().strip()

        if act in ("play_pause", "play", "pause"):
            ok = _send_windows_media_key(VK_MEDIA_PLAY_PAUSE)
            if ok:
                return ToolResult(
                    name=self.name,
                    content="Toggled media playback (Play/Pause).",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            return self._unavailable(act)

        elif act == "next":
            ok = _send_windows_media_key(VK_MEDIA_NEXT_TRACK)
            if ok:
                return ToolResult(
                    name=self.name,
                    content="Skipped to next track.",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            return self._unavailable(act)

        elif act in ("previous", "prev"):
            ok = _send_windows_media_key(VK_MEDIA_PREV_TRACK)
            if ok:
                return ToolResult(
                    name=self.name,
                    content="Skipped to previous track.",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            return self._unavailable(act)

        elif act == "volume_up":
            if not all(_send_windows_media_key(VK_VOLUME_UP) for _ in range(3)):
                return self._unavailable(act)
            return ToolResult(
                name=self.name,
                content="Increased volume.",
                is_error=False,
                safety_level=self.safety_level,
            )

        elif act == "volume_down":
            if not all(_send_windows_media_key(VK_VOLUME_DOWN) for _ in range(3)):
                return self._unavailable(act)
            return ToolResult(
                name=self.name,
                content="Decreased volume.",
                is_error=False,
                safety_level=self.safety_level,
            )

        elif act == "mute":
            ok = _send_windows_media_key(VK_VOLUME_MUTE)
            if not ok:
                return self._unavailable(act)
            return ToolResult(
                name=self.name,
                content="Toggled audio mute.",
                is_error=False,
                safety_level=self.safety_level,
            )

        return ToolResult(
            name=self.name,
            content=f"Unsupported media action '{act}'. No action was performed.",
            is_error=True,
            safety_level=self.safety_level,
        )

    def _unavailable(self, action: str) -> ToolResult:
        """Report a failed OS media-key request without implying it took effect."""
        return ToolResult(
            name=self.name,
            content=(
                f"Could not perform '{action}': the Windows media-key operation was unavailable. "
                "No playback or volume change is confirmed."
            ),
            is_error=True,
            safety_level=self.safety_level,
        )
