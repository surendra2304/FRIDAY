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
import threading
import time
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
    "terminal": {
        "cim_cmd": "explorer.exe shell:AppsFolder\\Microsoft.WindowsTerminal_8wekyb3d8bbwe!App",
        "fallback_cmd": ["wt.exe"],
        "keywords": ["terminal", "powershell", "command prompt"],
        "classes": ["CASCADIA_HOSTING_WINDOW_CLASS"],
    },
    "chrome": {
        "cim_cmd": 'explorer.exe "https://www.google.com"',
        "fallback_cmd": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            "https://www.google.com",
        ],
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
}


def force_window_foreground(hwnd: int) -> bool:
    """Force any HWND directly to the foreground on top of Chrome without snapping or resizing."""
    if not hwnd:
        return False
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    try:
        import win32gui

        if not win32gui.IsWindow(hwnd):
            return False

        # If minimized, restore; otherwise show cleanly without resizing
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        else:
            user32.ShowWindow(hwnd, 5)  # SW_SHOW

        fg_hwnd = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(fg_hwnd, None)
        target_tid = user32.GetWindowThreadProcessId(hwnd, None)
        cur_tid = kernel32.GetCurrentThreadId()

        if fg_tid != target_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, True)
            user32.AttachThreadInput(cur_tid, target_tid, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)
            user32.AttachThreadInput(cur_tid, fg_tid, False)
            user32.AttachThreadInput(cur_tid, target_tid, False)
        else:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetFocus(hwnd)

        # Topmost pulse to place right on top of Chrome without side-by-side snapping
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_SHOWWINDOW = 0x0040
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW)
        return True
    except Exception as e:
        logger.debug(f"Foreground activation error for HWND {hwnd}: {e}")
        return False


def _bring_to_front_worker(keywords: list[str], classes: list[str], max_seconds: float = 3.0) -> None:
    """Worker thread running on WinSta0\\Default desktop to find newly created windows and bring to front."""
    try:
        import win32gui

        user32 = ctypes.windll.user32
        h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desk:
            user32.SetThreadDesktop(h_desk)

        deadline = time.time() + max_seconds
        while time.time() < deadline:
            time.sleep(0.18)
            found: list[int] = []

            def enum_cb(h: int, _: Any) -> None:
                if win32gui.IsWindowVisible(h):
                    t = win32gui.GetWindowText(h).lower()
                    c = win32gui.GetClassName(h)
                    if any(k in t for k in keywords) or any(cls.lower() == c.lower() for cls in classes):
                        found.append(h)

            win32gui.EnumWindows(enum_cb, None)
            if found:
                target = found[0]
                force_window_foreground(target)
                break
    except Exception as e:
        logger.debug(f"bring_to_front_worker error: {e}")


def find_existing_window(keywords: list[str], classes: list[str]) -> int | None:
    """Find an already running window on WinSta0\\Default matching keywords or window classes."""
    try:
        import win32gui

        user32 = ctypes.windll.user32
        h_desk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
        if h_desk:
            user32.SetThreadDesktop(h_desk)

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


def launch_desktop_app(app_name: str) -> tuple[bool, str]:
    """Launch a desktop application reliably on the user's interactive desktop and bring to front.

    If the application is already running, brings the existing window to the foreground
    to prevent opening duplicate windows or tabs.

    Args:
        app_name: Canonical or spoken application name (e.g. 'chrome', 'explorer', 'notepad', 'calculator', 'vscode', 'terminal').

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
    else:
        key = app_key
        title = app_name.title()

    cfg = APP_LAUNCH_CONFIGS.get(key)
    launched = False

    if cfg:
        keywords = cfg.get("keywords", [key])
        classes = cfg.get("classes", [])

        # 1. First check if window is already open - focus it without opening duplicate tabs/windows
        existing_hwnd = find_existing_window(keywords, classes)
        if existing_hwnd:
            force_window_foreground(existing_hwnd)
            return True, f"Brought active {title} to front."

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
                subprocess.Popen(cfg["fallback_cmd"], startupinfo=si)
                launched = True
            except Exception as fe:
                logger.warning(f"Fallback launch error for {key}: {fe}")

        # Spawn foreground-raising worker in background thread
        keywords = cfg.get("keywords", [key])
        classes = cfg.get("classes", [])
        worker = threading.Thread(
            target=_bring_to_front_worker,
            args=(keywords, classes, 3.0),
            daemon=True,
        )
        worker.start()

        return True, f"Opened {title}."
    else:
        # Generic application launch via shell
        try:
            ps_cmd = f"Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{CommandLine='{app_name}'}}"
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True,
                timeout=5,
            )
            return True, f"Opened {title}."
        except Exception as e:
            return False, f"Failed to open {title}: {e}"
