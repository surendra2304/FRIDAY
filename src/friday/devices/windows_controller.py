"""Windows Device Controller implementation for FRIDAY.

Encapsulates Windows OS APIs, pywinauto, os.startfile, pyautogui, ImageGrab, and pytesseract.
"""

import os
import subprocess
from typing import Any

from friday.core.device_controller import BaseDeviceController
from friday.core.logging import get_logger
from friday.vision.intent_detector import IntentDetector

logger = get_logger("devices.windows")

_SPECIAL_CHARS = set("+^%~(){}[]")


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
        """Map common application name to Windows executable or URI."""
        app = (name or "").strip().lower()
        if app in IntentDetector.APP_LAUNCH_MAP:
            return IntentDetector.APP_LAUNCH_MAP[app]
        for known, exe in IntentDetector.APP_LAUNCH_MAP.items():
            if known in app:
                return exe
        return app

    def open_app(self, name: str) -> bool:
        """Launch application using os.startfile or PATH lookup."""
        executable = self._resolve_executable(name)
        if not executable:
            return False

        # Attempt 1: os.startfile
        if os.name == "nt" and hasattr(os, "startfile"):
            try:
                os.startfile(executable)
                logger.info(f"Opened '{name}' via os.startfile('{executable}')")
                return True
            except OSError as e:
                logger.debug(f"os.startfile failed for '{executable}': {e}; falling back to subprocess")

        # Attempt 2: subprocess fallback
        try:
            cmd = f'start "" "{executable}"' if os.name == "nt" else executable
            subprocess.Popen(cmd, shell=True)
            logger.info(f"Opened '{name}' via subprocess shell start")
            return True
        except Exception as e:
            logger.error(f"Failed to launch application '{name}': {e}")
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

    def close_app(self, name: str) -> bool:
        """Close an application process by name."""
        try:
            import psutil
            low = name.lower()
            closed_any = False
            for p in psutil.process_iter(["pid", "name"]):
                if low in (p.info["name"] or "").lower():
                    p.terminate()
                    closed_any = True
            return closed_any
        except Exception as e:
            logger.debug(f"Could not close app '{name}': {e}")
            return False
