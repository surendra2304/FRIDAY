"""Robust Windows Application Launcher with Interactive Desktop Shell Routing & Foreground Lock Bypass.

Solves:
1. Windows 10/11 Explorer no-arg silence (spawns explicit target e.g. home directory).
2. Desktop isolation (uses CIM/WMI Win32_Process Create on Default desktop to escape non-interactive job sandboxes).
3. Windows 11 ForegroundLockTimeout (attaches thread input via Win32 AttachThreadInput to bring newly launched windows directly in front of maximized browsers).
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import time
import ctypes.wintypes
from typing import Any

from friday.core.logging import get_logger

logger = get_logger("devices.app_launcher")

APP_LAUNCH_CONFIGS: dict[str, dict[str, Any]] = {
    "explorer": {
        "cim_cmd": f"explorer.exe \"{os.path.expanduser('~')}\"",
        "fallback_cmd": ["explorer.exe", os.path.expanduser("~")],
        "keywords": ["file explorer", os.path.basename(os.path.expanduser("~")).lower()],
        "classes": ["CabinetWClass"],
    },
    "notepad": {
        "cim_cmd": "explorer.exe shell:AppsFolder\\Microsoft.WindowsNotepad_8wekyb3d8bbwe!App",
        "fallback_cmd": ["notepad.exe"],
        "keywords": ["notepad", "untitled"],
        "classes": ["Notepad"],
    },
    "calculator": {
        "cim_cmd": "explorer.exe shell:AppsFolder\\Microsoft.WindowsCalculator_8wekyb3d8bbwe!App",
        "fallback_cmd": ["calc.exe"],
        "keywords": ["calculator"],
        "classes": ["ApplicationFrameWindow"],
    },
    "vscode": {
        "cim_cmd": "explorer.exe vscode:",
        "fallback_cmd": [
            r"C:\Users\Surendra\AppData\Local\Programs\Microsoft VS Code\Code.exe"
            if os.path.exists(r"C:\Users\Surendra\AppData\Local\Programs\Microsoft VS Code\Code.exe")
            else "code"
        ],
        "keywords": ["visual studio code", "code"],
        "classes": [],
    },
    "cursor": {
        "cim_cmd": "explorer.exe cursor:",
        "fallback_cmd": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\cursor\Cursor.exe")
            if os.path.exists(os.path.expandvars(r"%LOCALAPPDATA%\Programs\cursor\Cursor.exe"))
            else "cursor"
        ],
        "keywords": ["cursor"],
        "classes": [],
    },

    "terminal": {
        "cim_cmd": "explorer.exe shell:AppsFolder\\Microsoft.WindowsTerminal_8wekyb3d8bbwe!App",
        "fallback_cmd": ["wt.exe"],
        "keywords": ["terminal", "powershell", "command prompt"],
        "classes": ["CASCADIA_HOSTING_WINDOW_CLASS"],
    },
    "chrome": {
        "cim_cmd": "chrome.exe",
        "fallback_cmd": [r"C:\Program Files\Google\Chrome\Application\chrome.exe"],
        "keywords": ["chrome", "google chrome"],
        "classes": ["Chrome_WidgetWin_1"],
    },
    "edge": {
        "cim_cmd": "explorer.exe microsoft-edge:",
        "fallback_cmd": ["start", "microsoft-edge:"],
        "keywords": ["edge", "microsoft edge"],
        "classes": [],
    },
    "paint": {
        "cim_cmd": "explorer.exe shell:AppsFolder\\Microsoft.Paint_8wekyb3d8bbwe!App",
        "fallback_cmd": ["mspaint.exe"],
        "keywords": ["paint", "untitled - paint"],
        "classes": ["MSPaintApp"],
    },
    "settings": {
        "cim_cmd": "explorer.exe ms-settings:",
        "fallback_cmd": ["start", "ms-settings:"],
        "keywords": ["settings"],
        "classes": ["ApplicationFrameWindow"],
    },
    "taskmgr": {
        "cim_cmd": "taskmgr.exe",
        "fallback_cmd": ["taskmgr.exe"],
        "keywords": ["task manager"],
        "classes": ["TaskManagerWindow"],
    },
    "whatsapp": {
        "cim_cmd": "explorer.exe \"https://web.whatsapp.com\"",
        "fallback_cmd": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "https://web.whatsapp.com",
        ],
        "keywords": ["whatsapp", "whatsapp web"],
        "classes": ["Chrome_WidgetWin_1", "ApplicationFrameWindow"],
    },
}


def force_window_foreground(hwnd: int) -> bool:
    """Restore and activate a window, returning true only when Windows confirms focus."""
    if not hwnd or os.name != "nt":
        return False
    try:
        import win32gui
        if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
            return False
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
        user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
        user32.SetForegroundWindow.restype = ctypes.wintypes.BOOL
        user32.BringWindowToTop.argtypes = [ctypes.wintypes.HWND]
        user32.BringWindowToTop.restype = ctypes.wintypes.BOOL
        user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
        user32.IsIconic.argtypes = [ctypes.wintypes.HWND]
        user32.IsIconic.restype = ctypes.wintypes.BOOL
        user32.AttachThreadInput.argtypes = [ctypes.wintypes.DWORD, ctypes.wintypes.DWORD, ctypes.wintypes.BOOL]
        user32.AttachThreadInput.restype = ctypes.wintypes.BOOL
        kernel32.GetCurrentThreadId.restype = ctypes.wintypes.DWORD
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        else:
            user32.ShowWindow(hwnd, 5)
        fg_hwnd = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        cur_tid = kernel32.GetCurrentThreadId()
        attached: list[int] = []
        try:
            for other_tid in {fg_tid, target_tid} - {0, cur_tid}:
                if user32.AttachThreadInput(cur_tid, other_tid, True):
                    attached.append(other_tid)
            # A foreground input event grants the documented Windows exception
            # for apps started by a background process. Always release the key.
            user32.keybd_event(0x12, 0, 0, 0)  # VK_MENU down
            user32.keybd_event(0x12, 0, 2, 0)  # VK_MENU up
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            for other_tid in reversed(attached):
                user32.AttachThreadInput(cur_tid, other_tid, False)
        return user32.GetForegroundWindow() == hwnd
    except Exception as e:
        logger.debug(f"Foreground activation error for HWND {hwnd}: {e}")
        return False


def _foreground_window_handle() -> int | None:
    """Read the OS foreground HWND without relying on cached UI state."""
    if os.name != "nt":
        return None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
        hwnd = user32.GetForegroundWindow()
        return int(hwnd) if hwnd else None
    except Exception:
        return None


def _foreground_window_title() -> tuple[str, bool]:
    """Return current foreground title and whether that window is always-on-top."""
    if os.name != "nt":
        return "another application", False
    try:
        import win32con
        import win32gui
        hwnd = _foreground_window_handle()
        if not hwnd:
            return "another application", False
        title = win32gui.GetWindowText(hwnd) or "another application"
        exstyle = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        return title, bool(exstyle & win32con.WS_EX_TOPMOST)
    except Exception:
        return "another application", False


def _remains_foreground(hwnd: int, settle_seconds: float = 1.0) -> bool:
    """Require the same window to stay foreground after Windows activation."""
    time.sleep(settle_seconds)
    return _foreground_window_handle() == hwnd


def _activation_failure(title: str) -> str:
    blocking_title, is_topmost = _foreground_window_title()
    if is_topmost:
        return f"{title} is open, but {blocking_title} is an always-on-top window and Windows kept it in front."
    return f"{title} is open, but Windows did not keep it in front of {blocking_title}."


def close_active_chrome_tab() -> tuple[bool, str]:
    """Close the active Chrome tab and report success only after visible state changes."""
    if os.name != "nt":
        return False, "Closing a browser tab is available only on Windows."
    hwnd = _foreground_window_handle()
    if not hwnd:
        return False, "No active browser window was found."

    try:
        import win32gui
        import win32process
        import psutil

        if win32gui.GetClassName(hwnd) != "Chrome_WidgetWin_1":
            return False, "Chrome is not the active window; I left the current tab unchanged."
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        if psutil.Process(pid).name().lower() != "chrome.exe":
            return False, "The active window is not a Chrome browser window."
        title_before = win32gui.GetWindowText(hwnd)
        tabs_before = None
        try:
            from pywinauto import Desktop
            tabs_before = len(Desktop(backend="uia").window(handle=hwnd).descendants(control_type="TabItem"))
        except Exception:
            pass

        from friday.vision.windows_input_driver import WindowsNativeInputDriver
        if not WindowsNativeInputDriver().hotkey(["ctrl", "w"]):
            return False, "Windows did not accept the Ctrl+W input; the tab was not confirmed closed."

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if not win32gui.IsWindow(hwnd):
                return True, "Closed the active Chrome tab; Windows confirmed its window closed."
            title_after = win32gui.GetWindowText(hwnd)
            if title_after != title_before:
                return True, f"Closed the active Chrome tab; the browser changed from '{title_before}' to '{title_after}'."
            if tabs_before is not None:
                try:
                    tabs_after = len(Desktop(backend="uia").window(handle=hwnd).descendants(control_type="TabItem"))
                    if tabs_after < tabs_before:
                        return True, f"Closed the active Chrome tab; tab count changed from {tabs_before} to {tabs_after}."
                except Exception:
                    pass
            time.sleep(0.1)
        return False, "Ctrl+W was sent, but Windows did not confirm that the active Chrome tab changed."
    except Exception as exc:
        logger.warning("Could not close active Chrome tab: %s", type(exc).__name__)
        return False, "FRIDAY could not verify the active Chrome tab or send its close command."


def find_existing_window(keywords: list[str], classes: list[str]) -> int | None:
    """Find a visible window matching title keywords or window classes."""
    if os.name != "nt":
        return None
    try:
        import win32gui
        found: list[int] = []

        def enum_cb(h: int, _: Any) -> None:
            if win32gui.IsWindowVisible(h):
                t = win32gui.GetWindowText(h).lower()
                c = win32gui.GetClassName(h)
                if any(k in t for k in keywords) or any(cls.lower() == c.lower() for cls in classes):
                    found.append(h)

        win32gui.EnumWindows(enum_cb, None)
        return found[0] if found else None
    except Exception as e:
        logger.debug(f"find_existing_window error: {e}")
        return None


def _find_chrome_windows() -> list[int]:
    """Return visible top-level windows owned by Google Chrome, excluding Chrome-based apps."""
    try:
        import psutil
        import win32gui
        import win32process
        handles: list[int] = []

        def enum_cb(hwnd: int, _: Any) -> None:
            if not win32gui.IsWindowVisible(hwnd) or win32gui.GetClassName(hwnd) != "Chrome_WidgetWin_1":
                return
            _, process_id = win32process.GetWindowThreadProcessId(hwnd)
            try:
                exe = os.path.normcase(psutil.Process(process_id).exe())
            except (psutil.Error, OSError):
                return
            if os.path.basename(exe) == "chrome.exe":
                handles.append(hwnd)

        win32gui.EnumWindows(enum_cb, None)
        return handles
    except Exception as e:
        logger.debug(f"Could not enumerate Chrome windows: {e}")
        return []


def find_all_installations(app_name: str) -> list[str]:
    """Discover all distinct installation paths for an application across standard Windows locations."""
    app_key = app_name.lower().strip()

    # Environment override for testing multi-installation scenarios
    mock_env = os.getenv("FRIDAY_MOCK_INSTALLATIONS")
    if mock_env:
        try:
            import json
            data = json.loads(mock_env)
            if app_key in data:
                return data[app_key]
        except Exception:
            pass

    candidates: list[str] = []

    if any(k in app_key for k in ["chrome", "google chrome"]):
        checks = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        ]
        which_path = shutil.which("chrome.exe") or shutil.which("chrome")
        if which_path:
            checks.append(which_path)

        for c in checks:
            if c and os.path.exists(c) and c not in candidates:
                candidates.append(c)

    elif any(k in app_key for k in ["code", "vscode", "vs code"]):
        checks = [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            r"C:\Program Files\Microsoft VS Code\Code.exe",
            r"C:\Program Files (x86)\Microsoft VS Code\Code.exe",
        ]
        which_path = shutil.which("code.exe") or shutil.which("code")
        if which_path:
            checks.append(which_path)

        for c in checks:
            if c and os.path.exists(c) and c not in candidates:
                candidates.append(c)

    return candidates


def launch_desktop_app(app_name: str, preferred_path: str | None = None) -> tuple[bool, str]:
    """Launch a desktop application reliably on the user's interactive desktop and bring to front.

    If the application is already running, brings the existing window to the foreground
    to prevent opening duplicate windows or tabs.

    If multiple installations of the application exist and no preferred path is specified,
    FRIDAY asks which installation to use and DOES NOT open a random executable.

    Args:
        app_name: Canonical or spoken application name (e.g. 'chrome', 'explorer', 'notepad', 'calculator', 'vscode', 'terminal').
        preferred_path: Optional explicit executable path selected by user.

    Returns:
        tuple of (success: bool, message: str)
    """
    app_key = app_name.lower().strip()

    # Match aliases
    if any(k in app_key for k in ["explorer", "file", "folder"]):
        key = "explorer"
        title = "File Explorer"
    elif any(k in app_key for k in ["notepad", "note", "text editor"]):
        key = "notepad"
        title = "Windows Notepad"
    elif any(k in app_key for k in ["calc", "calculator"]):
        key = "calculator"
        title = "Windows Calculator"
    elif any(k in app_key for k in ["code", "vscode", "vs code"]):
        key = "vscode"
        title = "Visual Studio Code"
    elif any(k in app_key for k in ["terminal", "powershell", "cmd", "prompt"]):
        key = "terminal"
        title = "Windows Terminal"
    elif any(k in app_key for k in ["chrome", "google chrome", "browser"]):
        key = "chrome"
        title = "Google Chrome"
    elif any(k in app_key for k in ["edge", "microsoft edge"]):
        key = "edge"
        title = "Microsoft Edge"
    elif any(k in app_key for k in ["paint", "draw"]):
        key = "paint"
        title = "Microsoft Paint"
    elif any(k in app_key for k in ["settings", "config"]):
        key = "settings"
        title = "Windows Settings"
    elif any(k in app_key for k in ["task manager", "taskmgr"]):
        key = "taskmgr"
        title = "Task Manager"
    elif any(k in app_key for k in ["whatsapp", "whatsaapp", "whatsap", "wa"]):
        key = "whatsapp"
        title = "WhatsApp"
    else:
        import difflib
        matches = difflib.get_close_matches(app_key, APP_LAUNCH_CONFIGS.keys(), n=1, cutoff=0.6)
        if matches:
            key = matches[0]
            title = key.title()
        else:
            key = app_key
            title = app_name.title()

    cfg = APP_LAUNCH_CONFIGS.get(key)
    launched = False

    if cfg:
        keywords = cfg.get("keywords", [key])
        classes = cfg.get("classes", [])

        # Reuse and focus an existing window (including Chrome); don't create
        # a new window or tab for a plain "open Chrome" request.
        existing_hwnd = find_existing_window(keywords, classes)
        if existing_hwnd:
            if force_window_foreground(existing_hwnd) and _remains_foreground(existing_hwnd):
                return True, f"Brought active {title} to front; Windows confirmed it remained focused."
            return False, _activation_failure(title)

        # Only ask which installation to launch when no existing app window
        # can be reused. A plain "open Chrome" should focus the running browser.
        if not preferred_path:
            installations = find_all_installations(key)
            if len(installations) > 1:
                opts = ", ".join(f"'{p}'" for p in installations)
                return False, f"Multiple installations of {title} were found: {opts}. Which installation would you like to use?"

        cim_cmd = cfg["cim_cmd"]
        ps_cmd = f"Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{CommandLine='{cim_cmd}'}}"
        try:
            res = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if "ReturnValue : 0" in res.stdout or "0" in res.stdout:
                launched = True
        except Exception as e:
            logger.warning(f"CIM launch error for {key}: {e}")

        # Fallback to direct subprocess with Default desktop startup info
        if not launched:
            try:
                si = subprocess.STARTUPINFO()
                si.lpDesktop = r"WinSta0\Default"
                fallback_cmd = cfg["fallback_cmd"]
                if key == "chrome":
                    installations = find_all_installations(key)
                    if len(installations) == 1:
                        fallback_cmd = [installations[0]]
                subprocess.Popen(fallback_cmd, startupinfo=si)
                launched = True
            except Exception as fe:
                logger.warning(f"Fallback launch error for {key}: {fe}")

        if not launched:
            return False, f"Could not start {title}. Windows did not confirm a launch request."
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            hwnd = find_existing_window(keywords, classes)
            if hwnd:
                if force_window_foreground(hwnd) and _remains_foreground(hwnd):
                    return True, f"Opened {title}; Windows confirmed its window remained focused."
                return False, _activation_failure(title)
            time.sleep(0.2)
        return False, f"A launch request for {title} was sent, but FRIDAY could not verify a visible focused window."
    else:
        # Safe generic application launch
        import re
        clean_name = app_name.strip()
        if not re.match(r"^[a-zA-Z0-9_\-. ]+$", clean_name):
            return False, f"Invalid application name '{app_name}'."

        from friday.devices.windows_controller import BLOCKED_EXECUTABLES
        if clean_name.lower() in BLOCKED_EXECUTABLES or f"{clean_name.lower()}.exe" in BLOCKED_EXECUTABLES:
            return False, f"Opening '{app_name}' is restricted for system safety."

        target_bin = shutil.which(clean_name) or shutil.which(f"{clean_name}.exe")
        if not target_bin:
            return False, f"Application '{app_name}' not recognized or not found on system PATH."

        try:
            subprocess.Popen([target_bin], shell=False)
            keywords = [clean_name.lower(), os.path.splitext(os.path.basename(target_bin))[0].lower()]
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                hwnd = find_existing_window(keywords, [])
                if hwnd:
                    if force_window_foreground(hwnd) and _remains_foreground(hwnd):
                        return True, f"Opened {title}; Windows confirmed its window remained focused."
                    return False, _activation_failure(title)
                time.sleep(0.2)
            return False, f"{title} started, but FRIDAY could not verify a visible application window."
        except Exception as e:
            return False, f"Failed to open {title}: {e}"
