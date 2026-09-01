"""Unit tests for Windows OS Settings Control tools."""

import subprocess
from unittest import mock

from friday.core.types import SafetyLevel
from friday.tools.builtin.os_settings import (
    ToggleBluetoothTool,
    ToggleDarkModeTool,
    ToggleWifiTool,
    _run_powershell_command,
)


def test_toggle_dark_mode_safety_and_name():
    """ToggleDarkModeTool is classified as SAFE."""
    tool = ToggleDarkModeTool()
    assert tool.safety_level == SafetyLevel.SAFE
    assert tool.name == "toggle_dark_mode"


def test_toggle_bluetooth_safety_and_name():
    """ToggleBluetoothTool is classified as SENSITIVE."""
    tool = ToggleBluetoothTool()
    assert tool.safety_level == SafetyLevel.SENSITIVE
    assert tool.name == "toggle_bluetooth"


def test_toggle_wifi_safety_and_name():
    """ToggleWifiTool is classified as SENSITIVE."""
    tool = ToggleWifiTool()
    assert tool.safety_level == SafetyLevel.SENSITIVE
    assert tool.name == "toggle_wifi"


def test_toggle_dark_mode_success():
    """ToggleDarkModeTool successfully issues registry commands."""
    tool = ToggleDarkModeTool()
    with mock.patch("friday.tools.builtin.os_settings._run_powershell_command") as mock_ps:
        mock_ps.return_value = (0, "", "")
        res = tool.execute(state=True)
        assert not res.is_error
        assert "Dark Mode" in res.content

        res_light = tool.execute(state=False)
        assert not res_light.is_error
        assert "Light Mode" in res_light.content


def test_toggle_dark_mode_error_handling():
    """ToggleDarkModeTool returns a clean error string on registry failure."""
    tool = ToggleDarkModeTool()
    with mock.patch("friday.tools.builtin.os_settings._run_powershell_command") as mock_ps:
        mock_ps.return_value = (1, "", "Access to the registry key is denied")
        res = tool.execute(state=True)
        assert res.is_error
        assert "Failed to set Dark Mode" in res.content
        assert "Access to the registry key is denied" in res.content


def test_toggle_bluetooth_success():
    """ToggleBluetoothTool turns Bluetooth on/off via radio state."""
    tool = ToggleBluetoothTool()
    with mock.patch("friday.tools.builtin.os_settings._run_powershell_command") as mock_ps:
        mock_ps.return_value = (0, "Success", "")
        res = tool.execute(state=True)
        assert not res.is_error
        assert "Bluetooth has been turned On." in res.content


def test_toggle_bluetooth_failure_handling():
    """ToggleBluetoothTool handles radio errors or missing hardware gracefully."""
    tool = ToggleBluetoothTool()
    with mock.patch("friday.tools.builtin.os_settings._run_powershell_command") as mock_ps:
        mock_ps.return_value = (0, "No Bluetooth radio found", "")
        res = tool.execute(state=False)
        assert res.is_error
        assert "No Bluetooth radio found" in res.content


def test_toggle_wifi_success():
    """ToggleWifiTool enables and disables the network interface."""
    tool = ToggleWifiTool()
    with mock.patch("friday.tools.builtin.os_settings._run_powershell_command") as mock_ps:
        mock_ps.return_value = (0, "", "")
        res = tool.execute(state=True, interface_name="Wi-Fi")
        assert not res.is_error
        assert "Wi-Fi (Wi-Fi) has been enabled." in res.content


def test_toggle_wifi_error_handling():
    """ToggleWifiTool captures interface error without raising exceptions."""
    tool = ToggleWifiTool()
    with mock.patch("friday.tools.builtin.os_settings._run_powershell_command") as mock_ps:
        mock_ps.return_value = (1, "", "An interface with this name is not registered with the router.")
        res = tool.execute(state=False, interface_name="Wi-Fi")
        assert res.is_error
        assert "Failed to turn Wi-Fi disabled" in res.content


def test_run_powershell_command_timeout():
    """_run_powershell_command handles timeout cleanly."""
    with mock.patch("subprocess.run") as mock_sub:
        mock_sub.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5.0)
        code, out, err = _run_powershell_command("Get-Process", timeout=5.0)
        assert code == 1
        assert "timed out" in err
