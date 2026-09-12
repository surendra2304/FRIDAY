"""Android Device Controller for Surendra's FRIDAY.

Provides a full device interface for real or connected Android phones/tablets via ADB
(Android Debug Bridge): taps, swipes, text typing, app launching, key events,
screenshot streaming, UI hierarchy dumping, and hardware button control.
"""

from __future__ import annotations

import io
import os
import re
import shlex
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


# Blocked commands for device security
BLOCKED_ADB_COMMANDS: set[str] = {
    "root", "unroot", "remount", "tcpip", "install", "uninstall",
    "pull", "push", "sideload", "recovery", "flash", "reboot", "reboot-bootloader",
    "disable-verity", "enable-verity",
}

BLOCKED_SHELL_COMMANDS: set[str] = {
    "su", "sh", "bash", "rm", "rmdir", "mkfs", "dd", "chmod", "chown",
    "reboot", "format", "wipe", "factory_reset",
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
        if not self.adb_device_id and args and args[0] != "devices":
            try:
                # Auto-discover first available connected device
                proc = subprocess.run([self.adb_bin, "devices"], capture_output=True, text=True, timeout=2.0, check=False)
                for line in proc.stdout.splitlines():
                    if "\tdevice" in line:
                        self.adb_device_id = line.split()[0]
                        break
            except Exception:
                pass

        if self.adb_device_id:
            cmd.extend(["-s", self.adb_device_id])
        cmd.extend(args)
        return cmd

    def run_adb(self, args: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
        """Execute an ADB command safely after capability checks."""
        if not args:
            return 0, "", ""
        primary_cmd = args[0].lower()
        if primary_cmd in BLOCKED_ADB_COMMANDS:
            logger.warning(f"ADB execution blocked dangerous command: '{primary_cmd}'")
            return -1, "", f"Operation '{primary_cmd}' is blocked for Android device safety."

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

    def select_device(self, device_id: str) -> bool:
        """Explicitly select an active Android device by ID."""
        devs = self.list_devices()
        matching = [d for d in devs if d["id"] == device_id]
        if matching or device_id == "":
            self.adb_device_id = device_id if device_id else None
            logger.info(f"Android: Explicitly selected target device '{self.adb_device_id}'")
            return True
        logger.warning(f"Android: Device ID '{device_id}' not found in active devices: {devs}")
        return False

    def get_device_status(self) -> dict[str, Any]:
        """Return explicit connection and authorization status for active device."""
        devs = self.list_devices()
        if not devs:
            return {"connected": False, "authorized": False, "status": "no_device", "device_id": None}
        target = None
        if self.adb_device_id:
            for d in devs:
                if d["id"] == self.adb_device_id:
                    target = d
                    break
        if not target:
            target = devs[0]
            self.adb_device_id = target["id"]

        is_auth = target.get("status") == "device"
        return {
            "connected": True,
            "authorized": is_auth,
            "status": target.get("status", "unknown"),
            "device_id": target.get("id"),
            "model": target.get("model", "unknown"),
        }

    def discover_capabilities(self) -> dict[str, Any]:
        """Discover Android device hardware, display, and OS capabilities."""
        status = self.get_device_status()
        if not status["connected"] or not status["authorized"]:
            return {"status": status["status"], "capabilities": {}, "error": "Device not connected or unauthorized"}

        # Screen resolution
        _, wm_size, _ = self.run_adb(["shell", "wm", "size"])
        # Android release version
        _, os_ver, _ = self.run_adb(["shell", "getprop", "ro.build.version.release"])
        # SDK API Level
        _, sdk_ver, _ = self.run_adb(["shell", "getprop", "ro.build.version.sdk"])
        # Battery level
        batt = self.get_battery_level()

        caps = {
            "device_id": status["device_id"],
            "model": status["model"],
            "android_version": os_ver.strip() if os_ver else "unknown",
            "sdk_level": int(sdk_ver.strip()) if sdk_ver and sdk_ver.strip().isdigit() else None,
            "screen_size": wm_size.replace("Physical size: ", "").strip() if wm_size else "unknown",
            "battery_percent": batt,
            "touchscreen": True,
            "hardware_keys": list(KEY_EVENT_MAP.keys()),
        }
        return {"status": "ok", "capabilities": caps}

    def dump_ui_hierarchy(self) -> str:
        """Dump UI XML hierarchy using 'adb shell uiautomator dump' and retrieve contents."""
        rc, _, err = self.run_adb(["shell", "uiautomator", "dump", "/data/local/tmp/uidump.xml"])
        if rc != 0:
            logger.warning(f"Failed to dump UI hierarchy: {err}")
            return ""
        rc, out, _ = self.run_adb(["shell", "cat", "/data/local/tmp/uidump.xml"])
        if rc == 0:
            return out
        return ""

    def open_app(self, name: str) -> bool:
        """Launch an Android application by common name or package identifier."""
        clean_name = name.strip().lower()
        package = COMMON_APP_PACKAGES.get(clean_name, name.strip())

        # Strict validation of package name format to prevent shell injection
        if not re.match(r"^[a-zA-Z0-9_\.]+$", package):
            logger.warning(f"Android: Rejected invalid app package name: '{package}'")
            return False

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

        # Strict validation of package name format to prevent shell injection
        if not re.match(r"^[a-zA-Z0-9_\.]+$", package):
            logger.warning(f"Android: Rejected invalid app package name for close: '{package}'")
            return False

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
        """Send text input to the currently focused Android input field safely."""
        if not text:
            return True
        logger.info(f"Android: Typing '{text}'")
        # Replace spaces with %s for ADB input text and safely quote for remote shell
        safe_text = text.replace(" ", "%s")
        quoted = shlex.quote(safe_text)
        rc, _, _ = self.run_adb(["shell", "input", "text", quoted])
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
        """Execute a safe Android diagnostic or inspection shell command."""
        cmd_clean = (command or "").strip()
        if not cmd_clean:
            return ""

        # Normalize tokens: strip quotes, path prefixes, and inspect basenames
        raw_tokens = re.split(r"[\s;|>&<`$()]+", cmd_clean.lower())
        for raw_tok in raw_tokens:
            tok = raw_tok.strip("\"' \t")
            if not tok:
                continue
            base_tok = os.path.basename(tok)
            if (
                tok in BLOCKED_SHELL_COMMANDS
                or base_tok in BLOCKED_SHELL_COMMANDS
                or tok in BLOCKED_ADB_COMMANDS
                or base_tok in BLOCKED_ADB_COMMANDS
            ):
                logger.warning(f"Blocked dangerous Android shell token: '{tok}' in command: '{command}'")
                return f"Error: Command contains restricted token '{tok}' for safety."

        rc, out, err = self.run_adb(["shell", command])
        if rc != 0 and err:
            return f"Error ({rc}): {err}"
        return out

    def open_url(self, url: str) -> bool:
        """Open web URL in default Android browser."""
        rc, _, _ = self.run_adb(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", url])
        return rc == 0

    def dial_phone(self, phone_number: str) -> bool:
        """Open phone dialer with phone number."""
        clean = re.sub(r"[^\d+]", "", phone_number)
        rc, _, _ = self.run_adb(["shell", "am", "start", "-a", "android.intent.action.DIAL", "-d", f"tel:{clean}"])
        return rc == 0

    def send_whatsapp_intent(self, phone_number: str, message: str) -> bool:
        """Send WhatsApp message directly via Android deep link intent."""
        import urllib.parse
        clean = re.sub(r"[^\d+]", "", phone_number)
        if clean.startswith("+"):
            clean = clean[1:]
        encoded = urllib.parse.quote(message)
        wa_url = f"https://api.whatsapp.com/send?phone={clean}&text={encoded}"
        rc, _, _ = self.run_adb(["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", wa_url, "com.whatsapp"])
        if rc == 0:
            import time
            time.sleep(2.0)
            self.press_key("enter")
            return True
        return False

    def get_battery_level(self) -> int:
        """Get Android device battery percentage."""
        rc, out, _ = self.run_adb(["shell", "dumpsys", "battery"])
        if rc == 0:
            match = re.search(r"level:\s*(\d+)", out)
            if match:
                return int(match.group(1))
        return -1

    def is_screen_on(self) -> bool:
        """Check if Android screen is currently awake / illuminated."""
        rc, out, _ = self.run_adb(["shell", "dumpsys", "power"])
        if rc == 0:
            return "mHoldingDisplaySuspendBlocker=true" in out or "Display Power: state=ON" in out
        return False

    def wake_screen(self) -> bool:
        """Ensure Android screen is turned on."""
        if not self.is_screen_on():
            return self.press_key("wake") or self.press_key("power")
        return True
