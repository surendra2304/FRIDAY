# -*- coding: utf-8 -*-
"""OS control tools: system volume, power actions, and window management.

All tools are Windows-native and degrade gracefully when the underlying
library or OS feature is unavailable. Dangerous power actions (shutdown,
restart) are refused here and must go through the SENSITIVE text-mode
authorization path.
"""

from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.os_control")


# ---------------------------------------------------------------------------
# System volume (pycaw / Windows Core Audio)
# ---------------------------------------------------------------------------


def _get_endpoint_volume():
    """Lazily resolve the default audio endpoint volume control via pycaw.

    Compatible with both legacy pycaw (GetSpeakers() returns the raw COM
    IMMDevice exposing .Activate) and 2025+ pycaw (returns a high-level
    AudioDevice wrapper whose ._dev holds the COM device).
    """
    try:
        import comtypes

        comtypes.CoInitialize()
    except Exception:
        pass
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    device = AudioUtilities.GetSpeakers()
    raw = getattr(device, "_dev", device)
    interface = raw.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return interface.QueryInterface(IAudioEndpointVolume)


class ManageVolumeTool(BaseTool):
    """Mute, unmute, or set the system master volume."""

    name = "manage_volume"
    description = (
        "Control the system master volume. Actions: 'mute', 'unmute', 'set' "
        "(requires level 0-100 as the speaker volume percentage)."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["mute", "unmute", "set"], "description": "Volume action."},
            "level": {"type": "integer", "description": "Volume percentage 0-100 (only for action='set')."},
        },
        "required": ["action"],
    }

    def execute(self, action: str = "", level: int = None, **kwargs: Any) -> ToolResult:
        action = (action or "").strip().lower()
        try:
            vol = _get_endpoint_volume()
        except Exception as e:
            return ToolResult(
                name=self.name,
                content=f"Volume control unavailable on this system: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )

        try:
            if action == "mute":
                vol.SetMute(1, None)
                return ToolResult(name=self.name, content="Volume muted.", is_error=False,
                                  safety_level=self.safety_level)
            if action == "unmute":
                vol.SetMute(0, None)
                return ToolResult(name=self.name, content="Volume unmuted.", is_error=False,
                                  safety_level=self.safety_level)
            if action == "set":
                if level is None or not (0 <= int(level) <= 100):
                    return ToolResult(
                        name=self.name,
                        content="action='set' requires level between 0 and 100.",
                        is_error=True, safety_level=self.safety_level,
                    )
                vol.SetMasterVolumeLevelScalar(int(level) / 100.0, None)
                return ToolResult(name=self.name, content=f"Volume set to {int(level)}%.",
                                  is_error=False, safety_level=self.safety_level)
            return ToolResult(name=self.name, content=f"Unknown action '{action}'.",
                              is_error=True, safety_level=self.safety_level)
        except Exception as e:
            return ToolResult(name=self.name, content=f"Volume action failed: {e}",
                              is_error=True, safety_level=self.safety_level)


# ---------------------------------------------------------------------------
# System power (safe actions only; dangerous actions require SENSITIVE path)
# ---------------------------------------------------------------------------


_SAFE_POWER_ACTIONS = {"lock", "sleep"}
_SENSITIVE_POWER_ACTIONS = {"shutdown", "restart", "reboot"}


class SystemPowerControlTool(BaseTool):
    """Lock the screen or put the computer to sleep.

    shutdown/restart are DANGEROUS system-wide actions: this SAFE tool refuses
    them and directs the user to explicit text-mode SENSITIVE authorization.
    """

    name = "system_power_control"
    description = (
        "Perform a system power action. Safe actions: 'lock' (lock the screen), "
        "'sleep' (put the computer to sleep). Actions 'shutdown' and 'restart' are "
        "refused by this tool and require explicit text-mode authorization."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["lock", "sleep", "shutdown", "restart"],
                       "description": "Power action to perform."},
        },
        "required": ["action"],
    }

    def execute(self, action: str = "", **kwargs: Any) -> ToolResult:
        import subprocess

        act = (action or "").strip().lower()
        if act in _SENSITIVE_POWER_ACTIONS or "restart" == act or "reboot" == act:
            return ToolResult(
                name=self.name,
                content=(
                    f"'{act}' is a dangerous system-wide action and is not available through "
                    "this tool. It requires explicit SENSITIVE text-mode authorization."
                ),
                is_error=True, safety_level=self.safety_level,
            )
        if act == "lock":
            try:
                import ctypes
                ctypes.windll.user32.LockWorkStation()
                return ToolResult(name=self.name, content="Screen locked.", is_error=False,
                                  safety_level=self.safety_level)
            except Exception as e:
                return ToolResult(name=self.name, content=f"Failed to lock screen: {e}",
                                  is_error=True, safety_level=self.safety_level)
        if act == "sleep":
            try:
                subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                               check=True, timeout=10)
                return ToolResult(name=self.name, content="Sleep requested.", is_error=False,
                                  safety_level=self.safety_level)
            except Exception as e:
                return ToolResult(name=self.name, content=f"Failed to sleep: {e}",
                                  is_error=True, safety_level=self.safety_level)
        return ToolResult(name=self.name, content=f"Unknown action '{act}'.",
                          is_error=True, safety_level=self.safety_level)


# ---------------------------------------------------------------------------
# Window management (minimize / maximize / restore / focus)
# ---------------------------------------------------------------------------


_WINDOW_ACTIONS = {"minimize", "maximize", "restore", "focus"}


class ManageWindowsTool(BaseTool):
    """Minimize, maximize, restore, or focus a window by title substring."""

    name = "manage_windows"
    description = (
        "Manage an open window: actions 'minimize', 'maximize', 'restore', or 'focus'. "
        "The window is found by title substring (e.g. 'Notepad' matches 'Untitled - Notepad')."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "window_title": {"type": "string", "description": "Substring of the window title."},
            "action": {"type": "string", "enum": ["minimize", "maximize", "restore", "focus"],
                       "description": "Window action."},
        },
        "required": ["window_title", "action"],
    }

    def execute(self, window_title: str = "", action: str = "", **kwargs: Any) -> ToolResult:
        from friday.tools.builtin.close_application import _find_window

        title = (window_title or "").strip()
        act = (action or "").strip().lower()
        if not title:
            return ToolResult(name=self.name, content="No window title provided.", is_error=True,
                              safety_level=self.safety_level)
        if act not in _WINDOW_ACTIONS:
            return ToolResult(name=self.name, content=f"Unknown action '{act}'.", is_error=True,
                              safety_level=self.safety_level)

        window = _find_window(title)
        if window is None:
            return ToolResult(name=self.name, content=f"No open window matching '{title}'.",
                              is_error=True, safety_level=self.safety_level)

        try:
            if act == "minimize":
                window.minimize()
            elif act == "maximize":
                window.maximize()
            elif act == "restore":
                window.restore()
            else:  # focus
                window.set_focus()
            return ToolResult(name=self.name, content=f"Performed '{act}' on '{window.window_text()}'.",
                              is_error=False, safety_level=self.safety_level)
        except Exception as e:
            return ToolResult(name=self.name, content=f"Window action failed: {e}",
                              is_error=True, safety_level=self.safety_level)
