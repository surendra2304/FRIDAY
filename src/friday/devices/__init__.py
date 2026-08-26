# -*- coding: utf-8 -*-
"""FRIDAY Device Control Abstractions (Inspired by OpenJarvis)."""

from typing import Any, Optional
from friday.core.device_controller import BaseDeviceController
from friday.devices.windows_controller import WindowsDeviceController
from friday.devices.android_controller import AndroidDeviceController


def get_device_controller(
    device_name: Optional[str] = None,
    settings: Optional[Any] = None,
) -> BaseDeviceController:
    """Factory to retrieve the active device controller based on settings or explicit device name."""
    if not device_name:
        if settings is None:
            try:
                from friday.core.config import get_settings
                settings = get_settings()
            except Exception:
                settings = None
        device_name = getattr(settings, "active_device", "windows") if settings else "windows"

    target = (device_name or "windows").lower().strip()
    if target == "android":
        return AndroidDeviceController()
    elif target in ("windows", "win32", "pc", "desktop"):
        tess_cmd = getattr(settings, "tesseract_cmd", None) if settings else None
        return WindowsDeviceController(tesseract_cmd=tess_cmd)
    else:
        return WindowsDeviceController()


__all__ = [
    "BaseDeviceController",
    "WindowsDeviceController",
    "AndroidDeviceController",
    "get_device_controller",
]
