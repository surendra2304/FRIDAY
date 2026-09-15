"""Tests for FRIDAY Device Control Abstractions (Inspired by open-source operator frameworks)."""

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
    """AndroidDeviceController returns False when ADB is missing."""
    android = AndroidDeviceController()
    assert android.device_type == "android"

    # Should return False when adb is missing or fails
    assert android.open_app("com.example.app") is False
    assert android.click(100, 200) is False

    assert android.type_text("hello") is False
    assert android.press_key("enter") is False
    assert android.close_app("com.example.app") is False


def test_windows_device_controller_launch():
    """WindowsDeviceController launches application cleanly."""
    win = WindowsDeviceController()
    assert win.device_type == "windows"

    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value.pid = 9999
        with patch("psutil.process_iter") as mock_psutil:
            from unittest.mock import Mock
            mock_process = Mock()
            mock_process.info = {"name": "notepad.exe", "pid": 9999}
            mock_psutil.return_value = [mock_process]
            res = win.open_app("notepad")
            assert res is True
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            assert args[0] == "notepad.exe" or args[0].endswith("\\notepad.exe")


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
