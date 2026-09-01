"""Tests for FRIDAY Device Control Abstractions (Inspired by OpenJarvis)."""

from unittest.mock import MagicMock, patch

import pytest

from friday.core.device_controller import BaseDeviceController
from friday.devices import get_device_controller
from friday.devices.android_controller import AndroidDeviceController
from friday.devices.windows_controller import WindowsDeviceController


def test_base_device_controller_inheritance():
    """Verify BaseDeviceController defines required abstract methods."""
    class CustomDevice(BaseDeviceController):
        device_type = "custom"

        def open_app(self, name: str) -> bool:
            return True

        def click(self, x: int, y: int) -> bool:
            return True

        def type_text(self, text: str) -> bool:
            return True

        def screenshot(self):
            return None

        def read_screen_text(self) -> str:
            return "Sample OCR"

    dev = CustomDevice()
    assert dev.open_app("notepad") is True
    assert dev.click(100, 200) is True
    assert dev.type_text("hello") is True
    assert dev.screenshot() is None
    assert dev.read_screen_text() == "Sample OCR"
    assert dev.close_app("notepad") is False


def test_android_device_controller_stub():
    """AndroidDeviceController raises NotImplementedError with clear messages."""
    android = AndroidDeviceController()
    assert android.device_type == "android"

    with pytest.raises(NotImplementedError, match="ADB is not yet implemented"):
        android.open_app("com.example.app")

    with pytest.raises(NotImplementedError, match="ADB is not yet implemented"):
        android.click(100, 200)

    with pytest.raises(NotImplementedError, match="ADB is not yet implemented"):
        android.type_text("hello")

    with pytest.raises(NotImplementedError, match="ADB is not yet implemented"):
        android.screenshot()

    with pytest.raises(NotImplementedError, match="ADB is not yet implemented"):
        android.read_screen_text()


def test_windows_device_controller_launch():
    """WindowsDeviceController launches application cleanly."""
    win = WindowsDeviceController()
    assert win.device_type == "windows"

    with patch("os.startfile", create=True) as mock_startfile:
        res = win.open_app("notepad")
        assert res is True
        mock_startfile.assert_called_once_with("notepad.exe")


def test_get_device_controller_factory():
    """get_device_controller factory resolves settings and explicit target."""
    win_dev = get_device_controller("windows")
    assert isinstance(win_dev, WindowsDeviceController)

    android_dev = get_device_controller("android")
    assert isinstance(android_dev, AndroidDeviceController)

    # Test settings object resolution
    mock_settings = MagicMock()
    mock_settings.active_device = "android"
    resolved = get_device_controller(settings=mock_settings)
    assert isinstance(resolved, AndroidDeviceController)
