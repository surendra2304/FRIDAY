"""Android Automation Tools for Surendra's FRIDAY.

Enables FRIDAY to interact with physical or emulated Android devices:
- Tap touch digitizer coordinates
- Swipe / drag gestures
- Type text into focused input fields
- Press navigation / hardware keys (Home, Back, Recents, Power, Volume, Enter)
- Launch applications by name or package identifier
- Capture device screenshots
- Inspect connected devices and battery/system status
"""

from __future__ import annotations

from typing import Any

from friday.core.types import SafetyLevel, ToolResult
from friday.devices.android_controller import AndroidDeviceController, COMMON_APP_PACKAGES, KEY_EVENT_MAP
from friday.tools.base import BaseTool

_controller = AndroidDeviceController()


class AndroidTapTool(BaseTool):
    """Taps the screen of a connected Android device at (x, y) coordinates."""

    name = "android_tap"
    description = "Taps the Android device screen at the specified pixel coordinates (x, y)."
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "X coordinate on the Android touchscreen"},
            "y": {"type": "integer", "description": "Y coordinate on the Android touchscreen"},
        },
        "required": ["x", "y"],
    }

    def execute(self, x: int, y: int, **kwargs: Any) -> ToolResult:
        success = _controller.click(int(x), int(y))
        if success:
            return ToolResult(name=self.name, content=f"Successfully tapped Android touchscreen at ({x}, {y}).")
        return ToolResult(
            name=self.name,
            content=f"Failed to tap Android screen at ({x}, {y}). Ensure an authorized device is connected via ADB.",
            is_error=True,
        )


class AndroidSwipeTool(BaseTool):
    """Performs a touch drag or swipe gesture on a connected Android device."""

    name = "android_swipe"
    description = "Swipes the Android device screen from (x1, y1) to (x2, y2) with optional duration in milliseconds."
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "x1": {"type": "integer", "description": "Starting X coordinate"},
            "y1": {"type": "integer", "description": "Starting Y coordinate"},
            "x2": {"type": "integer", "description": "Ending X coordinate"},
            "y2": {"type": "integer", "description": "Ending Y coordinate"},
            "duration_ms": {"type": "integer", "description": "Duration in milliseconds (default: 300)", "default": 300},
        },
        "required": ["x1", "y1", "x2", "y2"],
    }

    def execute(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300, **kwargs: Any) -> ToolResult:
        success = _controller.swipe(int(x1), int(y1), int(x2), int(y2), int(duration_ms))
        if success:
            return ToolResult(
                name=self.name,
                content=f"Successfully swiped Android screen from ({x1}, {y1}) to ({x2}, {y2}) over {duration_ms}ms.",
            )
        return ToolResult(
            name=self.name,
            content="Failed to swipe Android screen. Verify ADB connection.",
            is_error=True,
        )


class AndroidTypeTool(BaseTool):
    """Types text into the currently focused text field on an Android device."""

    name = "android_type"
    description = "Types literal text into the active input focus on the connected Android device."
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to type into the focused field"},
        },
        "required": ["text"],
    }

    def execute(self, text: str, **kwargs: Any) -> ToolResult:
        success = _controller.type_text(str(text))
        if success:
            return ToolResult(name=self.name, content=f"Successfully typed text '{text}' on Android device.")
        return ToolResult(
            name=self.name,
            content="Failed to type text on Android device. Ensure a text field has keyboard focus.",
            is_error=True,
        )


class AndroidKeyEventTool(BaseTool):
    """Sends a hardware or navigation key event to the Android device."""

    name = "android_keyevent"
    description = (
        "Sends a key event to the Android device: 'home', 'back', 'app_switch', 'power', "
        "'volume_up', 'volume_down', 'enter', 'space', 'tab', 'delete'."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Key event name (e.g. 'home', 'back', 'app_switch', 'power', 'enter')",
            },
        },
        "required": ["key"],
    }

    def execute(self, key: str, **kwargs: Any) -> ToolResult:
        success = _controller.press_key(str(key))
        if success:
            return ToolResult(name=self.name, content=f"Pressed Android key '{key}'.")
        return ToolResult(
            name=self.name,
            content=f"Failed to press Android key '{key}'. Supported: {', '.join(sorted(KEY_EVENT_MAP.keys()))}.",
            is_error=True,
        )


class AndroidOpenAppTool(BaseTool):
    """Launches an application package on the Android device."""

    name = "android_open_app"
    description = (
        "Launches an Android application by common name (e.g. 'youtube', 'chrome', 'whatsapp', "
        "'settings', 'camera', 'calculator', 'spotify', 'maps') or package ID."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "app_name": {
                "type": "string",
                "description": "App name (e.g. 'youtube', 'chrome', 'whatsapp') or full package identifier",
            },
        },
        "required": ["app_name"],
    }

    def execute(self, app_name: str, **kwargs: Any) -> ToolResult:
        success = _controller.open_app(str(app_name))
        if success:
            return ToolResult(name=self.name, content=f"Successfully launched Android app '{app_name}'.")
        return ToolResult(
            name=self.name,
            content=f"Failed to launch Android app '{app_name}'. Supported aliases: {', '.join(sorted(COMMON_APP_PACKAGES.keys()))}.",
            is_error=True,
        )


class AndroidDeviceInfoTool(BaseTool):
    """Checks ADB connectivity, lists attached Android devices, and returns system info."""

    name = "android_device_info"
    description = "Inspects ADB connectivity, attached Android devices, battery level, and model status."
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
    }

    def execute(self, **kwargs: Any) -> ToolResult:
        devices = _controller.list_devices()
        if not devices:
            return ToolResult(
                name=self.name,
                content="No authorized Android devices detected over ADB. Connect an Android phone with USB Debugging enabled.",
            )

        details = [f"Found {len(devices)} connected Android device(s):"]
        for d in devices:
            details.append(f" - Device ID: {d['id']} | Status: {d['status']} | Model: {d['model']}")

        # Read battery info from first device
        rc, battery, _ = _controller.run_adb(["shell", "dumpsys", "battery"])
        if rc == 0 and battery:
            level_line = [ln.strip() for ln in battery.splitlines() if "level:" in ln]
            if level_line:
                details.append(f" - Battery: {level_line[0]}")

        return ToolResult(name=self.name, content="\n".join(details))


# Aliases for backward compatibility
TapScreenTool = AndroidTapTool
SwipeScreenTool = AndroidSwipeTool
TypeTextTool = AndroidTypeTool
OpenAndroidAppTool = AndroidOpenAppTool

