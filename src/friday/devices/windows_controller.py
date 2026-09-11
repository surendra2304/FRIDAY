"""Windows Device Controller implementation for FRIDAY.

Encapsulates Windows OS APIs, pywinauto, os.startfile, pyautogui, ImageGrab, and pytesseract.
"""

import os
import shutil
import subprocess
from typing import Any

from friday.core.device_controller import BaseDeviceController
from friday.core.logging import get_logger
from friday.vision.intent_detector import IntentDetector

logger = get_logger("devices.windows")

_SPECIAL_CHARS = set("+^%~(){}[]")

APP_ALLOWLIST: dict[str, str] = {
    "notepad": "notepad.exe",
    "calc": "calc.exe",
    "calculator": "calc.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "code": "Code.exe",
    "vscode": "Code.exe",
    "visual studio code": "Code.exe",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    "paint": "mspaint.exe",
    "mspaint": "mspaint.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "taskmgr": "taskmgr.exe",
    "task manager": "taskmgr.exe",
    "spotify": "Spotify.exe",
    "slack": "slack.exe",
    "discord": "Discord.exe",
    "zoom": "Zoom.exe",
    "excel": "EXCEL.EXE",
    "word": "WINWORD.EXE",
    "powerpoint": "POWERPNT.EXE",
    "vlc": "vlc.exe",
    "whatsapp": "WhatsApp.exe",
    "whatsapp web": "https://web.whatsapp.com",
}

BLOCKED_EXECUTABLES: set[str] = {
    "cmd.exe", "powershell.exe", "pwsh.exe", "bash.exe", "sh.exe",
    "wscript.exe", "cscript.exe", "certutil.exe", "reg.exe", "rundll32.exe",
    "format.com", "vssadmin.exe", "bcdedit.exe", "net.exe"
}

CRITICAL_SYSTEM_PROCESSES: set[str] = {
    "system", "system idle process", "smss.exe", "csrss.exe", "wininit.exe",
    "services.exe", "lsass.exe", "winlogon.exe", "explorer.exe", "svchost.exe",
    "fontdrvhost.exe", "dwm.exe", "spoolsv.exe"
}


def _escape_literal(text: str) -> str:
    """Escape special characters so pywinauto / send_keys sends literal strings."""
    out = []
    for ch in text:
        if ch in _SPECIAL_CHARS:
            out.append(f"{{{ch}}}")
        else:
            out.append(ch)
    return "".join(out)


class WindowsDeviceController(BaseDeviceController):
    """Native Windows 10/11 Device Controller."""

    device_type: str = "windows"

    def __init__(self, tesseract_cmd: str | None = None) -> None:
        self.tesseract_cmd = tesseract_cmd

    def _resolve_executable(self, name: str) -> str:
        """Map common application name to Windows executable or URI using strict allowlist."""
        app = (name or "").strip().lower()
        if not app:
            return ""

        # Direct allowlist match
        if app in APP_ALLOWLIST:
            return APP_ALLOWLIST[app]

        # Check intent detector map if present and allowed
        if app in IntentDetector.APP_LAUNCH_MAP:
            candidate = IntentDetector.APP_LAUNCH_MAP[app]
            if candidate.lower() not in BLOCKED_EXECUTABLES:
                return candidate

        # Known sub-phrase match in allowlist
        for known, exe in APP_ALLOWLIST.items():
            if known in app:
                return exe

        return ""

    def open_app(self, name: str) -> bool:
        """Launch application safely using allowlist and shell=False."""
        executable = self._resolve_executable(name)
        if not executable:
            logger.warning(f"Application '{name}' is not in the approved allowlist; launch rejected.")
            return False

        if executable.lower() in BLOCKED_EXECUTABLES:
            logger.warning(f"Launch of blocked executable '{executable}' rejected.")
            return False

        # Protocol URI (e.g. ms-settings:)
        if ":" in executable and not executable.endswith(".exe"):
            if not executable.lower().startswith("ms-settings:"):
                logger.warning(f"Rejected unapproved protocol URI: '{executable}'")
                return False
            if os.name == "nt" and hasattr(os, "startfile"):
                try:
                    os.startfile(executable)
                    logger.info(f"Opened URI '{executable}' safely via os.startfile")
                    return True
                except OSError as e:
                    logger.error(f"Failed to open URI '{executable}': {e}")
                    return False

        # Standard file execution: resolve absolute binary path
        target_bin = shutil.which(executable) or executable
        if not os.path.isabs(target_bin):
            # Check known locations
            common_paths = [
                os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", executable),
                os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), executable),
            ]
            for cp in common_paths:
                if os.path.exists(cp):
                    target_bin = cp
                    break

        try:
            # Safe launch without shell=True
            subprocess.Popen([target_bin], shell=False)
            logger.info(f"Opened '{name}' safely via subprocess ([{target_bin}], shell=False)")
            return True
        except Exception as e:
            logger.error(f"Failed to launch application '{name}' ({target_bin}): {e}")
            return False

    def click(self, x: int, y: int) -> bool:
        """Click at coordinate (x, y)."""
        try:
            import pywinauto.mouse
            pywinauto.mouse.click(coords=(int(x), int(y)))
            return True
        except Exception:
            try:
                import pyautogui
                pyautogui.click(x=int(x), y=int(y))
                return True
            except Exception as e:
                logger.error(f"Failed to synthesize click at ({x}, {y}): {e}")
                return False

    def type_text(self, text: str) -> bool:
        """Type literal text string into active focus."""
        if not text:
            return True
        escaped = _escape_literal(text)
        try:
            from pywinauto.keyboard import send_keys
            send_keys(escaped, pause=0.01, with_spaces=True)
            return True
        except Exception:
            try:
                import pyautogui
                pyautogui.write(text)
                return True
            except Exception as e:
                logger.error(f"Failed to type text: {e}")
                return False

    def screenshot(self) -> Any | None:
        """Capture Windows desktop screen."""
        try:
            from PIL import ImageGrab
            return ImageGrab.grab()
        except Exception as e:
            logger.error(f"Failed to capture screenshot: {e}")
            return None

    def read_screen_text(self) -> str:
        """Extract text from current screen via Tesseract OCR."""
        img = self.screenshot()
        if img is None:
            return ""
        try:
            import pytesseract
            if self.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
            elif os.name == "nt" and not getattr(pytesseract.pytesseract, "tesseract_cmd", ""):
                default_tess = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
                if os.path.exists(default_tess):
                    pytesseract.pytesseract.tesseract_cmd = default_tess

            text = pytesseract.image_to_string(img)
            return text.strip()
        except Exception as e:
            logger.debug(f"OCR extraction error: {e}")
            return ""

    def close_app(self, name: str, pid: int | None = None) -> bool:
        """Close an application process safely by allowlisted name or specific PID."""
        try:
            import psutil
            closed_any = False

            if pid is not None:
                try:
                    p = psutil.Process(pid)
                    proc_name = (p.name() or "").lower()
                    if proc_name in CRITICAL_SYSTEM_PROCESSES:
                        logger.warning(f"Refusing to close critical system process '{proc_name}' (PID {pid}).")
                        return False
                    p.terminate()
                    return True
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    logger.debug(f"Could not terminate PID {pid}: {e}")
                    return False

            low = (name or "").strip().lower()
            if not low:
                return False

            # Resolve expected process name strictly from allowlist
            target_exe = APP_ALLOWLIST.get(low)
            if not target_exe:
                # Check if the name matches any approved allowlisted executable
                for exe in APP_ALLOWLIST.values():
                    if exe.lower() == low or exe.lower() == f"{low}.exe":
                        target_exe = exe
                        break

            if not target_exe:
                logger.warning(f"Process '{name}' is not in approved allowlist; close rejected.")
                return False

            if not target_exe.endswith(".exe") and "." not in target_exe:
                target_exe = f"{target_exe}.exe"
            target_exe = target_exe.lower()

            for p in psutil.process_iter(["pid", "name"]):
                proc_name = (p.info["name"] or "").lower()
                if proc_name in CRITICAL_SYSTEM_PROCESSES:
                    continue
                # Require exact match to prevent accidental termination of substring matches
                if proc_name == target_exe or proc_name == low:
                    try:
                        p.terminate()
                        closed_any = True
                    except Exception as pe:
                        logger.debug(f"Failed to terminate process {p.info}: {pe}")
            return closed_any
        except Exception as e:
            logger.debug(f"Could not close app '{name}': {e}")
            return False
