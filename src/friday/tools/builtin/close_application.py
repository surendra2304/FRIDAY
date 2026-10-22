"""Close a matching Windows window gracefully and verify its disappearance.

WM_CLOSE lets the application show its own unsaved-work prompt. FRIDAY does
not force-kill the process when the window stays open.
"""

from typing import Any
import time

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.tools.base import BaseTool

logger = get_logger("tools.close_application")


def _find_window(title_substring: str):
    """Return the first top-level UIA window matching the title substring, or None."""
    from pywinauto import Desktop

    needle = (title_substring or "").strip().lower()
    if not needle:
        return None
    try:
        windows = Desktop(backend="uia").windows()
        for w in windows:
            if needle in (w.window_text() or "").lower():
                return w
    except Exception as e:
        logger.warning(f"Window enumeration failed: {e}")
    return None


def _native_matching_windows(title_substring: str) -> list[int]:
    """Enumerate visible top-level windows by title without COM/UI Automation."""
    try:
        import win32gui

        needle = title_substring.strip().lower()
        matches: list[int] = []
        win32gui.EnumWindows(
            lambda hwnd, _: matches.append(hwnd)
            if win32gui.IsWindowVisible(hwnd)
            and needle in (win32gui.GetWindowText(hwnd) or "").lower()
            else None,
            None,
        )
        return matches
    except Exception:
        return []


class CloseApplicationTool(BaseTool):
    """Gracefully close an open application window by title."""

    name = "close_application"
    description = (
        "Close an open application window by its title (substring match, e.g. "
        "'Notepad' matches 'Untitled - Notepad', 'Settings' matches 'Settings'). "
        "The close is graceful: applications with unsaved changes will show "
        "their own save prompt. Use whenever the user asks to close or quit "
        "an application."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "window_title": {
                "type": "string",
                "description": "Substring of the window title to close (e.g. 'Notepad').",
            }
        },
        "required": ["window_title"],
    }

    def execute(self, window_title: str = "", **kwargs: Any) -> ToolResult:
        title = (window_title or "").strip()
        if not title:
            return ToolResult(
                name=self.name, content="No window title provided.", is_error=True,
                safety_level=self.safety_level,
            )

        # WM_CLOSE is the normal Windows close message. It preserves the app's
        # own unsaved-work prompts and avoids force-killing unrelated processes.
        close_requested = False
        try:
            import win32con
            import win32gui

            for hwnd in _native_matching_windows(title):
                win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                close_requested = True
        except Exception as e:
            logger.debug("Native WM_CLOSE fallback unavailable: %s", type(e).__name__)

        if not close_requested:
            return ToolResult(
                name=self.name,
                content=f"No open window found matching '{title}'.",
                is_error=True,
                safety_level=self.safety_level,
            )

        deadline = time.monotonic() + 2.5
        while time.monotonic() < deadline:
            if not _native_matching_windows(title):
                return ToolResult(
                    name=self.name,
                    content=f"Closed {title}; Windows confirmed no matching visible window remains.",
                    is_error=False,
                    safety_level=self.safety_level,
                )
            time.sleep(0.1)

        return ToolResult(
            name=self.name,
            content=f"Windows received a graceful close request for '{title}', but the window remains open or needs attention. I could not confirm it closed.",
            is_error=True,
            safety_level=self.safety_level,
        )
