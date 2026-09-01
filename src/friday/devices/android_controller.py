"""Android Device Controller stub for FRIDAY (Inspired by OpenJarvis).

Provides the standard device interface for remote or connected Android phones/tablets.
"""

from typing import Any

from friday.core.device_controller import BaseDeviceController
from friday.core.logging import get_logger

logger = get_logger("devices.android")


class AndroidDeviceController(BaseDeviceController):
    """Android Device Controller (ADB bridge scaffold)."""

    device_type: str = "android"

    def __init__(self, adb_device_id: str | None = None) -> None:
        self.adb_device_id = adb_device_id
        # TODO: Implement Android device automation using ADB (Android Debug Bridge)

    def open_app(self, name: str) -> bool:
        """Launch an Android package or activity via ADB monkey/am start."""
        # TODO: Implement Android device automation using ADB (Android Debug Bridge)
        raise NotImplementedError("Android device controller via ADB is not yet implemented.")

    def click(self, x: int, y: int) -> bool:
        """Synthesize a tap on the Android touch digitizer via 'adb shell input tap x y'."""
        # TODO: Implement Android device automation using ADB (Android Debug Bridge)
        raise NotImplementedError("Android device controller via ADB is not yet implemented.")

    def type_text(self, text: str) -> bool:
        """Send key events or input text via 'adb shell input text'."""
        # TODO: Implement Android device automation using ADB (Android Debug Bridge)
        raise NotImplementedError("Android device controller via ADB is not yet implemented.")

    def screenshot(self) -> Any | None:
        """Capture Android framebuffer using 'adb exec-out screencap -p'."""
        # TODO: Implement Android device automation using ADB (Android Debug Bridge)
        raise NotImplementedError("Android device controller via ADB is not yet implemented.")

    def read_screen_text(self) -> str:
        """Extract text from UI hierarchy XML or OCR."""
        # TODO: Implement Android device automation using ADB (Android Debug Bridge)
        raise NotImplementedError("Android device controller via ADB is not yet implemented.")
