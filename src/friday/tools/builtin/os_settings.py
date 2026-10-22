"""Windows OS Settings Control tools.

Provides voice & agent tools to control Windows OS settings via PowerShell & registry edits:
- toggle_dark_mode: Toggles AppsUseLightTheme and SystemUsesLightTheme (SAFE)
- toggle_bluetooth: Turns Bluetooth on/off via PowerShell Radio control (SENSITIVE)
- toggle_wifi: Turns Wi-Fi interface on/off via netsh interface (SENSITIVE)
"""

import subprocess
from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.os_settings")

_DEFAULT_POWERSHELL_TIMEOUT = 10.0


def _run_powershell_command(command: str, timeout: float = _DEFAULT_POWERSHELL_TIMEOUT) -> tuple[int, str, str]:
    """Execute a PowerShell command safely and return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout.strip(), proc.stderr.strip()
    except subprocess.TimeoutExpired:
        logger.warning(f"PowerShell command timed out after {timeout}s: {command}")
        return 1, "", f"PowerShell command timed out after {timeout} seconds."
    except Exception as e:
        logger.error(f"PowerShell execution failed: {e}")
        return 1, "", str(e)


class ToggleDarkModeTool(BaseTool):
    """Toggle Windows Dark Mode vs Light Mode via Registry."""

    name = "toggle_dark_mode"
    description = (
        "Toggle Windows system and app theme between Dark Mode and Light Mode. "
        "Pass state=True for Dark Mode, state=False for Light Mode."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "state": {
                "type": "boolean",
                "description": "True to enable Dark Mode, False to enable Light Mode.",
            },
        },
        "required": ["state"],
    }

    def execute(self, state: bool, **kwargs: Any) -> ToolResult:
        # Dark mode in Windows registry: 0 = Dark, 1 = Light
        reg_val = 0 if state else 1
        theme_name = "Dark Mode" if state else "Light Mode"

        cmd = (
            f"Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name 'AppsUseLightTheme' -Value {reg_val} -Type DWord; "
            f"Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name 'SystemUsesLightTheme' -Value {reg_val} -Type DWord"
        )

        code, out, err = _run_powershell_command(cmd)
        if code != 0:
            msg = f"Failed to set {theme_name}: {err or out or 'Unknown registry error'}"
            logger.warning(msg)
            return ToolResult(
                name=self.name,
                content=msg,
                is_error=True,
                safety_level=self.safety_level,
            )

        logger.info(f"Windows theme set to {theme_name}")
        return ToolResult(
            name=self.name,
            content=f"Windows theme successfully switched to {theme_name}.",
            is_error=False,
            safety_level=self.safety_level,
            metadata={"dark_mode": state, "theme": theme_name},
        )


class ToggleBluetoothTool(BaseTool):
    """Toggle Windows Bluetooth radio on or off. Marked SENSITIVE."""

    name = "toggle_bluetooth"
    description = (
        "Turn Bluetooth on or off on the Windows system. "
        "Requires authorization as a SENSITIVE action."
    )
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "state": {
                "type": "boolean",
                "description": "True to turn Bluetooth ON, False to turn Bluetooth OFF.",
            },
        },
        "required": ["state"],
    }

    def execute(self, state: bool, **kwargs: Any) -> ToolResult:
        status_target = "On" if state else "Off"
        # Using Windows Runtime Radio control in PowerShell
        ps_cmd = (
            f"[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null; "
            f"$radios = [Windows.Devices.Radios.Radio]::GetRadiosAsync().GetAwaiter().GetResult(); "
            f"$bt = $radios | Where-Object {{ $_.Kind -eq 'Bluetooth' }}; "
            f"if ($bt) {{ $bt.SetStateAsync('{status_target}').GetAwaiter().GetResult() | Out-Null; 'Success' }} "
            f"else {{ 'No Bluetooth radio found' }}"
        )

        code, out, err = _run_powershell_command(ps_cmd)
        if code != 0 or "No Bluetooth radio found" in out:
            msg = f"Failed to turn Bluetooth {status_target}: {err or out or 'No Bluetooth radio found'}"
            logger.warning(msg)
            return ToolResult(
                name=self.name,
                content=msg,
                is_error=True,
                safety_level=self.safety_level,
            )

        logger.info(f"Windows Bluetooth set to {status_target}")
        return ToolResult(
            name=self.name,
            content=f"Bluetooth has been turned {status_target}.",
            is_error=False,
            safety_level=self.safety_level,
            metadata={"bluetooth_state": status_target},
        )


class ToggleWifiTool(BaseTool):
    """Toggle Windows Wi-Fi interface on or off. Marked SENSITIVE."""

    name = "toggle_wifi"
    description = (
        "Turn Wi-Fi networking interface on or off on the Windows system. "
        "Requires authorization as a SENSITIVE action."
    )
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "state": {
                "type": "boolean",
                "description": "True to enable Wi-Fi interface, False to disable Wi-Fi interface.",
            },
            "interface_name": {
                "type": "string",
                "description": "Optional specific network interface name (defaults to 'Wi-Fi').",
            },
        },
        "required": ["state"],
    }

    def execute(self, state: bool, interface_name: str | None = None, **kwargs: Any) -> ToolResult:
        admin_state = "enabled" if state else "disabled"
        iface = (interface_name or "Wi-Fi").strip()

        cmd = f"netsh interface set interface name=\"{iface}\" admin={admin_state}"
        code, out, err = _run_powershell_command(cmd)

        if code != 0:
            msg = f"Failed to turn Wi-Fi {admin_state}: {err or out or 'Interface command error'}"
            logger.warning(msg)
            return ToolResult(
                name=self.name,
                content=msg,
                is_error=True,
                safety_level=self.safety_level,
            )

        logger.info(f"Wi-Fi interface '{iface}' set to {admin_state}")
        return ToolResult(
            name=self.name,
            content=f"Wi-Fi ({iface}) has been {admin_state}.",
            is_error=False,
            safety_level=self.safety_level,
            metadata={"wifi_state": admin_state, "interface": iface},
        )
