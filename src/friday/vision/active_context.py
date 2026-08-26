# -*- coding: utf-8 -*-
"""Active Window Tracker for Full-Duplex Voice Engine3: Active Screen Awareness.

Uses pywinauto (UI Automation / Win32) to extract the title, process name,
and active URL (for web browsers) of the window currently in foreground focus.
Runs lightweight and synchronously on local CPU with zero perceivable latency.
"""

from typing import Any, Dict, Optional
import os
import sys

from friday.core.logging import get_logger

logger = get_logger("vision.active_context")


def get_active_window_context() -> Dict[str, Any]:
    """Retrieve title, process name, and active browser URL of the foreground window.

    Returns:
        Dict containing:
        - "title": Window title string
        - "process_name": Process executable (e.g., 'chrome.exe', 'Code.exe')
        - "url": Extracted URL if focused in a supported web browser, else None
        - "is_active": True if a valid foreground window was identified
    """
    if sys.platform != "win32":
        return {
            "title": "Desktop Screen",
            "process_name": "unknown",
            "url": None,
            "is_active": False,
        }

    try:
        from pywinauto import Desktop
        import win32gui
        import win32process
        import psutil

        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return {
                "title": "",
                "process_name": "",
                "url": None,
                "is_active": False,
            }

        title = win32gui.GetWindowText(hwnd).strip()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        process_name = ""
        try:
            p = psutil.Process(pid)
            process_name = p.name()
        except Exception:
            process_name = "unknown"

        url = None
        # If active window is a known browser (Chrome, Edge, Brave), attempt fast address bar lookup
        proc_lower = process_name.lower()
        if any(b in proc_lower for b in ["chrome", "msedge", "brave", "firefox"]):
            try:
                # Fast UIA lookup for AddressBar / Edit control
                win = Desktop(backend="uia").window(handle=hwnd)
                # Look for address and search bar edit control
                edit = win.child_window(control_type="Edit", found_index=0)
                if edit.exists(timeout=0.1):
                    val = edit.get_value()
                    if val and ("." in val or val.startswith("http")):
                        url = val
            except Exception:
                url = None

        return {
            "title": title,
            "process_name": process_name,
            "url": url,
            "is_active": bool(title or process_name),
        }

    except Exception as e:
        logger.debug(f"Failed to query active foreground window context: {e}")
        return {
            "title": "",
            "process_name": "",
            "url": None,
            "is_active": False,
        }


def format_active_window_prompt() -> str:
    """Format active window context into a concise ambient prompt line."""
    ctx = get_active_window_context()
    if not ctx.get("is_active"):
        return ""
    app_name = ctx.get("process_name", "")
    if app_name.lower().endswith(".exe"):
        app_name = app_name[:-4].capitalize()
    title = ctx.get("title", "")
    url = ctx.get("url")
    url_info = f" (URL: {url})" if url else ""
    if app_name and title:
        return f"The user is currently looking at: {app_name} - {title}{url_info}."
    elif title:
        return f"The user is currently looking at: {title}{url_info}."
    elif app_name:
        return f"The user is currently looking at: {app_name}."
    return ""
