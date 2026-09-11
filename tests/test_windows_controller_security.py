# -*- coding: utf-8 -*-
"""Unit tests for WindowsDeviceController security hardening."""

from unittest.mock import patch, MagicMock
import pytest

from friday.devices.windows_controller import (
    WindowsDeviceController,
    APP_ALLOWLIST,
    BLOCKED_EXECUTABLES,
    CRITICAL_SYSTEM_PROCESSES,
)


def test_open_app_allowlist_enforcement():
    """Verify non-allowlisted apps and blocked binaries are rejected."""
    controller = WindowsDeviceController()

    # Blocked shell
    assert controller.open_app("cmd.exe") is False
    assert controller.open_app("powershell.exe") is False

    # Unknown app
    assert controller.open_app("malicious_hax_tool") is False


def test_open_app_safe_subprocess_spawn():
    """Verify allowlisted app is spawned with shell=False and safe list arguments."""
    controller = WindowsDeviceController()

    with patch("subprocess.Popen") as mock_popen, patch("shutil.which", return_value="C:\\Windows\\System32\\notepad.exe"):
        success = controller.open_app("notepad")
        assert success is True
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        assert kwargs.get("shell") is False
        assert "notepad.exe" in args[0][0].lower()


def test_close_app_avoids_critical_system_processes():
    """Verify critical system processes are never terminated."""
    controller = WindowsDeviceController()

    mock_proc = MagicMock()
    mock_proc.info = {"pid": 4, "name": "System"}

    with patch("psutil.process_iter", return_value=[mock_proc]):
        # Even if user asks to close 'system', it should be protected
        closed = controller.close_app("system")
        assert closed is False
        mock_proc.terminate.assert_not_called()


def test_close_app_exact_match_not_substring():
    """Verify close_app does not terminate apps by broad substring match."""
    controller = WindowsDeviceController()

    mock_proc1 = MagicMock()
    mock_proc1.info = {"pid": 100, "name": "chrome.exe"}

    mock_proc2 = MagicMock()
    mock_proc2.info = {"pid": 101, "name": "notepad.exe"}

    with patch("psutil.process_iter", return_value=[mock_proc1, mock_proc2]):
        # "not" should not match "notepad.exe"
        closed = controller.close_app("not")
        assert closed is False
        mock_proc1.terminate.assert_not_called()
        mock_proc2.terminate.assert_not_called()

        # "notepad" should match notepad.exe exactly
        closed = controller.close_app("notepad")
        assert closed is True
        mock_proc2.terminate.assert_called_once()
