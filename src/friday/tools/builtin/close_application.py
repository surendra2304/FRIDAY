# -*- coding: utf-8 -*-
"""Close Application tool: gracefully close an open window by title.

Uses UI Automation to find a top-level window whose title contains the given
substring (e.g. 'Notepad' matches 'Untitled - Notepad') and closes it via
pywinauto's graceful .close() — the application receives a normal WM_CLOSE,
so apps with unsaved work show their own save prompt (no force-kill).
"""

from typing import Any

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

        try:
            window = _find_window(title)
        except Exception as e:
            return ToolResult(
                name=self.name,
                content=f"Window automation unavailable: {e}",
                is_error=True,
                safety_level=self.safety_level,
            )

        if window is None:
            return ToolResult(
                name=self.name,
                content=f"No open window found matching '{title}'.",
                is_error=True,
                safety_level=self.safety_level,
            )

        try:
            window_text = window.window_text()
            window.close()
            logger.info(f"Gracefully closed window '{window_text}' (matched '{title}')")
            return ToolResult(
                name=self.name,
                content=f"Closed {title}.",
                is_error=False,
                safety_level=self.safety_level,
            )
        except Exception as e:
            logger.error(f"Failed to close window matching '{title}': {e}")
            return ToolResult(
                name=self.name,
                content=f"Failed to close '{title}': {e}",
                is_error=True,
                safety_level=self.safety_level,
            )
