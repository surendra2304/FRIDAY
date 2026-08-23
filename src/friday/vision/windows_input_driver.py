# -*- coding: utf-8 -*-
"""Safe Win32 Input Synthesis Driver and Test Mock for Windows OS.

Provides:
- `BaseWindowsInputDriver`: Abstract contract for OS input synthesis and cursor query.
- `WindowsNativeInputDriver`: High-fidelity, safe ctypes implementation using Windows `SendInput`,
  `SetCursorPos`, `GetCursorPos`, and `GetSystemMetrics`.
- `MockWindowsInputDriver`: Deterministic in-memory mock for sandbox isolation and automated testing.
- `check_desktop_interactivity`: Honest hardware/environment probe for active interactive desktop.
"""

from abc import ABC, abstractmethod
import ctypes
from ctypes import wintypes
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from friday.core.logging import get_logger

logger = get_logger("vision.input_driver")
_DPI_AWARENESS_SET = False

# Windows Virtual Key Codes
VK_MAP: Dict[str, int] = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "control": 0x11,
    "ctrl": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "escape": 0x1B,
    "esc": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "insert": 0x2D,
    "delete": 0x2E,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}

# Win32 Constants
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
INPUT_HARDWARE = 2

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
WHEEL_DELTA = 120

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

SM_CXSCREEN = 0
SM_CYSCREEN = 1


# 64-bit / 32-bit compatible ctypes Win32 structures
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("u", _INPUT_UNION),
    ]


class POINT(ctypes.Structure):
    _fields_ = [
        ("x", wintypes.LONG),
        ("y", wintypes.LONG),
    ]


def check_desktop_interactivity() -> Tuple[bool, str]:
    """Check if the current Windows session has an active, accessible interactive desktop."""
    if sys.platform != "win32":
        return False, "Operating system is not Windows"

    try:
        user32 = ctypes.windll.user32
        pt = POINT()
        ok = user32.GetCursorPos(ctypes.byref(pt))
        if not ok:
            err = ctypes.GetLastError()
            return False, f"Desktop not interactive or locked (Win32 GetLastError={err})"
        return True, "Interactive desktop active"
    except Exception as e:
        return False, f"Failed to query desktop state: {e}"


class BaseWindowsInputDriver(ABC):
    """Abstract contract for Windows input synthesis driver."""

    @abstractmethod
    def move_cursor(self, x: int, y: int) -> bool:
        """Move mouse cursor to absolute pixel coordinates (x, y)."""
        pass

    @abstractmethod
    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> bool:
        """Click mouse button at specified or current coordinates."""
        pass

    @abstractmethod
    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        """Perform rapid double left click."""
        pass

    @abstractmethod
    def scroll(self, delta_y: int) -> bool:
        """Scroll mouse wheel vertically."""
        pass

    @abstractmethod
    def press_key(self, key: str) -> bool:
        """Press and release a single allowlisted key."""
        pass

    @abstractmethod
    def type_text(self, text: str) -> bool:
        """Type safe text string via Unicode input synthesis."""
        pass

    @abstractmethod
    def hotkey(self, keys: List[str]) -> bool:
        """Execute a combination of modifier and target keys."""
        pass

    @abstractmethod
    def get_cursor_position(self) -> Tuple[int, int]:
        """Return current mouse cursor position (x, y)."""
        pass

    @abstractmethod
    def get_screen_dimensions(self) -> Tuple[int, int]:
        """Return screen width and height in pixels."""
        pass


class WindowsNativeInputDriver(BaseWindowsInputDriver):
    """Real Win32 input synthesis driver using user32.SendInput and user32 cursor APIs."""

    def __init__(self) -> None:
        self._enable_dpi_awareness()
        self._user32 = ctypes.windll.user32
        # Set function argument and return types for 64-bit safety
        self._user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self._user32.SendInput.restype = wintypes.UINT
        self._user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self._user32.SetCursorPos.restype = wintypes.BOOL
        self._user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
        self._user32.GetCursorPos.restype = wintypes.BOOL
        self._user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self._user32.GetSystemMetrics.restype = ctypes.c_int

    @staticmethod
    def _enable_dpi_awareness() -> None:
        """Make cursor/screen coordinates physical pixels on scaled Windows desktops."""
        global _DPI_AWARENESS_SET
        if _DPI_AWARENESS_SET or sys.platform != "win32":
            return
        try:
            # Windows 10+: per-monitor v2 awareness.
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            _DPI_AWARENESS_SET = True
            return
        except Exception:
            pass
        try:
            # Windows 8.1 fallback: PROCESS_PER_MONITOR_DPI_AWARE = 2.
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
            _DPI_AWARENESS_SET = True
            return
        except Exception:
            pass
        try:
            ctypes.windll.user32.SetProcessDPIAware()
            _DPI_AWARENESS_SET = True
        except Exception as e:
            logger.debug(f"Could not set process DPI awareness: {e}")

    def get_screen_dimensions(self) -> Tuple[int, int]:
        width = int(self._user32.GetSystemMetrics(SM_CXSCREEN))
        height = int(self._user32.GetSystemMetrics(SM_CYSCREEN))
        return (width, height)

    def get_cursor_position(self) -> Tuple[int, int]:
        pt = POINT()
        ok = self._user32.GetCursorPos(ctypes.byref(pt))
        if not ok:
            err = ctypes.GetLastError()
            logger.warning(f"Failed to retrieve cursor position from Win32 GetCursorPos (error={err}).")
            return (0, 0)
        return (int(pt.x), int(pt.y))

    def move_cursor(self, x: int, y: int) -> bool:
        target_x = int(x)
        target_y = int(y)
        # First try SetCursorPos (handles multi-monitor absolute desktop coords directly)
        ok = bool(self._user32.SetCursorPos(target_x, target_y))
        if not ok:
            # Fallback to SendInput with MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_VIRTUALDESK
            SM_CXVIRTUALSCREEN = 78
            SM_CYVIRTUALSCREEN = 79
            SM_XVIRTUALSCREEN = 76
            SM_YVIRTUALSCREEN = 77
            MOUSEEVENTF_VIRTUALDESK = 0x4000

            virt_w = int(self._user32.GetSystemMetrics(SM_CXVIRTUALSCREEN))
            virt_h = int(self._user32.GetSystemMetrics(SM_CYVIRTUALSCREEN))
            virt_x = int(self._user32.GetSystemMetrics(SM_XVIRTUALSCREEN))
            virt_y = int(self._user32.GetSystemMetrics(SM_YVIRTUALSCREEN))

            if virt_w <= 0 or virt_h <= 0:
                virt_w, virt_h = self.get_screen_dimensions()
                virt_x, virt_y = 0, 0

            if virt_w > 0 and virt_h > 0:
                norm_x = int(((target_x - virt_x) * 65535) / virt_w)
                norm_y = int(((target_y - virt_y) * 65535) / virt_h)
                inp = (INPUT * 1)()
                inp[0].type = INPUT_MOUSE
                inp[0].mi.dx = norm_x
                inp[0].mi.dy = norm_y
                inp[0].mi.dwFlags = MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_VIRTUALDESK
                sent = self._user32.SendInput(1, inp, ctypes.sizeof(INPUT))
                ok = (sent == 1)

        if not ok:
            time.sleep(0.01)
            return False

        # Some scaled or remote Windows sessions acknowledge SetCursorPos but
        # land at a virtualized coordinate. Verify and correct using the
        # observed residual so physical automation does not claim false success.
        for _ in range(4):
            time.sleep(0.02)
            cur_x, cur_y = self.get_cursor_position()
            if abs(cur_x - target_x) <= 2 and abs(cur_y - target_y) <= 2:
                return True
            correction_x = target_x + (target_x - cur_x)
            correction_y = target_y + (target_y - cur_y)
            if not self._user32.SetCursorPos(int(correction_x), int(correction_y)):
                break

        cur_x, cur_y = self.get_cursor_position()
        return abs(cur_x - target_x) <= 2 and abs(cur_y - target_y) <= 2

    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> bool:
        if x is not None and y is not None:
            self.move_cursor(x, y)

        btn = button.lower()
        if btn == "right":
            down_flag = MOUSEEVENTF_RIGHTDOWN
            up_flag = MOUSEEVENTF_RIGHTUP
        elif btn == "middle":
            down_flag = MOUSEEVENTF_MIDDLEDOWN
            up_flag = MOUSEEVENTF_MIDDLEUP
        else:
            down_flag = MOUSEEVENTF_LEFTDOWN
            up_flag = MOUSEEVENTF_LEFTUP

        inputs = (INPUT * 2)()
        # Mouse Down
        inputs[0].type = INPUT_MOUSE
        inputs[0].mi.dwFlags = down_flag
        # Mouse Up
        inputs[1].type = INPUT_MOUSE
        inputs[1].mi.dwFlags = up_flag

        sent = self._user32.SendInput(2, inputs, ctypes.sizeof(INPUT))
        time.sleep(0.02)
        return sent == 2

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        if x is not None and y is not None:
            self.move_cursor(x, y)

        ok1 = self.click(button="left")
        time.sleep(0.05)
        ok2 = self.click(button="left")
        return ok1 and ok2

    def scroll(self, delta_y: int) -> bool:
        inputs = (INPUT * 1)()
        inputs[0].type = INPUT_MOUSE
        inputs[0].mi.dwFlags = MOUSEEVENTF_WHEEL
        inputs[0].mi.mouseData = int(delta_y * WHEEL_DELTA) if abs(delta_y) < 100 else int(delta_y)

        sent = self._user32.SendInput(1, inputs, ctypes.sizeof(INPUT))
        return sent == 1

    def press_key(self, key: str) -> bool:
        k = key.lower().strip()
        vk = VK_MAP.get(k)
        if vk is None:
            if len(k) == 1:
                vk = ord(k.upper())
            else:
                logger.error(f"Unsupported virtual key: '{key}'")
                return False

        inputs = (INPUT * 2)()
        inputs[0].type = INPUT_KEYBOARD
        inputs[0].ki.wVk = vk
        inputs[0].ki.dwFlags = 0
        inputs[1].type = INPUT_KEYBOARD
        inputs[1].ki.wVk = vk
        inputs[1].ki.dwFlags = KEYEVENTF_KEYUP

        sent = self._user32.SendInput(2, inputs, ctypes.sizeof(INPUT))
        time.sleep(0.01)
        return sent == 2

    def type_text(self, text: str) -> bool:
        if not text:
            return True

        input_list = []
        for ch in text:
            inp_down = INPUT()
            inp_down.type = INPUT_KEYBOARD
            inp_down.ki.wVk = 0
            inp_down.ki.wScan = ord(ch)
            inp_down.ki.dwFlags = KEYEVENTF_UNICODE
            input_list.append(inp_down)

            inp_up = INPUT()
            inp_up.type = INPUT_KEYBOARD
            inp_up.ki.wVk = 0
            inp_up.ki.wScan = ord(ch)
            inp_up.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
            input_list.append(inp_up)

        n = len(input_list)
        inputs = (INPUT * n)(*input_list)
        sent = self._user32.SendInput(n, inputs, ctypes.sizeof(INPUT))
        time.sleep(0.02)
        return sent == n

    def hotkey(self, keys: List[str]) -> bool:
        if not keys:
            return True

        vks = []
        for k in keys:
            vk = VK_MAP.get(k.lower().strip())
            if vk is None:
                if len(k) == 1:
                    vk = ord(k.upper())
                else:
                    return False
            vks.append(vk)

        total = len(vks) * 2
        input_list = []
        for vk in vks:
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.ki.wVk = vk
            inp.ki.dwFlags = 0
            input_list.append(inp)

        for vk in reversed(vks):
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.ki.wVk = vk
            inp.ki.dwFlags = KEYEVENTF_KEYUP
            input_list.append(inp)

        inputs = (INPUT * total)(*input_list)
        sent = self._user32.SendInput(total, inputs, ctypes.sizeof(INPUT))
        time.sleep(0.02)
        return sent == total


class MockWindowsInputDriver(BaseWindowsInputDriver):
    """Deterministic in-memory mock driver that simulates cursor and inputs without OS effect."""

    def __init__(self, screen_width: int = 1920, screen_height: int = 1080) -> None:
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.cursor_pos: Tuple[int, int] = (0, 0)
        self.call_log: List[Dict[str, Any]] = []

    def get_screen_dimensions(self) -> Tuple[int, int]:
        return (self.screen_width, self.screen_height)

    def get_cursor_position(self) -> Tuple[int, int]:
        return self.cursor_pos

    def move_cursor(self, x: int, y: int) -> bool:
        self.cursor_pos = (int(x), int(y))
        self.call_log.append({"action": "move_cursor", "x": x, "y": y})
        return True

    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> bool:
        if x is not None and y is not None:
            self.cursor_pos = (int(x), int(y))
        self.call_log.append({"action": "click", "x": self.cursor_pos[0], "y": self.cursor_pos[1], "button": button})
        return True

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> bool:
        if x is not None and y is not None:
            self.cursor_pos = (int(x), int(y))
        self.call_log.append({"action": "double_click", "x": self.cursor_pos[0], "y": self.cursor_pos[1]})
        return True

    def scroll(self, delta_y: int) -> bool:
        self.call_log.append({"action": "scroll", "delta_y": delta_y})
        return True

    def press_key(self, key: str) -> bool:
        self.call_log.append({"action": "press_key", "key": key})
        return True

    def type_text(self, text: str) -> bool:
        self.call_log.append({"action": "type_text", "text": text})
        return True

    def hotkey(self, keys: List[str]) -> bool:
        self.call_log.append({"action": "hotkey", "keys": list(keys)})
        return True
