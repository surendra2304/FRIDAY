"""Android Device Controller for Surendra's FRIDAY.

Provides a full device interface for real or connected Android phones/tablets via ADB
(Android Debug Bridge): taps, swipes, text typing, app launching, key events,
screenshot streaming, UI hierarchy dumping, and hardware button control.
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
from typing import Any

from friday.core.device_controller import BaseDeviceController
from friday.core.logging import get_logger

logger = get_logger("devices.android")


# Common Android key event mappings (Linux / Android input event codes)
KEY_EVENT_MAP: dict[str, int] = {
    "home": 3,
    "back": 4,
    "call": 5,
    "endcall": 6,
    "volume_up": 24,
    "volume_down": 25,
    "power": 26,
    "camera": 27,
    "clear": 28,
    "enter": 66,
    "delete": 67,
    "backspace": 67,
    "tab": 61,
    "space": 62,
    "menu": 82,
    "search": 84,
    "media_play_pause": 85,
    "media_stop": 86,
    "media_next": 87,
    "media_previous": 88,
    "mute": 91,
    "app_switch": 187,  # Recent apps
    "overview": 187,
    "wake": 224,
    "sleep": 223,
}

# Common package aliases for user-friendly app launching
COMMON_APP_PACKAGES: dict[str, str] = {
    "youtube": "com.google.android.youtube",
    "chrome": "com.android.chrome",
    "maps": "com.google.android.apps.maps",
    "camera": "com.android.camera",
    "settings": "com.android.settings",
    "messages": "com.google.android.apps.messaging",
    "phone": "com.google.android.dialer",
    "dialer": "com.google.android.dialer",
    "contacts": "com.google.android.contacts",
    "calculator": "com.google.android.calculator",
    "clock": "com.google.android.deskclock",
    "calendar": "com.google.android.calendar",
    "photos": "com.google.android.apps.photos",
    "gmail": "com.google.android.gm",
    "playstore": "com.android.vending",
    "whatsapp": "com.whatsapp",
    "spotify": "com.spotify.music",
    "instagram": "com.instagram.android",
    "twitter": "com.twitter.android",
    "x": "com.twitter.android",
    "telegram": "org.telegram.messenger",
    "netflix": "com.netflix.ninja",
}


class AndroidDeviceController(BaseDeviceController):
    """Full-featured Android Device Controller via Android Debug Bridge (ADB)."""

    device_type: str = "android"

    def __init__(self, adb_device_id: str | None = None, adb_path: str = "adb") -> None:
        self.adb_device_id = adb_device_id
        self.adb_bin = shutil.which(adb_path) or adb_path
        self._last_screen_cache: bytes | None = None

    def _build_cmd(self, args: list[str]) -> list[str]:
        cmd = [self.adb_bin]
        if self.adb_device_id:
            cmd.extend(["-s", self.adb_device_id])
        cmd.extend(args)
        return cmd

    def run_adb(self, args: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
        """Execute an arbitrary ADB command and return (returncode, stdout, stderr)."""
        cmd = self._build_cmd(args)
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
            return res.returncode, res.stdout.strip(), res.stderr.strip()
        except FileNotFoundError:
            logger.warning("ADB binary not found in PATH.")
            return -1, "", "ADB not found. Please install Android Platform Tools and add to PATH."
        except subprocess.TimeoutExpired:
            logger.warning(f"ADB command timed out after {timeout}s: {' '.join(cmd)}")
            return -2, "", f"ADB command timed out after {timeout}s."
        except Exception as e:
            logger.error(f"ADB command exception: {e}")
            return -3, "", str(e)

    def is_connected(self) -> bool:
        """Check if at least one authorized Android device is connected."""
        rc, out, _ = self.run_adb(["devices"])
        if rc != 0:
            return False
        lines = [line.strip() for line in out.splitlines() if line.strip() and not line.startswith("List of")]
        return any("\tdevice" in line for line in lines)

    def list_devices(self) -> list[dict[str, str]]:
        """Return list of connected Android devices with their status."""
        rc, out, _ = self.run_adb(["devices", "-l"])
        if rc != 0:
            return []
        devices = []
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("List of"):
                continue
            parts = line.split()
            if len(parts) >= 2:
                dev_id = parts[0]
                status = parts[1]
                model = "unknown"
                for p in parts[2:]:
                    if p.startswith("model:"):
                        model = p.split(":", 1)[1]
                devices.append({"id": dev_id, "status": status, "model": model})
        return devices

    def open_app(self, name: str) -> bool:
        """Launch an Android application by common name or package identifier."""
        clean_name = name.strip().lower()
        package = COMMON_APP_PACKAGES.get(clean_name, name.strip())

        logger.info(f"Android: Launching app package '{package}' (requested: '{name}')")
        # Try launch via monkey first (starts launcher activity automatically)
        rc, out, err = self.run_adb(["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])
        if rc == 0 and "No activities found" not in out and "No activities found" not in err:
            return True

        # Fallback to am start
        rc, _, _ = self.run_adb(["shell", "am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", "-n", f"{package}/"])
        return rc == 0

    def close_app(self, name: str) -> bool:
        """Force-stop an application package on the Android device."""
        clean_name = name.strip().lower()
        package = COMMON_APP_PACKAGES.get(clean_name, name.strip())
        rc, _, _ = self.run_adb(["shell", "am", "force-stop", package])
        return rc == 0

    def click(self, x: int, y: int) -> bool:
        """Synthesize a tap on the Android touch digitizer via 'adb shell input tap x y'."""
        logger.info(f"Android: Tap at ({x}, {y})")
        rc, _, _ = self.run_adb(["shell", "input", "tap", str(x), str(y)])
        return rc == 0

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> bool:
        """Synthesize a touch drag/swipe gesture from (x1, y1) to (x2, y2)."""
        logger.info(f"Android: Swipe ({x1}, {y1}) -> ({x2}, {y2}) duration={duration_ms}ms")
        rc, _, _ = self.run_adb(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])
        return rc == 0

    def type_text(self, text: str) -> bool:
        """Send text input to the currently focused Android input field."""
        if not text:
            return True
        logger.info(f"Android: Typing '{text}'")
        # Escape spaces for ADB input text
        escaped = text.replace(" ", "%s").replace("&", "\\&").replace("<", "\\<").replace(">", "\\>")
        rc, _, _ = self.run_adb(["shell", "input", "text", escaped])
        return rc == 0

    def press_key(self, key: str) -> bool:
        """Send a hardware or navigation key event (e.g. 'home', 'back', 'power', 'enter')."""
        key_clean = key.strip().lower()
        key_code = KEY_EVENT_MAP.get(key_clean)
        if key_code is None:
            # Check if key is a raw integer string
            if key_clean.isdigit():
                key_code = int(key_clean)
            else:
                logger.warning(f"Android: Unknown key event '{key}'")
                return False

        logger.info(f"Android: Press key '{key}' (code: {key_code})")
        rc, _, _ = self.run_adb(["shell", "input", "keyevent", str(key_code)])
        return rc == 0

    def screenshot(self) -> Any | None:
        """Capture Android display framebuffer using 'adb exec-out screencap -p'."""
        cmd = self._build_cmd(["exec-out", "screencap", "-p"])
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=10.0, check=False)
            if proc.returncode == 0 and proc.stdout:
                self._last_screen_cache = proc.stdout
                try:
                    from PIL import Image
                    return Image.open(io.BytesIO(proc.stdout))
                except Exception:
                    return proc.stdout
        except Exception as e:
            logger.error(f"Android: Screenshot capture failed: {e}")
        return None

    def read_screen_text(self) -> str:
        """Extract visible UI hierarchy text via 'adb shell uiautomator dump'."""
        # Dump window hierarchy to XML on device
        rc, out, _ = self.run_adb(["shell", "uiautomator", "dump", "/sdcard/window_dump.xml"])
        if rc != 0:
            return ""

        # Read back XML contents
        rc, xml_text, _ = self.run_adb(["shell", "cat", "/sdcard/window_dump.xml"])
        if rc != 0 or not xml_text:
            return ""

        # Extract text="" and content-desc="" attributes from XML
        matches = re.findall(r'(?:text|content-desc)="([^"]+)"', xml_text)
        filtered = [m.strip() for m in matches if m.strip()]
        return "\n".join(dict.fromkeys(filtered))  # Deduplicate preserving order

    def shell(self, command: str) -> str:
        """Execute an arbitrary Android shell command."""
        rc, out, err = self.run_adb(["shell", command])
        if rc != 0 and err:
            return f"Error ({rc}): {err}"
        return out
