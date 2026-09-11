# -*- coding: utf-8 -*-
"""Unit tests for AndroidDeviceController security hardening."""

from unittest.mock import patch, MagicMock
import pytest

from friday.devices.android_controller import AndroidDeviceController


def test_android_run_adb_blocks_dangerous_commands():
    """Verify dangerous ADB commands like root, install, pull are blocked."""
    controller = AndroidDeviceController()

    for dangerous in ["root", "remount", "install", "pull", "push", "recovery"]:
        rc, out, err = controller.run_adb([dangerous])
        assert rc == -1
        assert "blocked" in err.lower()


def test_android_shell_blocks_dangerous_tokens():
    """Verify shell execution blocks su, rm, reboot, etc."""
    controller = AndroidDeviceController()

    res = controller.shell("rm -rf /sdcard/Photos")
    assert "Error: Command contains restricted token" in res

    res = controller.shell("su -c id")
    assert "Error: Command contains restricted token" in res

    res = controller.shell("reboot")
    assert "Error: Command contains restricted token" in res


def test_android_run_adb_allows_safe_commands():
    """Verify safe diagnostic queries pass through to subprocess."""
    controller = AndroidDeviceController()

    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "List of devices attached\n12345678\tdevice\n"
    mock_res.stderr = ""

    with patch("subprocess.run", return_value=mock_res):
        rc, out, err = controller.run_adb(["devices"])
        assert rc == 0
        assert "12345678" in out


def test_android_app_package_validation():
    """Verify package names with shell injection characters are rejected."""
    controller = AndroidDeviceController()

    with patch.object(controller, "run_adb", return_value=(0, "", "")) as mock_adb:
        assert not controller.open_app("com.android.settings; reboot")
        assert not controller.close_app("com.android.settings && rm -rf /")
        mock_adb.assert_not_called()

        assert controller.open_app("settings")
        mock_adb.assert_called()


def test_android_type_text_shell_quoting():
    """Verify type_text safely shell-quotes metacharacters."""
    controller = AndroidDeviceController()

    with patch.object(controller, "run_adb", return_value=(0, "", "")) as mock_adb:
        controller.type_text("hello; reboot")
        mock_adb.assert_called_once()
        args = mock_adb.call_args[0][0]
        assert args[:3] == ["shell", "input", "text"]
        # In single-quoted shell argument, semicolon cannot be interpreted as command separator
        assert args[3].startswith("'") and args[3].endswith("'")
        assert ";%sreboot" in args[3]


def test_android_shell_path_and_quote_bypass_blocked():
    """Verify shell execution blocks absolute paths and quoted tokens."""
    controller = AndroidDeviceController()

    res = controller.shell("/system/bin/rm -rf /sdcard")
    assert "Error: Command contains restricted token" in res

    res = controller.shell('"/system/bin/reboot"')
    assert "Error: Command contains restricted token" in res
